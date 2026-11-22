"""Apply and verify the horizontal rounded-top tab pageNavigator and #D12330 divider line across all 10 operational pages.

Modelled on W2TH - Finance's pageNavigator ('tabRoundTopCorners', 10 px radius, #EDF0F4 / #E2E8F0 / #D12330)
and full-width 3 px #D12330 line overlapping the bottom 4 px of the tab strip.

Each operational page keeps its exact existing visual IDs (zero net visual-count change):
  - PAGE_NAV becomes the horizontal pageNavigator (x=18, y=88, width=1884, height=34, z=20000).
  - HOME_NAV becomes the full-width accent line shape (x=0, y=118, width=1920, height=8, z=21000).
  - Banner UpdateDate slicers tuck cleanly inside y=0..81 (y=39, height=40) so nothing overlaps y=88..126.
  - Select Project button (x=1782, y=20, width=126, height=41), metadata shapes (x=1260, width=512), and the
    4 hidden Project Menu overlay visuals (x=988..1908, z >= 55000) align inside the right-hand banner.
  - HOME_NAV bookmark entries on Summary and Sched. Metrics update visualType from 'pageNavigator' to 'shape'.

Modes:
  --check   Verify navigation styling, bounds, zero y=81..128 overlap, and bookmark visualTypes (exit 1 on drift).
  --apply   Write the navigation chrome, header adjustments, and bookmark visualType updates to the report.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "Project Review - Programme (datalake).Report" / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"

ACCENT_RED = "#D12330"

EXPECTED_DISPLAY_NAMES = {
    "60269a73141469b06603": "Completion Progress",
    "584ca37745f48e8b6958": "Schedule Adherence",
}

# All 10 operational pages (Home and the 10 hidden drill-through pages are excluded).
OPERATIONAL_PAGES: list[dict] = [
    {
        "page_id": "1351c9e89c045d35e160",
        "name": "Summary",
        "page_nav": "00512552024169605546",
        "home_nav": "a80bca4d98e425e7069c",
        "update_slicer": "6ddb9f1cc011d51baf88",
        "select_btn": "6acb130ed1d561354ef5",
        "metadata_shapes": ["d22ee062727934210b2c", "8ca99c7666839eab4ada", "9bd88eac72339d01b378"],
        "menu": ("1b0199ca6ac8d14eab79", "be200f14d934dae1bec0", "3a91548c4ddc2ccbc6ba", "908b7eab1f23dc85a87c"),
    },
    {
        "page_id": "90b784e28b9f50741b0b",
        "name": "Programme",
        "page_nav": "849d94e92cb76b0402ae",
        "home_nav": "8378d1671a136231aa76",
        "update_slicer": None,
        "select_btn": "4f78d5e267656a0ac8ca",
        "metadata_shapes": ["ee923a53f52cfd89a4ac", "9c07c8641100954388dd", "03f461a9ad0401389b10"],
        "menu": ("93830d99485684facd9e", "e0f72f806623530a071e", "ef4cb267530e2d6ab185", "8ba2c330dc3cf686c85c"),
    },
    {
        "page_id": "349fceb1aa22881316d8",
        "name": "Gantt Chart",
        "page_nav": "048aaeb06ec0c8669559",
        "home_nav": "97f39455dd60046e8bd2",
        "update_slicer": "1385101dc026933eed63",
        "select_btn": "90ce65d26722436d05c0",
        "metadata_shapes": ["d9fa0348557498acaf22", "4d054e420dd73f763592", "72f70eb506aa3c80e92d"],
        "menu": ("0ccb95af1982b18b4e88", "cf60987be92fd9c7a222", "598c8b38c59c411ffead", "b95be6f48a5ff7f9024b"),
    },
    {
        "page_id": "60269a73141469b06603",
        "name": "Completion Progress",
        "page_nav": "3ada7de485b17c8b66b4",
        "home_nav": "8b050eb7306cbe1c563c",
        "update_slicer": "49e78e73ffa150d909c0",
        "select_btn": "9157df83a554288c317e",
        "metadata_shapes": ["0be7eab8a1160d69c5af", "c23b4a3337c6619967c4"],
        "menu": ("911ce61bd36b9e766de8", "4be5a607758f7dd44a48", "779fbcd804ee942584c0", "b5f57fbb4bb3b6465687"),
    },
    {
        "page_id": "584ca37745f48e8b6958",
        "name": "Schedule Adherence",
        "page_nav": "55cee430e4b337d80530",
        "home_nav": "414d44089a4b3905ed88",
        "update_slicer": "bb5ebc004c5b96514bc1",
        "select_btn": "c6d6faf7e69cc744a28a",
        "metadata_shapes": ["9d38f2774e606f403b6b", "11bc1dd9747229ca84d4", "59f619602341db72bd77"],
        "menu": ("d4cfbbae03a346fd26c8", "f44524754c3dbf4319a3", "6a6c3b8d4eeecc0a83a3", "4012a7016af92e987485"),
    },
    {
        "page_id": "4c53a34bba9dcc7f3e8c",
        "name": "Resources",
        "page_nav": "74e2064f8f7b491836ed",
        "home_nav": "f65942cc79122e1d5341",
        "update_slicer": "ad7400649f94db2c6276",
        "select_btn": "42028c831190ced43922",
        "metadata_shapes": ["8176899626f3b56a69c1", "03fe0bf469cf674fcd83", "a12fa8f42142c61203d5"],
        "menu": ("f07b62160a6bcaded91e", "bf2c5a9d2aaf3cf456d7", "d80c22aa4fc16a4ee9d2", "fa323b6b39cecca295b5"),
    },
    {
        "page_id": "ca1da4a175154c398f01",
        "name": "Calendar",
        "page_nav": "ca09navpage000000009",
        "home_nav": "ca08navhome000000008",
        "update_slicer": "ca03update0000000003",
        "select_btn": "ca07openbtn000000007",
        "metadata_shapes": ["ca04selttl0000000004", "ca05ddttl00000000005", "ca06selfil0000000006"],
        "menu": ("ca10menubg0000000010", "ca11state00000000011", "ca12proj000000000012", "ca13closebt000000013"),
    },
    {
        "page_id": "eb4b0a43085cad901574",
        "name": "Cross-WBS Analysis",
        "page_nav": "a70586e08033a1060c0e",
        "home_nav": "612b3664c4a0011ddadb",
        "update_slicer": "20a217eb520400e1b9b8",
        "select_btn": "868fe50f0be7e3d59f79",
        "metadata_shapes": ["1f1ce611c0cd31041cd7", "2901bcdf949a3ac8c590", "76e42b25c0170b790e00"],
        "menu": ("f7d730a81623609efa7f", "b5b9e58ac61e23e6960f", "a080ddcc97529e047055", "0b8551c19458f13c9d1f"),
    },
    {
        "page_id": "327b48a7fbd37ce0a51c",
        "name": "Sched. Metrics",
        "page_nav": "702daf49280b8a448783",
        "home_nav": "e4ac7038c18417cc04e2",
        "update_slicer": "92f6f22e7132b588160e",
        "select_btn": "27a3320fc07793cec13a",
        "metadata_shapes": [],
        "menu": ("9003403baa60d58e5d3b", "d778f258649d6153fd4c", "39bf0f694c30cb5529b0", "e417356479b02aac4464"),
    },
    {
        "page_id": "ea24ab599f13f4ea4572",
        "name": "Analysis",
        "page_nav": "61e0db864305eb370d9a",
        "home_nav": "aa8dc15c7c240e9067a0",
        "update_slicer": "c22b2438bbd9d00fd0e1",
        "select_btn": "e45bc3c225dae6d2d3a9",
        "metadata_shapes": ["bdfab5e73bd079886347", "abf5ecc046f1d270f610", "5bde46f89a3445e4b278"],
        "menu": ("eaf7e2cc480bee8a5d49", "519501f73536aa481135", "fba8bc780d88aab07dd2", "0ba2331cc30004d87ab1"),
    },
]

# Bookmarks that reference HOME_NAV inside visualContainers (Summary & Sched. Metrics).
HOME_NAV_BOOKMARKS = [
    ("7ba233f17b73db50f64d", "1351c9e89c045d35e160", "a80bca4d98e425e7069c", False),
    ("ee89dfac45f8e8775b22", "1351c9e89c045d35e160", "a80bca4d98e425e7069c", False),
    ("b34c0f54772d7192cb76", "1351c9e89c045d35e160", "a80bca4d98e425e7069c", False),
    ("b84be06ab571056d3338", "1351c9e89c045d35e160", "a80bca4d98e425e7069c", False),
    ("1a93e9bf0e2fc3eaa8d3", "327b48a7fbd37ce0a51c", "e4ac7038c18417cc04e2", False),
    ("2fd7cfa3db915ff3b54e", "327b48a7fbd37ce0a51c", "e4ac7038c18417cc04e2", True),
    ("909e6c8546c6587d82b9", "327b48a7fbd37ce0a51c", "e4ac7038c18417cc04e2", False),
    ("cb5d862970d6a9512370", "327b48a7fbd37ce0a51c", "e4ac7038c18417cc04e2", False),
]

DESKTOP_MANAGED_KEYS = {"$schema", "z", "tabOrder"}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def solid(colour_hex: str) -> dict:
    return {"solid": {"color": lit(f"'{colour_hex}'")}}


def hidden_container_objects() -> dict:
    return {
        "background": [{"properties": {"show": lit("false")}}],
        "border": [{"properties": {"show": lit("false")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
        "title": [{"properties": {"show": lit("false")}}],
        "subTitle": [{"properties": {"show": lit("false")}}],
        "visualHeader": [{"properties": {"show": lit("false")}}],
        "padding": [
            {
                "properties": {
                    "top": lit("0D"),
                    "bottom": lit("0D"),
                    "left": lit("0D"),
                    "right": lit("0D"),
                }
            }
        ],
    }


def build_page_navigator(visual_id: str, schema_url: str | None = None) -> dict:
    return {
        "$schema": schema_url or (SCHEMA + "visualContainer/2.14.0/schema.json"),
        "name": visual_id,
        "position": {
            "x": 18,
            "y": 88,
            "z": 20000,
            "height": 34,
            "width": 1884,
            "tabOrder": 20000,
        },
        "visual": {
            "visualType": "pageNavigator",
            "objects": {
                "pages": [{"properties": {"showHiddenPages": lit("false")}}],
                "shape": [
                    {
                        "properties": {
                            "tileShape": lit("'tabRoundTopCorners'"),
                            "tabRoundCornerTop": lit("10L"),
                        },
                        "selector": {"id": "default"},
                    }
                ],
                "fill": [
                    {"properties": {"show": lit("true")}},
                    {"properties": {"fillColor": solid("#EDF0F4")}, "selector": {"id": "default"}},
                    {"properties": {"fillColor": solid("#E2E8F0")}, "selector": {"id": "hover"}},
                    {"properties": {"fillColor": solid(ACCENT_RED)}, "selector": {"id": "selected"}},
                ],
                "outline": [
                    {"properties": {"show": lit("true")}},
                    {"properties": {"lineColor": solid("#CBD5E1"), "weight": lit("1D")}, "selector": {"id": "default"}},
                    {"properties": {"lineColor": solid("#94A3B8"), "weight": lit("1D")}, "selector": {"id": "hover"}},
                    {"properties": {"lineColor": solid(ACCENT_RED), "weight": lit("2D")}, "selector": {"id": "selected"}},
                ],
                "text": [
                    {
                        "properties": {
                            "fontSize": lit("10D"),
                            "fontColor": solid("#334155"),
                            "fontFamily": lit("'''Segoe UI Semibold'', wf_segoe-ui_semibold, helvetica, arial, sans-serif'"),
                        },
                        "selector": {"id": "default"},
                    },
                    {"properties": {"fontColor": solid("#0F172A")}, "selector": {"id": "hover"}},
                    {
                        "properties": {"fontColor": solid("#FFFFFF"), "bold": lit("true")},
                        "selector": {"id": "selected"},
                    },
                ],
                "layout": [{"properties": {"cellPadding": lit("3L")}}],
            },
            "visualContainerObjects": hidden_container_objects(),
            "drillFilterOtherVisuals": True,
        },
    }


def build_divider_line(visual_id: str, schema_url: str | None = None) -> dict:
    return {
        "$schema": schema_url or (SCHEMA + "visualContainer/2.14.0/schema.json"),
        "name": visual_id,
        "position": {
            "x": 0,
            "y": 118,
            "z": 21000,
            "height": 8,
            "width": 1920,
            "tabOrder": 21000,
        },
        "visual": {
            "visualType": "shape",
            "objects": {
                "shape": [{"properties": {"tileShape": lit("'line'")}}],
                "rotation": [{"properties": {"shapeAngle": lit("0L")}}],
                "fill": [
                    {"properties": {"fillColor": solid(ACCENT_RED)}, "selector": {"id": "default"}},
                    {"properties": {"show": lit("false")}},
                ],
                "outline": [
                    {
                        "properties": {"lineColor": solid(ACCENT_RED), "weight": lit("3D")},
                        "selector": {"id": "default"},
                    }
                ],
            },
            "visualContainerObjects": hidden_container_objects(),
            "drillFilterOtherVisuals": True,
        },
    }


def neutral(value):
    if isinstance(value, dict):
        return {k: neutral(v) for k, v in value.items() if k not in DESKTOP_MANAGED_KEYS}
    if isinstance(value, list):
        return [neutral(v) for v in value]
    return value


def expected_chrome_files(definition: Path) -> dict[Path, dict]:
    outputs: dict[Path, dict] = {}
    for cfg in OPERATIONAL_PAGES:
        pid = cfg["page_id"]
        pdir = Path("pages") / pid

        if pid in EXPECTED_DISPLAY_NAMES:
            page = read(definition / pdir / "page.json")
            page["displayName"] = EXPECTED_DISPLAY_NAMES[pid]
            outputs[pdir / "page.json"] = page

        nav_rel = pdir / "visuals" / cfg["page_nav"] / "visual.json"
        nav_cur = read(definition / nav_rel)
        outputs[nav_rel] = build_page_navigator(cfg["page_nav"], nav_cur.get("$schema"))

        line_rel = pdir / "visuals" / cfg["home_nav"] / "visual.json"
        line_cur = read(definition / line_rel)
        outputs[line_rel] = build_divider_line(cfg["home_nav"], line_cur.get("$schema"))

        if cfg["update_slicer"]:
            upd_rel = pdir / "visuals" / cfg["update_slicer"] / "visual.json"
            upd = read(definition / upd_rel)
            upd["position"]["y"] = 39
            upd["position"]["height"] = 40
            outputs[upd_rel] = upd

        btn_rel = pdir / "visuals" / cfg["select_btn"] / "visual.json"
        btn = read(definition / btn_rel)
        btn["position"].update({"x": 1782, "y": 20, "width": 126, "height": 41})
        outputs[btn_rel] = btn

        for m_id in cfg["metadata_shapes"]:
            m_rel = pdir / "visuals" / m_id / "visual.json"
            m = read(definition / m_rel)
            m["position"].update({"x": 1260, "width": 512})
            outputs[m_rel] = m

        menu_bg, menu_state, menu_proj, menu_close = cfg["menu"]
        menu_specs = [
            (menu_bg, 988, 0.3, 920, 500, 55000),
            (menu_state, 1008, 50.3, 880, 60, 56000),
            (menu_proj, 1008, 120.3, 880, 360, 57000),
            (menu_close, 1808, 10.3, 80, 32, 58000),
        ]
        for vid, x, y, w, h, z in menu_specs:
            m_rel = pdir / "visuals" / vid / "visual.json"
            v = read(definition / m_rel)
            v["position"].update({"x": x, "y": y, "width": w, "height": h, "z": z})
            outputs[m_rel] = v

    for bmid, sec_id, home_nav_id, must_hide in HOME_NAV_BOOKMARKS:
        bm_rel = Path("bookmarks") / f"{bmid}.bookmark.json"
        bm = read(definition / bm_rel)
        vc = bm["explorationState"]["sections"][sec_id]["visualContainers"][home_nav_id]
        vc["singleVisual"]["visualType"] = "shape"
        if must_hide:
            vc["singleVisual"]["display"] = {"mode": "hidden"}
        outputs[bm_rel] = bm

    return outputs


def resolve_visual_bounds(visuals: dict[str, dict]) -> list[tuple[str, float, float, float, float, dict]]:
    resolved = []
    for vid, v in visuals.items():
        pos = v["position"]
        x, y, w, h = pos["x"], pos["y"], pos["width"], pos["height"]
        grp = v.get("parentGroupName")
        if grp and grp in visuals:
            gp = visuals[grp]["position"]
            x += gp["x"]
            y += gp["y"]
        resolved.append((vid, x, y, x + w, y + h, v))
    return resolved


def run_check(definition: Path) -> None:
    errors: list[str] = []
    expected = expected_chrome_files(definition)

    for rel, exp in expected.items():
        path = definition / rel
        if not path.exists():
            errors.append(f"Missing file: {rel.as_posix()}")
            continue
        cur = read(path)
        if neutral(cur) != neutral(exp):
            errors.append(f"Chrome/bookmark drift: {rel.as_posix()}")

    for cfg in OPERATIONAL_PAGES:
        pid = cfg["page_id"]
        pname = cfg["name"]
        pdir = definition / "pages" / pid
        page = read(pdir / "page.json")
        if page["displayName"] != pname:
            errors.append(f"{pid}: displayName is {page['displayName']!r}, expected {pname!r}")

        visuals = {p.parent.name: read(p) for p in sorted((pdir / "visuals").glob("*/visual.json"))}
        nav_z = visuals[cfg["page_nav"]]["position"]["z"]
        line_z = visuals[cfg["home_nav"]]["position"]["z"]
        if not (line_z > nav_z):
            errors.append(f"{pname}: divider line z ({line_z}) must be above pageNavigator z ({nav_z})")
        for mvid in cfg["menu"]:
            mz = visuals[mvid]["position"]["z"]
            if not (mz > line_z):
                errors.append(f"{pname}: project menu {mvid} z ({mz}) must be above divider line z ({line_z})")

        menu_set = set(cfg["menu"])
        # Sched. Metrics Metric Guide full-screen backdrop also covers y=0..1080 when hidden
        guide_overlay = {"5fbf6bb45a3959aca15a", "d6730e81cc2759769303", "c8cc0477639e5511b87f",
                         "3417fca7eb12552c805f", "1493a602e8915d90b8c0", "6857152451b45c128976"}
        exempt_ids = {cfg["page_nav"], cfg["home_nav"]} | menu_set | guide_overlay

        for vid, x1, y1, x2, y2, v in resolve_visual_bounds(visuals):
            if x1 < -0.5 or y1 < -0.5 or x2 > page["width"] + 0.5 or y2 > page["height"] + 0.5:
                errors.append(f"{pname}: {vid} exceeds {page['width']}x{page['height']} bounds ({x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f})")
            if vid in exempt_ids:
                continue
            vt = v.get("visual", {}).get("visualType", "GROUP")
            if vt == "GROUP":
                continue
            # Top-banner visuals must stay above the y=88 tab strip; content visuals must start at or below y=130.
            in_banner = y1 < 60 and y2 <= 82.5
            below_line = y1 >= 130.0
            if not (in_banner or below_line):
                errors.append(f"{pname}: {vid} ({vt}) overlaps navigation band y=81..130 (y={y1:.1f}..{y2:.1f})")

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print(json.dumps({
        "status": "PASS",
        "operational_pages": len(OPERATIONAL_PAGES),
        "bookmarks_updated": len(HOME_NAV_BOOKMARKS),
        "navigation": "horizontal tabRoundTopCorners (10pt) + 3px #D12330 divider line",
    }, indent=2))


def run_apply(definition: Path) -> None:
    expected = expected_chrome_files(definition)
    written = 0
    for rel, content in expected.items():
        path = definition / rel
        text = rendered(content)
        if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written += 1
    print(json.dumps({"applied": True, "files_checked": len(expected), "files_written": written}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--definition", type=Path, default=DEFINITION)
    args = parser.parse_args()
    definition = args.definition.resolve()
    if args.check:
        run_check(definition)
    else:
        run_apply(definition)


if __name__ == "__main__":
    main()
