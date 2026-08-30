"""Linked C/E/V archive handling for Prince room graphics.

Dungeon and palace artwork is unusual among POP1 resources: CGA, EGA, and
VGA use independent archives rather than one shared indexed image set.  This
module keeps those files separate and resolves matching images by resource ID.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from prince_dat import DatArchive, ResourceAnalysis


ROOM_FAMILIES = ("DUNGEON", "PALACE")
ADAPTER_PREFIX = {"cga": "C", "ega": "E", "vga": "V"}
PREFIX_ADAPTER = {prefix: adapter for adapter, prefix in ADAPTER_PREFIX.items()}
DISPLAY_ADAPTER = {
    "vga": "vga",
    "ega": "ega",
    "cga": "cga",
    "mode6": "cga",
    "composite": "cga",
}
_ROOM_MEMBER = re.compile(r"^([CEV])(DUNGEON|PALACE)$", re.IGNORECASE)


class RoomSetError(ValueError):
    """Raised when a file does not belong in the linked room-set workspace."""


@dataclass(frozen=True)
class RoomSetMember:
    adapter: str
    family: str


def identify_room_set(path: str | Path) -> RoomSetMember | None:
    """Identify conventional C/E/V dungeon and palace filenames."""

    match = _ROOM_MEMBER.fullmatch(Path(path).stem)
    if match is None:
        return None
    return RoomSetMember(PREFIX_ADAPTER[match.group(1).upper()], match.group(2).upper())


def _case_insensitive_child(parent: Path, filename: str) -> Path | None:
    direct = parent / filename
    if direct.is_file():
        return direct
    folded = filename.casefold()
    try:
        return next(
            (candidate for candidate in parent.iterdir() if candidate.is_file() and candidate.name.casefold() == folded),
            None,
        )
    except OSError:
        return None


@dataclass
class ArchiveContext:
    """A primary archive plus adapter-specific room companions when applicable."""

    primary: DatArchive
    family: str | None = None
    archives: dict[str, DatArchive | None] = field(default_factory=dict)
    discovery_errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def discover(cls, primary: DatArchive) -> "ArchiveContext":
        member = identify_room_set(primary.path)
        if member is None:
            return cls(
                primary=primary,
                archives={"cga": primary, "ega": primary, "vga": primary},
            )

        context = cls(
            primary=primary,
            family=member.family,
            archives={"cga": None, "ega": None, "vga": None},
        )
        context.archives[member.adapter] = primary
        for adapter in ("cga", "ega", "vga"):
            if context.archives[adapter] is not None:
                continue
            candidate = _case_insensitive_child(
                primary.path.parent,
                context.expected_filename(adapter),
            )
            if candidate is None:
                continue
            try:
                archive = DatArchive.open(candidate)
                context.attach(adapter, archive)
            except (OSError, ValueError) as exc:
                context.discovery_errors[adapter] = str(exc)
        return context

    @property
    def is_room_set(self) -> bool:
        return self.family is not None

    @property
    def composite_target(self) -> DatArchive | None:
        return self.archives.get("cga") if self.is_room_set else self.primary

    def expected_filename(self, adapter: str) -> str:
        if adapter not in ADAPTER_PREFIX:
            raise RoomSetError(f"Unknown room adapter: {adapter}")
        if self.family is None:
            return self.primary.path.name
        suffix = self.primary.path.suffix or ".DAT"
        return f"{ADAPTER_PREFIX[adapter]}{self.family}{suffix}"

    def attach(self, adapter: str, archive: DatArchive) -> None:
        """Attach one explicitly selected room archive after strict validation."""

        if not self.is_room_set:
            raise RoomSetError("Companion archives apply only to DUNGEON and PALACE room sets.")
        if adapter not in ADAPTER_PREFIX:
            raise RoomSetError(f"Unknown room adapter: {adapter}")
        member = identify_room_set(archive.path)
        expected = self.expected_filename(adapter)
        if member is None:
            raise RoomSetError(
                f"{archive.path.name} is not a conventional room archive; expected {expected}."
            )
        if member.family != self.family or member.adapter != adapter:
            raise RoomSetError(
                f"{archive.path.name} is {member.adapter.upper()} {member.family}; expected {expected}."
            )
        self.archives[adapter] = archive
        self.discovery_errors.pop(adapter, None)

    def archive_for_display_mode(self, mode: str) -> DatArchive | None:
        if mode not in DISPLAY_ADAPTER:
            raise RoomSetError(f"Unknown display mode: {mode}")
        if not self.is_room_set:
            return self.primary
        return self.archives.get(DISPLAY_ADAPTER[mode])

    def analysis_for_display_mode(
        self, mode: str, resource_id: int
    ) -> tuple[DatArchive, ResourceAnalysis] | None:
        """Resolve a matching image/data record by ID, never by index position."""

        archive = self.archive_for_display_mode(mode)
        if archive is None:
            return None
        analysis = archive.analysis_by_id(resource_id)
        return (archive, analysis) if analysis is not None else None

    def source_description(self, mode: str) -> str:
        adapter = DISPLAY_ADAPTER[mode]
        archive = self.archive_for_display_mode(mode)
        if archive is not None:
            return archive.path.name
        error = self.discovery_errors.get(adapter)
        expected = self.expected_filename(adapter)
        return f"{expected} unavailable" + (f" ({error})" if error else "")

