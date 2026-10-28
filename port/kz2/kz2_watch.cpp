/* Killzone 2 port: guest memory region watch (diagnostic, off by default), written for the black level frames: who writes the
 * 64x64 A8R8G8B8 texture the composite draw samples on unit 2 (RSX main-memory offset 0x05417A00, all zero in
 * kz2-spu24), and the 8x8 one on unit 14 (0x006CF880)?
 *
 *   KZ2_WATCH="io:05417A00:4000,io:006CF880:100"   up to 4 regions, hex; io: = RSX main-memory (IO) offset, resolved
 *                                                    through the GCM IO table on every poll; ea: = guest address
 *   KZ2_WATCH_MAX=<n>                                at most n [kz2-watch] lines (default 400)
 *   KZ2_WATCH_SCAN=<hex>[,<hex>...] once, KZ2_WATCH_SCAN_AT flips (default 100) after region 0 first resolves, scan
 *                                                    committed guest memory below 0xC0000000 for these big-endian
 *                                                    words (e.g. the region's IO offset and EA: who holds the
 *                                                    texture) and print each hit with 8 words around it (max 40)
 *   KZ2_WATCH_TRAP=<n>                               also write-protect the host pages under each region and log up to
 *                                                    n writes that land inside a region (writer's host RIP, thread,
 *                                                    guest address, the 16 bytes after the write); 0/unset = off
 *
 * Poll (kz2_watch_poll, called by main.cpp's present_guest_frame on the frame thread, once per presented flip): each
 * region's EA, FNV-1a hash, count of non-zero bytes and the first non-zero 16 bytes, logged when the EA or the hash
 * changes, and a heartbeat every 500 flips. The trap is the universal write watch: lifted PPU stores of every kind
 * (scalar, stvx/stvewx/stvlx/stvrx, dcbz), SPU DMA puts (spu_dma.h memcpy), HLE copies (cellFs reads) all write
 * through vm_base + ea, so a read-only host page faults for each of them. The vectored handler (installed at the head of
 * the chain, before main.cpp's demand-commit handler) unprotects the page, single-steps the writing instruction with
 * the trap flag, records it and re-protects. ASSUMPTION: a write from a second thread while the page is open for the
 * first is not seen (pages stay open for one instruction). Writes outside the regions but in the same host pages are
 * only counted. Records go to a lock-free ring printed by the poll, so the handler never takes the stdio lock.
 * Each write names the writing instruction and up to 3 callers (RtlVirtualUnwind): frames in kz2.exe as exe:<address>
 * at image base 0x140000000 (resolve with addr2line/nm on the exe), others as <dll>+<offset>. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#endif

extern "C" uint32_t cellGcmResolveIO(uint32_t offset);
extern uint8_t* vm_base;

namespace {

struct Region {
    bool io;
    uint32_t addr, size;   // addr: IO offset (io) or EA
    uint32_t ea;           // last resolved EA (0 = unmapped)
    uint64_t hash;
    bool seen;
    uint32_t pg_lo, pg_n;  // armed host pages (EA >> 12), 0 = not armed
};

Region g_r[4];
int g_n = -1;
int g_max = 400, g_lines;
int g_trap;
unsigned g_flip_last;
unsigned long long g_t0;

#ifdef _WIN32
unsigned long long now_ms() { return GetTickCount64(); }
#else
unsigned long long now_ms() { return 0; }
#endif

bool line_ok() { return g_lines < g_max; }

uint64_t fnv(const uint8_t* p, uint32_t n)
{
    uint64_t h = 1469598103934665603ull;
    for (uint32_t i = 0; i < n; i++) { h ^= p[i]; h *= 1099511628211ull; }
    return h;
}

void parse()
{
    g_n = 0;
    const char* e = getenv("KZ2_WATCH");
    if (const char* m = getenv("KZ2_WATCH_MAX")) g_max = atoi(m);
    if (const char* t = getenv("KZ2_WATCH_TRAP")) g_trap = atoi(t);
    if (!e || !*e) return;
    const char* p = e;
    while (*p && g_n < 4) {
        Region r = {};
        if (!strncmp(p, "io:", 3)) { r.io = true; p += 3; }
        else if (!strncmp(p, "ea:", 3)) p += 3;
        char* q;
        r.addr = (uint32_t)strtoul(p, &q, 16);
        if (*q != ':') break;
        r.size = (uint32_t)strtoul(q + 1, &q, 16);
        if (r.size == 0 || r.size > 0x100000u) break;
        g_r[g_n++] = r;
        p = q;
        if (*p == ',') p++;
    }
    g_t0 = now_ms();
    fprintf(stderr, "[kz2-watch] %d region(s), trap %d, max %d lines\n", g_n, g_trap, g_max);
}

uint32_t resolve(const Region& r)
{
    if (!r.io) return r.addr;
    const uint32_t ea = cellGcmResolveIO(r.addr);
    if (!ea) return 0;
    return cellGcmResolveIO(r.addr + r.size - 1) == ea + r.size - 1 ? ea : 0;   // whole span in one mapping
}

#ifdef _WIN32
/* ---- write trap ---- */
struct Rec { unsigned flip; uint32_t tid; uint64_t rip[4]; uint32_t ea; uint8_t after[16]; volatile LONG done; };
const int RING = 1024;
Rec g_ring[RING];
volatile LONG g_ring_w;
LONG g_ring_r;
volatile LONG g_outside;               // writes in armed pages outside every region
volatile LONG g_open[64];              // per armed page: threads stepping on it
uint32_t g_pages[64];                  // armed host pages (EA >> 12)
volatile LONG g_npages;
volatile LONG g_logged;
unsigned g_cur_flip;
uint64_t g_exe_base;
thread_local int t_page = -1;              // the armed page this thread is stepping over
thread_local int t_rec = -1;

