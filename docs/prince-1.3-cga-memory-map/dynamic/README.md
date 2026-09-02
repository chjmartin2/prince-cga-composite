# Prince 1.3 stock-DOSBox conventional-memory probe

This directory records a controlled dynamic measurement of the unmodified
DOS `PRINCE.EXE` 1.3 startup path.  The intended machine is CGA with 640 KiB
conventional memory, no XMS, no EMS, and no UMBs.  Three command-line sound
selections were tested: `STDSND`, `SBLAST`, and `MIDI`.

The important boundary is this: DOS sees Prince reserve almost all of the
remaining conventional-memory arena during startup.  Once the PC-speaker and
Sound-Blaster traces enter level 14, later DAT opens do **not** cause another
DOS `AH=48h`, `49h`, or `4Ah` call.  Level/scene resource turnover therefore
happens inside Prince's already-reserved far heap; an MCB map alone cannot
describe live resource occupancy.

## Evidence labels

- **Measured** means emitted by stock DOSBox, `MCBMAP.COM`, or the hooked DOS
  calls in `MEMTRACE.COM`.
- **Reconstructed** means calculated from measured MCB segments/sizes using
  DOS's one-paragraph MCB headers.
- **Inferred** means supported by both the trace and static executable control
  flow but not directly named by a runtime symbol.

## Chain of custody

No file under `C:\DOS\PRINCE13` or the installed DOSBox directory was changed.
The game was copied to ignored directories under `runtime/build/`, and only
the copied `CONFIG.DAT` was changed.

| File | Bytes | SHA-256 |
|---|---:|---|
| `C:\DOS\PRINCE13\PRINCE.EXE` | 125,115 | `24FDC79B4DE563348313B50D717E171919191E5C38559F5BDD6A4751D39B7158` |
| original `C:\DOS\PRINCE13\CONFIG.DAT` | 28 | `73D6A651F83B36673081FB14B51A233C71080CE381FF1F600F0E00D843FC134E` |
| CGA control-copy `CONFIG.DAT` | 28 | `FB0050F1D95A9727ED98847164DAADB5555C72E72637E8A2F945F5F5B71A801D` |
| installed `DOSBox.exe.bak` / isolated `DOSBox.exe` | 3,745,792 | `DCFD46FA521F5CE89DCE3BF026056F3A1D15533F80321EE887403E30D7949F5E` |
| installed `SDL.dll.bak` / isolated `SDL.dll` | 448,231 | `69037EBC43755296C0CC292D57D560028D7F2265F7B86CA84E714835C19BBD58` |
| installed `SDL_net.dll.bak` / isolated `SDL_net.dll` | 13,312 | `2F39DC04ACBECF47EFA45034891602B6EA7BF6FD2F27B5C0A5CA8D7FB155C929` |
| `stock-cga-640k.conf` | 958 | `70813789A2DD981523A5F6459B1EBB2C9AF9620D8291715FF86DFA59FFEE8955` |
| `MCBMAP.COM` | 834 | `091A53A32FF42FA14FFE37519A6791FAE9700BEA8A5A976BCF7DBB9BB0B82EC5` |
| `MEMTRACE.COM` | 1,413 | `F0FDC51AADE6D71FAD39DEC531BB37080555BA600742F2EAED3D24F28956BFA3` |

`DOSBox.exe.bak` reports file/product version `0.74.3.0`; its matching
`SDL.dll.bak` reports `1.2.13.0`.  The active installed `DOSBox.exe` is a
different SVN-era binary (3,862,528 bytes, SHA-256
`95253EF0250D2918A77CFB8B34EB130F7C500C272C988224DA0832816DC08EBF`),
and the active `SDL.dll` is also different.  A real stock control therefore
used copies of the three `.bak` files, with their normal names, in
`runtime/build/dosbox-stock-control/`.  Merely starting `DOSBox.exe.bak` next
to the replacement DLLs is not an authenticated stock pairing.

