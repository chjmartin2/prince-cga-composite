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
- Treat V20U as the current DOSBox-confirmed moving-sword baseline. Its shared
  P0/P2 sword patterns need no runtime variants. Preserve V19L underneath it.
- Treat V20V as the current statically verified loader candidate. It changes
  only command-tail forwarding and awaits DOSBox confirmation.
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

- `editor/`: Prince DAT Explorer v0.4.27 source and tests.
- `runtime/`: deterministic V15C-through-V20V build scripts and local inputs.
- `runtime/build/`: ignored local generated packages, including verified V19K,
  statically verified V19L/V20V, and DOSBox-confirmed V20U.
- `docs/`: architecture, status-supporting notes, and workflows.
- `releases/`: ignored local release ZIPs.

## Current next runtime task

First confirm both `CGA4K2V.COM` and `CGA4K2V.COM improved` in DOSBox. The V20U
moving sword remains confirmed underneath V20V. Then continue with guard-family
graphics; the skeleton audit indicates its black/white silhouettes may also
work with one shared treatment rather than runtime phase variants.
