# Project Pyrrhus: Windows VM installer test

Run in the guest as the normal user, one line at a time, from cmd.exe (an ssh session lands there). Python is
called by its full path (`python` and `py` may be the Microsoft Store stubs). Each step writes
`C:\kz2\out\NN-name.txt` and ends with `RESULT NN-name PASS|FAIL|SKIP <why>`. When done (or at the first FAIL), send
back the whole `C:\kz2\out` folder. Needs about 20 GB free on C:. A FAIL stops the run unless the line says otherwise.

1. Copy the kit and the game files to a local folder (the share is slow and breaks junctions):
   `powershell -NoProfile -Command "New-Item -ItemType Directory -Force C:\kz2\out | Out-Null; robocopy <SHARE> C:\kz2 /E /R:2 /W:5 /NP /NFL /NDL /LOG:C:\kz2\out\01-copy.txt; $rc = $LASTEXITCODE; Add-Content C:\kz2\out\01-copy.txt ('robocopy exit ' + $rc); 'robocopy exit ' + $rc"`
   PASS: robocopy exit 0 to 7. FAIL: 8 or more.
2. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 02-verify`
   Checks the kit's SHA-256 list, the game files and the free space; notes Windows, cores, RAM.
   PASS: `RESULT 02-verify PASS`. FAIL: a kit file differs, a game file is missing, or under 6 GB free.
3. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 03-install`
   Silent per-user install to the default folder (`%LOCALAPPDATA%\Programs\Project Pyrrhus`), no build:
   `Project-Pyrrhus-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=... /MERGETASKS=!buildnow`.
   PASS: setup exit 0, the uninstall entry and the main files present. Expected: under a minute, no window.
4. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 04-layout`
   Every installed file against the payload's own list (manifest.json), the Start menu entries, the settings file.
   PASS: 0 problems, Start menu entries present.
5. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 05-checks`
   The first-run file checks on the copied game files. PASS: every line OK or WARN, `first-run checks: pass`.
6. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 06-build`
   The first-run build (translate and compile) with 2 jobs for 8 GB RAM. Expected: tens of minutes; the console
   shows nothing until the end. PASS: `kz2.exe` and the build stamp present, and the launcher would now start the
   game. Its log: `out\06-firstrun.log`.
7. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 07-launch`
   Starts `Project Pyrrhus.exe` once, watches its processes and windows for 60 s, then ends them by process id.
   Expected without a GPU: the game stops at Direct3D 12 device creation (a WARP fallback is still to come), and the
   launcher shows "The game stopped unexpectedly". PASS: `kz2.exe` started; a device-creation stop is not a FAIL.
   Go on to step 8 even on FAIL.
8. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 08-readonly`
   The same start with the install folder denied to this user for writing (icacls, restored afterwards).
   Facts only: which writes into the install folder fail. PASS or SKIP; go on either way.
9. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 09-uninstall`
   Silent uninstall (`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`). PASS: the uninstall entry is gone.
10. `"C:\Program Files\Python312\python.exe" C:\kz2\kit\vm_test.py 10-leftovers`
   PASS: the install folder, shortcuts and uninstall entry are gone; `%APPDATA%\Project Pyrrhus` holds only saves
   and settings (or nothing); the game files are unchanged.

To repeat a step, run its line again (it overwrites its file). Steps 07 and 08 open windows; in an ssh session
without a desktop they may not show, and the step's file then lists no window titles.