The installed user config was not used.  Its SHA-256 is
`B0C4A68385092CB77A6485907C151422D986078F1F34FC42C7E3F8461B5D297C`
and it requests `machine=vgaonly`, `xms=true`, `ems=true`, and `umb=true`.

### CONFIG.DAT control change

The 14 little-endian words were:

```text
original: 0005 0000 FFFF 0003 0003 0000 0000 0220 0000 0220 0000 0001 0001 0000
control:  0001 0000 FFFF 0003 0003 0000 0000 0220 0000 0220 0000 0001 0001 0000
```

The only byte difference is file offset 0, `05 -> 01`, selecting CGA.  Sound
and music remained words 3 and 4 (`0003`, `0003`); each run then used an
authenticated Prince command-line override.

## Effective DOSBox profile

`PROFILE.BAT` asked stock DOSBox to echo its effective values to
`PROFILE.TXT`:

```text
machine=cga       memsize=16
xms=false         ems=false         umb=false
mpu401=intelligent  mididevice=default
sbtype=sb16       sbbase=220        irq=7       dma=1       hdma=5
pcspeaker=true
```

The DOS environment exposed to Prince contains the measured line
`BLASTER=A220 I7 D1 T4` (captured in `DOSENV.TXT`).  This is kept separate
from the config echo above: it is the exact compatibility string emitted by
this stock DOSBox build, not a value inferred from the config text.

`memsize=16` is DOSBox's configured extended-memory size; it does not enlarge
the DOS conventional arena.  `INT 12h` measured exactly `0280h` = 640 KiB.

## Reproduction commands

The repository intentionally excludes prebuilt `.COM` files under its public
binary-safety policy. Rebuild the two probes from the tracked NASM sources
before creating a run directory:

```powershell
Set-Location docs/prince-1.3-cga-memory-map/dynamic
nasm -f bin -o MCBMAP.COM mcbmap.asm
nasm -f bin -o MEMTRACE.COM memtrace.asm
Set-Location ../../..
```

The hashes of the exact binaries used for this investigation remain in the
chain-of-custody table and `SHA256SUMS.txt`.

The isolated stock runtime was prepared once in PowerShell:

```powershell
$stock = 'runtime/build/dosbox-stock-control'
New-Item -ItemType Directory -Path $stock
Copy-Item 'C:\Program Files (x86)\DOSBox-0.74-3\DOSBox.exe.bak' "$stock/DOSBox.exe"
Copy-Item 'C:\Program Files (x86)\DOSBox-0.74-3\SDL.dll.bak' "$stock/SDL.dll"
Copy-Item 'C:\Program Files (x86)\DOSBox-0.74-3\SDL_net.dll.bak' "$stock/SDL_net.dll"
```

Each sound run was a fresh `Copy-Item -Recurse` clone of
`C:\DOS\PRINCE13`, with the one-byte CGA edit above and `MEMTRACE.COM` copied
in.  From its mounted clone the exact DOS commands were:

```powershell
$run = 'runtime/build/prince13-memory-probe/new-pcspeaker-run'
if (Test-Path -LiteralPath $run) { throw "Choose a new run directory: $run" }
Copy-Item -LiteralPath 'C:\DOS\PRINCE13' -Destination $run -Recurse
$configPath = Join-Path $run 'CONFIG.DAT'
$config = [IO.File]::ReadAllBytes($configPath)
if ($config.Length -ne 28 -or $config[0] -ne 5 -or $config[1] -ne 0) {
    throw 'Unexpected source CONFIG.DAT'
}
$config[0] = 1
[IO.File]::WriteAllBytes($configPath, $config)
Copy-Item -LiteralPath 'docs/prince-1.3-cga-memory-map/dynamic/MEMTRACE.COM' -Destination $run
```

```dos
MEMTRACE STDSND IMPROVED 14
MEMTRACE SBLAST IMPROVED 14
MEMTRACE MIDI IMPROVED 14
```

The corresponding host command shape was:

