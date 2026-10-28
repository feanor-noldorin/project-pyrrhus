#!/usr/bin/env python3
"""Windows VM test of the Project Pyrrhus installer, one step per command. Standard library only,
Python 3.8+; runs on the guest's own Python (3.12 in the test VM) and, for the pre-flight, on the bundled embeddable
Python under Wine/Proton (tools/release/vm_kit.sh preflight).

    "C:\\Program Files\\Python312\\python.exe" vm_test.py STEP [--base C:\\kz2] [--jobs 2] [--wait 60]

Folders under --base: kit\\ (setup exe, this script, SHA256SUMS.txt), game\\dump\\PS3_GAME, game\\update\\BCUS98116,
game\\eboot\\EBOOT.elf (the tester's own files) and out\\, where every step writes out\\NN-name.txt (all it prints)
plus its tool logs, and out\\state.json carries facts between steps. The last line of each step is
"RESULT NN-name PASS|FAIL|SKIP <why>"; the exit code is 0 for PASS and SKIP, 1 for FAIL.

Steps (in order; each can be re-run):
  02-verify     kit hashes against SHA256SUMS.txt, the game files present, machine facts, a fingerprint of the dump
  03-install    setup /VERYSILENT /SUPPRESSMSGBOXES /MERGETASKS="!buildnow" (per-user, default folder); the
                uninstall key and the main files present
  04-layout     the installed files against the payload's manifest.json (launch.py --print --repair), the shortcuts,
                kz2-install.ini, VERSION.txt
  05-checks     the first-run file checks (installed firstrun_check.py on the installed Python)
  06-build      the first-run build (installed firstrun.py, --jobs N, default 2 for an 8 GB guest); kz2.exe and the
                build stamp present; the launcher's decision is "run" afterwards
  07-launch     the launcher once ("Project Pyrrhus.exe"): processes and window titles for --wait seconds, then the
                started tree is ended by process id; the launcher's notes and the game's log tails. A game that stops
                at D3D12 device creation (no GPU in the guest) is expected here and still a PASS if kz2.exe started.
  08-readonly   the same start with the install folder's top level refusing new files for this user (icacls deny
                "create files" on the folder itself, no inheritance; restored after), as an install under Program
                Files would: the launcher and kz2.exe still start (logs\\ and build\\ stay writable); the step records
                which writes fail and that nothing (such as a vkd3d-proton cache) tried to land in the install folder.
                Facts only (SKIP where icacls is missing). A deny of all writes, inherited, also stopped the launch
                (VM run 2026-10-27), so it showed nothing about the cache.
  09-uninstall  unins000.exe /VERYSILENT /SUPPRESSMSGBOXES; waits until the uninstall key is gone
  10-leftovers  the install folder, the shortcuts and the key gone; what is left in %APPDATA%\\Project Pyrrhus is
                user data only (saves and settings, not caches); the dump unchanged (same fingerprint as 02)
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

APP = "Project Pyrrhus"
APP_ID = "{5C5D4C2E-8AE0-4446-BEC0-560BC45B6E20}"   # installer/kz2.iss AppId (never changes)
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID + "_is1"
SETUP = "Project-Pyrrhus-setup.exe"
LAUNCHER = APP + ".exe"
# What the uninstaller may leave in %APPDATA%\Project Pyrrhus: the player's saves and settings (cellSaveData's
# gamedata, the .ini files). Caches (cache\, scratch\, vkd3d-proton.cache*) and logs are not user data.
USER_DATA = ("gamedata",)
USER_DATA_EXT = (".ini",)
STEPS = ("02-verify", "03-install", "04-layout", "05-checks", "06-build", "07-launch", "08-readonly",
         "09-uninstall", "10-leftovers")


class Step:
    def __init__(self, base, name):
        self.base, self.name = base, name
        self.out = os.path.join(base, "out")
        os.makedirs(self.out, exist_ok=True)
        self.f = open(os.path.join(self.out, name + ".txt"), "w", encoding="utf-8", newline="\r\n")
        self.state_path = os.path.join(self.out, "state.json")
        try:
            with open(self.state_path, encoding="utf-8") as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        self.say(f"# {name} {datetime.datetime.now().isoformat(timespec='seconds')} base={base} "
                 f"python={sys.version.split()[0]}")

    def say(self, text=""):
        for line in str(text).splitlines() or [""]:
            print(line)
            self.f.write(line + "\n")
        self.f.flush()

    def save(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)

    def end(self, verdict, why=""):
        self.say(f"RESULT {self.name} {verdict} {why}".rstrip())
        self.f.close()
        return 1 if verdict == "FAIL" else 0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(st, argv, timeout, log_name=None, cwd=None, tail=40):
    """Run argv, keep its output in out\\<log_name> (and its last lines in the step file). -> (rc, seconds, text)."""
    st.say("$ " + subprocess.list2cmdline(argv))
    t0 = time.time()
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, cwd=cwd)
        rc, text = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        rc, text = "timeout", (e.stdout or b"").decode("utf-8", "replace")
    except OSError as e:
        rc, text = f"oserror {e}", ""
    secs = round(time.time() - t0, 1)
    if log_name:
        with open(os.path.join(st.out, log_name), "w", encoding="utf-8") as f:
            f.write(text)
    lines = text.splitlines()
    for line in lines[-tail:]:
        st.say("  " + line[:300])
    st.say(f"rc={rc} after {secs} s" + (f" (full output: out\\{log_name})" if log_name else ""))
    return rc, secs, text


def reg_install_dir():
    """The install folder from the per-user uninstall key, or ""."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0].rstrip("\\")
    except (ImportError, OSError):
        return ""


