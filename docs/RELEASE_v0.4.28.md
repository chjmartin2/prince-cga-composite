# Prince DAT Explorer v0.4.28

Prince DAT Explorer v0.4.28 adds whole-archive Mode-6 GIF interchange for
moving graphics between the DAT editor and external art tools. From the
Composite editor's Image menu, one command exports every editable 1-bit or
4-bit resource and another imports a folder back into the phase-aware project.

Single-phase resources use simple numeric names such as `54.gif`. Multi-phase
families use complete sets such as `751_P0.gif` and `751_P2.gif`. Import may
contain any subset of resource families, but it validates every included
filename, resource ID, required phase, dimension, palette, transparency mask,
and inverse CGA mapping before changing the project. The complete folder import
is committed as one undoable action.

## Downloads

- `Prince-DAT-Explorer-v0.4.28-Standalone-Windows-x64.zip` is the simplest
  Windows package. Extract the complete folder and run
  `PrinceDATExplorer.exe`; Python does not need to be installed.
- `Prince-DAT-Explorer-v0.4.28-Python.zip` contains the complete editor source,
  tests, documentation, standalone-launcher source, and packaging instructions.
  Run `PrinceDATViewer.pyw` with Python 3.10 or newer.
- `Prince-DAT-Explorer-v0.4.28-SHA256SUMS.txt` authenticates both archives.

The editor contains no Prince of Persia executable, DAT archive, or game
artwork. Open archives from your own legally obtained DOS Prince of Persia 1.3
installation. The Windows executable is not code-signed and may trigger a
SmartScreen warning.

The complete editor test suite passes: 175 tests. The standalone package also
passes reproducible-build comparison, archive CRC checks, per-file checksum
generation, x64 PE validation, an isolated bundled-Python/Tk import test, and a
fresh-extraction Windows GUI launch test.

## SHA-256

```text
42d622275e355562e654730524180e3d6d21980d7073c11f9aefd6e37def9f82  Prince-DAT-Explorer-v0.4.28-Python.zip
65bf58570ee479bfba1c7cbc80e9edce69dcffe91c447a093d06435d18ddf976  Prince-DAT-Explorer-v0.4.28-Standalone-Windows-x64.zip
```
