#!/usr/bin/env python3
"""Test-only (wizard_test.sh `launcher`): lay out an installed Project Pyrrhus in a Proton prefix so the real
Project Pyrrhus.exe finds a finished build and starts the game: the payload tree, the launcher exe, the stand-in
python (pyshim.exe) as toolchain\\python\\pythonw.exe and python.exe, build\\kz2.exe from a staged game folder, and
paths.json + build-stamp.json computed with launch.py's own functions so decide() answers "run".
Never ships; the paths are Linux paths because the stand-in interpreter is the Linux python (see winpy.py)."""
import argparse, json, os, shutil, sys

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--payload", required=True)
ap.add_argument("--launcher", required=True)
ap.add_argument("--pyshim", required=True)
ap.add_argument("--game", required=True, help="folder with kz2.exe and its DLLs, PS3_GAME/")
ap.add_argument("--ini", default="")
a = ap.parse_args()
root = os.path.abspath(a.root)
if os.path.isdir(root):
    shutil.rmtree(root)
shutil.copytree(a.payload, root, symlinks=True)
shutil.copyfile(a.launcher, os.path.join(root, "Project Pyrrhus.exe"))
for n in ("pythonw.exe", "python.exe"):
    os.makedirs(os.path.join(root, "toolchain", "python"), exist_ok=True)
    shutil.copyfile(a.pyshim, os.path.join(root, "toolchain", "python", n))
b = os.path.join(root, "build")
os.makedirs(b, exist_ok=True)
for n in ("kz2.exe", "at3_standalone.dll"):
    shutil.copyfile(os.path.join(a.game, n), os.path.join(b, n))
rel = os.path.join(root, "kz2-setup", "release")
for f in os.listdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):   # the real scripts (the payload may hold fixtures)
    if f.endswith(".py"):
        shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f), os.path.join(rel, f))
sys.path.insert(0, rel)
import firstrun as fr, launch as L   # the payload's own copies
# the port is lifted from the 1.29 update: its folder (RPCS3's layout, <game>/dev_hdd0/game/<id>) and EBOOT.elf
upd = os.path.join(os.path.abspath(a.game), "dev_hdd0", "game", "BCUS98116")
eboot = os.path.join(upd, "USRDIR", "EBOOT.elf")
paths = {"dump": os.path.abspath(a.game), "update": upd, "eboot": eboot, "facts": {}}
json.dump(paths, open(os.path.join(b, "paths.json"), "w"))
json.dump({"parts": L.ctx_for(root, paths).parts(), "eboot_stat": fr.eboot_stat(eboot)},
          open(os.path.join(b, "build-stamp.json"), "w"))
if a.ini:
    shutil.copyfile(a.ini, os.path.join(root, "kz2-install.ini"))
print("staged", root, "->", L.decide(root))
