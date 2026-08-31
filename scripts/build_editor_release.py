#!/usr/bin/env python3
"""Build deterministic Prince DAT Explorer source and standalone ZIP files."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "editor"
RELEASES = ROOT / "releases"
BOOTSTRAP_VERSION = "0.4.22"
BOOTSTRAP_SHA256 = "21daf813d33f1edc8e13e43802b6f19b17d8a40e595e26c266c5d6d6e7966d59"
EMBED_NAME = "python-3.12.10-embed-amd64.zip"
EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
FIXED_TIME = (2026, 8, 30, 0, 0, 0)

SOURCE_ROOT_FILES = {
    ".gitignore",
    "LICENSE.txt",
    "PrinceDATViewer.pyw",
    "README.md",
    "RUN_TESTS.bat",
    "RUN_VIEWER.bat",
    "THIRD_PARTY_NOTICES.md",
}
APP_ROOT_FILES = {
    "LICENSE.txt",
    "PrinceDATViewer.pyw",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
}
FORBIDDEN_APP_SUFFIXES = {".dat", ".exe", ".com", ".zip", ".gif", ".png"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def editor_files(*, standalone: bool) -> list[Path]:
    selected: list[Path] = []
    roots = APP_ROOT_FILES if standalone else SOURCE_ROOT_FILES
    for path in EDITOR.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(EDITOR)
        if len(relative.parts) == 1:
            if relative.name in roots or relative.suffix in {".py", ".pyw"}:
                selected.append(path)
        elif relative.parts[0] in ({"docs", "packaging"} if standalone else {"docs", "packaging", "tests"}):
            selected.append(path)
    if not selected:
        raise RuntimeError("No editor files selected")
    return sorted(selected, key=lambda item: item.as_posix().lower())


def write_zip(path: Path, files: list[tuple[Path, str]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, archive_name in sorted(files, key=lambda item: item[1].lower()):
            info = zipfile.ZipInfo(archive_name.replace("\\", "/"), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC failure in {path.name}: {bad}")


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def verify_x64_pe(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise RuntimeError(f"Invalid PE file: {path}")
    header = int.from_bytes(data[0x3C:0x40], "little")
    if header + 6 > len(data) or data[header:header + 4] != b"PE\0\0":
        raise RuntimeError(f"Invalid PE header: {path}")
    machine = int.from_bytes(data[header + 4:header + 6], "little")
    if machine != 0x8664:
        raise RuntimeError(f"Non-x64 PE file in Windows x64 package: {path}")


def standalone_readme(version: str) -> str:
    return f"""Prince DAT Explorer v{version} - Standalone Windows x64

Run PrinceDATExplorer.exe. You may also drag a Prince of Persia DAT archive
onto the executable. The package includes its own 64-bit Python 3.12.10 and
Tk runtime, so no Python installation is required.

This distribution contains editor source code and its runtime dependencies.
It contains no Prince of Persia game executable, DAT archive, or copyrighted
game artwork. Open archives from your own legally obtained game installation.

