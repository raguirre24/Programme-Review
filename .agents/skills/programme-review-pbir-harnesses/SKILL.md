---
name: programme-review-pbir-harnesses
description: Edit and validate the Programme Review PBIR report definition (.Report/definition/pages, visuals, bookmarks, filters, themes, custom visuals) and run the repository's automated Python/PowerShell verification and code-generation suites in scripts/ (test_prefilter.py, scripts/schedule_metrics/, scripts/resource_playground/, switch_theme.js). Use this skill whenever touching any PBIR JSON file, visual binding, bookmark, page filter, theme asset, Schedule Metrics, or Resource Calendars (Playground).
---

# Programme Review — PBIR Report & Validation Harnesses

This skill governs changes to the PBIR report layer (`Project Review - Programme (datalake).Report/definition/`) and the automated validation/generation suites in `scripts/`.

## 1. PBIR Report Structure (`16` Pages, `42` Bookmarks & `3` Custom Visuals)

- **13 Visible Pages** (`definition/pages/pages.json`):
  1. `Home` (`2cc544dc10a1e237ae90`, 17 visuals) — Landing page
  2. `Summary` (`1351c9e89c045d35e160`, 22 visuals)
  3. `Programme` (`90b784e28b9f50741b0b`, 57 visuals)
  4. `Gantt Chart` (`349fceb1aa22881316d8`, 17 visuals)
  5. `Activity Completion Progress` (`60269a73141469b06603`, 22 visuals)
  6. `Schedule Adherence Scorecard` (`584ca37745f48e8b6958`, 23 visuals)
  7. `Resources` (`099895b98057d0135349`, 21 visuals)
  8. `Resource Calendars` (`4c53a34bba9dcc7f3e8c`, 50 visuals — Resource Playground + Calendar Comparison)
  9. `Calendar Analysis` (`ca1da4a175154c398f01`, 25 visuals — Monthly Working Days Matrix with colour legend + Calendar-Stretched Critical Activities Inspector)
  10. `Sched. Metrics` (`327b48a7fbd37ce0a51c`, 55 visuals — 10 scored schedule-health gauges/trends + detail/counts tables)
  11. `Float Analysis` (`ea24ab599f13f4ea4572`, 19 visuals)
  12. `Duration Analysis` (`97f7d216ba38e55033da`, 19 visuals)
  13. `Constraint Analysis` (`1eb7703c500eb2ba5a6c`, 22 visuals)
- **3 Hidden Drill-Through Pages (`HiddenInViewMode`)**:
  14. `Cross-WBS Analysis` (`eb4b0a43085cad901574`, 25 visuals)
  15. `Missing Successor` (`4f15f55676d2add4e922`, 12 visuals)
  16. `Missing Predecessor` (`061f748900951ae92ba9`, 12 visuals)
- **3 Custom Visuals** (`CustomVisuals/` & `report.json`):
  - `timelineOfEvents1E8747A536B74AB586FADD94AE72B347`
  - `LongestPathVisual`
  - `P6WBSMatrix84723947293847`

## 2. Report & Page Filter Rules

- **Report-Level Filter (`definition/report.json`)**:
  - Filters `'01 XER_TASK'[IsExcludedFromDataLake]` across the entire report.
- **Page-Level `Is Unscheduled = false` Placement**:
  - Applied at the page level on the **13 operational pages** (`Home`, `Summary`, `Programme`, `Gantt Chart`, `Activity Completion Progress`, `Schedule Adherence Scorecard`, `Resources`, `Resource Calendars`, `Calendar Analysis`, `Float Analysis`, `Duration Analysis`, `Constraint Analysis`, `Cross-WBS Analysis`) and inside the 4 `Summary` page bookmarks.
  - **Intentionally omitted** on `Sched. Metrics` (`327b48a7fbd37ce0a51c`), `Missing Predecessor` (`061f748900951ae92ba9`), and `Missing Successor` (`4f15f55676d2add4e922`) so schedule health checks and their drill-through activity lists evaluate the same population (including unscheduled activities). Never re-add `Is Unscheduled = false` as a report-level filter.

## 3. Safe Visual & Bookmark Editing in PBIR

1. **Preserve `queryRef` Keys When Swapping Measures**:
   - In `visual.json`, conditional formatting, series colours, and markers reference projections by `"selector": {"metadata": "<queryRef>"}`. When replacing a field or binding a ` (History)` wrapper measure, update `Entity` and `Property` while keeping `queryRef` intact (or updating every matching selector and bookmark). Set `"displayName"` explicitly so legends and column headers remain clean.
