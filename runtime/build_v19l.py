#!/usr/bin/env python3
"""Build V19L by swapping only the V19K Prince-health absolute-phase rule."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import build_v19 as v19


ROOT = Path(__file__).resolve().parent
V19K = v19.OUT
BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-Phase-Aware-V19L-HP-Absolute-Phase-Fix-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

SOURCE_EXE = "P4KX19.EXE"
SOURCE_COM = "CGA4K19.COM"
OUTPUT_EXE = "P4KX1L.EXE"
OUTPUT_COM = "CGA4K1L.COM"
V19K_EXE_SHA256 = "8e1edb8203b0bd61a0d606912eb67bb337696723baf3e15cf1c379464a6972c4"
V19K_COM_SHA256 = "561eb6c66626fc6f1d4635ffad5f96dfe19cc037f08a010f7c6dce14cb3ee557"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_v19k_package() -> dict[str, object]:
    manifest_path = V19K / "PACKAGE-MANIFEST.JSON"
    if not manifest_path.exists():
        raise ValueError(f"missing V19K package manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != v19.PACKAGE_NAME:
        raise ValueError("unexpected V19K package identity")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("invalid V19K package file manifest")
    for relative, metadata in files.items():
        path = V19K / relative
        if not path.is_file():
            raise ValueError(f"missing V19K input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V19K input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V19K input hash mismatch: {relative}")
    if sha256_file(V19K / SOURCE_EXE) != V19K_EXE_SHA256:
        raise ValueError("unexpected V19K executable")
    if sha256_file(V19K / SOURCE_COM) != V19K_COM_SHA256:
        raise ValueError("unexpected V19K launcher")
    return manifest


def replace_once(data: bytes, old: bytes, new: bytes) -> bytes:
    if len(old) != len(new) or data.count(old) != 1:
        raise ValueError(f"expected one equal-length marker {old!r}")
    return data.replace(old, new, 1)


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (V19K / SOURCE_EXE).read_bytes()
    if sha256_bytes(source) != V19K_EXE_SHA256:
        raise ValueError("unexpected V19K executable")

    v19_code, labels = v19.build_extended_mapper_and_hp_helper()
    code_start = v19.HIGH_CODE_FILE + v19.EXTENDED_MAPPER_OFFSET
    code_end = code_start + len(v19_code)
    if source[code_start:code_end] != v19_code:
        raise ValueError("V19K mapper/helper region no longer matches its builder")

    helper_offset = labels["hp_pointer"]
    helper_file = v19.HIGH_CODE_FILE + helper_offset
    parity_branch_file = helper_file + 15
    if source[parity_branch_file:parity_branch_file + 2] != bytes.fromhex("74 1f"):
        raise ValueError("V19K HP parity branch signature changed")

    data = bytearray(source)
    data[parity_branch_file] = 0x75  # even index -> P2; odd index -> P0
    data = bytearray(replace_once(bytes(data), b"KID TABLE V19K", b"KID TABLE V19L"))

    # The ordinary mapper, including the hurt splash, must remain exact.
    if data[code_start:helper_file] != source[code_start:helper_file]:
        raise ValueError("ordinary V19 mapper or hurt-splash route changed")
    if data[v19.HEADER_BYTES:v19.HEADER_BYTES + v19.HP_EMPTY_POINTER_HOOK + 12] != source[
        v19.HEADER_BYTES:v19.HEADER_BYTES + v19.HP_EMPTY_POINTER_HOOK + 12
    ]:
        raise ValueError("code before the empty-HP hook changed")
    empty = v19.HEADER_BYTES + v19.HP_EMPTY_POINTER_HOOK
    full = v19.HEADER_BYTES + v19.HP_FULL_POINTER_HOOK
    if data[empty:empty + 12] != source[empty:empty + 12]:
        raise ValueError("empty-HP call hook changed")
    if data[full:full + 12] != source[full:full + 12]:
        raise ValueError("full-HP call hook changed")

    changed_offsets = [
        index for index, (before, after) in enumerate(zip(source, data)) if before != after
    ]
    marker_offset = source.index(b"KID TABLE V19K") + len(b"KID TABLE V19")
    if changed_offsets != sorted((parity_branch_file, marker_offset)):
        raise ValueError(f"V19L executable changed unexpected offsets: {changed_offsets}")

    high_code = bytes(data[v19.HIGH_CODE_FILE:v19.HIGH_CODE_FILE + v19.RUNTIME_HEAP_RESERVE])
    hp_cases = 0
    lazy_load_cases = 0
    for image_id in (216, 217):
        for hp_index in range(10):
            for graphics_mode in (1, 5):
                for loaded in (False, True):
                    slot, alias, ended_loaded = v19.emulate_hp_helper(
                        high_code,
                        helper_offset,
                        image_id,
                        hp_index,
                        graphics_mode,
                        loaded,
                        phase_on_even=True,
                    )
                    expected = v19.hp_pointer_model(
                        image_id,
                        hp_index,
                        graphics_mode,
                        phase_on_even=True,
                    )
                    if (slot, alias) != expected:
                        raise ValueError("V19L HP helper/model mismatch")
                    hp_cases += 1
                    if graphics_mode == 1 and not (hp_index & 1) and not loaded and ended_loaded:
                        lazy_load_cases += 1

    executable = bytes(data)
    return executable, {
        "file": OUTPUT_EXE,
        "bytes": len(executable),
        "sha256": sha256_bytes(executable),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": V19K_EXE_SHA256,
        "visible_ctrl_v_marker": "KID TABLE V19L    V1.3",
        "hp_helper": f"{v19.HIGH_CODE_SEGMENT:04X}:{helper_offset:04X}",
        "hp_parity_branch_file_offset": f"0x{parity_branch_file:05X}",
        "hp_parity_opcode_change": "JE hp_p0 -> JNE hp_p0",
        "hp_phase_rule": "even index (screen positions 1/3) -> P2; odd index (2/4) -> P0",
        "machine_hp_cases_verified": hp_cases,
        "hp_lazy_load_cases_verified": lazy_load_cases,
        "binary_offsets_changed_from_v19k": [f"0x{offset:05X}" for offset in changed_offsets],
        "ordinary_mapper_byte_identical_to_v19k": True,
        "hurt_splash_route_byte_identical_to_v19k": True,
        "hp_call_hooks_byte_identical_to_v19k": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (V19K / SOURCE_COM).read_bytes()
    if sha256_bytes(source) != V19K_COM_SHA256:
        raise ValueError("unexpected V19K launcher")
    data = v19.v18.v17.replace_exact(
        source,
        b"P4KX19.EXE",
        b"P4KX1L.EXE",
        expected=3,
    )
    data = replace_once(data, b"V19K", b"V19L")
    if b"KID PHASE TABLE V19L ACTIVE" not in data:
        raise ValueError("V19L launcher banner patch failed")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": V19K_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "KID PHASE TABLE V19L ACTIVE",
    }


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 30, 16, 0, 0)
    try:
        with zipfile.ZipFile(
            staging,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = Path(PACKAGE_NAME) / path.relative_to(source_dir)
                info = zipfile.ZipInfo(relative.as_posix(), fixed_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        with staging.open("r+b") as handle:
            os.fsync(handle.fileno())
        staging.replace(zip_path)
    except BaseException:
        if staging.exists():
            staging.unlink()
        raise


README = """PRINCE OF PERSIA 1.3 - PHASE-AWARE KID V19L
==================================================