def default_install_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", APP)


def inst_dir(st):
    return reg_install_dir() or st.state.get("inst") or default_install_dir()


def data_dir():
    return os.path.join(os.environ.get("APPDATA", ""), APP)


def start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", APP)


def game_paths(base):
    g = os.path.join(base, "game")
    return (os.path.join(g, "dump"), os.path.join(g, "update", "BCUS98116"), os.path.join(g, "eboot", "EBOOT.elf"))


def fingerprint(root):
    """(files, bytes, newest mtime) of a tree; read-only (names, sizes and times only)."""
    n = b = 0
    newest = 0.0
    for d, _, files in os.walk(root):
        for f in files:
            try:
                s = os.stat(os.path.join(d, f))
            except OSError:
                continue
            n, b, newest = n + 1, b + s.st_size, max(newest, s.st_mtime)
    return [n, b, int(newest)]


def listing(st, root, limit=60, depth=2):
    """Relative paths under root down to `depth` levels, with sizes of files; at most `limit` lines."""
    if not os.path.isdir(root):
        st.say(f"  (no folder {root})")
        return []
    seen = []
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        lvl = 0 if rel == "." else rel.count(os.sep) + 1
        if lvl >= depth:
            dirs[:] = []
        for x in sorted(dirs):
            seen.append(os.path.join(rel, x).lstrip(".\\/") + "\\")
        for x in sorted(files):
            p = os.path.join(d, x)
            try:
                size = os.path.getsize(p)
            except OSError:
                size = -1
            seen.append(f"{os.path.join(rel, x).lstrip('.' + os.sep)}  {size:,}")
    for line in seen[:limit]:
        st.say("  " + line)
    if len(seen) > limit:
        st.say(f"  ... {len(seen) - limit} more")
    return seen


def mem_facts():
    """(total, available) RAM in bytes via GlobalMemoryStatusEx, or (0, 0)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys, m.ullAvailPhys
    except (ImportError, AttributeError, OSError):
        return 0, 0


def processes():
    """{pid: (parent pid, exe name)} via a Toolhelp32 snapshot (works on Windows and under Wine)."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def descendants(root_pid, procs):
    kids, todo = [], [root_pid]
    while todo:
        p = todo.pop()
        for pid, (ppid, _) in procs.items():
            if ppid == p and pid not in kids and pid != root_pid:
                kids.append(pid)
                todo.append(pid)
    return kids