2. **Scoped Reset Bookmarks (`applyOnlyToTargetVisuals: true`)**:
   - Any bookmark that resets slicers or switches panels on a page (such as Reset bookmark `e899bf3a9c2d243f33bf` on `Resource Calendars`, which targets 14 visuals) **must** set `"applyOnlyToTargetVisuals": true` in `options` and list the exact target visual IDs in `targetVisualNames`.
   - Never capture report-level or page-level `filters` inside a scoped bookmark's `explorationState` — doing so silently overwrites user slicer/filter selections on activation.
3. **Field-Parameter & Slicer Bookmark Contracts**:
   - When a bookmark resets a field-parameter slicer (`Scenario Period` visual `5f5e832a845f69b11b99`), filter the identity column (`Period Fields`, e.g. `'''Scenario Date''[Month]'`) and include matching `filterExpressionMetadata.decomposedIdentities`, never the display label column alone.
   - For clearable single-select slicers (`Scenario Calendar` visual `16643c36a5f294a63a18` and `Scenario Comparison Calendar` visual `6c020ed71f08415292d4`), keep `strictSingleSelect` set to `"false"` in both the visual and the bookmark so Reset/Clear can restore an empty selection.
4. **Canvas Background Theme Switching**:
   - Use `node scripts/switch_theme.js contract` or `node scripts/switch_theme.js target` to switch canvas background images across all `page.json` files.

## 4. Automated Validation & Generation Playbook (`scripts/`)

Always run the corresponding verification suite after making changes:

| Subsystem Touched | Required Commands | Notes |
|---|---|---|
| **Athena SQL / `expressions.tmdl` / `01 XER_TASK.tmdl` / `11 XER_CALENDAR_DETAILED.tmdl`** | `python scripts/test_prefilter.py` | Translates `AthenaScopeSql`, `01 XER_TASK` and table 11 Trino SQL to DuckDB and verifies all 11 consumer queries, table 11's dated-exception alignment vote (`CalendarAlignmentTests`), `dbo_project` filtering, `CJ:<digits>` preference (`CJ:6012` exception), and baseline month-end shifting. |
| **Schedule Metrics (`XER Metrics`, `Schedule Metric Detail`, `Schedule Metric Guide`, `Sched. Metrics`, Drill-Through Pages)** | `python scripts/schedule_metrics/validate_static.py` | Verifies all 10 scored checks, measure dependencies, guide rows, and PBIR visual/bookmark bindings offline. If `scripts/schedule_metrics/metric_guide.json` was edited, first run `python scripts/schedule_metrics/build_metric_guide.py --content-only`. When Power BI Desktop is open, also run `pwsh -File scripts/schedule_metrics/Validate-Live.ps1 -UseLoadedModel`. |
| **Resource Playground (`Resource Scenario Measures`, `Scenario *` tables, `Resource Calendars` page)** | `python scripts/resource_playground/verify_rule_calculations.py`<br>`python scripts/resource_playground/verify_integration.py`<br>`python scripts/resource_playground/verify_comparison_integration.py` | Ensure `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` is set in PowerShell before calling the TOM-backed verifiers. Never run `generate_scaffold.py`, `generate_measures.py`, or `generate_page.py` without `--output-dir <temp_dir>`. |
| **Calendar Analysis (`XER Measures` `CA *` measures, `Calendar Analysis` page)** | `python scripts/calendar_analysis/validate_calendar_analysis.py` | Verifies Monthly Civil Partition and Activity Stretch Decomposition conservation laws, TOM round-trip compilation of all 34 `CA *` measures, the `CA Inspector Selection Match` gate (summary/matrix cross-filter plus the one-project guard), the row-iterator rule for activity day counts, the matrix colour rules (grey/critical/near-critical cell measures bound to `CA Monthly Working Days`, with every colour shown in the legend), the `Workweek Mask` off-day formula against a day-by-day count for all 128 workweeks, the table 11 alignment wiring on both the Athena and CSV paths (no calendar-name workweek guesses), and PBIR page/visual/bookmark/slicer/interaction contracts. After refreshing in Desktop, also run `python scripts/calendar_analysis/validate_calendar_live.py` (read-only): every dated row's weekday matches its date, no source file still votes for a shift, and working days between Start and Finish reproduce `remaining_duration` for at least 99% of not-started activities per update. |
