/* Killzone 2 port: host side of the lifter's instruction probes (ps3recomp patch 6017, `ppu_lifter --probes`).
 * A lift made with KZ2_PROBES=<list> (tools/lift.sh) calls ppu_probe(ctx, addr) before each listed instruction, with
 * the guest registers as they are before it; a lift without a list never calls it. Lists: tools/runtime/probes/.
 *
 * Probes in the AI waypoint search 0x613DF0 (Dijkstra over the AIWaypointNeighbors graph; 1.29 addresses), list
 * tools/runtime/probes/dijkstra-613df0.txt. Logs `[kz2-astar]` lines: the inputs
 * and a scan of the graph at each entry (first KZ2_PROBE_LOG calls, default 8, then every 256th), the pop count and
 * callback results per call, a "not terminating" report once a call pops more than 20 x nodeCount + 1000 times, and
 * every bad value (neighbour count > 15, neighbour id >= nodeCount, a cost callback result outside 0..0xFFFF).
 *
 * Probes in the renderer fence wait 0x48AE8 (list tools/runtime/probes/fence-48ae8.txt): `[kz2-fence]` lines with the
 * fence table T = 0xFE1180 (+0x14 base, +0x18 stride, +0x34 IO offset table), index, wanted value, the polled EA and
 * its word (and the GCM label window word of the same index, NV406E semaphore offset index*16), at each entry (first
 * KZ2_PROBE_LOG calls, then every 256th) and while the loop 0x48B20 spins (1st, 1000th, then every 65536th pass).
 *
 * Probes on the colour-correction LUT path (list tools/runtime/probes/colorize-52ec18.txt): `[kz2-lut]` lines
 * at the LUT builder 0x52EC18, its caller 0x52F880, the texture create / lock / unlock returns, and the shader setups
 * that name the LUT parameter.
 *
 * LUT source (list tools/runtime/probes/lut-stream-a5eda8.txt): `[kz2-lutsrc]` lines. The buffered stream Read
 * func_00A5ED6C copies with memmove at 0xA5EDA8 (fast path) or func_0006D050's 0x6D0E8 (refill path); when the
 * destination overlaps the LUT (EA 0x23717A00, 16 KB) the probe logs the source, its FNV-1a hash and non-zero count,
 * the buffer object B = *(stream+0xC) (+0x80/+0x84 buffers, +0xA0 index, +0xA8 file position after the buffer,
 * +0xB0 read position, +0xB4 end; stream position = +0xA8 - (+0xB4 - +0xB0)), the file object *(B+0x14) and its words,
 * the last 8 reads of the same stream before it and the next 4 after. The refill reads (the file object's vtable +0x10
 * at 0x6CF0C / 0x6CF64) are recorded per buffer and printed for the buffer the source lies in. `[kz2-blend]` lines: the
 * colorize blend list of func_00530570 (entries, weights, which entry's ColorizeTexture is the zero LUT). List
 * tools/runtime/probes/blackscreen-seq.txt adds `[kz2-seq]` (sequence pause events, event instance creation, timed-event
 * frames, animated screen effects), `[kz2-tick]` (the Sequence tick) and `[kz2-ent]` (the base Entity update 0x67B218). */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ppu_overrides.h"   /* ppu_recomp.h: ppu_context, vm_read* */

static bool pr_ok(uint32_t ea) { return ea >= 0x10000u && ea < 0xF0000000u; }
static uint32_t pr32(uint32_t ea) { return pr_ok(ea) ? vm_read32(ea) : 0xDEADDEADu; }
static uint32_t pr16(uint32_t ea) { return pr_ok(ea) ? vm_read16(ea) : 0xDEADu; }
static float prf(uint32_t ea) { uint32_t u = pr32(ea); float f; memcpy(&f, &u, 4); return f; }
static int pr_limit()
{
    static int n = -1;
    if (n < 0) { const char* e = getenv("KZ2_PROBE_LOG"); n = e ? atoi(e) : 8; }
    return n;
}

/* Per-thread state of the current 0x613DF0 call. */
struct AstarState {
    uint32_t calls, W, H, N, G, nodes, O;
    uint64_t pops, edges, relax, pushes;
    int64_t cb_min, cb_max;
    uint32_t bad_cb, bad_cnt, bad_nb, bad_j;
    bool log, nonterm;
};
static thread_local AstarState g_as;

static void astar_entry(ppu_context* ctx)
{
    AstarState& s = g_as;
    const uint32_t W = (uint32_t)ctx->gpr[3];
    s = AstarState{};
    static uint32_t calls;   // all threads; the counter only selects which calls log
    s.calls = ++calls;
    static uint32_t other;   // calls through 0x6145E0 (lr 0x61475C), the path the main thread stops in
    s.log = (int)s.calls <= pr_limit() || (s.calls & 255u) == 0 ||
            ((uint32_t)ctx->lr != 0x006148C0u && (int)++other <= pr_limit());
    s.W = W; s.H = pr32(W); s.N = pr32(W + 4); s.O = (uint32_t)ctx->gpr[4]; s.G = (uint32_t)ctx->gpr[8];
    s.nodes = pr32(s.N);
    s.cb_min = INT64_MAX; s.cb_max = INT64_MIN;
    if (!s.log) return;
    const uint32_t G = s.G, ids = pr32(G + 0x10), trav = pr32(G + 0x1C), links = pr32(G + 0x28);
    fprintf(stderr, "[kz2-astar] enter #%u tid=%u lr=0x%08X W=0x%08X H={cnt %u data 0x%08X cap %u} N={nodes %u rec 0x%08X bmp 0x%08X} "
                    "O=0x%08X{0x%08X,%u,%u} r5=0x%08X r6=0x%08X r7=0x%08X G=0x%08X ids=0x%08X trav=0x%08X links=0x%08X\n",
            s.calls, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, W, pr32(s.H), pr32(s.H + 4), pr32(s.H + 8), s.nodes,
            pr32(s.N + 4), pr32(s.N + 8), s.O, pr32(s.O), pr32(s.O + 4), pr32(s.O + 8), (uint32_t)ctx->gpr[5],
            (uint32_t)ctx->gpr[6], (uint32_t)ctx->gpr[7], G, ids, trav, links);
    /* Graph scan: neighbour counts <= 15, ids < nodeCount, travel bytes -> finite non-negative table floats. */
    uint32_t badc = 0, badn = 0, badt = 0, edges = 0, first_bad = 0xFFFFFFFFu;
    const uint32_t n = s.nodes > 200000u ? 200000u : s.nodes;
    if (pr_ok(ids))
        for (uint32_t i = 0; i < n; i++) {
            const uint32_t c = pr16(ids + i * 32);
            if (c > 15) { badc++; if (first_bad == 0xFFFFFFFFu) first_bad = i; continue; }
            for (uint32_t j = 0; j < c; j++) {
                edges++;
                if (pr16(ids + i * 32 + 2 * (j + 1)) >= s.nodes) { badn++; if (first_bad == 0xFFFFFFFFu) first_bad = i; }
                if (pr_ok(trav)) {
                    const float t = prf(0x011F3628u + 4u * (pr32(trav + i * 16 + (j & ~3u)) >> (8 * (3 - (j & 3))) & 0xFF));
                    if (!(t >= 0.0f) || isinf(t)) badt++;
                }
            }
        }
    uint32_t tz = 0, tn = 0;
    for (int k = 0; k < 256; k++) { const float t = prf(0x011F3628u + 4u * k); if (t == 0.0f) tz++; if (t != t) tn++; }
    fprintf(stderr, "[kz2-astar]   graph: %u nodes, %u edges, counts>15 %u, ids>=nodes %u, bad travel %u (first bad node %d); "
                    "table 0x11F3628: zero %u NaN %u [1]=%g [255]=%g; origin 0x11F4810 = (%g %g %g); start rec0 [%08X %08X %08X]\n",
            s.nodes, edges, badc, badn, badt, (int)first_bad, tz, tn, prf(0x011F362Cu), prf(0x011F3A24u), prf(0x011F4810u),
            prf(0x011F4814u), prf(0x011F4818u), pr32(pr32(s.N + 4)), pr32(pr32(s.N + 4) + 4), pr32(pr32(s.N + 4) + 8));
}