def window_titles(pids):
    """Visible top-level window titles of the given processes: [(pid, title)]."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                found.append((pid.value, buf.value))
        return True
    u32.EnumWindows(proto(cb), 0)
    return found


def end_tree(st, pids):
    """End the given processes by id (children first)."""
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    for pid in reversed(pids):
        h = k32.OpenProcess(0x0001, False, pid)        # PROCESS_TERMINATE
        if h:
            k32.TerminateProcess(h, 1)
            k32.CloseHandle(h)
            st.say(f"  ended pid {pid}")


def tail_file(st, path, n=40, label=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        st.say(f"  (cannot read {path}: {e})")
        return []
    st.say(f"--- {label or path}: last {min(n, len(lines))} of {len(lines)} lines")
    for line in lines[-n:]:
        st.say("  " + line[:300])
    return lines


def newest(folder, pattern_ext=(".log", ".txt")):
    try:
        fs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(pattern_ext)]
    except OSError:
        return []
    return sorted(fs, key=os.path.getmtime)


def py_of(inst):
    return os.path.join(inst, "toolchain", "python", "python.exe")


# ---------------------------------------------------------------------------------------------------- the steps
def s_verify(st, a):
    kit = os.path.join(a.base, "kit")
    sums = os.path.join(kit, "SHA256SUMS.txt")
    bad = []
    try:
        lines = [x.split(None, 1) for x in open(sums, encoding="utf-8").read().splitlines() if x.strip()]
    except OSError as e:
        return st.end("FAIL", f"no {sums}: {e}")
    for h, name in lines:
        p = os.path.join(kit, name.strip().lstrip("*").replace("/", os.sep))
        got = sha256(p) if os.path.isfile(p) else "missing"
        st.say(f"  {'ok ' if got == h else 'BAD'} {name.strip()}  {os.path.getsize(p) if os.path.isfile(p) else 0:,}")
        if got != h:
            bad.append(name.strip())
    total, avail = mem_facts()
    du = shutil.disk_usage(a.base)
    st.say(f"windows {platform.version()} {platform.machine()}; cores {os.cpu_count()}; RAM {total / 2**30:.1f} GiB "
           f"(available {avail / 2**30:.1f}); free on {os.path.splitdrive(a.base)[0] or a.base}: {du.free / 2**30:.1f} GiB")
    dump, update, eboot = game_paths(a.base)
    need = [os.path.join(dump, "PS3_GAME", "PARAM.SFO"), os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"),
            os.path.join(update, "PARAM.SFO"), os.path.join(update, "USRDIR", "EBOOT.BIN"),
            os.path.join(update, "USRDIR", "added_data_ps3.psarc"), eboot]
    missing = [p for p in need if not os.path.isfile(p)]
    for p in need:
        st.say(f"  {'ok ' if p not in missing else 'MISSING'} {os.path.relpath(p, a.base)}"
               + (f"  {os.path.getsize(p):,}" if p not in missing else ""))
    pd = os.path.join(update, "USRDIR", "patch_data_ps3")
    st.say(f"  update patch_data_ps3: {len(os.listdir(pd)) if os.path.isdir(pd) else 'MISSING'} entries")
    st.state["dump_fp"] = fingerprint(dump)
    st.say(f"dump fingerprint (files, bytes, newest mtime): {st.state['dump_fp']}")
    st.save()
    if bad or missing:
        return st.end("FAIL", f"{len(bad)} kit file(s) differ, {len(missing)} game file(s) missing")
    if du.free < 6 * 2**30:
        return st.end("FAIL", f"only {du.free / 2**30:.1f} GiB free (install + build need about 6)")
    return st.end("PASS", f"{len(lines)} kit files ok, game files present")


def s_install(st, a):
    setup = os.path.join(a.base, "kit", SETUP)
    log = os.path.join(st.out, "03-inno-install.log")
    argv = [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}", "/MERGETASKS=!buildnow"]
    if a.dir:
        argv.append(f"/DIR={a.dir}")
    rc, secs, _ = run(st, argv, 1800)
    inst = reg_install_dir()
    st.say(f"uninstall key HKCU\\{UNINSTALL_KEY}: {'present, InstallLocation ' + inst if inst else 'MISSING'}")
    inst = inst or a.dir or default_install_dir()
    st.state.update(inst=inst, install_s=secs)
    st.save()
    have = {f: os.path.isfile(os.path.join(inst, f)) for f in (LAUNCHER, "unins000.exe", "manifest.json",
                                                                 "VERSION.txt", "kz2-install.ini")}
    for f, ok in have.items():
        st.say(f"  {'ok ' if ok else 'MISSING'} {f}")
    if rc != 0 or not all(have.values()) or not reg_install_dir():
        return st.end("FAIL", f"setup rc={rc}; see out\\03-inno-install.log")
    return st.end("PASS", f"installed in {secs} s to {inst}")


def s_layout(st, a):
    inst = inst_dir(st)
    rc, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                           "--print", "--repair"], 600, "04-launch-print.json", tail=0)
    try:
        rep = json.loads(text)
    except ValueError:
        return st.end("FAIL", "launch.py --print gave no JSON")
    chk = rep.get("repair", {})
    st.say(f"manifest check: {chk.get('checked')} files, {len(chk.get('problems', []))} problem(s); "
           f"launcher decision: {rep.get('action')} ({rep.get('reason')})")
    for p in chk.get("problems", [])[:20]:
        st.say("  " + p)
    st.say("top-level layout:")
    listing(st, inst, limit=40, depth=1)
    try:
        st.say("VERSION.txt: " + open(os.path.join(inst, "VERSION.txt"), encoding="utf-8").read().strip())
        st.say("kz2-install.ini:\n" + open(os.path.join(inst, "kz2-install.ini"), encoding="utf-8").read().strip())
    except OSError as e:
        st.say(f"  {e}")
    sm = start_menu_dir()
    st.say("start menu:")
    links = listing(st, sm, limit=20, depth=1)
    desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP + ".lnk")
    st.say(f"desktop shortcut: {'present' if os.path.isfile(desk) else 'missing'}")
    if rc != 0 or not chk.get("checked") or chk.get("problems") or not links:
        return st.end("FAIL", "install differs from manifest.json or no Start menu entries")
    return st.end("PASS", f"{chk['checked']} files match manifest.json; {len(links)} Start menu entries")


def s_checks(st, a):
    inst = inst_dir(st)
    dump, update, eboot = game_paths(a.base)
    rc, _, _ = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "firstrun_check.py"),
                        "--dump", dump, "--update", update, "--eboot", eboot], 600, "05-firstrun-check.txt")
    return st.end("PASS" if rc == 0 else "FAIL", "no FAIL line" if rc == 0 else "a check failed (see above)")


def s_build(st, a):
    inst = inst_dir(st)
    dump, update, eboot = game_paths(a.base)
    total, avail = mem_facts()
    st.say(f"RAM {total / 2**30:.1f} GiB, available {avail / 2**30:.1f} GiB; jobs {a.jobs}")
    rc, secs, _ = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "firstrun.py"), "--root", inst,
                           "--dump", dump, "--update", update, "--eboot", eboot,
                           "--toolchain", os.path.join(inst, "toolchain", "llvm-mingw"), "--jobs", str(a.jobs),
                           "--log-dir", st.out, "--log-name", "06-firstrun.log",
                           "--status-file", os.path.join(st.out, "06-status.txt")], a.build_timeout,
                      "06-firstrun-stdout.txt", tail=25)
    st.state["build_s"] = secs
    st.save()
    exe = os.path.join(inst, "build", "kz2.exe")
    stamp = os.path.join(inst, "build", "build-stamp.json")
    st.say(f"kz2.exe: {os.path.getsize(exe):,} bytes" if os.path.isfile(exe) else "kz2.exe: MISSING")
    st.say(f"build-stamp.json: {'present' if os.path.isfile(stamp) else 'MISSING'}")
    tail_file(st, os.path.join(st.out, "06-firstrun.log"), 30, "out\\06-firstrun.log")
    _, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                          "--print"], 300, "06-launch-print.json", tail=0)
    try:
        action = json.loads(text).get("action")
    except ValueError:
        action = None
    st.say(f"launcher decision after the build: {action}")
    try:
        st.say(f"build folder: {fingerprint(os.path.join(inst, 'build'))[1] / 2**30:.2f} GiB")
    except OSError:
        pass
    if rc != 0 or not os.path.isfile(exe) or not os.path.isfile(stamp) or action != "run":
        return st.end("FAIL", f"firstrun rc={rc} after {secs} s")
    return st.end("PASS", f"built in {secs / 60:.1f} min with {a.jobs} jobs")


def launch_once(st, inst, wait, tag):
    """Start the launcher, watch its process tree for `wait` seconds, end it. -> (saw kz2.exe, launcher rc)."""
    logs, glogs = os.path.join(inst, "logs"), os.path.join(inst, "build", "logs")
    before = set(newest(glogs))
    _, _, text = run(st, [py_of(inst), os.path.join(inst, "kz2-setup", "release", "launch.py"), "--root", inst,
                          "--print"], 300, f"{tag}-launch-print.json", tail=0)
    try:
        rep = json.loads(text)
        st.say(f"decision {rep.get('action')}; cwd {rep.get('cwd')}; game variables: "
               + ", ".join(f"{k}={v}" for k, v in sorted(rep.get("env", {}).items())))
    except ValueError:
        st.say("launch.py --print gave no JSON")
    p = subprocess.Popen([os.path.join(inst, LAUNCHER)], cwd=inst)
    st.say(f"started {LAUNCHER} pid {p.pid}")
    saw, kz2_pids, t0, last = False, set(), time.time(), ""
    tree = []
    while time.time() - t0 < wait:
        time.sleep(1)
        procs = processes()
        tree = descendants(p.pid, procs)
        names = sorted({procs[x][1] for x in tree if x in procs})
        for x in tree:
            if procs.get(x, (0, ""))[1].lower() == "kz2.exe":
                saw = True
                kz2_pids.add(x)
        titles = window_titles(set(tree) | {p.pid})
        line = f"{names} windows {[t for _, t in titles]}"
        if line != last:
            st.say(f"  t={time.time() - t0:5.1f} s  processes {line}")
            last = line
        if p.poll() is not None:
            st.say(f"  launcher ended with code {p.returncode} (0x{p.returncode & 0xFFFFFFFF:08X}) at "
                   f"t={time.time() - t0:.1f} s")
            break
    procs = processes()
    tree = [x for x in descendants(p.pid, procs)]
    if p.poll() is None:
        end_tree(st, tree + [p.pid])
    else:
        end_tree(st, tree)
    try:
        p.wait(20)
    except subprocess.TimeoutExpired:
        pass
    for f in newest(logs)[-2:]:
        tail_file(st, f, 15, "install logs\\" + os.path.basename(f))
    new = [f for f in newest(glogs) if f not in before]
    if new:
        saw = True      # kz2.exe writes this log itself: it started even if it ended before a process sample
        lines = tail_file(st, new[-1], 40, "build\\logs\\" + os.path.basename(new[-1]))
        dev = [x for x in lines if "D3D12" in x or "device" in x.lower() or "WARP" in x or "[CRASH]" in x]
        for x in dev[:10]:
            st.say("  device line: " + x[:300])
    else:
        st.say(f"no new game log in {glogs}")
    st.say(f"data folder {data_dir()}:")
    listing(st, data_dir(), limit=30, depth=2)
    return saw, p.returncode


def s_launch(st, a):
    inst = inst_dir(st)
    saw, rc = launch_once(st, inst, a.wait, "07")
    if not saw:
        return st.end("FAIL", "the launcher did not start kz2.exe")
    return st.end("PASS", "kz2.exe started (a stop at D3D12 device creation without a GPU is expected)")


# 08: deny only "create files / write data" (WD) on the install folder itself. No (OI)/(CI): the ACE is not inherited,
# so existing files and every subfolder (logs\, build\, build\logs\) keep their rights and the launch runs.
READONLY_ACE = "(WD)"


def s_readonly(st, a):
    inst = inst_dir(st)
    user = os.environ.get("USERNAME", "")
    icacls = shutil.which("icacls")
    if not icacls or not user:
        return st.end("SKIP", "no icacls or USERNAME here")
    before = set(os.listdir(inst)) if os.path.isdir(inst) else set()
    rc, _, _ = run(st, [icacls, inst, "/deny", f"{user}:{READONLY_ACE}"], 300, tail=5)
    if rc != 0:
        return st.end("FAIL", "icacls could not deny file creation")
    try:
        for where, folder in (("install folder", inst), ("logs\\ below it", os.path.join(inst, "logs"))):
            probe = os.path.join(folder, "write-probe.txt")
            try:
                os.makedirs(folder, exist_ok=True)
                open(probe, "w").close()
                os.remove(probe)
                st.say(f"write probe, {where}: a new file can be created")
            except OSError as e:
                st.say(f"write probe, {where}: no new file ({e.__class__.__name__})")
        saw, rc2 = launch_once(st, inst, a.wait, "08")
    finally:
        run(st, [icacls, inst, "/remove:d", user], 300, tail=3)
    after = set(os.listdir(inst)) if os.path.isdir(inst) else set()
    new = sorted(after - before - {"write-probe.txt"})
    st.say(f"new entries in the install folder during the start: {new or 'none'}")
    if not saw:
        return st.end("FAIL", "the launcher did not start kz2.exe with the install folder closed to new files")
    return st.end("PASS", "kz2.exe started with the install folder closed to new files (facts above)")


def s_uninstall(st, a):
    inst = inst_dir(st)
    unins = os.path.join(inst, "unins000.exe")
    if not os.path.isfile(unins):
        return st.end("FAIL", f"no {unins}")
    run(st, [unins, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             "/LOG=" + os.path.join(st.out, "09-inno-uninstall.log")], 900)
    t0 = time.time()
    while reg_install_dir() and time.time() - t0 < 600:     # the uninstaller re-starts itself from %TEMP%
        time.sleep(2)
    while os.path.isfile(unins) and time.time() - t0 < 600:
        time.sleep(2)
    gone = not reg_install_dir()
    st.say(f"uninstall key: {'gone' if gone else 'STILL PRESENT'} after {time.time() - t0:.0f} s of waiting")
    return st.end("PASS" if gone else "FAIL", "uninstalled" if gone else "the uninstall key stayed")


def s_leftovers(st, a):
    inst = st.state.get("inst") or default_install_dir()
    problems = []
    st.say(f"install folder {inst}:")
    left = listing(st, inst, limit=40, depth=3)
    if left:
        problems.append(f"install folder not empty ({len(left)} entries)")
    if os.path.isdir(start_menu_dir()):
        problems.append("Start menu folder still there")
    if os.path.isfile(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP + ".lnk")):
        problems.append("desktop shortcut still there")
    if reg_install_dir():
        problems.append("uninstall key still there")
    st.say(f"data folder {data_dir()} (user data may stay; caches and logs should not):")
    listing(st, data_dir(), limit=40, depth=2)
    if os.path.isdir(data_dir()):
        for x in os.listdir(data_dir()):
            p = os.path.join(data_dir(), x)
            if x in USER_DATA or (os.path.isfile(p) and x.lower().endswith(USER_DATA_EXT)):
                continue
            problems.append(f"not user data left in the data folder: {x}")
    dump = game_paths(a.base)[0]
    fp = fingerprint(dump)
    st.say(f"dump fingerprint now {fp}, at 02-verify {st.state.get('dump_fp')}")
    if st.state.get("dump_fp") and fp != st.state["dump_fp"]:
        problems.append("the dump changed")
    for p in problems:
        st.say("  PROBLEM " + p)
    return st.end("FAIL" if problems else "PASS", "; ".join(problems) or "only user data left (or nothing)")


FUNCS = dict(zip(STEPS, (s_verify, s_install, s_layout, s_checks, s_build, s_launch, s_readonly, s_uninstall,
                         s_leftovers)))


def safe_console():
    """The console may be cp1252 (cmd.exe over ssh): a character it cannot show (U+FFFD from a tool's output) crashed
    a step there (VM run). Print UTF-8 where the stream allows it, else replace; the out\\ files stay UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--base", default="C:\\kz2")
    ap.add_argument("--dir", default="", help="install folder for 03-install (default: setup's per-user default)")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--wait", type=int, default=60, help="seconds to watch the launcher in 07/08")
    ap.add_argument("--build-timeout", type=int, default=4 * 3600)
    a = ap.parse_args(argv)
    st = Step(a.base, a.step)
    try:
        return FUNCS[a.step](st, a)
    except Exception as e:   # noqa: BLE001 (a crash is a FAIL with its reason, never a silent stop)
        import traceback
        st.say(traceback.format_exc())
        return st.end("FAIL", f"vm_test crashed: {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
