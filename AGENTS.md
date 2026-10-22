# Agent Instructions — Power BI / P6 Reporting Workspace

This workspace contains Power BI development and Primavera P6 schedule-data work: Power Query (M), DAX, semantic model definitions (PBIP/TMDL), SQL for Amazon Athena, and pipelines built over P6 XER exports.

## Skills (mandatory)

Specialist skills live in `.agents/skills/` — one folder per skill, each with a `SKILL.md` (some with a `references/` folder for deeper detail). If your environment auto-discovers skills from that folder, use them as designed. If it does not, treat this section as the trigger index: **before starting any task matching a description below, open and follow the corresponding `SKILL.md` in full.**

| Skill folder | Use for |
|---|---|
| `p6-schedule-data` | Anything touching Primavera P6 / XER data: TASK, TASKPRED, WBS, calendars, float, data date, percent complete, snapshots, trend-by-update visuals (history up to the `CurrentDate` selection). Also read `references/xer-table-reference.md` before writing ingestion code or wide queries |
| `p6-numbered-xer-reporting` | Anything touching the 11 numbered XER tables (`01 XER_TASK` through `15_XER_RESOURCE_DISTRIBUTION`), SharePoint CSV schema `5.0` bundles, `CSV::` compact keys, Table 11 calendar rules/exceptions, Table 06 `free_float_status`, or Table 15 resource spreads. Read the matching `references/*.md` files before modifying table contracts or measures |
| `powerbi-data-connections` | Connecting Power BI to Amazon Athena (`AmazonAthena.Databases`) or SharePoint (`SharePoint.Contents`), `AthenaScopeSql` project selection, `XerCsvRouting` ownership, `XER CSV Refresh Audit`, gateways, credentials, and environment parameters |
| `power-query-m` | Any Power Query / M code, however small; `expressions.tmdl`, query folding, SharePoint CSV streaming, refresh performance, formula firewall |
| `dax-development` | Any DAX — measures, calculated columns, time intelligence, wrong totals, filter context questions, `XER Metrics`, `Resource Scenario Measures`, and `Schedule Metric Detail` |
| `powerbi-data-modeling` | Table/relationship design, star schema, `Project_Dimension` RLS, `CurrentDate` vs `UpdateHistory`, storage modes, incremental refresh, model size |
| `powerbi-performance` | Anything slow: reports, visuals, refreshes, oversized models; profiling with DAX Studio / Performance Analyzer, avoiding visual-level measure filters on high-grain visuals |
| `powerbi-deployment-alm` | PBIP/TMDL, git, deployment pipelines, XMLA, Tabular Editor, dev/test/prod promotion |
| `programme-review-pbir-harnesses` | Anything touching PBIR report pages/visuals/bookmarks/themes (`.Report/definition/`), custom visuals, `Is Unscheduled` filter placement, or the automated verification/generation harnesses in `scripts/` (`test_prefilter.py`, `scripts/schedule_metrics/`, `scripts/resource_playground/`, `switch_theme.js`) |

Multiple skills often apply to one task (e.g. a new Athena-backed report touches connections + M + modelling + DAX). Consult every relevant one, not just the first match.

## Hard rules for this workspace (apply even without loading a skill)

- P6 `task_id` is snapshot-local; cross-export joins use `task_code` (+ project + data date). Never join snapshots on `task_id`.
- Raw P6 XER durations/floats/lags are in hours (converted upstream via the activity calendar `day_hr_cnt` or Table 11 rules, never a flat ÷8). **However, in this model's imported `01 XER_TASK` and `06 XER_PREDECESSOR` tables, `total_float`, `free_float`, `remaining_duration`, `original_duration`, and `lag` are already in working days** (do not divide them by 8 in DAX; note also that `10 XER_CALENDARS` only imports `clndr_id_key` and `clndr_name`, plus the calculated `Workweek Mask` built from Table 11's weekday rules). Historical finish/start variances (`Finish_Variance_Previous_Month`, `Variance_Finish_BL`) use the 5-day Monday–Friday SQL convention.
- Every schedule metric is relative to the Data Date (`PROJECT.last_recalc_date`); carry it with any snapshot-derived output.
- Parameterise all connection and scope values via the 9 Power Query parameters in `expressions.tmdl` (`AthenaDsn`, `SharePointSite`, `SelectedProjects`, `ExcludedProjects`, `SelectedProgrammeType`, `XerCsvEnabled`, `XerCsvProjectCodes`, `XerCsvLibrary`, `XerCsvRootFolder`) — never hard-code connection strings or project lists.
- **Desktop uses a reduced development dataset, whereas Power BI Service runs with `SelectedProjects = "ALL"` to load the full project portfolio.** Never assume the report only serves the projects currently loaded in the local Desktop cache (e.g. `J5064`, `J5068`, `C6014`). All SQL, M, calculated tables, DAX measures, and visuals must be multi-project safe, isolated by project/programme/snapshot keys, and performant at full `ALL`-projects portfolio scale.
- Preserve query folding in M (`AmazonAthena.Databases(AthenaDsn, null, [EnableNativeQuery = true])`); never add `Table.Buffer` or large-file `Binary.Buffer` to the 11 CSV loader queries.
- TMDL files: preserve tab-based indentation, `lineageTag` values, and property casing exactly; edit measures/columns in `tables/*.tmdl`, never regenerate whole files unnecessarily.
- The Athena Table 11 feed stores dated calendar exceptions one day early. `11 XER_CALENDAR_DETAILED` realigns them at load (per-source-file vote; hidden `ExceptionDateShiftDays`), so every consumer must read its `date` / `day_of_week_num` as loaded: never add another shift in DAX or M, and never infer a workweek from a calendar name (use `'10 XER_CALENDARS'[Workweek Mask]`).
- Run the matching static verification scripts before completing changes: `python scripts/test_prefilter.py` (for Athena SQL / `01 XER_TASK` / `11 XER_CALENDAR_DETAILED` edits), `python scripts/schedule_metrics/validate_static.py` (for Schedule Metrics / drill-through / guide edits), `python scripts/resource_playground/verify_rule_calculations.py` + `verify_integration.py` + `verify_comparison_integration.py` (for Resource Playground / `Resource Calendars` edits), and `python scripts/calendar_analysis/validate_calendar_analysis.py` + `validate_calendar_stretch.py` (for Calendar Analysis / Calendar Stretch edits; generate the Calendar Stretch page with `generate_stretch_page.py`, never by hand).
- Always keep `ARCHITECTURE.md` 100% accurate whenever tables, columns, measures, parameters, report pages, visuals, or scripts are added, removed, or re-architected.
- Use NZ/UK English spelling in documentation, comments, and report text.

## Conventions

- Prefer editing existing queries/measures over creating parallel copies; keep staging queries load-disabled.
- Commit-worthy outputs: PBIP/TMDL, SQL, M, and markdown docs. Never commit PBIX binaries or cache folders.
- When a task reveals a recurring correction or project-specific fact not covered by a skill, propose adding it to the relevant `SKILL.md` rather than leaving it implicit.
