#!/usr/bin/env python3
"""Validate the generated Prince 1.3 memory-atlas artifact set."""

from __future__ import annotations

import argparse
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
EXE_SHA256 = "24fdc79b4de563348313b50d717e171919191e5c38559f5bdd6a4751d39b7158"


class IdAndLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-exe", type=Path)
    args = parser.parse_args()

    if args.source_exe and sha256(args.source_exe) != EXE_SHA256:
        raise SystemExit("source PRINCE.EXE hash mismatch")

    model = json.loads((ROOT / "data/memory-model.json").read_text(encoding="utf-8"))
    assert model["schema"] == 2
    assert len(model["levels"]) == 16
    assert len(model["scenes"]) == 7
    assert len(model["memory_states"]) == 27
    assert len(model["asset_catalog"]) == 40
    assert len(model["archives"]) == 27
    assert len(model["graphic_components"]) == 19
    assert model["allocator"]["startup_pools"]["pc"]["far_pool_payload"] == 466_608
    assert model["allocator"]["startup_pools"]["mt32"]["far_pool_payload"] == 425_696
    assert model["levels"][14]["devices"]["mt32"]["far_live_with_surface"] == 123_896
    assert model["scenes"][4]["devices"]["mt32"]["load_peak_live_with_surface"] == 148_498
    assert sum(v["live"] for v in model["phase_banks_v21b"].values()) == 284_976

    assert len(csv_rows(ROOT / "data/levels.csv")) == 16
    assert len(csv_rows(ROOT / "data/scenes.csv")) == 7
    assert len(csv_rows(ROOT / "data/archives.csv")) == 27
    assert len(csv_rows(ROOT / "data/graphic-components.csv")) == 19
    assert len(csv_rows(ROOT / "data/sound-profiles.csv")) == 3
    expected_state_asset_rows = sum(
        (len(state["retained_asset_ids"]) + 1) * 3
        for state in model["memory_states"]
    )
    assert len(csv_rows(ROOT / "data/state-asset-blocks.csv")) == expected_state_asset_rows

    html = (ROOT / "memory-map.html").read_text(encoding="utf-8")
    assert "__MODEL_JSON__" not in html
    assert "\ufffd" not in html
    embedded = re.search(r"const model=(\{.*?\});\nconst devices=", html, re.DOTALL)
    assert embedded is not None
    assert json.loads(embedded.group(1)) == model
    for marker in (
        'id="statePicker"',
        'id="farLane"',
        'id="nearLane"',
        'id="assetInspector"',
        'id="assetDirectoryRows"',
        "function renderBlockMap",
    ):
        assert marker in html
    parsed = IdAndLinkParser()
    parsed.feed(html)
    assert len(parsed.ids) == len(set(parsed.ids))
    for href in parsed.links:
        if "://" not in href and not href.startswith("#"):
            assert (ROOT / href.split("#", 1)[0]).exists(), href
    catalog_ids = [asset["id"] for asset in model["asset_catalog"]]
    assert len(catalog_ids) == len(set(catalog_ids))
    for asset in model["asset_catalog"]:
        assert (ROOT / asset["report_href"].split("#", 1)[0]).exists()

    svg_root = ET.parse(ROOT / "memory-map.svg").getroot()
    assert svg_root.tag.endswith("svg")
    assert svg_root.attrib["viewBox"] == "0 0 1600 1220"

    report = (ROOT / "REPORT.md").read_text(encoding="utf-8")
    for link in re.findall(r"\[[^]]+\]\(([^)]+)\)", report):
        if "://" not in link and not link.startswith("#"):
            assert (ROOT / link.split("#", 1)[0]).exists(), link

    checksum_lines = (ROOT / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()
    assert checksum_lines
    for line in checksum_lines:
        digest, relative = line.split("  ", 1)
        assert sha256(ROOT / relative) == digest, relative

    print("OK: source, model, CSVs, embedded HTML data, links, SVG, and checksums validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