static void astar_pop(ppu_context* ctx)
{
    AstarState& s = g_as;
    const uint32_t H = pr32((uint32_t)ctx->gpr[23]);
    s.pops++;
    const uint64_t lim = 20ull * s.nodes + 1000;
    if (s.pops == lim) {
        s.nonterm = true;
        fprintf(stderr, "[kz2-astar] NOT TERMINATING call #%u: %llu pops (nodes %u), edges %llu, relaxed %llu, pushes %llu, "
                        "heap cnt %u cap %u, cb result min %lld max %lld (bad %u), O count %u\n",
                s.calls, (unsigned long long)s.pops, s.nodes, (unsigned long long)s.edges, (unsigned long long)s.relax,
                (unsigned long long)s.pushes, pr32(H), pr32(H + 8), (long long)s.cb_min, (long long)s.cb_max, s.bad_cb,
                pr32(s.O + 8));
    }
    if (s.pops >= lim && s.pops < lim + 24) {
        const uint32_t w = pr32(pr32(H + 4)), id = w & 0xFFFF, rec = pr32(s.N + 4) + id * 32;
        fprintf(stderr, "[kz2-astar]   pop %llu: heap cnt %u top 0x%08X (cost %u id %u) rec [%08X %08X %08X %08X %08X] bmp %02X\n",
                (unsigned long long)s.pops, pr32(H), w, w >> 16, id, pr32(rec), pr32(rec + 4), pr32(rec + 8), pr32(rec + 12),
                pr32(rec + 16), pr_ok(pr32(s.N + 8)) ? vm_read8(pr32(s.N + 8) + (id >> 2)) : 0xEEu);
    }
    if (s.nonterm && (s.pops & ((1ull << 24) - 1)) == 0)
        fprintf(stderr, "[kz2-astar]   still in call #%u: %llu pops, heap cnt %u, relaxed %llu, O count %u\n", s.calls,
                (unsigned long long)s.pops, pr32(H), (unsigned long long)s.relax, pr32(s.O + 8));
}

static void astar_cb(ppu_context* ctx, uint32_t addr)
{
    AstarState& s = g_as;
    const int32_t r = (int32_t)(uint32_t)ctx->gpr[3];
    if (r < s.cb_min) s.cb_min = r;
    if (r > s.cb_max) s.cb_max = r;
    if ((r < 0 || r > 0xFFFF) && s.bad_cb++ < 8)
        fprintf(stderr, "[kz2-astar] cost callback @0x%08X result %d (0x%08X) call #%u ctr=0x%08X id %u nb %u link %d\n", addr,
                r, (uint32_t)r, s.calls, (uint32_t)ctx->ctr, (uint32_t)ctx->gpr[24], (uint32_t)ctx->gpr[29],
                (int)(int32_t)ctx->gpr[28]);
}

extern "C" uint32_t ppu_hle_inject_base;   /* GCM label window (cellGcmGetLabelAddress) */

static const char* fence_class(uint32_t ea)
{
    const uint32_t lb = ppu_hle_inject_base;
    if (ea >= lb && ea < lb + 0x1000u) return "gcm-label";
    if (ea >= lb && ea < lb + 0x8000u) return "gcm-window";
    if (ea >= 0xC0000000u && ea < 0xD0000000u) return "rsx-local";
    if (ea < 0x10000000u) return "main(elf/heap)";
    if (ea < 0x40000000u) return "main(mmapper)";
    if (ea < 0x50000000u) return "main(sys_memory)";
    return "other";
}

struct FenceState { uint32_t call; uint64_t spins; uint32_t first_word; };
static thread_local FenceState g_fs;

static void fence_log(ppu_context* ctx, const char* what, uint32_t idx, uint32_t want)
{
    const uint32_t T = 0x00FE1180u, base = pr32(T + 0x14), stride = pr32(T + 0x18), ea = base + idx * stride;
    const uint32_t lab = ppu_hle_inject_base + ((idx * 16u) & 0xFFFFu);
    fprintf(stderr, "[kz2-fence] %s call #%u tid=%u spins=%llu idx=%u want=0x%08X T{base 0x%08X stride 0x%X io 0x%08X} "
                    "ea=0x%08X(%s) word=0x%08X first=0x%08X label[idx]@0x%08X=0x%08X lr=0x%08X\n",
            what, g_fs.call, (unsigned)ctx->thread_id, (unsigned long long)g_fs.spins, idx, want, base, stride,
            pr32(T + 0x34), ea, fence_class(ea), pr32(ea), g_fs.first_word, lab, pr32(lab), (uint32_t)ctx->lr);
}

