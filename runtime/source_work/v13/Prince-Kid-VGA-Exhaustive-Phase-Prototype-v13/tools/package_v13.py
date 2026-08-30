#!/usr/bin/env python3
"""Create the deterministic V13 VGA DOS test/visual-verification ZIP."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


ROOT_NAME = "Prince-Kid-VGA-Exhaustive-Phase-Prototype-v13"
FIXED_TIME = (2026, 8, 23, 0, 0, 0)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(project: Path, build: Path, destination: Path) -> Path:
    mappings: list[tuple[str, Path]] = [
        ("README.TXT", project / "README.TXT"),
        ("VISUAL-VERIFICATION.TXT", project / "VISUAL-VERIFICATION.TXT"),
        ("LICENSE.txt", project / "LICENSE.txt"),
        ("THIRD_PARTY_NOTICES.md", project / "THIRD_PARTY_NOTICES.md"),
        ("CGA4K13.COM", build / "CGA4K13.COM"),
        ("P4KX13.EXE", build / "P4KX13.EXE"),
        ("KID.DAT", build / "KID.DAT"),
        ("MANIFEST.JSON", build / "MANIFEST.JSON"),
        (
            "tools/make_four_way_kid.py",
            project / "tools" / "make_four_way_kid.py",
        ),
        (
            "tools/verify_four_way_kid.py",
            project / "tools" / "verify_four_way_kid.py",
        ),
        (
            "tools/render_visual_verification.py",
            project / "tools" / "render_visual_verification.py",
        ),
        (
            "tools/make_phase_prototype.py",
            project / "tools" / "make_phase_prototype.py",
        ),
        ("tools/package_v13.py", project / "tools" / "package_v13.py"),
    ]
    for engine in (
        "composite_converter.py",
        "composite_project.py",
        "composite_signal.py",
        "prince_dat.py",
    ):
        mappings.append((f"tools/engine/{engine}", project / "tools" / "engine" / engine))
    for name in (
        "VISUAL-LEFT-PHASE-TOGGLE.gif",
        "VISUAL-RIGHT-PHASE-TOGGLE.gif",
        "VISUAL-RIGHT-STAND-CORRECTED.png",
        "VISUAL-RUN-STAND.png",
        "VISUAL-RUN-TURN.png",
        "VISUAL-TURN.png",
    ):
        mappings.append((f"visual-verification/{name}", build / "visual-verification" / name))

    payloads: dict[str, bytes] = {}
    for relative, source in mappings:
        if not source.is_file():
            raise FileNotFoundError(source)
        payloads[relative] = source.read_bytes()
    checksum_text = "".join(
        f"{sha256(payloads[name])}  {name}\n"
        for name in sorted(payloads)
    ).encode("ascii")
    payloads["SHA256SUMS.TXT"] = checksum_text

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative in sorted(payloads):
            info = zipfile.ZipInfo(f"{ROOT_NAME}/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payloads[relative], compresslevel=9)
    destination.with_name(destination.name + ".sha256").write_text(
        f"{sha256(destination.read_bytes())}  {destination.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.project.resolve(), args.build.resolve(), args.output.resolve())
    print(result)
    print(result.with_name(result.name + ".sha256"))


if __name__ == "__main__":
    main()