int page_index(uint32_t pg)
{
    for (LONG i = 0; i < g_npages; i++) if (g_pages[i] == pg) return (int)i;
    return -1;
}

int region_of(uint32_t ea)
{
    for (int i = 0; i < g_n; i++)
        if (g_r[i].ea && ea >= g_r[i].ea && ea - g_r[i].ea < g_r[i].size) return i;
    return -1;
}

LONG WINAPI watch_veh(EXCEPTION_POINTERS* ep)
{
    EXCEPTION_RECORD* er = ep->ExceptionRecord;
    if (er->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && vm_base && er->NumberParameters >= 2 &&
        er->ExceptionInformation[0] == 1) {
        const uintptr_t a = er->ExceptionInformation[1], base = (uintptr_t)vm_base;
        if (a < base || a - base >= 0x100000000ull) return EXCEPTION_CONTINUE_SEARCH;
        const uint32_t ea = (uint32_t)(a - base);
        const int pi = page_index(ea >> 12);
        if (pi < 0) return EXCEPTION_CONTINUE_SEARCH;
        InterlockedIncrement(&g_open[pi]);
        DWORD old;
        VirtualProtect(vm_base + ((uint64_t)g_pages[pi] << 12), 0x1000, PAGE_READWRITE, &old);
        t_page = pi; t_rec = -1;
        if (region_of(ea) >= 0) {
            if (InterlockedIncrement(&g_logged) <= g_trap) {
                const LONG w = InterlockedIncrement(&g_ring_w) - 1;
                Rec& r = g_ring[w % RING];
                r.done = 0; r.flip = g_cur_flip; r.tid = GetCurrentThreadId(); r.ea = ea;
                /* The writer and up to 3 callers (a store inside memcpy/memset in a CRT DLL names its caller
                 * only one frame up): RtlVirtualUnwind on a copy of the faulting context. */
                CONTEXT c = *ep->ContextRecord;
                for (int f = 0; f < 4; f++) {
                    r.rip[f] = c.Rip;
                    if (f == 3) break;
                    DWORD64 img = 0;
                    PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(c.Rip, &img, NULL);
                    if (!fn) { c.Rip = *(DWORD64*)c.Rsp; c.Rsp += 8; continue; }   // leaf: return address on top
                    void* hd = NULL; DWORD64 est = 0;
                    RtlVirtualUnwind(UNW_FLAG_NHANDLER, img, c.Rip, fn, &c, &hd, &est, NULL);
                    if (!c.Rip) { for (int g = f + 1; g < 4; g++) r.rip[g] = 0; break; }
                }
                t_rec = (int)(w % RING);
            }
        } else {
            InterlockedIncrement(&g_outside);
        }
        ep->ContextRecord->EFlags |= 0x100;   // trap flag: come back after the store
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    if (er->ExceptionCode == EXCEPTION_SINGLE_STEP && t_page >= 0) {
        const int pi = t_page; t_page = -1;
        if (t_rec >= 0) {
            Rec& r = g_ring[t_rec];
            memcpy(r.after, vm_base + (r.ea & ~15u), 16);
            InterlockedExchange(&r.done, 1);
            t_rec = -1;
        }
        if (InterlockedDecrement(&g_open[pi]) == 0) {
            DWORD old;
            VirtualProtect(vm_base + ((uint64_t)g_pages[pi] << 12), 0x1000, PAGE_READONLY, &old);
        }
        ep->ContextRecord->EFlags &= ~0x100u;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

/* Arm (or re-arm after a remap) the host pages of every resolved region. */
void arm()
{
    static bool veh;
    if (!veh) {
        veh = true;
        g_exe_base = (uint64_t)GetModuleHandleA(NULL);
        AddVectoredExceptionHandler(1, watch_veh);
    }
    for (int i = 0; i < g_n; i++) {
        Region& r = g_r[i];
        if (!r.ea) continue;
        const uint32_t lo = r.ea >> 12, hi = (r.ea + r.size - 1) >> 12;
        for (uint32_t pg = lo; pg <= hi; pg++) {
            int pi = page_index(pg);
            if (pi < 0) {
                if (g_npages >= 64) break;
                g_pages[g_npages] = pg; pi = (int)g_npages; InterlockedIncrement(&g_npages);
            }
            if (g_open[pi]) continue;
            MEMORY_BASIC_INFORMATION mbi;
            void* hp = vm_base + ((uint64_t)pg << 12);
            if (!VirtualQuery(hp, &mbi, sizeof mbi)) continue;
            if (mbi.State != MEM_COMMIT) {   // demand-commit first (main.cpp vm_commit_veh commits 64 KB on access)
                VirtualAlloc((void*)((uintptr_t)hp & ~(uintptr_t)0xFFFF), 0x10000, MEM_COMMIT, PAGE_READWRITE);
            }
            if (mbi.Protect != PAGE_READONLY) {
                DWORD old;
                if (VirtualProtect(hp, 0x1000, PAGE_READONLY, &old) && line_ok()) {
                    g_lines++;
                    fprintf(stderr, "[kz2-watch] trap armed on page ea 0x%08X (region %d)\n", pg << 12, i);
                }
            }
        }
    }
}

void drain(unsigned flip)
{
    while (g_ring_r < g_ring_w) {
        Rec& r = g_ring[g_ring_r % RING];
        if (!r.done) break;
        g_ring_r++;
        if (!line_ok()) continue;
        g_lines++;
        const int ri = region_of(r.ea);
        fprintf(stderr, "[kz2-watch] write flip %u region %d ea 0x%08X (+0x%X) tid %u after", r.flip, ri, r.ea,
                ri >= 0 ? r.ea - g_r[ri].ea : 0, r.tid);
        for (int k = 0; k < 16; k++) fprintf(stderr, " %02X", r.after[k]);
        fprintf(stderr, " at");
        for (int f = 0; f < 4 && r.rip[f]; f++) {   // exe frames as kz2.exe addresses, others as module+offset
            HMODULE m = NULL; char name[64] = "?";
            if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   (LPCSTR)(uintptr_t)r.rip[f], &m) && m) {
                char full[260]; DWORD n = GetModuleFileNameA(m, full, sizeof full);
                const char* b = full + n; while (b > full && b[-1] != '\\' && b[-1] != '/') b--;
                snprintf(name, sizeof name, "%s", n ? b : "?");
            }
            if ((uint64_t)(uintptr_t)m == g_exe_base) fprintf(stderr, " exe:0x%llX", (unsigned long long)(r.rip[f] - g_exe_base + 0x140000000ull));
            else fprintf(stderr, " %s+0x%llX", name, (unsigned long long)(r.rip[f] - (uint64_t)(uintptr_t)m));
        }
        fprintf(stderr, "\n");
    }
    (void)flip;
}
#endif

#ifdef _WIN32
void scan_words(unsigned flip)
{
    const char* e = getenv("KZ2_WATCH_SCAN");
    if (!e || !*e) return;
    uint32_t want[8]; int nw = 0;
    for (const char* p = e; *p && nw < 8;) {
        char* q; const uint32_t v = (uint32_t)strtoul(p, &q, 16);
        if (q == p) break;
        want[nw++] = v; p = *q == ',' ? q + 1 : q;
    }
    int hits = 0; uint64_t bytes = 0;
    for (uint64_t a = 0x10000; a < 0xC0000000ull && hits < 40;) {
        MEMORY_BASIC_INFORMATION mbi;
        if (!VirtualQuery(vm_base + a, &mbi, sizeof mbi)) break;
        const uint64_t rb = (uint64_t)((uint8_t*)mbi.BaseAddress - vm_base), re = rb + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
            bytes += re - a;
            for (uint64_t x = a; x + 4 <= re && hits < 40; x += 4) {
                const uint8_t* b = vm_base + x;
                const uint32_t w = ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
                for (int k = 0; k < nw; k++) if (w == want[k]) {
                    hits++;
                    fprintf(stderr, "[kz2-watch] scan flip %u: 0x%08X at ea 0x%08llX:", flip, w, (unsigned long long)x);
                    for (int64_t o = -32; o <= 32; o += 4) {
                        const int64_t y = (int64_t)x + o;
                        if (y < (int64_t)rb || y + 4 > (int64_t)re) continue;
                        const uint8_t* c = vm_base + y;
                        fprintf(stderr, "%s%08X", o == 0 ? " [" : " ", ((uint32_t)c[0] << 24) | ((uint32_t)c[1] << 16) | ((uint32_t)c[2] << 8) | c[3]);
                        if (o == 0) fprintf(stderr, "]");
                    }
                    fprintf(stderr, "\n");
                }
            }
        }
        a = re;
    }
    fprintf(stderr, "[kz2-watch] scan flip %u: %d hit(s) in %llu MB committed\n", flip, hits, (unsigned long long)(bytes >> 20));
}
#endif

}  // namespace

