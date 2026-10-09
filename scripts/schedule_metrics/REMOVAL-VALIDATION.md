# Date alignment removal

Validation record for the approved removal on 9 October 2026. Earlier validation
documents retain their historical three-route and 19-row results; this record
supersedes that feature scope.

## Scope

- Removed the Date alignment counts-table column, its dedicated drill-through
  page, related bookmarks and guide row/instructions. No replacement metric was
  added. The report retains 15 pages, two drill-through routes and 18 guide rows.
- Removed `DD Driving`, `DataDate%`, `DataDate% (History)`,
  `SM Drill Date Alignment Header`, `SM Drill Date Alignment Reason` and
  `XER Measures[ShowDriven]`. The imported `Driven_DataDate` column is retained
  and hidden; no source query or refresh policy changed.
- Missing Predecessor and Missing Successor retain their existing routes,
  populations and hierarchy. The independent invalid-dates check remains in
  the eight-check score. High float remains contextual and unscored.

The native saved backup is
`../.remove-date-alignment-20261009-173215/desktop-saved.zip`.

## Before-removal loaded baseline

The read-only target was `localhost:56658`, catalog
`aefcff5f-27ab-4779-a9de-e0487c30283b`, with 93 `XER Metrics` measures.
These identifiers describe this Desktop session, not a fixed connection.

| Project / latest update | Score | Within / review / priority | Missing predecessor / successor |
| --- | ---: | --- | --- |
| J4007 / August 2026 | 87.5% | 6 / 2 / 0 | 0 / 0 |
| J5064 / September 2026 | 62.5% | 3 / 4 / 1 | 9 / 24 |

## Automated checks

Static checks passed for 15 retained pages, 18 guide rows, exactly eight scored
checks, all 11 history bindings and all 56 Schedule Metrics visuals. The removed
page is absent from the page index and bookmark references; all six removed
measures are absent from source declarations and report field references.
The raw source classification column remains present. All eight offline Python
regression tests pass. The pre-existing `Has_Unscheduled_Task_In_Path` reference
warning is unchanged.

`Validate-Drillthrough.ps1 -SkipWbs` now checks the two retained routes. It keeps
snapshot counts, activity grain, source/detail reconciliation, isolated
population fixtures, context labels and unavailable/ambiguous snapshot guards.
It deliberately skips the exhaustive per-WBS count sweep; the remaining helper
checks still reject diagnostic evidence on WBS summary rows. The obsolete
Date alignment rate was removed from the core/cutoff validators.

The population fixture also corrects an existing expectation from seven to six
partial scored checks: high float had already been removed from the score.
This is a test correction, not a metric calculation change.

Candidate engine checks passed **87 policy/detail fixtures and 2,903 assertions**,
plus **29 aggregate population assertions**. All five updated PowerShell
validators parse and `git diff --check` passes. These checks use scoped
candidate expressions and do not claim that Desktop has loaded the removal.

After Desktop reloaded the source, eight read-only metadata assertions confirmed
88 retained `XER Metrics` measures, absence of all six removed measures and the
retained/hidden source classification column.

The direct loaded drill-through run passed **533 assertions**, including:

| Check | Result |
| --- | ---: |
| Project/programme/update snapshots | 16 |
| Retained source/destination count comparisons | 32 |
| Zero-count destinations | 12 |
| Isolated source/destination fixture comparisons | 12 |
| Loaded context and activity-evidence helper checks | 320 |
| Unavailable/ambiguous/structural snapshot guard checks | 28 |
| Other pages retaining their scheduled-only filter | 12 |

The exhaustive per-WBS count sweep was intentionally skipped. All route counts
and normal helper checks used loaded measures without candidate overrides;
isolated population and structural guard fixtures remained query-local.

The loaded guide partition was **Ready**. All **18 rows** matched the current
authored content, and the table remained disconnected. No guide processing or
source-data refresh was required.

Twelve final direct loaded assertions confirmed both baseline rows above remain
unchanged: score, within/review/priority counts and both retained diagnostic
counts. Thus the latest scores remain **87.5%** and **62.5%**. The prior all-16
score-policy validation is historical evidence; this removal run specifically
rechecks the two latest score contexts and all 16 retained drill-through contexts.

## Native Desktop acceptance

The two retained August drill-through routes were exercised in Desktop:
Missing Predecessor showed **5** matching activities and Missing Successor
showed **10**. Back restored the selected September source-page context.

After **Refresh visuals**, the guide ended with **Zero total float**, with no
Date alignment row. It was returned to the top and closed, and the report was
saved with Ctrl+S. Refresh visuals cleared a stale guide query; it did not
refresh source data.

The external reload initially displayed **ActivePageName not found** because
the removed page had been active in Desktop. The source page index already
named a retained page and contained no removed-page references. **Continue**
recovered the report. The guide partition was Ready and no source or
constant-table refresh was needed.

Desktop confirmed **Last saved Today at 5:49 pm**. The final Malabar September
view showed score **62.50%**, execution index **0.80**, date integrity **0.02%**
and no Date alignment count column. After the save settled, the static removal
checks, all eight Python regression tests and `git diff --check` passed again.

## Verification limits

The scripts issue read-only metadata/DAX statements against the cached Desktop
model. They do not refresh source data, write to the open model or establish
Service behaviour. The native acceptance above covers the reported Desktop
routes and guide state; Service behaviour and exported activity row sets were
not tested during this removal.