```powershell
$exe   = (Resolve-Path 'runtime/build/dosbox-stock-control/DOSBox.exe').Path
$conf  = (Resolve-Path 'docs/prince-1.3-cga-memory-map/dynamic/stock-cga-640k.conf').Path
$game  = (Resolve-Path 'runtime/build/prince13-memory-probe/pcspeaker-audio').Path
$args  = '-noconsole -conf "' + $conf + '" -c "mount c ' + $game + '" -c "c:" -c "MEMTRACE STDSND IMPROVED 14"'
$p = Start-Process -FilePath $exe -ArgumentList $args -PassThru
```

Substitute the fresh run directory and `SBLAST` or `MIDI` token for the other
profiles.  The PC-speaker and SBLAST runs were allowed to reach the level-14
room; the host window was then closed normally.  Records are flushed one at a
time.  Because Prince did not return to the wrapper, these captures correctly
have no synthetic end record.

The three primary captures map exactly as follows:

| CSV evidence | Generated run directory | DOS command | Raw `MTRACE.BIN` SHA-256 |
|---|---|---|---|
| `trace-pcspeaker-startup.csv` | `pcspeaker-audio` | `MEMTRACE STDSND IMPROVED 14` | `00496A6CD9469BA66A243ECC5A7E24D800AFD907F108E4CD10DF620940A2A3C8` |
| `trace-soundblaster-startup.csv` | `soundblaster-audio` | `MEMTRACE SBLAST IMPROVED 14` | `7BB174B48244A19B42CECD7F71DCE3E2BF5145BFC228A4116B98A7AD055FBCAE` |
| `trace-mt32-startup.csv` | `mt32-audio` | `MEMTRACE MIDI IMPROVED 14` | `9EE9BC349566B567B28E7BE0157E1F3A937F35CE1B8A3F182C148AAD6DF1DA23` |

Decode a trace with:

```powershell
python docs/prince-1.3-cga-memory-map/dynamic/parse_memtrace.py `
  runtime/build/prince13-memory-probe/pcspeaker-audio/MTRACE.BIN `
  --csv docs/prince-1.3-cga-memory-map/dynamic/trace-pcspeaker-startup.csv
```

The baseline commands used the same executable and config, mounted this
directory, and ran:

```dos
MEM /C > MEMC.TXT
MCBMAP > MCBBASE.TXT
SET BLASTER > DOSENV.TXT
```

