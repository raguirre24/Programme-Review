# Schedule Metrics drill-through acceptance — 9 October 2026

This record covers **Missing Predecessor**, **Missing Successor** and
**Date alignment**, reached from the existing Schedule Metrics counts table.
It supplements [DISPLAY-VALIDATION.md](DISPLAY-VALIDATION.md) and supersedes
that earlier pass's global-unscheduled-filter caveat and untested drill-through
status. Native observations below were reported by the agent operating the
user's main Power BI Desktop report.

## Implemented scope

- Moved `Is Unscheduled = false` from report scope to the other **12 pages**.
  Schedule Metrics and its **three drill-through pages** are exempt, so their
  counts and activity lists include the same unscheduled work. The report-level
  datalake exclusion and security definitions remain unchanged.
- Retained the existing three measure-based drill-through bindings and WBS
  hierarchy. Every target uses incomplete task-dependent/resource-dependent
  activities. Date alignment now requires a nonblank classification other than
  `Not Driven`; missing predecessor/successor targets use their respective
  flag equal to 1.
- Added **11 display helpers** for snapshot validity, context, source data date,
  source file, three count headers, status and three diagnostic evidence fields.
  All **71 existing core measure expressions**, and other pre-existing model
  measure expressions, were unchanged. These additions do not alter metric
  calculations or score thresholds.
- The three existing selected-project labels now bind `SM Drill Context`, so
  empty results retain their project and clicked update. Valid zero results
  show zero matching activities. Unavailable or ambiguous snapshots instead
  request one project and an available update. Activity status/evidence fields
  are blank on WBS summary rows.
- Updated the four Summary bookmark captures for the local filter placement.
  Navigation and project changes were checked as recorded below.

The baseline/recovery backup is `../.sdt-b47e`, relative to the repository root.
The final 11 display helpers were applied to the main loaded model through a
targeted TOM write. The validator itself made no model or data writes. No
source-data refresh or publication was performed.

## Loaded-model and saved-report evidence

[Validate-Drillthrough.ps1](Validate-Drillthrough.ps1), run with
`-UseLoadedModel`, completed with **118,899 assertions passed** against the
verified main Desktop cache (`localhost:56658`, catalog
`aefcff5f-27ab-4779-a9de-e0487c30283b`). These are session identifiers, not
connection defaults for later runs.

| Coverage | Passed result |
| --- | ---: |
| Project/programme/update snapshots | 16 |
| Source measure versus destination activity-count comparisons | 48 |
| Loaded zero-count cases | 13 |
| Comparisons under the WBS dimension filter | 118,149 |
| Isolated source/destination fixture comparisons | 18 |
| Actual loaded display-helper checks | 480 |
| Availability/header guard checks | 42 |
| PBIR/filter/binding assertions | 70 |

All 11 loaded helper expressions matched disk. Normal population and helper
queries used the actual loaded measures without query-scoped replacements.
The validator translated the saved PBIR predicates into DAX to compare the
destination's activity population with the originating measure. It also
checked distinct activity-code grain, inherited drill-through context,
matrix/helper bindings and preservation of all 12 local exclusions.

The 480 helper checks covered all three routes and all 16 snapshots: correct
count headers, project/update context, actual source data date and filename;
matching activity-leaf counts and evidence values; and blank status/evidence
on WBS summaries. The 42 guard checks covered six real unavailable or ambiguous
selection cases plus one synthetic structural-rejection case, each on all
three routes. The real cases included unavailable task/CurrentDate updates,
multiple task/CurrentDate updates, multiple projects and direct access without
a snapshot selection.

Synthetic fixtures used isolated query-local records and the implementation's
actual expressions. They included qualifying unscheduled tasks, blank
date-alignment classifications, completed/milestone/LOE/WBS exclusions,
datalake exclusions and other project/programme/update/WBS scopes. The
structural-rejection fixture re-declared the exact helper expressions alongside
its mocked validity input: a query-local input override alone does not rebind
dependencies inside an already compiled loaded measure. This fixture is not
presented as a mutation or rejection of the user's cached source records.

## Native Desktop acceptance

| Selection or action | Observed result |
| --- | --- |
| Malabar, September selected; drill through the **August** Missing Predecessor count | **5** matching activities; clicked August context retained; status, predecessor evidence and WBS hierarchy verified. |
| Same state, August Missing Successor count | **10** matching activities; clicked August context, status, successor evidence and hierarchy verified. |
| Same state, August Date alignment count | **203** matching activities; clicked August context, status, source classification and hierarchy verified. |
| Malabar August data-date label | **04 September 2026**, the actual source data date, rather than the August update timestamp. |
| Back from each Malabar route | Returned to the source page and retained the original selection. |
| Alkimos August, Missing Predecessor | **0** matching activities and an empty activity table; project/update, source filename and data date **25 August 2026** remained visible. |
| Summary navigation | All four Summary buttons and project changes worked after the filter/bookmark migration. |

These native checks confirm the listed navigation, visible row counts,
hierarchy and labels. They do not replace the broader engine reconciliation.

## Final reload and limits

After the final reload, the focused `-HelpersOnly -UseLoadedModel` run passed
**617 assertions**: all 16 snapshots, 480 loaded-helper checks, 42 guard checks,
70 static assertions and the setup/parity checks. The full WBS/population suite
was not repeated because its definitions were unchanged. `Validate-Guide.ps1`
also passed: **19 loaded rows**, matching source content and no relationships.

Final native guide-introduction fit passed: all three paragraphs, including
the activity-list instruction and population explanation, were visible without
an introduction scrollbar. Closing the guide retained **Malabar, September
2026, all WBS, baseline coverage 81.6%**.

All three final supplementary context-label bindings were confirmed after
reload. The native zero-result test above preceded that final label rebinding;
the supplementary label has saved-binding and loaded-DAX evidence, but its
native zero-result repeat was interrupted by a Windows low-battery notice.
No successful repeat is claimed. The final four visual-file edits were saved
on disk and reloaded; a subsequent Desktop save of the closing UI selection
was not verified.

No Power BI Service, View As/RLS impersonation, fresh Athena/CSV source refresh,
or exhaustive exported-row acceptance is claimed. Retaining the security
definitions is distinct from testing them under impersonation.

For a later session, discover and verify its Desktop server/catalog before
running the parameterised validator. `-HelpersOnly -UseLoadedModel` performs
the focused loaded-helper and scope-guard pass; omitting `-HelpersOnly` runs the
complete population, WBS, fixture and helper suite.