V19L is the focused health-icon absolute-phase correction to V19K.

Only the dedicated Prince HP parity branch changed:

  screen positions 1/3 (zero-based even HP index)  -> PHASE3 / P2
  screen positions 2/4 (zero-based odd HP index)   -> KID / P0

The confirmed V18 body-motion mapper and the V19 hurt-splash route remain
byte-identical. KID.DAT, PHASE.DAT, PHASE2.DAT, PHASE3.DAT, and every other
DAT archive are byte-identical to V19K.

Run CGA4K1L.COM. Static and machine-helper verification passed. DOSBox runtime
confirmation is still required before the health-icon defect is marked fixed.
"""


def main() -> None:
    source_manifest = verify_v19k_package()
    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(V19K, OUT)

    stale = (
        SOURCE_EXE,
        SOURCE_COM,
        "README.TXT",
        "KID-V19K-README.TXT",
        "KID-V19K-VERIFICATION.TXT",
        "KID-V19K-MANIFEST.JSON",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    )
    for name in stale:
        path = OUT / name
        if path.exists():
            path.unlink()

    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "KID-V19L-README.TXT").write_text(
        README,
        encoding="ascii",
        newline="\r\n",
    )

    dat_hashes = {}
    for source_path in sorted(V19K.glob("*.DAT")):
        output_path = OUT / source_path.name
        if output_path.read_bytes() != source_path.read_bytes():
            raise ValueError(f"V19L changed DAT archive {source_path.name}")
        dat_hashes[source_path.name] = sha256_file(output_path)

    verification = f"""Prince of Persia 1.3 V19L HP Absolute-Phase Verification
