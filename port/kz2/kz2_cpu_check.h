/* Killzone 2: CPU check for the -mfma SPU build (kz2_cpu_check.c). */
#ifndef KZ2_CPU_CHECK_H
#define KZ2_CPU_CHECK_H
#ifdef __cplusplus
extern "C" {
#endif

#define KZ2_CPU_MISSING_AVX    0x1u
#define KZ2_CPU_MISSING_FMA    0x2u
#define KZ2_CPU_MISSING_OS_AVX 0x4u /* no OSXSAVE, or XCR0 lacks the SSE+AVX state bits */
#define KZ2_CPU_MISSING_FORCED 0x8u /* KZ2_CPU_CHECK_FAIL set */

unsigned kz2_cpu_check_eval(unsigned cpuid1_ecx, unsigned long long xcr0);
unsigned kz2_cpu_check_host(void);
unsigned kz2_cpu_check_run(void);

#ifdef __cplusplus
}
#endif
#endif
