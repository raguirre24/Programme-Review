"""Merge the Resources page into the Resource Simulator page as its Histogram view, and rename that page 'Resources'.

The merged page (4c53a34bba9dcc7f3e8c) gets three views on the header bookmark navigator: Histogram (the former Resources
page: resource cards, monthly histogram, 'To Complete Distribution' table and their slicers; the saved view), Simulator
(the Playground's single-calendar view) and Compare (calendar comparison). The views share the page header, project menu
and project/update context, and neither view filters the other. The former Resources page (099895b98057d0135349) and its
two project-menu bookmarks are removed; its header, project menu and navigators duplicated the merged page's own.

Written files: the eight Histogram visuals (moved unchanged), the saved visibility of the Simulator and Compare visuals,
the header title, the view navigator, page.json (name and interactions), the three view bookmarks and their group,
bookmarks.json and pages.json. The move is one-off: once the former page is gone the Histogram visuals are read from the
merged page, so a re-run is idempotent.

Modes: --check compares the generated files' content with the report, ignoring what Desktop rewrites on save (exit 1
on difference), --output-dir writes a review copy
outside the report, --apply writes them into the report (close Power BI Desktop without saving first). --definition
points every mode at another report definition folder, for example a scratch copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
from generate_page import expr, props, string  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
PAGE = "4c53a34bba9dcc7f3e8c"
PAGE_NAME = "Resources"
FORMER_PAGE = "099895b98057d0135349"
FORMER_BOOKMARKS = ("21f27f8d8881933c3479", "7497750c116260029497")  # its project-menu open/close


def identifier(label: str) -> str:
    return hashlib.sha256(("resources-page-merge-v1:" + label).encode()).hexdigest()[:20]


# Histogram view: the former Resources page's content (cards, histogram, distribution table, help text, slicers).
HISTOGRAM_VIEW = [
    "771dc5360ec0ec8ceaa6", "bb2e46e5dbae497008e6", "224fd832199fc5bc1ac1", "703edc6c7e8b19a18055",
    "e9af69e6897909605e00", "42e5e3dd0509ccb14090", "00fd2ccccacc893aaab0", "4b282f020b022db79006",
]
# Shown in both Simulator and Compare: the scenario inputs and Reset, the evaluation window, display period and calendar note.
SIMULATOR_SHARED = [
    "a47a28f5f6803a0bd238", "76632dab0ff8b86a8c55", "342b3372b9f35b4d628c", "f0c4beaebbd1f349d8fa",
    "34ac98823f173c5173e2", "179c68eefe44759dc6a6", "7c85a4199efc0955fcf9", "c3f32af88a59421d9975",
    "5b3c0db966d719181dd4", "cf0eeaddb7f90594dee2", "4de2ffc08e51a2b74f2f", "2d84bec282bacc9e7c9c",
    "43a8c411f9ebd9675ed5", "5f5e832a845f69b11b99", "06120b3c44abd47df1e9",
]
# Single-calendar outputs and calendar selector (Simulator), and the comparison visuals (Compare).
SINGLE_VIEW = [
    "16643c36a5f294a63a18", "03410ac18c0fb7b35af1", "b8131dcaa0d2fd84ea2c", "f1268db2c25979d9b9c3",
    "f62b2a2433a4e7baa768", "6989681937a36a7c31bf", "dfe45a9f6ada77e1e968", "d0ef1452175fcccbadc7",
    "dea161918df8bfd0fc62", "f138b12e316741ce70dd", "72af6b2274a8e97ddc2e", "fa2eaf106e8ead20b935",
    "d5725d830dac62d285ce", "c4762ffe207ce780fc4d",
]
COMPARE_VIEW = [
    "385d6b9651949eee2c43", "13675cfdfe89b2fc33d2", "8ccd002fac5dfe15fae1", "267a11031012e4ad4e48",
    "4048e613efa20dcf8bd5", "72d698c1dda5e61397ad",
]
SIMULATOR_SIDE = SIMULATOR_SHARED + SINGLE_VIEW + COMPARE_VIEW
TOGGLED = HISTOGRAM_VIEW + SIMULATOR_SIDE
TITLE, NAVIGATOR = "c3fd436b960b0d6d8f8c", "03e21a133719c93400ba"
HISTOGRAM_BOOKMARK = identifier("histogram-bookmark")
SIMULATOR_BOOKMARK, COMPARE_BOOKMARK, VIEW_GROUP = "3fc3d41f00865b324fc4", "e1c605698b0ada439b54", "c4ae381d0adac7597341"
VIEWS = {
    HISTOGRAM_BOOKMARK: ("Histogram", HISTOGRAM_VIEW),
    SIMULATOR_BOOKMARK: ("Simulator", SIMULATOR_SHARED + SINGLE_VIEW),
    COMPARE_BOOKMARK: ("Compare", SIMULATOR_SHARED + COMPARE_VIEW),
}
# The former page's own interactions: a histogram month filters the distribution table, not the reverse.
HISTOGRAM_INTERACTIONS = {
    ("bb2e46e5dbae497008e6", "224fd832199fc5bc1ac1"): "DataFilter",
    ("224fd832199fc5bc1ac1", "bb2e46e5dbae497008e6"): "NoFilter",
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


# What Power BI Desktop rewrites when it saves, so --check and --apply compare content rather than formatting: the
# visualContainer $schema version, stacking and tab order (z, tabOrder), projection 'active' flags and Deneb's state.
DESKTOP_MANAGED_KEYS = {"$schema", "z", "tabOrder", "active", "stateManagement", "developer"}


def desktop_neutral(value):
    if isinstance(value, dict):
        result = {key: desktop_neutral(item) for key, item in value.items() if key not in DESKTOP_MANAGED_KEYS}
        for entry in result.get("vega", []) if isinstance(result.get("vega"), list) else []:
            entry.get("properties", {}).pop("version", None)
        return result
    if isinstance(value, list):
        return [desktop_neutral(item) for item in value]
    return value


def interactions(page: dict) -> list[dict]:
    """Keep the Simulator and Compare pairs, add the former page's pairs, and keep the views from filtering each other."""
    histogram = set(HISTOGRAM_VIEW)
    pairs = {(entry["source"], entry["target"]): entry["type"] for entry in page.get("visualInteractions", [])
             if entry["source"] not in histogram and entry["target"] not in histogram}
    pairs.update(HISTOGRAM_INTERACTIONS)
    # Hidden slicers and visuals keep filtering, so each view ignores the other's selections.
    for histogram_visual in HISTOGRAM_VIEW:
        for simulator_visual in SIMULATOR_SIDE:
            pairs[(histogram_visual, simulator_visual)] = pairs[(simulator_visual, histogram_visual)] = "NoFilter"
    return [{"source": source, "target": target, "type": kind} for (source, target), kind in pairs.items()]


