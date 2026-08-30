# Prince CGA Composite

Private development workspace for the phase-aware New-CGA composite conversion
of DOS *Prince of Persia 1.3* and the Prince DAT Explorer editor.

## Current baselines

- Runtime: **V19K**. All 219 KID images have stored phase-aware graphics.
- Editor: **Prince DAT Explorer v0.4.22**. Phase-aware `.pdcproj` sidecars retain
  all stored P0-P3 variants.
- Known runtime issue: the Prince health icons are visually consistent with one
  another but use the wrong absolute composite phase. The narrow V19L correction
  is intentionally parked.

See `PROJECT_STATUS.md` before making changes.

## First-time Windows setup

This folder is intended to live at:

```text
C:\Users\chjmartin2\code\prince-cga-composite
```

1. Extract the handoff ZIP so this `README.md` is directly inside that folder.
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

## Useful VS Code tasks

Open **Terminal -> Run Task** and choose:

- `Editor: run all tests`
- `Editor: launch`
- `Runtime: rebuild V19K from V18`
- `Runtime: verify V19K ZIP`

The runtime build chain and local binary inputs are present in this handoff but
ignored by Git so they cannot be pushed accidentally.

## Publish to a private GitHub repository

After opening in VS Code:

1. Select **Source Control**.
2. Choose **Publish Branch** or **Publish to GitHub**.
3. Select **Private repository**.
4. Use the name `prince-cga-composite`.

The repository already has an initial local Git commit. Generated and
copyrighted game files are excluded; confirm the Source Control view contains
no `.DAT`, `.EXE`, `.COM`, or release ZIP files before publishing.

## Main folders

- `editor/` - v0.4.22 source, documentation, and 151-test suite.
- `runtime/` - V15C-V19K deterministic builders and local build baselines.
- `docs/` - architecture, runtime build notes, and GitHub safety guidance.
- `releases/` - local editor release ZIPs, excluded from Git.

