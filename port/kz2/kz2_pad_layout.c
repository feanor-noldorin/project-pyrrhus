/* KZ2_PAD_LAYOUT: see kz2_pad_layout.h. ENHANCEMENT: the Modern preset is the port's
 * (tools/assets/pad_layouts.py MODERN); `original` (the launcher's default) and unset change
 * nothing for a profile that never held the Modern map. */
#include "kz2_pad_layout.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>

static int ieq(const char* a, const char* b)
{
    for (; *a && *b; a++, b++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return 0;
    return *a == *b;
}

int kz2_pad_layout_parse(const char* s)
{
    if (!s || !*s || ieq(s, "original")) return KZ2_PAD_ORIGINAL;
    if (ieq(s, "modern")) return KZ2_PAD_MODERN;
    return -1;
}

int kz2_pad_layout_mode(void)
{
    static int mode = -2;
    if (mode == -2) {
        const char* e = getenv("KZ2_PAD_LAYOUT");
        int m = kz2_pad_layout_parse(e);
        if (m < 0) {
            fprintf(stderr, "[kz2-pad] KZ2_PAD_LAYOUT=%s not understood (original|modern): original\n", e);
            m = KZ2_PAD_ORIGINAL;
        }
        fprintf(stderr, "[kz2-pad] pad layout %s (KZ2_PAD_LAYOUT)\n", m == KZ2_PAD_MODERN ? "modern" : "original");
        mode = m;
    }
    return mode;
}

int kz2_pad_layout_slot_ok(int32_t func)
{
    return func >= 0 && func < KZ2_PAD_NFUNC && func != 18 && kz2_pad_modern[func] != KZ2_PAD_NOT_SET;
}

int32_t kz2_pad_layout_set_button(int mode, int32_t func, int32_t button)
{
    if (mode != KZ2_PAD_MODERN || !kz2_pad_layout_slot_ok(func)) return button;
    return kz2_pad_modern[func];
}

int kz2_pad_layout_is_modern(const int32_t map[KZ2_PAD_NFUNC])
{
    for (int f = 0; f < KZ2_PAD_NFUNC; f++)
        if (kz2_pad_layout_slot_ok(f) && map[f] != kz2_pad_modern[f]) return 0;
    return 1;
}

int kz2_pad_layout_fix_map(int mode, int32_t map[KZ2_PAD_NFUNC], uint32_t scheme)
{
    const int8_t* want;
    if (mode == KZ2_PAD_MODERN) want = kz2_pad_modern;
    else if (kz2_pad_layout_is_modern(map)) want = kz2_pad_original[scheme < KZ2_PAD_NPRESETS ? scheme : 0];
    else return 0;
    int n = 0;
    for (int f = 0; f < KZ2_PAD_NFUNC; f++)
        if (kz2_pad_layout_slot_ok(f) && map[f] != want[f]) { map[f] = want[f]; n++; }
    return n;
}