/* Probes around the wait 0x4E0E00 (`while (*(obj+0x30164) != 0) usleep(1)` at 0x4E0E48): a pending-work counter that
 * 0x4E0750 increments (lwarx/stwcx. at 0x4E0AF8 through *(r29+0x3C) = obj+0x30164) and something else decrements. */
struct PendState { uint32_t call, obj; uint64_t spins; };
static thread_local PendState g_ps;
static uint32_t g_pend_incs, g_pend_ea;
static void pend_log(ppu_context* ctx, const char* what)
{
    const uint32_t ea = g_ps.obj + 0x30164u;
    fprintf(stderr, "[kz2-pend] %s call #%u tid=%u obj=0x%08X spins=%llu counter@0x%08X=%u incs=%u (last inc ea 0x%08X) "
                    "desc 0x11F4230 {0x%08X 0x%08X 0x%08X} lr=0x%08X\n", what, g_ps.call, (unsigned)ctx->thread_id, g_ps.obj,
            (unsigned long long)g_ps.spins, ea, pr32(ea), g_pend_incs, g_pend_ea, pr32(0x011F4230u), pr32(0x011F4234u),
            pr32(0x011F4238u), (uint32_t)ctx->lr);
}

/* Where the fence release goes and when it is kicked: 0x39A298 emits NV406E SEMAPHORE_RELEASE (r3 command context
 * {begin, end, current}, r4 value); 0x39BBDC stores the new put (r0) to the control register (r11) in the flip path.
 * IO offset of an EA from the game's IO table *(0xFE1180+0x34) (u16 per 1 MB, >= 0x100 = unmapped). */
static uint32_t ea2io(uint32_t ea)
{
    const uint32_t tbl = pr32(0x00FE1180u + 0x34u);
    const uint32_t e = pr_ok(tbl) ? pr16(tbl + (ea >> 20) * 2u) : 0xFFFFu;
    return e >= 0x100u ? 0xFFFFFFFFu : (e << 20) | (ea & 0xFFFFFu);
}
static uint32_t g_put_prev;

/* Long fence wait: find every NV406E SEMAPHORE_OFFSET(idx*16) + SEMAPHORE_RELEASE(want) pair in IO-mapped memory
 * (the game's IO table) and print its IO offset, plus the control register and the ring words around put. */
static void fence_scan(uint32_t idx, uint32_t want)
{
    const uint32_t tbl = pr32(0x00FE1180u + 0x34u);
    const uint32_t ctrl = ppu_hle_inject_base + 0x2000u, put = pr32(ctrl), get = pr32(ctrl + 4);
    unsigned found = 0, any = 0;
    for (uint32_t mb = 0; mb < 0x1000u && pr_ok(tbl); mb++) {
        const uint32_t e = pr16(tbl + mb * 2u);
        if (e >= 0x100u) continue;
        const uint32_t ea0 = mb << 20;
        for (uint32_t o = 8; o + 8 <= 0x100000u; o += 4) {
            if (vm_read32(ea0 + o) != 0x0004006Cu) continue;
            const uint32_t v = vm_read32(ea0 + o + 4);
            const bool off = vm_read32(ea0 + o - 8) == 0x00040064u && vm_read32(ea0 + o - 4) == idx * 16u;
            if (!off) continue;
            any++;
            if (v == want && found++ < 8)
                fprintf(stderr, "[kz2-fence] scan: release of 0x%X for idx %u at ea 0x%08X io 0x%08X\n", v, idx, ea0 + o,
                        (e << 20) | o);
        }
    }
    fprintf(stderr, "[kz2-fence] scan: %u releases of idx %u in IO memory, %u with value 0x%X; ctrl put 0x%08X get 0x%08X\n",
            any, idx, found, want, put, get);
}

/* where the LUT's 16 KB come from in the level stream. EA 0x23717A00 was measured on ps3recomp v0.16.0,
 * where the runtime gave the game's page-heap reservation 0x20000000. Since v0.17.0 (upstream #296) mapper reservations
 * start at 0x40000000, so the default is 0x43717A00. Reservation order measured (KZ2_MMAP_LOG, level run):
 * flags 0x40F 0x20000000 -> 0x40000000, 0x208 0x30000000 -> 0x80000000; the page offset itself is not re-measured.
 * KZ2_LUT_EA=<hex> overrides. */
