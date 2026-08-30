# Runtime Build Workflow

Run commands from the repository root using the `.venv` Python interpreter.

## Rebuild the existing V19K output

The handoff includes the verified V18 predecessor, so the focused rebuild is:

```powershell
.\.venv\Scripts\python.exe runtime\build_v19.py
```

This is intentionally exhaustive and may take time. The builder validates
source hashes, mappings, transparency, binary hooks, resource counts, visual
verification output, and deterministic packaging.

## Rebuild the full incremental chain

```powershell
.\.venv\Scripts\python.exe runtime\build_v15c.py
.\.venv\Scripts\python.exe runtime\build_v16.py
.\.venv\Scripts\python.exe runtime\build_v17.py
.\.venv\Scripts\python.exe runtime\build_v18.py
.\.venv\Scripts\python.exe runtime\build_v19.py
```

Each later builder imports constants and helpers from its predecessor. Preserve
the filenames and execution order.

## Runtime acceptance

Static verification is necessary but not sufficient. A new version is not
confirmed until tested in DOSBox in both directions, at adjacent X positions,
through level transitions, restarts, cinematics, and the affected motion or HUD
path.

