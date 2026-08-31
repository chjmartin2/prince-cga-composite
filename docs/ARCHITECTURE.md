# Architecture

## Components

### Prince DAT Explorer

`editor/` is a standard-library-only Python/Tk application. It reads Prince
1.3 DAT archives, displays VGA/EGA/CGA/composite interpretations, edits Mode-6
bitstreams, and stores phase-aware authoring state in schema-v6 `.pdcproj`
sidecars.

The sidecar is the recoverable authoring source. An ordinary patched DAT can
contain only one selected fallback image for each resource.

### DOS runtime patch

`runtime/build_v15c.py` through `runtime/build_v20.py` form an incremental,
deterministic build chain. Each version validates the exact input hashes and
binary signatures before patching.

V19L consumes the complete verified V19K package and swaps one conditional
branch in the dedicated health-icon helper. The ordinary mapper and every DAT
table remain byte-identical to V19K.

V20U consumes the complete verified V19L package and changes only moving-sword
resources 701-734 in `PRINCE.DAT`. It deliberately adds no runtime selector or
phase bank: each frame contains one exact shared pattern optimized over P0 and
P2, constrained to the source palette's representable CGA codes. DOSBox visual
testing confirmed this shared treatment, including the colored hilt frames, so
selective sword variants are unnecessary.

The working phase-table layout is:

| Native slot | File | Purpose |
| ---: | --- | --- |
| 3 | `PHASE.DAT` | First 73 source-image families, three alternates each. |
| 4 | `PHASE2.DAT` | Next 73 source-image families, three alternates each. |
| 9 | `PHASE3.DAT` | Final 73 KID image families, including HP and hurt. |

For moving Prince body images, normal right/P0 remains in `KID.DAT`. Each
phase table supplies right/P2, left/P0, and left/P2 aliases. Runtime selection
depends on direction and final screen X parity.

### Local binary inputs

The build chain relies on original/derived DOS binaries under `runtime/work/`,
`runtime/work_v14/`, `runtime/source_work/`, and generated predecessors under
`runtime/build/`. They are included in the local handoff but ignored by Git.

Do not relocate these directories without updating and testing every builder's
path constants.
