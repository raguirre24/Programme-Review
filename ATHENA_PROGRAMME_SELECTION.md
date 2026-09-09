# Athena programme selection

## Business rule

Athena programme files must first match a named project in `prod_projectcontrols_linkedsitereports.dbo_project`. For exact numeric C/J codes, a nonblank name on either alias validates the project family. Other codes require their own exact registry match. Missing, null, empty or whitespace-only names do not validate a project. Files that fail this check are excluded from every XER import.

For each valid project and each programme type (Contract `C`, Target `T`), use the entire J-coded programme series whenever it exists in the eligible Athena project metadata. Use C only when no eligible J series exists for that programme type. A J series does not need to be newer than C and does not need to contain a baseline to take precedence. C-only earlier updates and C baselines are deliberately excluded once J exists. The winning series still uses the report's latest-baseline-plus-later-updates window; this change does not load every historical baseline.

`J4017-C-2608_20260831.xer` means project J4017, Contract programme, update 2608. Project prefix and programme type are independent. J Contract must not suppress C Target.

Only exact `C<digits>` and `J<digits>` forms are aliases. Preserve leading zeroes: `C04017` and `J04017` match each other, not `C4017`. Bare `4017`, `CNZ01` and underscore-containing codes remain separate exact identities. Filename project codes are trimmed and uppercased; original filenames and snapshot IDs are retained for source joins. Registry keys retain the existing exact native lookup semantics: `dbo_project.projectno` must match the canonical code or its numeric C/J alias. Registry keys are not rewritten or merged, avoiding new duplicate metadata matches.

For example, C1046 is excluded if neither C1046 nor J1046 has a usable registry name. C4018B requires a named C4018B entry: C4018 and J4018B are not aliases of it. These are lookup rules, not a hardcoded skip list. A corrected registry entry becomes eligible on the next full refresh.

## Parameters and source ownership

- `SelectedProjects`: selecting either C4017 or J4017 considers both aliases. `ALL` considers every eligible named project. An explicit selection cannot bypass the registry check; an entirely unrecognised selection returns no XER rows. This is an intentional change from exact Athena inclusion.
- `SelectedProgrammeType`: `C`, `T`, or `ALL`; preference and comparisons are independent per type.
- `ExcludedProjects`: continues to exclude the entire numeric C/J project family. It is not a way to force the C series.
- CSV ownership remains explicit. An active routed project excludes both aliases from Athena; J preference does not override a selected CSV bundle. The new registry gate applies to Athena-owned files. Existing CSV routing, files, headers, keys and manifest contracts are unchanged.
- No wildcard parameter or manually maintained J-project list is needed.

## Query-side prefiltering

`AthenaScopeSql` uses only read-only SELECT/CTE logic:

1. Read `filename` and `monthupdate` from `02_xer_project`; apply programme/project/exclusion/CSV filters there.
2. Derive a stable project identity (`CJ:<digits>` or `EXACT:<code>`).
3. Build a distinct set of named project identities from `dbo_project` and join the candidate file metadata to it. Duplicate registry entries cannot multiply the filename scope. This gate runs before J/C preference and baseline ranking.
4. Group the eligible metadata by identity and programme type and select the preferred code. Each CJ family contains only its C/J aliases, so `MAX(project_code)` selects J without a second ranking window; each exact identity has one code.
5. Remove the losing C history before parsing baseline tags and ranking baselines. Preserve full tags such as `BL1-A`, including when project codes contain underscores.
6. Produce a distinct `kept_filenames` scope. All ten XER consumers join their source tables against this scope before their downstream transformations. TASK also reuses its parsed metadata instead of parsing filenames for every activity.

No views, tables, CTAS, staging writes, database configuration or permission changes are required. There is no local download of all fact tables followed by a C/J filter.

Each native table query executes independently. Neither a shared M expression nor a SQL CTE guarantees one evaluation across an entire refresh. Do not add a large `Table.Buffer`/`Binary.Buffer` or claim cross-query caching. Athena's optimiser decides physical execution order. This design reduces the eligible rows and avoids unnecessary parsing in the activity query; actual scan-byte/time savings depend on source format, partitions and plans and require measurement.

The registry gate excludes rejected XER rows inside SQL; it does not guarantee that Athena scans no underlying files or makes no source request for an empty result. No new model-level project filter is used to hide already imported invalid rows. Project metadata names are trimmed and blank names become null consistently in `dbo_project` and TASK, allowing a usable C name to provide the existing fallback when the J name is blank. Registry keys, IDs, security metadata and roles are unchanged.