static const uint32_t LUT_N = 0x4000u;
static uint32_t lut_ea(void)
{
    static uint32_t v;
    if (!v) { const char* e = getenv("KZ2_LUT_EA"); v = e ? (uint32_t)strtoul(e, nullptr, 16) : 0x43717A00u; }
    return v;
}
struct RefillRec { uint32_t file, buf, n, r6, r7, ctr, tid, pos_hi, pos_lo; };
static RefillRec g_refill[32];
static uint32_t g_refill_i;
struct ReadRec { uint32_t B, dst, src, n, poshi, poslo; };
static ReadRec g_reads[64];
static uint32_t g_reads_i, g_after_B, g_after_left;
static uint64_t fnv_ea(uint32_t ea, uint32_t n, uint32_t* nz)
{
    uint64_t h = 1469598103934665603ull; uint32_t z = 0;
    for (uint32_t i = 0; i < n; i++) { const uint8_t b = pr_ok(ea + i) ? vm_read8(ea + i) : 0; z += b != 0; h = (h ^ b) * 1099511628211ull; }
    if (nz) *nz = z;
    return h;
}
static void lut_words(const char* tag, uint32_t ea, uint32_t n)
{
    char buf[600]; int b = 0;
    for (uint32_t i = 0; i < n && b < (int)sizeof buf - 12; i++) b += snprintf(buf + b, sizeof buf - b, " %08X", pr32(ea + i * 4));
    buf[b] = 0;
    fprintf(stderr, "[kz2-lutsrc]   %s @0x%08X:%s\n", tag, ea, buf);
}
static void lut_str(uint32_t ea)
{
    if (!pr_ok(ea)) return;
    char s[96]; int k = 0;
    for (; k < 95; k++) { const uint8_t c = vm_read8(ea + k); if (!c) break; if (c < 0x20 || c > 0x7E) return; s[k] = (char)c; }
    if (k < 4) return;
    s[k] = 0;
    fprintf(stderr, "[kz2-lutsrc]   str @0x%08X '%s'\n", ea, s);
}
static void lut_copy(ppu_context* ctx, uint32_t addr, uint32_t B)
{
    const uint32_t dst = (uint32_t)ctx->gpr[3], src = (uint32_t)ctx->gpr[4], n = (uint32_t)ctx->gpr[5];
    const uint64_t a8 = ((uint64_t)pr32(B + 0xA8) << 32) | pr32(B + 0xAC);
    const uint32_t b0 = pr32(B + 0xB0), b4 = pr32(B + 0xB4);
    const uint64_t pos = a8 - (uint64_t)(b4 - b0);   /* stream position of src (func_00A5EF08 tell) */
    ReadRec& r = g_reads[g_reads_i++ & 63u];
    r = { B, dst, src, n, (uint32_t)(pos >> 32), (uint32_t)pos };
    if (g_after_left && B == g_after_B) {
        g_after_left--;
        fprintf(stderr, "[kz2-lutsrc] after: at 0x%08X dst=0x%08X src=0x%08X n=0x%X pos=0x%llX\n", addr, dst, src, n, (unsigned long long)pos);
    }
    const uint32_t LUT_EA = lut_ea();
    if (!(dst < LUT_EA + LUT_N && dst + n > LUT_EA)) return;
    static uint32_t hits;
    if (++hits > 8) return;
    uint32_t nz = 0; const uint64_t h = fnv_ea(src, n < 0x10000u ? n : 0x10000u, &nz);
    fprintf(stderr, "[kz2-lutsrc] HIT #%u at 0x%08X tid=%u lr=0x%08X dst=0x%08X src=0x%08X n=0x%X src-hash=%016llX nonzero=%u "
                    "stream=0x%08X B=0x%08X B+80=0x%08X B+84=0x%08X B+A0=%u B+A8=0x%llX B+B0=0x%08X B+B4=0x%08X pos=0x%llX file=0x%08X\n",
            hits, addr, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, dst, src, n, (unsigned long long)h, nz, (uint32_t)ctx->gpr[30],
            B, pr32(B + 0x80), pr32(B + 0x84), pr32(B + 0xA0), (unsigned long long)a8, b0, b4, (unsigned long long)pos, pr32(B + 0x14));
    lut_words("src", src, 8);
    lut_words("B+0x00", B, 16);
    lut_words("B+0x80", B + 0x80, 16);
    const uint32_t F = pr32(B + 0x14);
    lut_words("file", F, 24);
    lut_words("file vtable", pr32(F), 16);
    for (uint32_t i = 0; i < 24; i++) { lut_str(pr32(F + i * 4)); }
    for (uint32_t i = 0; i < 16; i++) lut_str(pr32(B + i * 4));
    for (uint32_t i = 1; i <= 8; i++) {
        const ReadRec& q = g_reads[(g_reads_i - 1 - i) & 63u];
        if (q.B != B) continue;
        fprintf(stderr, "[kz2-lutsrc]   before-%u: dst=0x%08X src=0x%08X n=0x%X pos=0x%llX\n", i, q.dst, q.src, q.n,
                ((unsigned long long)q.poshi << 32) | q.poslo);
    }
    for (uint32_t i = 0; i < 32; i++) {
        const RefillRec& f = g_refill[i];
        if (f.buf && src >= f.buf && src < f.buf + 0x40000u)
            fprintf(stderr, "[kz2-lutsrc]   refill of this buffer: file=0x%08X buf=0x%08X n=0x%X r6=0x%08X r7=0x%08X ctr=0x%08X tid=%u B+A8 at call=0x%X_%08X\n",
                    f.file, f.buf, f.n, f.r6, f.r7, f.ctr, f.tid, f.pos_hi, f.pos_lo);
    }
    g_after_B = B; g_after_left = 4;
}
static void lut_refill(ppu_context* ctx, uint32_t addr)
{
    RefillRec& f = g_refill[g_refill_i++ & 31u];
    const uint32_t B = (uint32_t)ctx->gpr[31];
    f = { (uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5], (uint32_t)ctx->gpr[6], (uint32_t)ctx->gpr[7],
          (uint32_t)ctx->ctr, (unsigned)ctx->thread_id, pr32(B + 0xA8), pr32(B + 0xAC) };
    static uint32_t n;
    if ((int)++n <= pr_limit())
        fprintf(stderr, "[kz2-lutsrc] refill #%u at 0x%08X file=0x%08X buf=0x%08X n=0x%X r6=0x%08X r7=0x%08X ctr=0x%08X tid=%u\n", n, addr,
                f.file, f.buf, f.n, f.r6, f.r7, f.ctr, f.tid);
}

/* the colorize blend list func_00530570 walks every frame (r3 = list: +0 count, +4 entries of
 * {ColorizeSettingsResource*, float weight}; +0x30..+0x3C the blended ForwardRenderingColorizeSettings). Logged when the
 * entries or weights change (at most 300 lines) and every 1024th call. For each entry: the resource, its weight, its
 * ColorizeTexture (+0x24) and whether that Texture object's first 0x60 bytes hold the zero LUT (lut_ea(), or the
 * v0.16.0 values EA 0x23717A00 / IO 0x05417A00; the IO offset may move with v0.17.0's first-fit IO pages, #410). */
static void lut_blend(ppu_context* ctx)
{
    static uint32_t calls, lines; static uint64_t prev;
    const uint32_t L = (uint32_t)ctx->gpr[3], n = pr32(L), E = pr32(L + 4);
    uint64_t sig = 1469598103934665603ull ^ n;
    for (uint32_t i = 0; i < n && i < 16; i++) { sig = (sig ^ pr32(E + i * 8)) * 1099511628211ull; sig = (sig ^ (pr32(E + i * 8 + 4) >> 12)) * 1099511628211ull; }
    ++calls;
    if (!((sig != prev && lines < 300) || (calls & 1023u) == 0)) return;
    prev = sig; lines++;
    char buf[1200]; int b = 0;
    for (uint32_t i = 0; i < n && i < 8 && b < (int)sizeof buf - 120; i++) {
        const uint32_t res = pr32(E + i * 8), tex = pr32(res + 0x24);
        bool lut0 = false;
        for (uint32_t k = 0; k < 0x60 && tex; k += 4) { const uint32_t w = pr32(tex + k); if (w == lut_ea() || w == 0x23717A00u || w == 0x05417A00u) lut0 = true; }
        b += snprintf(buf + b, sizeof buf - b, " [%u] res=0x%08X w=%.4f tex=0x%08X%s fr=(%.3f %.3f %.3f %.3f)", i, res, prf(E + i * 8 + 4), tex,
                      lut0 ? " ZERO-LUT" : "", prf(res + 0x50), prf(res + 0x54), prf(res + 0x58), prf(res + 0x5C));
    }
    buf[b] = 0;
    fprintf(stderr, "[kz2-blend] #%u tid=%u lr=0x%08X list=0x%08X n=%u flags=0x%X%s\n", calls, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, L, n,
            pr32(L + 0x40), buf);
}

