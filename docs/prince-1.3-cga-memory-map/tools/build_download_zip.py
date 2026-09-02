#!/usr/bin/env python3
"""Build the deterministic, source-only memory-atlas download ZIP.

The archive is assembled from the Git index rather than the working tree. This
keeps ignored local evidence such as COM probes and screenshots out of the
download and makes the ZIP exactly reproducible from a staged tree.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_REPO_PATH = PACKAGE_ROOT.relative_to(REPOSITORY_ROOT).as_posix()
OUTPUT = PACKAGE_ROOT / "prince-1.3-cga-memory-map.zip"
CHECKSUM = PACKAGE_ROOT / "prince-1.3-cga-memory-map.zip.sha256"
ARCHIVE_PREFIX = "prince-1.3-cga-memory-map"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
EXCLUDED_NAMES = {OUTPUT.name, CHECKSUM.name}
FORBIDDEN_SUFFIXES = {
    ".com",
    ".dat",
    ".exe",
    ".gif",
    ".pdcproj",
    ".png",
    ".zip",
}


def run_git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def staged_package_paths() -> list[PurePosixPath]:
    output = run_git("ls-files", "--cached", "-z", "--", PACKAGE_REPO_PATH)
    paths = []
    prefix = f"{PACKAGE_REPO_PATH}/"
    for raw_path in output.split(b"\0"):
        if not raw_path:
            continue
        repo_path = raw_path.decode("utf-8")
        if not repo_path.startswith(prefix):
            raise RuntimeError(f"Unexpected staged path: {repo_path}")
        relative = PurePosixPath(repo_path[len(prefix) :])
        if relative.name in EXCLUDED_NAMES:
            continue
        if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"Forbidden staged payload: {repo_path}")
        paths.append(relative)
    return sorted(paths, key=lambda path: path.as_posix())


def staged_blob(relative: PurePosixPath) -> bytes:
    repo_path = f"{PACKAGE_REPO_PATH}/{relative.as_posix()}"
    return run_git("show", f":{repo_path}")


def build() -> dict[str, object]:
    paths = staged_package_paths()
    if not paths:
        raise RuntimeError("No staged memory-map files were found.")

    temporary = tempfile.NamedTemporaryFile(
        dir=PACKAGE_ROOT,
        prefix=".memory-map-download-",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()

    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative in paths:
                archive_path = f"{ARCHIVE_PREFIX}/{relative.as_posix()}"
                info = zipfile.ZipInfo(archive_path, date_time=FIXED_TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(
                    info,
                    staged_blob(relative),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary_path, OUTPUT)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    CHECKSUM.write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii", newline="\n")

    with zipfile.ZipFile(OUTPUT) as archive:
        archived_files = [name for name in archive.namelist() if not name.endswith("/")]
        if len(archived_files) != len(paths):
            raise RuntimeError("ZIP entry count does not match the staged source set.")
        bad = [
            name
            for name in archived_files
            if PurePosixPath(name).suffix.lower() in FORBIDDEN_SUFFIXES
        ]
        if bad:
            raise RuntimeError(f"Forbidden archive entries: {bad}")
        if archive.testzip() is not None:
            raise RuntimeError("ZIP CRC verification failed.")

    return {
        "archive": str(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
        "files": len(paths),
        "sha256": digest,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