Application documentation is under app\\docs. Runtime licenses are under
RUNTIME_LICENSES. SHA256SUMS.txt covers every other file in this folder.
"""


def build(version: str) -> tuple[Path, Path, Path]:
    version_line = f'VERSION = "{version}"'
    if version_line not in (EDITOR / "prince_dat.py").read_text(encoding="utf-8"):
        raise RuntimeError(f"editor/prince_dat.py does not declare {version_line}")

    RELEASES.mkdir(exist_ok=True)
    bootstrap_zip = RELEASES / f"Prince-DAT-Explorer-v{BOOTSTRAP_VERSION}-Standalone-Windows-x64.zip"
    if not bootstrap_zip.is_file() or sha256(bootstrap_zip) != BOOTSTRAP_SHA256:
        raise RuntimeError("Verified v0.4.22 standalone bootstrap ZIP is missing or changed")
    embed_zip = RELEASES / EMBED_NAME
    if not embed_zip.is_file() or sha256(embed_zip) != EMBED_SHA256:
        raise RuntimeError(
            f"Official {EMBED_NAME} is missing or changed; download it from python.org"
        )

    source_zip = RELEASES / f"Prince-DAT-Explorer-v{version}-Python.zip"
    standalone_zip = RELEASES / f"Prince-DAT-Explorer-v{version}-Standalone-Windows-x64.zip"
    checksums = RELEASES / f"Prince-DAT-Explorer-v{version}-SHA256SUMS.txt"

    source_payload = []
    for source in editor_files(standalone=False):
        relative = source.relative_to(EDITOR)
        if relative.suffix.lower() in FORBIDDEN_APP_SUFFIXES:
            raise RuntimeError(f"Forbidden source payload: {relative}")
        source_payload.append((source, relative.as_posix()))
    write_zip(source_zip, source_payload)

    with tempfile.TemporaryDirectory(prefix=f"prince-dat-explorer-{version}-") as temp_name:
        temp = Path(temp_name)
        with zipfile.ZipFile(bootstrap_zip) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Bootstrap ZIP failed CRC validation")
            archive.extractall(temp / "bootstrap")
        old_root = temp / "bootstrap" / f"Prince-DAT-Explorer-v{BOOTSTRAP_VERSION}-Standalone-Windows-x64"
        stage_root = temp / f"Prince-DAT-Explorer-v{version}-Standalone-Windows-x64"
        stage_root.mkdir()
        shutil.copy2(old_root / "PrinceDATExplorer.exe", stage_root / "PrinceDATExplorer.exe")
        copy_tree(old_root / "runtime", stage_root / "runtime")
        copy_tree(old_root / "RUNTIME_LICENSES", stage_root / "RUNTIME_LICENSES")
        with zipfile.ZipFile(embed_zip) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Official CPython embeddable ZIP failed CRC validation")
            archive.extractall(stage_root / "runtime")
        shutil.copy2(
            EDITOR / "packaging" / "python312._pth",
            stage_root / "runtime" / "python312._pth",
        )
        with zipfile.ZipFile(stage_root / "runtime" / "python312.zip") as archive:
            if archive.testzip() is not None or "encodings/__init__.pyc" not in archive.namelist():
                raise RuntimeError("Bundled CPython standard library is incomplete")

        app = stage_root / "app"
        app.mkdir()
        for source in editor_files(standalone=True):
            relative = source.relative_to(EDITOR)
            if relative.suffix.lower() in FORBIDDEN_APP_SUFFIXES:
                raise RuntimeError(f"Forbidden standalone app payload: {relative}")
            destination = app / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        (stage_root / "README.txt").write_text(standalone_readme(version), encoding="utf-8", newline="\r\n")
        for pe_file in stage_root.rglob("*"):
            if pe_file.suffix.lower() in {".exe", ".dll", ".pyd"}:
                verify_x64_pe(pe_file)

        smoke_environment = os.environ.copy()
        smoke_environment.update({
            "PYTHONHOME": str(stage_root / "runtime"),
            "TCL_LIBRARY": str(stage_root / "runtime" / "tcl" / "tcl8.6"),
            "TK_LIBRARY": str(stage_root / "runtime" / "tcl" / "tk8.6"),
        })
        smoke = subprocess.run(
            [
                str(stage_root / "runtime" / "python.exe"),
                "-B",
                "-X",
                "utf8",
                "-c",
                (
                    "import tkinter, prince_dat, editor_windows, indexed_gif, "
                    f"composite_project; assert prince_dat.VERSION == '{version}'"
                ),
            ],
            cwd=stage_root,
            env=smoke_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if smoke.returncode != 0:
            raise RuntimeError(
                "Standalone Python/Tk import smoke test failed:\n"
                + smoke.stdout
                + smoke.stderr
            )

        checksum_lines = []
        for payload in sorted(stage_root.rglob("*"), key=lambda item: item.as_posix().lower()):
            if payload.is_file() and payload.name != "SHA256SUMS.txt":
                rel = payload.relative_to(stage_root).as_posix()
                checksum_lines.append(f"{sha256(payload)}  ./{rel}")
        (stage_root / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="ascii")

        standalone_payload = [
            (payload, payload.relative_to(temp).as_posix())
            for payload in stage_root.rglob("*")
            if payload.is_file()
        ]
        write_zip(standalone_zip, standalone_payload)

    checksums.write_text(
        f"{sha256(source_zip)}  {source_zip.name}\n"
        f"{sha256(standalone_zip)}  {standalone_zip.name}\n",
        encoding="ascii",
    )
    return source_zip, standalone_zip, checksums


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    for output in build(args.version):
        print(f"{sha256(output)}  {output}")


if __name__ == "__main__":
    main()