================================================================
EXE PASS     {OUTPUT_EXE}: {executable_meta['bytes']} bytes, SHA-256 {executable_meta['sha256']}
BASE PASS    Exact verified V19K package used as input
SCOPE PASS   Only HP parity opcode and V19K->V19L visible marker changed in EXE
HP PASS      {executable_meta['machine_hp_cases_verified']}/{executable_meta['machine_hp_cases_verified']} helper cases select the swapped P0/P2 rule
LOAD PASS    {executable_meta['hp_lazy_load_cases_verified']} even-index cases verify lazy PHASE3 loading
BODY PASS    Confirmed V18 body mapper byte-identical to V19K
HURT PASS    V19 hurt-splash route byte-identical to V19K
HOOK PASS    Both direct HP FAR call hooks byte-identical to V19K
DAT PASS     All {len(dat_hashes)} DAT archives byte-identical to V19K
COM PASS     {OUTPUT_COM}: child={OUTPUT_EXE}, SHA-256 {launcher_meta['sha256']}
CPU PASS     Modified branch remains 8086/8088 compatible

STATIC VERIFICATION PASSED.
DOSBox runtime verification is still required.
"""
    (OUT / "KID-V19L-VERIFICATION.TXT").write_text(
        verification,
        encoding="ascii",
        newline="\r\n",
    )

    v19_manifest = json.loads(
        (V19K / "KID-V19K-MANIFEST.JSON").read_text(encoding="utf-8")
    )
    manifest = {
        **v19_manifest,
        "package": PACKAGE_NAME,
        "status": "V19L static/machine/resource verification passed; DOS runtime verification pending",
        "baseline": {
            "version": "V19K",
            "package": v19.PACKAGE_NAME,
            "package_manifest_sha256": sha256_file(V19K / "PACKAGE-MANIFEST.JSON"),
            "known_defect": "Prince HP direct-blit absolute phase reversed",
        },
        "scope": {
            "change": "swap only the Prince HP direct-blit P0/P2 parity rule",
            "screen_positions_1_3": "PHASE3/P2",
            "screen_positions_2_4": "KID/P0",
            "dat_archives_changed": [],
            "ordinary_mapper_changed": False,
            "hurt_splash_route_changed": False,
        },
        "runtime_architecture": {
            **v19_manifest["runtime_architecture"],
            "hp_phase_rule": "even index -> P2; odd index -> P0",
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "dat_sha256": dat_hashes,
    }
    (OUT / "KID-V19L-MANIFEST.JSON").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tools_dir = OUT / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {
        "package": PACKAGE_NAME,
        "status": manifest["status"],
        "baseline_package": source_manifest["package"],
        "files": {},
    }
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}:
            relative = path.relative_to(OUT).as_posix()
            package_manifest["files"][relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    (OUT / "PACKAGE-MANIFEST.JSON").write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksums = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksums.append(f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}")
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksums) + "\n",
        encoding="ascii",
    )

    make_zip(OUT, ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        if archive.testzip() is not None:
            raise ValueError("V19L ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V19L ZIP contents differ from package directory")

    print(json.dumps({
        "package_dir": str(OUT),
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "executable": executable_meta,
        "launcher": launcher_meta,
        "dat_archives_verified_identical": len(dat_hashes),
    }, indent=2))


if __name__ == "__main__":
    main()