/* sequence pause events (ScriptPauseEventInstance, vtable 0xF8DC04; the level's "CR_BlackScreen" sequence
 * pauses at frame 5 on a ScriptPauseEvent "CR_BlackScreen_Done" while its black screen effect is at weight 1).
 * `[kz2-seq]` lines: 0x1D4DA0 / 0x1D4E28 (pause: sets inst+0x18 and Sequence+0x15C = inst), 0x1D4E88 / 0x1D4F20 (call
 * the script side 0x54DAF0 / 0x54EED8), 0x1D78D0 (unpause: Sequence+0x15C = 0, func_001DEE70). r3 = instance, +0x10 the
 * resource (+0x1C Message String), +0x14 the Sequence. */
static void seq_str(char* out, size_t n, uint32_t ea)
{
    out[0] = 0;
    for (int pass = 0; pass < 3 && ea; pass++) {   /* the String may be a char*, or point at a header before the chars */
        size_t k = 0;
        if (pr_ok(ea)) for (; k + 1 < n; k++) { const uint8_t c = vm_read8(ea + k); if (!c || c < 0x20 || c > 0x7E) break; out[k] = (char)c; }
        out[k] = 0;
        if (k >= 3) return;
        ea = pass == 0 ? pr32(ea) : 0;
    }
}
static void seq_probe(ppu_context* ctx, uint32_t addr)
{
    static uint32_t n;
    if (++n > 400) return;
    const uint32_t inst = (uint32_t)ctx->gpr[3], res = pr32(inst + 0x10), seq = pr32(inst + 0x14);
    char msg[64]; seq_str(msg, sizeof msg, pr32(res + 0x1C));
    fprintf(stderr, "[kz2-seq] 0x%08X tid=%u lr=0x%08X inst=0x%08X vt=0x%08X res=0x%08X start=%d msg='%s' seq=0x%08X seq+15C=0x%08X inst+18=%u\n",
            addr, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, inst, pr32(inst), res, (int)pr32(res + 0x18), msg, seq,
            pr32(seq + 0x15C), pr_ok(inst) ? vm_read8(inst + 0x18) : 0xEEu);
}

/* who keeps the black screen effect at weight 1. `[kz2-seq]` lines also at: 0x1D7528 / 0x1D7868 (create a
 * ScreenEffectEventInstance / ScriptPauseEventInstance for resource r3), 0x1DC140 (a timed event instance's "finished?"
 * test: Sequence+0x128 current frame >= resource+0x1C StopFrame; first KZ2_PROBE_LOG*4, then every 256th), 0x2D7B58
 * (script call: animated screen effect by name r5, time f1) and 0x2D79A8 (apply AnimatedScreenEffectResource r5 to every
 * player's view, time f1). */
static void seq_probe2(ppu_context* ctx, uint32_t addr)
{
    static uint32_t n[5];
    const int k = addr == 0x001D7528u ? 0 : addr == 0x001D7868u ? 1 : addr == 0x001DC140u ? 2 : addr == 0x002D7B58u ? 3 : 4;
    const uint32_t c = ++n[k];
    if (k == 2 ? ((int)c > pr_limit() * 4 && (c & 255u) != 0) : c > 64) return;
    const uint32_t r3 = (uint32_t)ctx->gpr[3];
    char msg[64] = "";
    if (k == 2) {
        const uint32_t res = pr32(r3 + 0x10), seq = pr32(r3 + 0x14);
        fprintf(stderr, "[kz2-seq] finished? #%u inst=0x%08X res=0x%08X start=%d stop=%d seq=0x%08X frame=%d seq+15C=0x%08X tid=%u\n", c, r3, res,
                (int)pr32(res + 0x18), (int)pr32(res + 0x1C), seq, (int)pr32(seq + 0x128), pr32(seq + 0x15C), (unsigned)ctx->thread_id);
        return;
    }
    if (k == 3) seq_str(msg, sizeof msg, (uint32_t)ctx->gpr[5]);
    if (k == 4) seq_str(msg, sizeof msg, pr32((uint32_t)ctx->gpr[5] + 4));
    fprintf(stderr, "[kz2-seq] 0x%08X #%u tid=%u lr=0x%08X r3=0x%08X r4=0x%08X r5=0x%08X f1=%.3f '%s' res words %08X %08X %08X %08X %08X %08X %08X %08X %08X %08X\n",
            addr, c, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, r3, (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5], ctx->fpr[1], msg,
            pr32(r3 + 0x00), pr32(r3 + 0x0C), pr32(r3 + 0x10), pr32(r3 + 0x14), pr32(r3 + 0x18), pr32(r3 + 0x1C), pr32(r3 + 0x20), pr32(r3 + 0x24),
            pr32(pr32(r3 + 0x20) + 0xC), pr32(pr32(r3 + 0x20) + 0x14));
}

/* the Sequence tick. 0x1DEAD0 (Sequence vtable slot, word 0xE8B498) calls func_001DE930, which returns at
 * once unless Sequence+0x11C (playing) is set, then advances the frame Sequence+0x128 (pause event at +0x15C, state
 * +0x160); 0x1DE270 sets the frame (r4 = frame pointer?). `[kz2-tick]` lines per sequence: the first 4 calls of each of
 * the first 32 sequences seen, then every 512th call overall. */
static void seq_tick(ppu_context* ctx, uint32_t addr)
{
    static uint32_t seqs[32], cnt[32], nseq, total;
    const uint32_t q = (uint32_t)ctx->gpr[3];
    ++total;
    uint32_t i = 0;
    for (; i < nseq && seqs[i] != q; i++) {}
    if (i == nseq && nseq < 32) { seqs[nseq] = q; cnt[nseq] = 0; nseq++; }
    const bool first = i < 32 && cnt[i]++ < 4;
    if (!first && (total & 511u) != 0) return;
    fprintf(stderr, "[kz2-tick] 0x%08X #%u tid=%u lr=0x%08X seq=0x%08X vt=0x%08X playing=%u state=%d frame=%d f124=%.3f pause=0x%08X r4=0x%08X f1=%.3f\n",
            addr, total, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, q, pr32(q), pr_ok(q) ? vm_read8(q + 0x11C) : 0xEEu, (int)pr32(q + 0x160),
            (int)pr32(q + 0x128), prf(q + 0x124), pr32(q + 0x15C), (uint32_t)ctx->gpr[4], ctx->fpr[1]);
}