Stock DOSBox's built-in `MEM /C` gives its one-line result, `632 Kb free
conventional memory`; it does not give a program-by-program `/C` report.
`MCBMAP.COM` is the read-only equivalent with exact MCB fields.

`testchild.asm` is a deterministic flat-format child used to validate the
hook before tracing Prince.  Its decoded run contains one child-program
resize, two successful allocations, one successful resize, two successful
frees, zero failures, and a final MCB/free snapshot exactly equal to the
pre-EXEC snapshot.  Rebuilding both COM tools with NASM 3.02 reproduced the
SHA-256 values above byte for byte.

## Baseline MCB measurement

While `MCBMAP.COM` is resident after shrinking itself to `0045h` paragraphs:

```text
MCBMAP1 PSP=0192 INT12_KB=0280 FIRST_MCB=016F PROBE_PARAS=0045
SEG  T OWNER PARAS
016F M 0008 0001
0171 M 0000 0004
0176 M 0040 0010
0187 M 0192 0009   probe environment
0191 M 0192 0045   probe PSP/program block
01D7 Z 0000 9E27
FREE_TOTAL=9E2B  FREE_LARGEST=9E27  BLOCKS=0006
```

That is 40,491 free paragraphs (647,856 bytes) at the observation point,
including the separate four-paragraph low hole.  Memory below the first MCB,
`0000:0000` through paragraph `016Eh`, is 5,872 bytes of interrupt vectors,
BIOS data, and DOS state outside the allocatable MCB chain.  The chain ends at
paragraph `9FFFh`; `A000h` and above is outside this conventional arena.

## Prince startup results

All numbers below are **measured in the instrumented run**.  A paragraph is
16 bytes.

| Selection | CLI mode | Main PSP block after shrink | Bootstrap far arena | Additional far arenas | Last free total | Largest free block | MCBs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `STDSND` | 0 | 11,187 paras / 178,992 B | 512 paras / 8,192 B | 7 x 4,093 paras | 86 paras / 1,376 B | 82 paras / 1,312 B | 16 |
| `SBLAST` | 3 | 11,187 paras / 178,992 B | 512 paras / 8,192 B | 7 x 4,093 paras | 86 paras / 1,376 B | 82 paras / 1,312 B | 16 |
| `MIDI` (MT-32 path) | 6 | 11,187 paras / 178,992 B | 2,048 paras / 32,768 B | 6 x 4,093 paras | 2,644 paras / 42,304 B | 2,640 paras / 42,240 B | 15 |

The common sequence is:

1. DOS initially gives the child almost the entire available block.
2. Prince resizes its PSP/program block at segment `0206h` to `2BB3h`
   paragraphs.
3. It allocates a 39-paragraph bootstrap far block at `2DBAh` and resizes it
   to `0200h` paragraphs.
4. It probes the largest block with a deliberately failing `FFFFh`
   allocation, then repeatedly allocates `0FFDh`-paragraph far arenas until
   the next one fails with DOS error 8.

The `MIDI` run inserts one mode-unique operation between steps 3 and 4: the
same bootstrap far arena grows from `0200h` to `0800h`.  The exact delta is
`0600h` = 1,536 paragraphs = 24,576 bytes.  This forces one fewer
`0FFDh`-paragraph arena.  The resize is measured; attribution to the mode-6
MIDI/MPU-401 driver bootstrap follows from its position and the static
mode-6-only initialization branch.  Complementary binary/resource analysis
identifies the concrete trigger: mode 6 transiently loads the 21,152-byte
`PRINCE.DAT/65535` `MThd`/Roland MT-32 setup bank in this arena.  Freeing that
object internally does not shrink the DOS MCB, so the 32-KiB arena persists.
The resize is **measured**; the resource identity is an **exact static
cross-check**, not a name emitted by the trace itself.

The apparently larger final DOS-free number for MIDI is not evidence that it
has the roomiest game heap.  Losing one arena returns 4,094 paragraphs when
its MCB is included, while enlarging the bootstrap consumes 1,536; the net is
2,558 paragraphs (40,928 bytes) left outside Prince.  The MIDI-selected game
therefore has one fewer approximately-64-KiB far arena available for internal
objects and resources.

### Reconstructed address layout

The stable PC-speaker/SBLAST layout after the arena sweep is:

```text
0205 MCB | 0206-2DB8 Prince PSP/program (2BB3h paras)
2DB9 MCB | 2DBA-2FB9 bootstrap far arena (0200h paras)
2FBA MCB | 2FBB-3FB7 far arena 1 (0FFDh paras)
3FB8 MCB | 3FB9-4FB5 far arena 2
4FB6 MCB | 4FB7-5FB3 far arena 3
5FB4 MCB | 5FB5-6FB1 far arena 4
6FB2 MCB | 6FB3-7FAF far arena 5
7FB0 MCB | 7FB1-8FAD far arena 6
8FAE MCB | 8FAF-9FAB far arena 7
9FAC MCB | 9FAD-9FFE free (0052h paras)
```

The MT-32-selected layout has bootstrap data `2DBA-35B9`, then six far
arenas beginning at `35BB`, `45B9`, `55B7`, `65B5`, `75B3`, and `85B1`.
Its final free MCB is at `95AE`, with `0A50h` data paragraphs through `9FFE`.
Both layouts retain the separate four-paragraph free block at `0171`.

### Instrumentation overhead

`MEMTRACE.COM` reports and retains `0069h` = 105 paragraphs (1,680 bytes) in
its own PSP/program block while it is Prince's EXEC parent.  Compared with a
direct shell-to-Prince launch, the wrapper also causes one extra MCB header
and one extra nine-paragraph copied environment plus its header.  The total
reconstructed penalty is therefore 116 paragraphs (1,856 bytes).

If Prince's fixed allocation requests are unchanged without the hook, the
direct-run residuals are consequently inferred as 202/198 total/largest
paragraphs for PC speaker or SBLAST, and 2,760/2,756 for MIDI.  Neither largest
block is enough for another 4,093-paragraph arena plus its MCB, so the measured
seven-versus-six arena count is robust to removing the wrapper.

## Command/device identity and sound DAT evidence

Static offsets below are offsets in the executable's first code segment; the
MZ header begins the load image at file offset `0200h`.

The command decoder begins at `0000:254E`.  It compares command-tail tokens in
this order and writes both device-mode bytes:

| Token | Compare/result sites | Result |
|---|---|---|
| `stdsnd` | compare pointer at `256F`; zeroing branch `257C-2581` | modes `0/0` |
| `sblast` | compare pointer at `25BD`; assignment `25CD-25D2` | modes `3/3`, base `0220h` |
| `midi` | compare pointer at `267D`; assignment `268A-268F` | modes `6/6`, port `0330h`, IRQ 2 at `2692-26A2` |

The driver jump table is selected at `26AB-26BA`.  Mode 3 dispatches to
`26BF`, which calls `0CC8:6502`, then falls through `26CF`, which sets
`[0110h]=1`.  Mode 6 dispatches to `2711`; `2711-273E` tests 6 explicitly,
sets the same global at `2717`, and calls `0CC8:C313` with the port/IRQ pair.
That global later participates in archive fallback.  This proves the three
command identities independently of what archive names are opened.

The sound archive loader at `0000:0C63` does **not** dispatch directly on that
mode number.  It always opens `IBM_SND1.DAT`, then tests separate runtime
resource flags at `[3187h]`: mask `02h` enables `MIDISND1.DAT`; mask `01h`
with `[0130h]==0` enables `DIGISND1.DAT` and `DIGISND3.DAT`; otherwise a
nonzero `[0110h]` enables `MT32SND1.DAT` (`0C7D-0CE3`).  Thus driver-selection
mode and `sfMidi`/`sfDigi`-style resource capability flags are distinct state.

Measured opens were:

- `STDSND`: `IBM_SND1.DAT`, followed by Kid/title/level-14 archives.
- `SBLAST`: `IBM_SND1.DAT`, `MIDISND1.DAT`, and `MT32SND1.DAT`, followed by
  Kid/title/level-14 archives.  No `DIGISND*.DAT` was opened.
- `MIDI`: the hooked run stopped progressing before sound/archive loading, so
  it provides no dynamic DAT-open result.

The SBLAST result repeated under DOSBox `sbtype=sb2`, and appending `DIGI` or
`BYPASS` tail tokens did not change the archive selection or MCB sequence.  It
is valid evidence for the authenticated **mode-3 SBLAST startup allocation
path**, but it must not be described as a successful digitized-Sound-Blaster
payload measurement.

## Limitations

- The hook traces DOS file open/close and conventional-memory allocate,
  free, and resize calls.  It cannot see Prince's suballocations inside the
  far arenas.  Level-by-level resource sizes require the complementary static
  heap/resource analysis.
- The trace handle is inherited by Prince, so Prince's first ordinary open is
  handle 6 rather than 5.  This did not change the MCB topology, but it is an
  instrumentation difference.
- PC-speaker and SBLAST captures reached level 14 and showed no further MCB
  changes after the initial arena sweep.  They were stopped by closing the
  DOSBox host, not by Prince returning.
- With the INT 21h hook installed, the `MIDI` run remained on a black screen
  after its arena sweep.  A direct uninstrumented `PRINCE MIDI IMPROVED 14`
  run under the same stock executable/config reached the level-14 princess
  scene.  Therefore its 2,048-paragraph bootstrap and six subsequent arenas
  are reliable early-startup measurements, but the trace does not prove a
  stable in-level MT-32 state or its opened DAT set.
- DOSBox's host-side synthesizer, mixer, and emulated devices do not themselves
  occupy emulated conventional RAM.  The measured differences are allocations
  made by Prince and its selected DOS-side driver path.
