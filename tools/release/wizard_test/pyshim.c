/* Test stand-in for the payload's toolchain\python\python.exe (wizard_test.sh only; never shipped, never in a payload).
   The Proton prefix has no Windows Python and the sandbox has no network, so this runs the Linux python3 on the
   same arguments through winpy.py, which maps the Windows paths. KZ2_WT_LINUXPY and KZ2_WT_WINPY come from
   wizard_test.sh (Z:\ paths). */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
int main(void) {
  char py[MAX_PATH], wp[MAX_PATH];
  if (!GetEnvironmentVariableA("KZ2_WT_LINUXPY", py, sizeof py) || !GetEnvironmentVariableA("KZ2_WT_WINPY", wp, sizeof wp)) {
    fprintf(stderr, "pyshim: KZ2_WT_LINUXPY / KZ2_WT_WINPY not set\n"); return 90;
  }
  const char *cl = GetCommandLineA();
  FILE *lg = fopen("C:\\pyshim.log", "a");
  if (lg) { fprintf(lg, "run: %s\n", cl); fclose(lg); }
  const char *rest = cl;
  if (*rest == '"') { rest++; while (*rest && *rest != '"') rest++; if (*rest) rest++; }
  else while (*rest && *rest != ' ') rest++;
  /* Wine's launch of a Unix program returns at once, so winpy.py writes a marker file when it is done; wait for it */
  char done[MAX_PATH]; snprintf(done, sizeof done, "C:\\pyshim-%lu.done", (unsigned long)GetTickCount());
  DeleteFileA(done); SetEnvironmentVariableA("KZ2_WT_DONE", done);
  static char cmd[32768];
  snprintf(cmd, sizeof cmd, "\"%s\" \"%s\" --done=%s%s", py, wp, done, rest);
  STARTUPINFOA si = { sizeof si }; PROCESS_INFORMATION pi;
  if (!CreateProcessA(py, cmd, 0, 0, FALSE, 0, 0, 0, &si, &pi)) {
    lg = fopen("C:\\pyshim.log", "a"); if (lg) { fprintf(lg, "CreateProcess failed %lu\n", GetLastError()); fclose(lg); }
    fprintf(stderr, "pyshim: CreateProcess %lu\n", GetLastError()); return 91; }
  WaitForSingleObject(pi.hProcess, INFINITE);
  DWORD rc = 1, t0 = GetTickCount(); int found = 0;
  char wb[16]; int waits = 250;     /* KZ2_WT_WAIT=seconds: a launcher walk waits for the whole game session */
  if (GetEnvironmentVariableA("KZ2_WT_WAIT", wb, sizeof wb)) waits = atoi(wb) * 10;
  for (int i = 0; i < waits; i++) {   /* up to 25 s: the sandbox has no network and a name lookup can hang */
    FILE *d = fopen(done, "r");
    if (d) { int v = 1; if (fscanf(d, "%d", &v) == 1) rc = (DWORD)v; fclose(d); found = 1; break; }
    Sleep(100);
  }
  DeleteFileA(done);
  lg = fopen("C:\\pyshim.log", "a"); if (lg) { fprintf(lg, "rc %lu marker %d after %lu ms\n", rc, found, GetTickCount() - t0); fclose(lg); }
  return (int)rc;
}