/* is any entity updated? func_0067B218 is the base Entity update the Sequence slot +0x4C (0x1DEAD0) calls
 * first. `[kz2-ent]` lines: each new (vtable, lr) pair (at most 64) and a count every 4096th call. */
static void ent_update(ppu_context* ctx)
{
    static uint32_t total, n; static uint64_t seen[64];
    ++total;
    const uint32_t e = (uint32_t)ctx->gpr[3], vt = pr32(e);
    const uint64_t key = ((uint64_t)vt << 32) | (uint32_t)ctx->lr;
    bool isnew = true;
    for (uint32_t i = 0; i < n; i++) if (seen[i] == key) { isnew = false; break; }
    if (isnew && n < 64) seen[n++] = key; else isnew = false;
    if (isnew || (total & 4095u) == 0)
        fprintf(stderr, "[kz2-ent] #%u tid=%u lr=0x%08X ent=0x%08X vt=0x%08X%s\n", total, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, e, vt, isnew ? " new" : "");
}

/* a call-count profiler over function entries (probe list tools/runtime/probes/prof-all-entries.txt, every
 * function start of work/runtime/analysis-129/functions.json). With KZ2_PROF_OUT=<file> every probe hit is counted per
 * address, split into main thread (tid 1) and other threads, with the last caller (lr) and the last other thread id; a
 * host thread writes the counts that changed since the previous snapshot every KZ2_PROF_SEC seconds (default 10):
 *   "S <n> <seconds>" then "<addr> <tid1 delta> <other delta> <last lr tid1> <last lr other> <last other tid>" lines.
 * It also prints `[kz2-prof] snapshot <n> t=<s>` to stderr so the snapshots line up with the other log lines.
 * Counters are plain (racy) increments: diagnostics only. ENHANCEMENT (port-only diagnostics). */
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>
static const uint32_t PROF_LO = 0x10000u, PROF_N = (0x00BD0000u - 0x10000u) / 4u;
static uint32_t *g_p1, *g_po, *g_plr1, *g_plro, *g_ptid, *g_q1, *g_qo;
static std::atomic<int> g_prof{-1};
static void prof_dump_loop(FILE* f, int sec)
{
    auto t0 = std::chrono::steady_clock::now();
    for (uint32_t n = 1;; n++) {
        std::this_thread::sleep_for(std::chrono::seconds(sec));
        const double t = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        fprintf(f, "S %u %.1f\n", n, t);
        uint32_t lines = 0;
        for (uint32_t i = 0; i < PROF_N; i++) {
            const uint32_t a = g_p1[i], b = g_po[i];
            if (a == g_q1[i] && b == g_qo[i]) continue;
            fprintf(f, "%08X %u %u %08X %08X %u\n", PROF_LO + 4u * i, a - g_q1[i], b - g_qo[i], g_plr1[i], g_plro[i], g_ptid[i]);
            g_q1[i] = a; g_qo[i] = b; lines++;
        }
        fflush(f);
        fprintf(stderr, "[kz2-prof] snapshot %u t=%.1f functions=%u\n", n, t, lines);
    }
}
static void prof_init()
{
    static std::mutex m;
    std::lock_guard<std::mutex> g(m);
    if (g_prof.load() >= 0) return;
    const char* out = getenv("KZ2_PROF_OUT");
    FILE* f = out && *out ? fopen(out, "w") : nullptr;
    if (!f) { g_prof.store(0); return; }
    const char* se = getenv("KZ2_PROF_SEC");
    const int sec = se && atoi(se) > 0 ? atoi(se) : 10;
    uint32_t** arrs[] = {&g_p1, &g_po, &g_plr1, &g_plro, &g_ptid, &g_q1, &g_qo};
    for (auto a : arrs) *a = (uint32_t*)calloc(PROF_N, 4);
    std::thread(prof_dump_loop, f, sec).detach();
    fprintf(stderr, "[kz2-prof] on: %s every %d s\n", out, sec);
    g_prof.store(1);
}
static inline void prof_hit(ppu_context* ctx, uint32_t addr)
{
    int on = g_prof.load(std::memory_order_relaxed);
    if (on < 0) { prof_init(); on = g_prof.load(); }
    if (!on || addr < PROF_LO) return;
    const uint32_t i = (addr - PROF_LO) >> 2;
    if (i >= PROF_N) return;
    if (ctx->thread_id == 1) { g_p1[i]++; g_plr1[i] = (uint32_t)ctx->lr; }
    else { g_po[i]++; g_plro[i] = (uint32_t)ctx->lr; g_ptid[i] = (uint32_t)ctx->thread_id; }
}

/* the game module (vtable 0xF98BB8, stored by the ctor at 0x2487A8; name ASSUMPTION): slot 19
 * 0x25D360 (vt+0x4C; counter +0x138, state +0x1F8 3..7) and slot 18 0x25B958 (vt+0x48; returns at once when +0x1F8
 * == 1). `[kz2-gm]` lines: the first KZ2_PROBE_LOG calls of each, then one a second with the module's words. */
static void gm_probe(ppu_context* ctx, uint32_t addr)
{
    static uint32_t c18, c19; static auto last = std::chrono::steady_clock::now();
    uint32_t& c = addr == 0x0025B958u ? c18 : c19;
    ++c;
    const auto now = std::chrono::steady_clock::now();
    const bool tick = std::chrono::duration<double>(now - last).count() >= 1.0;
    if ((int)c > pr_limit() && !tick) return;
    if (tick) last = now;
    const uint32_t w = (uint32_t)ctx->gpr[3];
    fprintf(stderr, "[kz2-gm] 0x%08X #%u (s18 %u s19 %u) tid=%u lr=0x%08X W=0x%08X vt=0x%08X 1f8=%d 138=%d 134=%u 1c1=%u 4c=0x%08X 80=0x%08X 3a4=0x%08X 8=0x%08X\n",
            addr, c, c18, c19, (unsigned)ctx->thread_id, (uint32_t)ctx->lr, w, pr32(w), (int)pr32(w + 0x1F8), (int)pr32(w + 0x138),
            pr_ok(w) ? vm_read8(w + 0x134) : 0xEEu, pr_ok(w) ? vm_read8(w + 0x1C1) : 0xEEu, pr32(w + 0x4C), pr32(w + 0x80), pr32(w + 0x3A4), pr32(w + 8));
}

