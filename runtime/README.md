# Runtime Builders

The scripts `build_v15c.py` through `build_v19.py` form the preserved,
incremental runtime build chain. Run them from this directory or invoke them by
path from the repository root.

Local input and output directories are deliberately excluded from Git:

- `work/`: V15B input package.
- `work_v14/`: confirmed V14 reference package.
- `source_work/`: original/private DAT inputs and the retained V13 optimizer.
- `build/`: generated V15C-V19K packages and visual verification.

The handoff ZIP includes those local files so development can continue
immediately, but `git status` will not offer to push them.

See `../docs/RUNTIME_BUILD.md` and `../PROJECT_STATUS.md` before modifying a
runtime hook or phase mapping.

