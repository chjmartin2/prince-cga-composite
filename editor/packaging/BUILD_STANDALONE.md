# Building the standalone Windows x64 bundle

The distribution uses the official CPython 3.12.10 Windows embeddable ZIP
(`python-3.12.10-embed-amd64.zip`, SHA-256
`4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`) and
the matching `amd64/tcltk.msi` from python.org. No packages from PyPI are part
of the runtime.

The bundle layout is fixed:

```text
PrinceDATExplorer.exe
app/PrinceDATViewer.pyw
app/*.py
runtime/pythonw.exe
runtime/python312.dll
runtime/python312.zip
runtime/python312._pth
runtime/_tkinter.pyd
runtime/tcl86t.dll
runtime/tk86t.dll
runtime/zlib1.dll
runtime/Lib/tkinter/
runtime/tcl/
```

Extract the embeddable ZIP into `runtime/`. Administratively extract the
matching Tcl/Tk MSI (`msiexec /a tcltk.msi /qn TARGETDIR=...`), then copy its
four DLL/PYD files, `Lib/tkinter/`, and `tcl/` as shown above. Replace the
default path file with the checked-in `python312._pth`.

The launcher has no C-runtime dependency. Zig 0.14.1 can cross-compile it on
Linux with:

```sh
zig cc -target x86_64-windows-gnu -O2 -fno-builtin \
  -Wall -Wextra -Werror -c windows_launcher.c -o windows_launcher.o
zig cc -target x86_64-windows-gnu -nostdlib \
  -Wl,--entry,launcher_entry -Wl,--subsystem,windows -Wl,--strip-all \
  windows_launcher.o -o PrinceDATExplorer.exe -lkernel32 -luser32
```

Before release, run the complete test suite, verify all PE files are x86-64,
confirm `_tkinter.pyd` resolves the bundled Tcl/Tk DLL names, checksum every
payload file, test the ZIP CRC, and launch the freshly extracted copy on
64-bit Windows.

From the repository root, `python scripts/build_editor_release.py --version
0.5.2` performs the deterministic assembly and checks. The prior verified
standalone archive supplies Tcl/Tk and runtime license files; the builder
always overlays and validates the official CPython embeddable archive so a
stale or damaged standard-library payload cannot be inherited.