def view_bookmark(name: str, visual_types: dict[str, str]) -> dict:
    """Display-only: shows one view's visuals and hides the others, without touching data, filters or other visuals."""
    caption, shown = VIEWS[name]
    targets = sorted(TOGGLED)
    states = {}
    for visual_id in targets:
        single = {"visualType": visual_types[visual_id], "objects": {}}
        if visual_id not in shown:
            single["display"] = {"mode": "hidden"}
        states[visual_id] = {"singleVisual": single}
    return {
        "$schema": SCHEMA + "bookmark/2.1.0/schema.json", "displayName": caption, "name": name,
        "options": {"targetVisualNames": targets, "suppressData": True, "suppressActiveSection": True,
                    "applyOnlyToTargetVisuals": True},
        "explorationState": {"version": "1.0", "activeSection": PAGE, "sections": {PAGE: {"visualContainers": states}}},
    }


def build() -> dict[Path, dict | None]:
    """Every file the merge writes; None removes a file or folder of the former Resources page."""
    page_dir = DEFINITION / "pages" / PAGE
    former_dir = DEFINITION / "pages" / FORMER_PAGE
    source_dir = former_dir if former_dir.exists() else page_dir
    histogram = {name: read(source_dir / "visuals" / name / "visual.json") for name in HISTOGRAM_VIEW}
    simulator = {name: read(page_dir / "visuals" / name / "visual.json") for name in SIMULATOR_SIDE + [TITLE, NAVIGATOR]}
    outputs: dict[Path, dict | None] = {}
    for name, item in histogram.items():
        item.pop("isHidden", None)  # Histogram is the saved view.
        outputs[Path("pages") / PAGE / "visuals" / name / "visual.json"] = item
    for name in SIMULATOR_SIDE:
        item = simulator[name]
        if item.get("isHidden") is not True:
            item["isHidden"] = True
            outputs[Path("pages") / PAGE / "visuals" / name / "visual.json"] = item

    title = simulator[TITLE]
    for entry in title["visual"]["objects"]["text"]:
        if "text" in entry.get("properties", {}):
            entry["properties"]["text"] = string(PAGE_NAME)
    outputs[Path("pages") / PAGE / "visuals" / TITLE / "visual.json"] = title

    navigator = simulator[NAVIGATOR]
    if former_dir.exists():
        # On the merge, move it to the header row right of the logo: its old spot overlaps the Histogram view's WBS slicer.
        # Afterwards its position is the report author's, so a navigator moved in Desktop stays where it is.
        navigator["position"].update({"x": 200, "y": 20, "width": 450, "height": 44})
    navigator["visual"]["objects"]["bookmarks"] = props(
        bookmarkGroup=string(VIEW_GROUP), allowDeselectionBookmark=expr("false"), selectedBookmark=string(HISTOGRAM_BOOKMARK))
    vco = navigator["visual"]["visualContainerObjects"]
    vco["title"][0]["properties"]["text"] = string("Resources view")
    vco["general"] = props(altText=string("Resources view: Histogram, Simulator or Compare"))
    outputs[Path("pages") / PAGE / "visuals" / NAVIGATOR / "visual.json"] = navigator

    page = read(page_dir / "page.json")
    page["displayName"] = PAGE_NAME
    page["visualInteractions"] = interactions(page)
    outputs[Path("pages") / PAGE / "page.json"] = page

    visual_types = {name: item["visual"]["visualType"] for name, item in {**histogram, **simulator}.items()}
    for name in VIEWS:
        outputs[Path("bookmarks") / f"{name}.bookmark.json"] = view_bookmark(name, visual_types)
    metadata = read(DEFINITION / "bookmarks" / "bookmarks.json")
    metadata["items"] = [entry for entry in metadata["items"] if entry.get("name") not in FORMER_BOOKMARKS]
    group = {"name": VIEW_GROUP, "displayName": "Resources view", "children": list(VIEWS)}
    positions = [index for index, entry in enumerate(metadata["items"]) if entry.get("name") == VIEW_GROUP]
    if positions:
        metadata["items"][positions[0]] = group
    else:
        metadata["items"].append(group)
    outputs[Path("bookmarks") / "bookmarks.json"] = metadata
    for name in FORMER_BOOKMARKS:
        outputs[Path("bookmarks") / f"{name}.bookmark.json"] = None
    outputs[Path("pages") / FORMER_PAGE] = None

    pages = read(DEFINITION / "pages" / "pages.json")
    pages["pageOrder"] = [name for name in pages["pageOrder"] if name != FORMER_PAGE]
    if pages.get("activePageName") == FORMER_PAGE:
        pages["activePageName"] = PAGE
    outputs[Path("pages") / "pages.json"] = pages
    return outputs


def main() -> None:
    global DEFINITION
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output-dir", type=Path)
    parser.add_argument("--definition", type=Path, help="Report definition folder to read and --apply to (default: the report)")
    args = parser.parse_args()
    production = DEFINITION
    if args.definition:
        DEFINITION = args.definition.resolve()
    outputs = build()
    destination = args.output_dir.resolve() if args.output_dir else DEFINITION
    if args.output_dir and (destination == production.parent or production.parent in destination.parents):
        raise ValueError("Review drafts must be outside the production report folder; use --apply for the merge.")
    changed = []
    for relative, value in outputs.items():
        path = destination / relative
        if value is None:
            if path.exists():
                changed.append(relative.as_posix() + " (removed)")
                if not args.check:
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            continue
        text = rendered(value)
        if not path.exists() or desktop_neutral(json.loads(path.read_text(encoding="utf-8-sig"))) != desktop_neutral(value):
            changed.append(relative.as_posix())
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    print(json.dumps({"result": "FAIL" if args.check and changed else "PASS", "page": PAGE, "changed": changed}, indent=2))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
