#!/usr/bin/env bash
# Run a command inside a bubblewrap sandbox.
#
#   tools/sandbox.sh [--gpu] [--net] [--ro PATH]... -- <command> [args...]
#
# Inside the sandbox:
#   - /nix (store) is read-only, the game disc ($KZ2_ROOT/Game) is read-only,
#   - only $KZ2_ROOT/work and $KZ2_ROOT/build are writable,
#   - the rest of the repo is read-only, $HOME is an empty tmpfs,
#   - no network (unless --net), no access to the user's display, audio or sessions,
#   - --gpu exposes the NVIDIA device nodes + /run/opengl-driver (for Vulkan/RPCS3 runs).
#   - --ro PATH binds an extra host path read-only at the same location (e.g. a Proton install).
#   - --x11 (main checkout only) exposes the X display :0
#     (Xwayland socket) as $KZ2_REAL_DISPLAY; still no network, no audio, no D-Bus.
# Run it from inside `nix develop` so the tools are on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPU=0 NET=0
EXTRA_RO=()
X11=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) GPU=1; shift ;;
    --net) NET=1; shift ;;
    --ro) EXTRA_RO+=("$2"); shift 2 ;;
    --x11) X11=1; shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[[ $# -gt 0 ]] || { echo "usage: $0 [--gpu] [--net] -- cmd..." >&2; exit 2; }


mkdir -p "$ROOT/work" "$ROOT/build"

args=(
  --die-with-parent --new-session
  --unshare-all
  --ro-bind /nix /nix
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind-try /etc/ssl /etc/ssl
  --ro-bind-try /etc/static/ssl /etc/static/ssl
  --ro-bind /run/current-system/sw /run/current-system/sw
  --ro-bind-try /usr/bin/env /usr/bin/env
  --ro-bind-try /bin/sh /bin/sh
  --proc /proc --dev /dev --tmpfs /tmp
  --tmpfs "$HOME"
  --ro-bind "$ROOT" "$ROOT"
  --bind "$ROOT/work" "$ROOT/work"
  --bind "$ROOT/build" "$ROOT/build"
  --chdir "$ROOT"
  --setenv HOME "$HOME"
  --setenv KZ2_ROOT "$ROOT"
  --setenv KZ2_GAME "$ROOT/Game"
  --setenv KZ2_WORK "$ROOT/work"
  --unsetenv DISPLAY --unsetenv WAYLAND_DISPLAY
  --unsetenv PULSE_SERVER --unsetenv DBUS_SESSION_BUS_ADDRESS
  --setenv PATH "$PATH"
  --setenv TMPDIR /tmp --setenv TMP /tmp --setenv TEMP /tmp --setenv TEMPDIR /tmp
)
# Game is read-only. When Game is a symlink (for example, the dump lives on another disk) bwrap cannot
# mount over a symlink, so bind the real target read-only at its own path and let the link resolve.
if [[ -L "$ROOT/Game" ]]; then
  G="$(readlink -f "$ROOT/Game")"; [[ -e "$G" ]] && args+=(--ro-bind "$G" "$G")
elif [[ -e "$ROOT/Game" ]]; then
  args+=(--ro-bind "$ROOT/Game" "$ROOT/Game")
fi
[[ $NET -eq 1 ]] && args+=(--share-net)
# Shared lock files: .kz2-lockdir names a lock directory outside the repo (e.g. one shared
# with another project, so both queue on one GPU); it is bound writable. Nothing else outside the repo is bound.
LOCKMAIN="$ROOT"; [[ -f "$ROOT/.kz2-main" ]] && LOCKMAIN="$(cat "$ROOT/.kz2-main")"
EXT_LOCKS="$(cat "$LOCKMAIN/.kz2-lockdir" 2>/dev/null || true)"
[[ -n "$EXT_LOCKS" && -d "$EXT_LOCKS" ]] && args+=(--bind "$EXT_LOCKS" "$EXT_LOCKS" --setenv KZ2_LOCK_DIR "$EXT_LOCKS")
# (KZ2_LOCK_DIR is set inside so build/lift scripts in a second worktree, which cannot see the main checkout's root and
# its .kz2-lockdir, still take the shared slots.)
for p in "${EXTRA_RO[@]}"; do args+=(--ro-bind "$(readlink -f "$p")" "$p"); done
if [[ $X11 -eq 1 ]]; then
  [[ -S /tmp/.X11-unix/X0 ]] || { echo "sandbox: no X display socket /tmp/.X11-unix/X0" >&2; exit 2; }
  args+=(--bind /tmp/.X11-unix/X0 /tmp/.X11-unix/X0 --setenv KZ2_REAL_DISPLAY :0)
fi
if [[ $GPU -eq 1 ]]; then
  args+=(--ro-bind /run/opengl-driver /run/opengl-driver)
  for d in /dev/nvidia* /dev/dri; do [[ -e $d ]] && args+=(--dev-bind "$d" "$d"); done
  args+=(--ro-bind-try /sys /sys)
fi

# Low priority by default: everything run here gets the lowest CPU and I/O priority, so other heavy work on the machine
# (e.g. a second project sharing the GPU) wins any contention. KZ2_NICE=0 turns it off (for speed measurements).
if [[ "${KZ2_NICE:-1}" == 1 ]]; then exec nice -n 15 ionice -c2 -n7 bwrap "${args[@]}" -- "$@"; fi
exec bwrap "${args[@]}" -- "$@"