extern "C" void kz2_watch_poll(unsigned flip)
{
    if (g_n < 0) parse();
    if (g_n == 0 || !vm_base) return;
    g_flip_last = flip;
#ifdef _WIN32
    g_cur_flip = flip;
#endif
    const double t = (now_ms() - g_t0) / 1000.0;
    for (int i = 0; i < g_n; i++) {
        Region& r = g_r[i];
        const uint32_t ea = resolve(r);
        const uint8_t* p = ea ? vm_base + ea : nullptr;
#ifdef _WIN32
        if (p) {   // a page the trap holds read-only is still readable; an uncommitted one would commit on read
            MEMORY_BASIC_INFORMATION mbi;
            if (!VirtualQuery(p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT) p = nullptr;
        }
#endif
        const uint64_t h = p ? fnv(p, r.size) : 0;
        const bool changed = !r.seen || ea != r.ea || h != r.hash;
        if ((changed || flip % 500u == 0) && line_ok()) {
            g_lines++;
            uint32_t nz = 0, first = 0xFFFFFFFFu;
            if (p) for (uint32_t k = 0; k < r.size; k++) if (p[k]) { nz++; if (first == 0xFFFFFFFFu) first = k; }
            fprintf(stderr, "[kz2-watch] %s flip %u t=%.1fs region %d %s 0x%08X ea 0x%08X hash %016llX nonzero %u/%u",
                    changed ? "change" : "same", flip, t, i, r.io ? "io" : "ea", r.addr, ea, (unsigned long long)h, nz, r.size);
            if (first != 0xFFFFFFFFu) {
                const uint32_t o = first & ~15u;
                fprintf(stderr, " first@+0x%X:", o);
                for (uint32_t k = o; k < o + 16 && k < r.size; k++) fprintf(stderr, " %02X", p[k]);
            }
            fprintf(stderr, "\n");
        }
        r.seen = true; r.ea = ea; r.hash = h;
    }
#ifdef _WIN32
    {   // KZ2_WATCH_SCAN: once, KZ2_WATCH_SCAN_AT flips after region 0 first resolves
        static unsigned at = 0; static bool done;
        if (!done && g_r[0].ea) {
            if (!at) { const char* s2 = getenv("KZ2_WATCH_SCAN_AT"); at = flip + (s2 ? (unsigned)atoi(s2) : 100u); }
            if (flip >= at) { done = true; scan_words(flip); }
        }
    }
    if (g_trap > 0) { arm(); drain(flip); }
    static unsigned long long last_out;
    if (g_trap > 0 && flip % 500u == 0 && g_outside != (LONG)last_out && line_ok()) {
        g_lines++; last_out = (unsigned long long)g_outside;
        fprintf(stderr, "[kz2-watch] flip %u: %ld writes so far into armed pages outside the regions\n", flip, (long)g_outside);
    }
#endif
}
