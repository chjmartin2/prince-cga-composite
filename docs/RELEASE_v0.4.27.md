# Prince DAT Explorer v0.4.27

Prince DAT Explorer v0.4.27 adds true full-width NTSC Composite previewing,
phase-aware comparison and editing improvements, transparency-aware Mode-6 GIF
round trips, and direct opaque-white, opaque-black, and transparent painting.
The transparency display color is user-selectable and is never written into a
DAT archive.

The exact composite encoder can restrict its search to the CGA codes available
through the selected resource's translation palette. Phase-aware project files
retain every enabled or disabled P0-P3 variant and their shared authored mask.

## Downloads

- `Prince-DAT-Explorer-v0.4.27-Standalone-Windows-x64.zip` is the simplest
  Windows package. Extract the complete folder and run
  `PrinceDATExplorer.exe`; Python does not need to be installed.
- `Prince-DAT-Explorer-v0.4.27-Python.zip` contains the complete editor source,
  tests, documentation, standalone-launcher source, and packaging instructions.
  Run `PrinceDATViewer.pyw` with Python 3.10 or newer.
- `Prince-DAT-Explorer-v0.4.27-SHA256SUMS.txt` authenticates both archives.

The editor contains no Prince of Persia executable, DAT archive, or game
artwork. Open archives from your own legally obtained DOS Prince of Persia 1.3
installation. The Windows executable is not code-signed and may trigger a
SmartScreen warning.

The complete editor test suite passes: 169 tests. The standalone package also
passes archive CRC checks, per-file checksum generation, x64 PE validation,
and an isolated bundled-Python/Tk import smoke test.

## SHA-256

```text
defc1735d81bb46622bf0ce2911bef44f487629153b36d4aeeeaecb791fdff68  Prince-DAT-Explorer-v0.4.27-Python.zip
c6745f4ac5f199d20259c0f7a35f52c94e0cf2f81aa19b0a51ff71739dc640d7  Prince-DAT-Explorer-v0.4.27-Standalone-Windows-x64.zip
```
