#!/usr/bin/env python3
"""Host test for tools/release/vm_test.py (the Windows VM kit's steps): the parts that do not need Windows, on fake
trees with no game data: 02-verify (kit hashes, game file presence, dump fingerprint), 10-leftovers (user data versus
caches, the dump fingerprint), 08-readonly's deny (file creation on the install folder only, removed after, the launch
still run), the RESULT line and exit codes, a crash turned into a FAIL, a cp1252 console.

    python3 tools/release/test_vm_test.py
"""
import contextlib
import hashlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vm_test as vt  # noqa: E402

FAILS = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond else f"\n     {str(detail)[:600]}"))
    if not cond:
        FAILS.append(what)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def step(base, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = vt.main([*args, "--base", base])
    return rc, buf.getvalue()


def make_base(tmp):
    base = os.path.join(tmp, "kz2")
    kit = os.path.join(base, "kit")
    write(os.path.join(kit, vt.SETUP), b"setup")
    write(os.path.join(kit, "vm_test.py"), b"script")
    with open(os.path.join(kit, "SHA256SUMS.txt"), "w") as f:
        for n in (vt.SETUP, "vm_test.py"):
            f.write(f"{hashlib.sha256(open(os.path.join(kit, n), 'rb').read()).hexdigest()}  {n}\n")
    dump, update, eboot = vt.game_paths(base)
    for p in (os.path.join(dump, "PS3_GAME", "PARAM.SFO"), os.path.join(dump, "PS3_GAME", "USRDIR", "data_ps3.psarc"),
              os.path.join(update, "PARAM.SFO"), os.path.join(update, "USRDIR", "EBOOT.BIN"),
              os.path.join(update, "USRDIR", "added_data_ps3.psarc"), eboot):
        write(p)
    os.makedirs(os.path.join(update, "USRDIR", "patch_data_ps3"))
    return base


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = make_base(tmp)
        out = os.path.join(base, "out")
        # 02-verify: the free-space floor is 6 GiB; the test filesystem may have less, so lower it via disk_usage
        real_du = vt.shutil.disk_usage
        vt.shutil.disk_usage = lambda p: real_du(p)._replace(free=100 * 2**30)
        try:
            rc, text = step(base, "02-verify")
            check(rc == 0 and "RESULT 02-verify PASS 2 kit files ok" in text, "02-verify passes on a full fake kit", text)
            check(os.path.isfile(os.path.join(out, "02-verify.txt")), "the step writes out\\02-verify.txt")
            st = vt.json.load(open(os.path.join(out, "state.json")))
            check(st.get("dump_fp", [0])[0] == 2, "the dump fingerprint counts the dump's files", st)
            write(os.path.join(base, "kit", "vm_test.py"), b"changed")
            os.remove(vt.game_paths(base)[2])
            rc, text = step(base, "02-verify")
            check(rc == 1 and "1 kit file(s) differ, 1 game file(s) missing" in text, "02-verify fails on a changed "
                  "kit file and a missing EBOOT", text)
            vt.shutil.disk_usage = lambda p: real_du(p)._replace(free=1 * 2**30)
            write(os.path.join(base, "kit", "vm_test.py"), b"script")
            write(vt.game_paths(base)[2])
            rc, text = step(base, "02-verify")
            check(rc == 1 and "GiB free" in text, "02-verify fails on too little disk", text)
        finally:
            vt.shutil.disk_usage = real_du

        # 10-leftovers: a fake APPDATA with saves and settings passes; a cache left behind fails; a changed dump fails
        appdata = os.path.join(tmp, "Roaming")
        os.environ.update(APPDATA=appdata, LOCALAPPDATA=os.path.join(tmp, "Local"), USERPROFILE=tmp)
        data = os.path.join(appdata, vt.APP)
        write(os.path.join(data, "gamedata", "BCUS98116-SAVE", "SYS-DATA"))
        write(os.path.join(data, "keybinds.ini"))
        st["dump_fp"] = vt.fingerprint(vt.game_paths(base)[0])
        st.pop("inst", None)
        vt.json.dump(st, open(os.path.join(out, "state.json"), "w"))
        rc, text = step(base, "10-leftovers")
        check(rc == 0 and "only user data left" in text, "10-leftovers passes with saves and .ini only", text)
        write(os.path.join(data, "scratch", "rsx_shader_cache_v3", "a.bin"))
        write(os.path.join(tmp, "Local", "Programs", vt.APP, "build", "kz2.exe"))
        rc, text = step(base, "10-leftovers")
        check(rc == 1 and "not user data left in the data folder: scratch" in text and "install folder not empty" in text,
              "10-leftovers names a cache and an install folder left behind", text)
        write(os.path.join(vt.game_paths(base)[0], "PS3_GAME", "NEW.TXT"))
        rc, text = step(base, "10-leftovers")
        check(rc == 1 and "the dump changed" in text, "10-leftovers notices a changed dump", text)

        # 08-readonly: icacls denies only "create files" on the install folder itself (no (OI)/(CI) inheritance, no
        # write or delete rights), the launch still runs, and the deny is removed even when the launch raises
        inst = os.path.join(tmp, "inst")
        os.makedirs(os.path.join(inst, "logs"))
        st = vt.json.load(open(os.path.join(out, "state.json")))
        st["inst"] = inst
        vt.json.dump(st, open(os.path.join(out, "state.json"), "w"))
        calls, launched = [], []
        real = (vt.shutil.which, vt.run, vt.launch_once, vt.reg_install_dir)
        vt.shutil.which = lambda n: "icacls" if n == "icacls" else real[0](n)
        vt.run = lambda st_, argv, *x, **k: (calls.append(list(argv)), (0, 0.0, ""))[1]
        vt.reg_install_dir = lambda: ""
        os.environ["USERNAME"] = "tester"
        try:
            vt.launch_once = lambda st_, i, w, tag: (launched.append((i, tag)), (True, 0))[1]
            rc, text = step(base, "08-readonly")
            deny = [c for c in calls if "/deny" in c]
            check(rc == 0 and "RESULT 08-readonly PASS" in text, "08-readonly passes when kz2.exe starts", text)
            check(deny == [["icacls", inst, "/deny", "tester:(WD)"]], "08 denies only file creation, not inherited", calls)
            check(not any(x in str(deny) for x in ("(OI)", "(CI)", "W,", "(W)", ",D")), "08's deny has no write, delete "
                  "or inheritance flags", deny)
            check(launched == [(inst, "08")], "08 still runs the launch", launched)
            check(calls[-1] == ["icacls", inst, "/remove:d", "tester"], "08 removes the deny after the launch", calls)
            calls.clear()
            vt.launch_once = lambda *x: (False, 1)
            rc, text = step(base, "08-readonly")
            check(rc == 1 and "RESULT 08-readonly FAIL" in text, "08 fails when kz2.exe does not start", text)
            calls.clear()
            vt.launch_once = lambda *x: 1 / 0
            rc, text = step(base, "08-readonly")
            check(rc == 1 and calls and calls[-1][2] == "/remove:d", "08 removes the deny when the launch crashes", calls)
        finally:
            vt.shutil.which, vt.run, vt.launch_once, vt.reg_install_dir = real

        # A cp1252 console (cmd.exe over ssh) cannot encode U+FFFD: after safe_console() printing it does not raise
        real_out = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        try:
            vt.safe_console()
            print("tool output with \ufffd and \u2192")
            sys.stdout.flush()
            ok = True
        except UnicodeEncodeError:
            ok = False
        finally:
            sys.stdout = real_out
        check(ok, "a cp1252 console gets U+FFFD without a UnicodeEncodeError")

        # A crash is a FAIL with its reason
        real = vt.FUNCS["05-checks"]
        vt.FUNCS["05-checks"] = lambda st, a: 1 / 0
        try:
            rc, text = step(base, "05-checks")
        finally:
            vt.FUNCS["05-checks"] = real
        check(rc == 1 and "RESULT 05-checks FAIL vm_test crashed: ZeroDivisionError" in text, "a crash ends in FAIL", text)
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
