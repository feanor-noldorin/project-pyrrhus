# FFmpeg's LGPL decoders for kz2.exe, as Windows x64 DLLs beside the exe.
#
# kz2.exe never links FFmpeg: ps3recomp's PS3RECOMP_FFMPEG_RUNTIME path (libs/codec/ffmpeg_runtime.c) opens
# avutil-61.dll and avcodec-63.dll with LoadLibrary the first time a decoder opens, and checks that the majors match
# the headers it was built against. This builds exactly those two DLLs (plus the headers the build needs) from the
# FFmpeg release the flake's nixpkgs pins (FFmpeg n9.0.1, the nixpkgs-pinned source pkgs.ffmpeg.src), with the
# MinGW-w64 cross compiler of `nix develop .#win`. SOURCE.txt names that source (URL, tag, hash) from the derivation.
#
# Licence: LGPL-2.1-or-later only. No --enable-gpl, no --enable-version3, no --enable-nonfree; --disable-autodetect
# keeps every external library out (zlib, iconv, SDL, hardware APIs...), so the DLLs contain FFmpeg's own code only.
# The build fails unless FFmpeg's own config.h says "LGPL version 2.1 or later" with CONFIG_GPL 0 and
# CONFIG_NONFREE 0. Decoders: h264 (the intro GameIntro_PS3.avi and cellVdec AVC), mpeg2video (cellVdec MPEG-2),
# ac3 (the intro's 5.1 track through cellAdec).
#
# Build (needs the network once, for the source tag and nasm, so run it outside the sandbox):
#   nix build --impure -o work/ffmpeg-win --expr \
#     'import ./tools/runtime/ffmpeg-lgpl-win.nix { pkgs = import (builtins.getFlake "git+file://<checkout, %20 for spaces>").inputs.nixpkgs { system = "x86_64-linux"; }; }'
#   (a git+file flake ref: a plain path ref copies the whole checkout, work/ included, into the store and fails).
# Output: bin/avcodec-63.dll bin/avutil-61.dll, include/, share/ffmpeg-lgpl/{COPYING.LGPLv2.1,LICENSE-build.txt,SOURCE.txt}.
{ pkgs }:
let
  win = pkgs.pkgsCross.mingwW64;
  ff = pkgs.ffmpeg;   # version and source tag pinned by flake.lock (9.0.1 at the time of writing)
  # The source pointer for SOURCE.txt, taken from the fetcher (fetchgit: url; fetchurl: urls).
  srcUrl = ff.src.url or (builtins.head (ff.src.urls or [ "unknown" ]));
in
win.stdenv.mkDerivation {
  pname = "ffmpeg-lgpl-kz2-win";
  inherit (ff) version src;
  # Build-machine tools: nasm for the x86 assembly; FFmpeg's configure also compiles and runs small host programs
  # with its --host-cc (default "cc", which the cross environment lacks: "Host compiler lacks C11 support"), so the
  # native compiler comes in through depsBuildBuild. No pkg-config: --disable-autodetect looks for no library.
  depsBuildBuild = [ pkgs.buildPackages.stdenv.cc ];
  nativeBuildInputs = [ pkgs.buildPackages.nasm ];
  # FFmpeg's configure is not autoconf: no --build/--host, its own cross switches instead.
  configurePlatforms = [ ];
  postPatch = "patchShebangs --build configure ffbuild";
  configureFlags = [
    "--enable-cross-compile" "--target-os=mingw32" "--arch=x86_64" "--cross-prefix=x86_64-w64-mingw32-"
    "--host-cc=${pkgs.buildPackages.stdenv.cc}/bin/cc"
    "--enable-shared" "--disable-static"
    "--disable-autodetect" "--enable-w32threads" "--disable-network"
    "--disable-programs" "--disable-doc" "--disable-debug"
    "--disable-avdevice" "--disable-avformat" "--disable-avfilter" "--disable-swscale" "--disable-swresample"
    "--disable-everything"
    "--enable-decoder=h264,mpeg2video,ac3"
    "--enable-parser=h264,mpegvideo,ac3"
  ];
  enableParallelBuilding = true;
  postInstall = ''
    grep -q '#define FFMPEG_LICENSE "LGPL version 2.1 or later"' config.h
    grep -q '#define CONFIG_GPL 0' config.h
    grep -q '#define CONFIG_NONFREE 0' config.h
    grep -q '#define CONFIG_VERSION3 0' config.h
    d=$out/share/ffmpeg-lgpl; mkdir -p $d
    cp COPYING.LGPLv2.1 $d/
    { grep -E '#define (FFMPEG_LICENSE|FFMPEG_CONFIGURATION|CONFIG_GPL|CONFIG_NONFREE|CONFIG_VERSION3) ' config.h; } > $d/LICENSE-build.txt
    printf 'FFmpeg %s, source %s tag %s (%s), homepage %s, LGPL-2.1-or-later, built unmodified by tools/runtime/ffmpeg-lgpl-win.nix\n' \
      ${ff.version} ${srcUrl} ${ff.src.rev or "n${ff.version}"} ${ff.src.outputHash or "no hash"} ${ff.meta.homepage or "-"} > $d/SOURCE.txt
    rm -rf $out/lib/pkgconfig $out/share/ffmpeg/examples
  '';
}