References: [AWS query optimisation](https://docs.aws.amazon.com/athena/latest/ug/performance-tuning-query-optimization-techniques.html), [Power Query multiple evaluations](https://learn.microsoft.com/en-us/power-query/multiple-queries).

## Baseline reporting-date calculation

TASK assigns each baseline row a calculated reporting `update_date`. Starting at the row's filled month-end date, it searches backwards for the nearest month-end not occupied by a nonbaseline update for the same project and programme type. The search includes the original month and 240 earlier months. This reporting date does not change the source activity start/finish dates or write to Athena.

The query now performs this search for each distinct `(project_group_key, programme_type, update_date_filled)` baseline date, then joins the one-row result back to the activities. Dates come from TASK, preserving different dates within one filename. It generates candidate months only for dated baseline groups; nonbaseline rows retain their filled date. `MAX` of the unoccupied candidate dates gives the nearest available month, replacing the old per-activity ranking and its temporary global `task_row_id` sort.

Null baseline dates remain null. If all 241 months are occupied, the result remains null. Duplicate activity rows and project-metadata join multiplicity are preserved. Project/programme separation, J/C preference, baseline selection, activity dates, downstream calculations and the exported SQL columns are unchanged.

For 10,000 baseline activities sharing one project/programme/date, the candidate search is 241 rows instead of 2,410,000; all 10,000 activities remain in the output. This is a reduction in a logical SQL intermediate, not a measured speed-up or an Athena materialisation guarantee. It primarily targets Athena execution work; the final Power BI model size is unchanged. Measure Service/gateway peak memory and refresh duration separately.

## Comparison and model consistency

- TASK SQL groups history by stable project identity and programme type rather than project display name.
- A hidden `ProgrammeType` is derived after Athena/CSV combination. Baseline selection and baseline-resource matches include it, avoiding Contract/Target mixing under `ALL`.
- PROJECT and WBS carry the same hidden canonical `ProjectKey`. Project_Dimension contains one row per project family even when J Contract and C Target both load. It chooses J as the representative when J survives for any type; otherwise it retains C. Existing metadata fallbacks are retained, and alias substitution is limited to numeric C/J codes.
- Original task/project/WBS/resource snapshot keys stay unchanged. Existing relationship IDs and RLS grant queries remain unchanged. The events relationship continues to select one display-code copy of each event.

## Selection diagnostic

`AthenaProgrammeSelectionAudit` is a load-disabled shared expression. Preview it in Power Query to inspect candidate filenames, project identity, programme type, metadata date, preferred code and reason:

- `KEPT`: included in the selected history window.
- `NO_NAMED_PROJECT_MATCH`: no named registry entry matches this canonical code or its recognised numeric C/J alias. The preferred project code is null because preference is not evaluated for this family.
- `J_HISTORY_PREFERRED`: excluded because this project's programme type has a J series.
- `OUTSIDE_BASELINE_WINDOW`: belongs to the winning code but is outside the existing baseline/history window.

The audit only sees candidates surviving the parameter filters, exclusions and CSV ownership. It includes candidates rejected by the named-project gate so their original filenames remain reviewable. It does not infer records absent from the queried metadata or grant project access. Previewing it issues a metadata query; it is not a new loaded model table.

## Validation and rollout

Automated checks: execute the extracted SQL on synthetic fixtures (Trino syntax translated to DuckDB), parse all TMDL and M, verify model relationships and preserve existing lineage IDs, check JSON and run `git diff --check`. SQL translation does not prove live Athena connector behaviour; syntax parsing does not execute M/DAX.

Run the SQL fixtures from the report repository with `python -m pip install -r scripts/requirements-prefilter.txt`, then `python scripts/test_prefilter.py`. The harness extracts SQL from the current TMDL; only parameter-to-predicate helpers are mirrored in Python. It supports `--definition` for an alternate model. The fixtures cover named-registry eligibility across all ten native source consumers, missing/blank names, exact codes, alias fallback, audit reasons, whole-history preference, scope/ownership, baseline selection, original filenames, activity comparison isolation and baseline reporting-date equivalence against the former per-activity SQL. Boundary cases include occupied months, null dates, duplicate rows, differing dates within one filename and exhaustion of the 240-month search. Runtime M/DAX and performance checks remain manual.

After external edits, reopen the PBIP in Power BI Desktop before refreshing. Do not save an older open model over the edited files.

1. Preview the metadata audit for 4017, a confirmed C-only project, both programme types, a J series with missing C-era history, and the suspected miscoded C1046/C4018B files. Confirm named-registry eligibility, the preferred code and excluded filenames with the project owner. Check that rejected projects contribute no XER rows after a full refresh.
2. Run Athena-only full refresh for `C`, `T`, then `ALL`. Confirm TASK baseline/previous values, baseline-resource totals, and no duplicate dimension keys. Inspect a mixed J-Contract/C-Target project and verify a known event cost is counted once.
3. Repeat with an active CSV-owned project. Confirm all ten XER tables have consistent source ownership and keys.
4. Use View as for C-granted/J-selected, J-granted/C-fallback, state/company/global and no-access cases. Representative metadata for a combined family comes from loaded J when available.
5. Inspect actual Athena requests and EXPLAIN plans; compare retained row counts, scanned bytes and execution time. No performance percentage is asserted without these measurements.
6. Verify Service refresh with its actual parameter values and gateway credentials before publishing this as validated behaviour.

Rollback is the pre-change versions of the changed report files, preserving any unrelated local edits. No database rollback is needed.