void ppu_probe(ppu_context* ctx, uint32_t addr)
{
    prof_hit(ctx, addr);
    switch (addr) {
    case 0x0025B958u: case 0x0025D360u: gm_probe(ctx, addr); return;
    case 0x00A5EDA8u: lut_copy(ctx, addr, (uint32_t)ctx->gpr[30]); return;   // @0x00A5EDA8 bl memmove (stream Read fast path)
    case 0x0006D0E8u: lut_copy(ctx, addr, (uint32_t)ctx->gpr[30]); return;   // @0x0006D0E8 bl memmove (refill path; r30 = B)
    case 0x0006CF0Cu: case 0x0006CF64u: lut_refill(ctx, addr); return;      // bctrl file vtable +0x10 (r31 = B)
    case 0x001D4DA0u: case 0x001D4E28u: case 0x001D4E88u: case 0x001D4F20u: case 0x001D78D0u: seq_probe(ctx, addr); return;
    case 0x001D7528u: case 0x001D7868u: case 0x001DC140u: case 0x002D7B58u: case 0x002D79A8u: seq_probe2(ctx, addr); return;
    case 0x001DEAD0u: case 0x001DE930u: case 0x001DE270u: seq_tick(ctx, addr); return;
    case 0x0067B218u: ent_update(ctx); return;
    case 0x00530570u: lut_blend(ctx); return;                                 // @0x00530570 colorize blend list (r3)
    case 0x004E0E00u: {                          // @0x004E0E00 entry: r3 obj
        static uint32_t calls;
        g_ps.call = ++calls; g_ps.obj = (uint32_t)ctx->gpr[3]; g_ps.spins = 0;
        if ((int)calls <= pr_limit() || (calls & 255u) == 0) pend_log(ctx, "enter");
        return;
    }
    case 0x004E0E48u: {                          // @0x004E0E48 wait loop (counter != 0)
        const uint64_t n = ++g_ps.spins;
        if (n == 1 || n == 1000 || (n & 0xFFFFu) == 0) pend_log(ctx, n == 1 ? "wait" : "spin");
        return;
    }
    case 0x004E0E68u:                            // @0x004E0E68 after the wait
        if (g_ps.spins >= 1000 || (int)g_ps.call <= pr_limit()) pend_log(ctx, "done");
        return;
    case 0x004E0AF8u: {                          // @0x004E0AF8 lwarx: atomic increment of *(r30)
        const uint32_t n = ++g_pend_incs; g_pend_ea = (uint32_t)ctx->gpr[30];
        if ((int)n <= pr_limit() || (n & 255u) == 0)
            fprintf(stderr, "[kz2-pend] inc #%u ea=0x%08X old=%u tid=%u\n", n, g_pend_ea, pr32(g_pend_ea), (unsigned)ctx->thread_id);
        return;
    }
    case 0x0039A298u: {                          // @0x0039A298 SEMAPHORE_RELEASE emit: r3 ctx, r4 value
        static uint32_t n;
        const uint32_t c = (uint32_t)ctx->gpr[3], cur = pr32(c + 8);
        const bool render = (uint32_t)ctx->lr == 0x0053F35Cu;   // the render pass's fence (0x53F358)
        if (render || (int)++n <= 8)
            fprintf(stderr, "[kz2-kick] %s #%u v=0x%X ctx=0x%08X {begin 0x%08X end 0x%08X cur 0x%08X} io 0x%08X tid=%u lr=0x%08X\n",
                    render ? "render-release" : "release", n, (uint32_t)ctx->gpr[4], c, pr32(c), pr32(c + 4), cur, ea2io(cur), (unsigned)ctx->thread_id,
                    (uint32_t)ctx->lr);
        return;
    }
    case 0x0039BBDCu: {                          // @0x0039BBDC stw r0 (put), 0(r11): flip-path kick
        static uint32_t n;
        const uint32_t put = (uint32_t)ctx->gpr[0], off = pr32((uint32_t)ctx->gpr[30] + 0x44);
        if ((int)++n <= pr_limit() * 4 || (n & 255u) == 0) {
            char buf[512]; int k = 0, calls = 0;
            if (g_put_prev && put > g_put_prev && put - g_put_prev < 0x10000u)
                for (uint32_t io = g_put_prev; io < put && calls < 8; io += 4) {
                    const uint32_t w = pr32(io + off);
                    if ((w & 3u) == 2u || (w & 3u) == 1u || (w & 0xE0000003u) == 0x20000000u) {
                        k += snprintf(buf + k, sizeof buf - k, " %s@%X->%X", (w & 3u) == 2u ? "call" : "jump", io,
                                      (w & 3u) ? (w & ~3u) : (w & 0x1FFFFFFCu));
                        calls++;
                    }
                }
            buf[k] = 0;
            fprintf(stderr, "[kz2-kick] put #%u 0x%08X -> 0x%08X ctrl=0x%08X tid=%u lr=0x%08X:%s\n", n, g_put_prev, put,
                    (uint32_t)ctx->gpr[11], (unsigned)ctx->thread_id, (uint32_t)ctx->lr, buf);
        }
        g_put_prev = put;
        return;
    }
    /* colour-correction LUT path (tools/runtime/probes/colorize-52ec18.txt). [kz2-lut] lines, the first
     * KZ2_PROBE_LOG (default 8) per address, then every 256th. */
    case 0x0052F880u: case 0x0052EC18u: case 0x0052EDBCu: case 0x0052EDF4u: case 0x0052F7D4u: case 0x0052F7E0u:
    case 0x005307A0u: case 0x00538CB0u: {
        static uint32_t n[9];
        const int k = addr == 0x0052F880u ? 0 : addr == 0x0052EC18u ? 1 : addr == 0x0052EDBCu ? 2 : addr == 0x0052EDF4u ? 3
                    : addr == 0x0052F7D4u ? 4 : addr == 0x0052F7E0u ? 5 : addr == 0x005307A0u ? 6 : addr == 0x00538CB0u ? 7 : 8;
        const uint32_t c = ++n[k];
        if ((int)c > pr_limit() && (c & 255u) != 0) return;
        const uint32_t r3 = (uint32_t)ctx->gpr[3];
        char buf[400]; int b = 0;
        if (addr == 0x0052F880u) b += snprintf(buf + b, sizeof buf - b, " *(r3+0x24)=0x%08X *(r3+8)=0x%08X", pr32(r3 + 0x24), pr32(r3 + 8));
        if (addr == 0x0052EDBCu || addr == 0x0052F7E0u || addr == 0x0052EC18u) {   // object words: look for the RSX offset / EA
            b += snprintf(buf + b, sizeof buf - b, " obj:");
            for (uint32_t i = 0; i < 16 && b < (int)sizeof buf - 12; i++) b += snprintf(buf + b, sizeof buf - b, " %08X", pr32(r3 + i * 4));
        }
        if (addr == 0x0052EDF4u) b += snprintf(buf + b, sizeof buf - b, " ptr io 0x%08X", ea2io(r3));
        buf[b] = 0;
        fprintf(stderr, "[kz2-lut] 0x%08X #%u tid=%u lr=0x%08X r3=0x%08X r4=0x%08X r28=0x%08X r16=0x%08X%s\n", addr, c,
                (unsigned)ctx->thread_id, (uint32_t)ctx->lr, r3, (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[28],
                (uint32_t)ctx->gpr[16], buf);
        return;
    }
    default: break;
    }
    if (addr == 0x00048AE8u) {                   // @0x00048AE8 entry: r3 device, r4 index, r5 wanted value
        static uint32_t calls;
        const uint32_t T = 0x00FE1180u, idx = (uint32_t)ctx->gpr[4];
        g_fs.call = ++calls; g_fs.spins = 0;
        g_fs.first_word = pr32(pr32(T + 0x14) + idx * pr32(T + 0x18));
        if ((int)calls <= pr_limit() || (calls & 255u) == 0) fence_log(ctx, "enter", idx, (uint32_t)ctx->gpr[5]);
        return;
    }
    if (addr == 0x00048B20u) {                   // @0x00048B20 poll loop head: r30 index, r31 wanted value
        const uint64_t n = ++g_fs.spins;
        if (n == 2 || n == 1000 || (n & 0xFFFFu) == 0)
            fence_log(ctx, n == 2 ? "wait" : "spin", (uint32_t)ctx->gpr[30], (uint32_t)ctx->gpr[31]);
        if (n == 0x40000u) fence_scan((uint32_t)ctx->gpr[30], (uint32_t)ctx->gpr[31]);
        return;
    }

    AstarState& s = g_as;
    switch (addr) {
    case 0x00613DF0u: astar_entry(ctx); break;   // @0x00613DF0 entry
    case 0x00613E84u: astar_pop(ctx); break;     // @0x00613E84 each pop
    case 0x006140B8u:                            // @0x006140B8 r15 = neighbour count of r24
        if ((uint32_t)ctx->gpr[15] > 15 && s.bad_cnt++ < 8)
            fprintf(stderr, "[kz2-astar] node %u has %u neighbours (call #%u)\n", (uint32_t)ctx->gpr[24],
                    (uint32_t)ctx->gpr[15], s.calls);
        break;
    case 0x006140E0u:                            // @0x006140E0 r29 = neighbour id, r27 = j, r15 = count
        s.edges++;
        if ((uint32_t)ctx->gpr[27] > 15 && s.bad_j++ < 4)
            fprintf(stderr, "[kz2-astar] neighbour index j=%u > 15 at node %u: r15 (count) = 0x%08X, count in graph %u, r22=0x%08X "
                            "sp=0x%08X *(sp+0xA8)=0x%08X_%08X call #%u pops %llu\n", (uint32_t)ctx->gpr[27], (uint32_t)ctx->gpr[24],
                    (uint32_t)ctx->gpr[15], pr16(pr32(s.G + 0x10) + (uint32_t)ctx->gpr[24] * 32), (uint32_t)ctx->gpr[22],
                    (uint32_t)ctx->gpr[1], pr32((uint32_t)ctx->gpr[1] + 0xA8), pr32((uint32_t)ctx->gpr[1] + 0xAC), s.calls,
                    (unsigned long long)s.pops);
        if ((s.edges & ((1ull << 24) - 1)) == 0)
            fprintf(stderr, "[kz2-astar]   call #%u: %llu edges, %llu pops, j=%u r15=0x%08X node %u\n", s.calls,
                    (unsigned long long)s.edges, (unsigned long long)s.pops, (uint32_t)ctx->gpr[27], (uint32_t)ctx->gpr[15],
                    (uint32_t)ctx->gpr[24]);
        if ((uint32_t)ctx->gpr[29] >= s.nodes && s.bad_nb++ < 8)
            fprintf(stderr, "[kz2-astar] node %u neighbour %u >= nodes %u (call #%u)\n", (uint32_t)ctx->gpr[24],
                    (uint32_t)ctx->gpr[29], s.nodes, s.calls);
        break;
    case 0x0061427Cu: case 0x006142C8u: astar_cb(ctx, addr); break;   // after the two cost callbacks
    case 0x006142D4u: s.relax++; break;          // @0x006142D4 relax accepted
    case 0x006143F8u: s.pushes++; break;         // @0x006143F8 push (not in heap yet)
    case 0x00614584u:                            // @0x00614584 exit
        if (s.log || s.nonterm || s.bad_j || s.pops > 4ull * s.nodes + 64)
            fprintf(stderr, "[kz2-astar] exit #%u: %llu pops, %llu edges, %llu relaxed, %llu pushes, cb min %lld max %lld, O count %u\n",
                    s.calls, (unsigned long long)s.pops, (unsigned long long)s.edges, (unsigned long long)s.relax,
                    (unsigned long long)s.pushes, (long long)(s.cb_min == INT64_MAX ? 0 : s.cb_min),
                    (long long)(s.cb_max == INT64_MIN ? 0 : s.cb_max), pr32(s.O + 8));
        break;
    case 0x00622790u: {                          // @0x00622790 path request (requester)
        static uint32_t c;
        if ((int)++c <= pr_limit() || (c & 255u) == 0)
            fprintf(stderr, "[kz2-astar] request 0x622790 #%u lr=0x%08X r3=0x%08X r4=0x%08X r5=0x%08X r6=0x%08X r7=0x%08X\n", c,
                    (uint32_t)ctx->lr, (uint32_t)ctx->gpr[3], (uint32_t)ctx->gpr[4], (uint32_t)ctx->gpr[5],
                    (uint32_t)ctx->gpr[6], (uint32_t)ctx->gpr[7]);
        break;
    }
    default: {
        static uint32_t c;
        if (c++ < 16) fprintf(stderr, "[kz2-probe] 0x%08X tid=%u r3=0x%08X\n", addr, (unsigned)ctx->thread_id, (uint32_t)ctx->gpr[3]);
    }
    }
}
