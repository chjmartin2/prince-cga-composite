# Prince CGA Composite

Development workspace for the phase-aware New-CGA composite conversion of DOS
*Prince of Persia 1.3* and the Prince DAT Explorer editor.

## Current baselines

- Runtime: **V21** has confirmed princess-room flame colors; **V21D** is the
  current statically verified candidate. It preserves V21B's outward torch
  spacing and leaves the three decoded gameplay phase banks unloaded on level
  14, retaining conventional memory for the final reunion.
- Editor source: **Prince DAT Explorer v0.5.1**. Its V22 Runtime Workspace
  links original actor DATs to complete right/P0 and left/P0 `ORIENT.DAT`
  artwork; legacy phase-aware `.pdcproj`
  sidecars retain all stored P0-P3 variants, and the editor can export the
  project's enabled variants as a full-NTSC phase-verification contact sheet.

See `PROJECT_STATUS.md` before making changes.

## Download Prince DAT Explorer

Download the current editor from the
[Prince DAT Explorer v0.5.1 release](https://github.com/chjmartin2/prince-cga-composite/releases/tag/v0.5.1).
Choose the standalone Windows x64 ZIP for the simplest setup, or the Python ZIP
to run from source. The standalone executable is not code-signed, so Windows
may display a SmartScreen warning.

The editor contains no Prince of Persia game files. It opens archives from a
copy of DOS *Prince of Persia 1.3* supplied by the user and always writes
patched archives as new files. This release is the graphics editor and
phase-aware authoring tool; it is not yet the planned one-click utility that
converts a complete game installation to the composite version.

## First-time Windows setup

1. Clone the repository or download and extract it into a folder of your choice.
   Ensure this `README.md` is directly inside the repository root.
2. Double-click `SETUP_WINDOWS.bat`. It creates a local Python virtual
   environment and runs the editor tests.
3. Double-click `OPEN_IN_VSCODE.bat`.
4. Accept VS Code's recommended extensions, including Codex and Python.
5. Open the Codex sidebar, sign in, and begin with:

```text
Read AGENTS.md and PROJECT_STATUS.md, then summarize the current project state.
```

Codex automatically reads the root `AGENTS.md` when opened in this Git
repository. Official setup guidance: [Codex in VS Code](https://learn.chatgpt.com/docs/codex/ide)
and [AGENTS.md instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Prince 1.3 CGA memory atlas

The [interactive memory atlas](docs/prince-1.3-cga-memory-map/memory-map.html)
and [technical report](docs/prince-1.3-cga-memory-map/REPORT.md) document how
the original US 1.3 executable uses conventional memory across startup,
levels, sound configurations, cutscenes, and the final reunion. The directory
also contains a level/cutscene-selectable DAT block map with hover details and
resource links, the machine-readable model, static shareable SVG, reproducible
analysis tools, and sanitized DOSBox trace evidence.

Download the complete source-only package as
[`prince-1.3-cga-memory-map.zip`](docs/prince-1.3-cga-memory-map/prince-1.3-cga-memory-map.zip?raw=1)
and verify it with the adjacent
[SHA-256 file](docs/prince-1.3-cga-memory-map/prince-1.3-cga-memory-map.zip.sha256).

## Useful VS Code tasks

Open **Terminal -> Run Task** and choose:

- `Editor: run all tests`
- `Editor: launch`
- `Runtime: rebuild V20U from V19L`
- `Runtime: verify V20U ZIP`

The runtime build chain is tracked. Required local binary inputs and generated
outputs are ignored by Git and must be supplied locally.

## Repository safety

Generated and copyrighted game files are excluded. Before committing, confirm
the Source Control view contains no `.DAT`, `.EXE`, `.COM`, or release ZIP
files. See `docs/GITHUB_SAFETY.md` for the complete publication checklist.

## Main folders

- `editor/` - v0.5.1 source, documentation, and 192-test suite.
- `runtime/` - V15C-V21D deterministic builders and local build baselines.
- `docs/` - architecture, runtime build notes, and GitHub safety guidance.
- `releases/` - local editor release ZIPs, excluded from Git.
