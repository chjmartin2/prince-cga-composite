# Codex Project Instructions

## Project goal

Develop and preserve the phase-aware New-CGA composite graphics conversion for
DOS Prince of Persia 1.3, together with Prince DAT Explorer.

## Start every task here

1. Read `PROJECT_STATUS.md`.
2. Read the relevant document under `docs/` before changing runtime mappings,
   DAT generation, editor phase behavior, or packaging.
3. Inspect `git status --short` and preserve unrelated user changes.

## Working rules

- Treat V18F as the confirmed body-animation baseline.
- Treat V19K as the current runtime baseline with one known defect: the Prince
  health icons are internally consistent but use the wrong absolute phase.
- Do not claim a DOS runtime change works until Chris tests it in DOSBox.
- Never overwrite original game archives. Write generated files beneath
  `runtime/build/` or another explicitly named output directory.
- Do not commit or upload original game binaries, DAT archives, generated game
  packages, or release ZIPs. The root `.gitignore` intentionally excludes them.
- Keep every runtime build deterministic and verify expected SHA-256 hashes,
  DAT structure, resource counts, executable signatures, and ZIP integrity.
- Preserve confirmed phase tables byte-for-byte unless the task explicitly
  changes their mapped resources.
- Give each shipped runtime or editor change a new version identifier and add
  it to `CHANGELOG.md` and `PROJECT_STATUS.md`.
- Run the editor's complete unit suite after editor changes:
  `python -m unittest discover -s tests -v` from `editor/`.
- Prefer focused changes. Document any newly discovered engine mapping or
  architectural constraint under `docs/`.

## Repository map

- `editor/`: Prince DAT Explorer v0.4.22 source and tests.
- `runtime/`: deterministic V15C-through-V19K build scripts and local inputs.
- `runtime/build/`: ignored local generated packages, including verified V19K.
- `docs/`: architecture, status-supporting notes, and workflows.
- `releases/`: ignored local release ZIPs.

## Current next runtime task

When Chris resumes the parked KID cleanup, create V19L by swapping only the
health-icon absolute-phase rule. Leave the confirmed hurt splash and all V18
motion mappings untouched. Reconfirm in DOSBox before tagging it as fixed.

