# Agent Instructions — Power BI / P6 Reporting Workspace

This workspace contains Power BI development and Primavera P6 schedule-data work: Power Query (M), DAX, semantic model definitions (PBIP/TMDL), SQL for Amazon Athena, and pipelines built over P6 XER exports.

## Skills (mandatory)

Specialist skills live in `.agents/skills/` — one folder per skill, each with a `SKILL.md` (some with a `references/` folder for deeper detail). If your environment auto-discovers skills from that folder, use them as designed. If it does not, treat this section as the trigger index: **before starting any task matching a description below, open and follow the corresponding `SKILL.md` in full.**

| Skill folder | Use for |
|---|---|
| `p6-schedule-data` | Anything touching Primavera P6 / XER data: TASK, TASKPRED, WBS, calendars, float, data date, percent complete, snapshots. Also read `references/xer-table-reference.md` before writing ingestion code or wide queries |
| `powerbi-data-connections` | Connecting Power BI to SharePoint, Amazon Athena (ODBC), SQL, dataflows; gateways, credentials, refresh failures, environment parameters |
| `power-query-m` | Any Power Query / M code, however small; query folding, combining files, refresh performance, formula firewall |
| `dax-development` | Any DAX — measures, calculated columns, time intelligence, wrong totals, filter context questions |
| `powerbi-data-modeling` | Table/relationship design, star schema, storage modes, incremental refresh, model size |
| `powerbi-performance` | Anything slow: reports, visuals, refreshes, oversized models; profiling with DAX Studio / Performance Analyzer |
| `powerbi-deployment-alm` | PBIP/TMDL, git, deployment pipelines, XMLA, Tabular Editor, dev/test/prod promotion |

Multiple skills often apply to one task (e.g. a new Athena-backed report touches connections + M + modelling + DAX). Consult every relevant one, not just the first match.

## Hard rules for this workspace (apply even without loading a skill)

- P6 `task_id` is snapshot-local; cross-export joins use `task_code` (+ project + data date). Never join snapshots on `task_id`.
- All P6 durations/floats are hours; convert to days via the activity's own calendar (`CALENDAR.day_hr_cnt`), never a flat ÷8.
- Every schedule metric is relative to the Data Date (`PROJECT.last_recalc_date`); carry it with any snapshot-derived output.
- Parameterise all connection values (Athena region/workgroup/S3 staging, SharePoint site URLs, environment names) as Power Query parameters — no hard-coded connection strings.
- Preserve query folding in M; verify with View Native Query before accepting a transformation chain over Athena or SQL sources.
- TMDL files: preserve tab-based indentation and property casing exactly; edit measures/columns in `tables/*.tmdl`, never regenerate whole files unnecessarily.
- Use NZ/UK English spelling in documentation, comments, and report text.

## Conventions

- Prefer editing existing queries/measures over creating parallel copies; keep staging queries load-disabled.
- Commit-worthy outputs: PBIP/TMDL, SQL, M, and markdown docs. Never commit PBIX binaries or cache folders.
- When a task reveals a recurring correction or project-specific fact not covered by a skill, propose adding it to the relevant `SKILL.md` rather than leaving it implicit.
