# Schedule Metrics implementation notes

The existing Schedule Metrics page and gauge/trend layout are retained. This
is a DCMA-inspired assessment using the current dataset, not a claim that all
14 DCMA checks are implemented or that the source schedule was rescheduled.

## Definitions and populations

Core activity checks use incomplete discrete activities (`TT_Task`, `TT_Rsrc`;
`Not Started`, `In Progress`). Milestones, LOE and WBS summaries are excluded
from those denominators. Relationship checks use links into these activities;
their predecessors need not themselves be incomplete. Missing logic counts an
activity once if either end is missing. The two component counts remain useful
diagnostics.

| Scored check | Green | Amber | Red |
| --- | --- | --- | --- |
| Missing predecessor or successor | <=5% | >5% to 10% | >10% |
| Leads | 0% | >0% to 1% | >1% |
| Positive lags | <=5% | >5% to 10% | >10% |
| Finish-to-start links | >=90% | 80% to <90% | <80% |
| Restrictive primary constraints | <=5% | >5% to 10% | >10% |
| Negative total float | 0% | >0% to 1% | >1% |
| Remaining duration above 44 working days | <=5% | >5% to 10% | >10% |
| Date integrity | 0% | >0% to 0.1% | >0.1% |

These are the approved practical review bands for this report, not a claim of
standard DCMA certification. Green is within band, amber needs review and red
is a priority. The compact metric titles show the green / amber boundaries;
gauge markers retain the green boundary. High float above 44 working days is
a blue review indicator with no universal pass/fail target and no score weight.
Its gauge target marker is removed; its percentage, counts and history remain.

Relationship denominators use eligible links with a known lag or recognised
relationship type. All positive lags count, including those of five days or
less. Constraints use recognised primary codes; blank means unconstrained and
secondary constraints are unavailable. Float is already in working days.
Remaining duration uses known, nonnegative remaining days and remains a custom
work-definition check. Date integrity includes completed activities, milestones
and unscheduled work, using the meaningful milestone endpoints.

Invalid dates additionally catches missing required fields, future actual dates,
overdue forecasts, inconsistent finish status and reversed start/finish dates.
The imported status-aware `Start` field is used; a raw actual-start field is not
available. Missing float/duration/lag, negative duration and unknown relevant
enums are excluded from the denominator of their affected check. Other known
records remain assessable. Each rate is therefore an observed rate among known
records, with excluded counts disclosed in the tooltip. An affected rate returns
BLANK only when no usable records remain or the snapshot/identity scope is
invalid. Partial-input warnings are separate from severity: an observed priority
result remains red, and an observed within-band result remains green. Coverage
is disclosed in the score status and metric tooltips.

`PR_FS1` is an explicit user-confirmed alias for `PR_FS`, not a general prefix
match or a new relationship type inferred from the standard. Imported rows are
retained: the report does not deduplicate a `PR_FS` row against a `PR_FS1` row.
Other unknown relationship types remain excluded and visible in coverage counts.

The total-float working-day unit is confirmed by the user's data contract.
Remaining-duration days are confirmed by the current CSV/exporter contract; no
fresh live Athena historical-object unit verification was performed. No extra
field conversion is introduced, and remaining duration remains a custom check.

All ratios use safe division and unavailable snapshots return BLANK. A single
project/programme/update with valid unique activity codes is required. Health
measures override the old incomplete/type/unscheduled filters to apply their own
documented populations while retaining project/WBS scope, datalake exclusions
and RLS. Baseline detail diagnostics use the whole project/programme so WBS or
current-status selection cannot redefine the original commitment.

## Score and presentation

The **Schedule health score** gives each assessed check 1 point for green,
0.5 for amber and 0 for red, then divides total points by assessed-check count.
The eight scored checks are listed above. Raw percentages are not averaged.
A check with usable inputs is assessed on those inputs; a check with no usable
result is omitted from the denominator. No assessable checks, or no incomplete
discrete work, gives N/A. High float and every selectable detail option are
excluded from scoring.

The overall colour shows the worst assessed severity: red if any check is a
priority, amber if there is a review check but no priority, and green if all
assessed checks are within band. A high numeric score can therefore remain red.
This prevents an aggregate from hiding a priority issue. A score of 100% means
all assessed checks are green; it does not imply complete evidence or assure
delivery.

The existing status card shows within/review/priority counts on its first line
and `SM Score Coverage` on its second. Coverage reports assessed/applicable
checks, unassessed checks and partial inputs independently of severity.
`SM Partial Checks` counts assessed checks with incomplete inputs; wholly
unavailable checks appear in the assessed/applicable gap. Coverage does not
replace a red or amber severity colour. The score denominator is the dynamic
assessed count, with eight configured checks rather than a fixed denominator.

The scored set is explicit: changes must stay aligned across points, severity,
assessed/applicable counts, coverage, colour measures, guide bands and tests.
Adding a diagnostic option does not add score weight. Zero-float share,
high float and longest-path share remain diagnostics. Longest-path
membership uses `driving_path_flag = "Y"`, not total float equal to zero.

The existing gauge/trend positions and IDs remain unchanged. High-float history
uses diagnostic blue. Other trend styles remain unchanged; their history-aware
tooltips show the severity at each update rather than colouring a whole history
from the selected cutoff. The guide can be refreshed with
`python scripts/schedule_metrics/build_metric_guide.py --content-only`; this
updates its reference table and two text visuals without rebuilding bookmarks,
filters, interactions or layout.

The trend axis remains the disconnected `UpdateHistory[UpdateDate]`; wrappers
return values only through the selected `CurrentDate` cutoff. The hidden
`SM Selected History Cutoff` helper reads an explicit date selection using
`FILTERS` before falling back to the visible maximum date. This preserves the
chosen cutoff when bidirectional project filtering removes that date from the
current project's available snapshots. Multiple selected dates use their maximum.
An unavailable selected update leaves current gauges BLANK while retaining valid
earlier history. The counts table
retains its task `UpdateDate` and base-measure bindings; each displayed row is
evaluated at its own snapshot and preserves the existing drill-through context.
Trend categories retain available but unassessed snapshot dates, so unknown
periods can be displayed as gaps. A separate history-scope filter removes future
dates and dates at which the selected project has no snapshot.

## Baseline detail

The four-option detail control uses current Table 01 data only:

- Matched-baseline missed dates (internal warning benchmark at most 5%).
- Matched-baseline execution index (internal benchmark at least 0.95).
- Current activity coverage by a matching dated baseline (100% means every
  current eligible activity matches a baseline activity with a finish date).
- Longest-path share (contextual diagnostic, with no universal pass threshold).

The baseline is the minimum loaded update for the selected project and programme,
with explicit baseline-filename provenance validation. Table 04 is itself a
derived earliest-snapshot subset, so it is not an independent proof that a real
baseline was supplied. An update-only history must not silently become a baseline.
Cross-snapshot matching uses activity code within project/programme, never
snapshot-local task IDs. Duplicate/blank keys and missing baseline provenance
remain guards. Row-level date/status exclusions apply only to metrics needing
those inputs, so unrelated field warnings do not blank all matched-cohort values.

Missed dates use matched discrete activities with known baseline/current finish
dates that were due by the data date; Start/status warnings do not remove a known
finish comparison. Execution index uses dated baseline matches with a known
completion state: Complete with an actual finish on/before the data date, or
Not Started/In Progress with no actual finish. Its numerator and due denominator
use the same eligible cohort; Start/current forecast Finish do not gate this
index. Tooltips show assessed, known and excluded counts. The missed-date and
execution-index colours use their unchanged performance benchmarks even when
inputs are partial; the partial-input status and tooltip disclose exclusions
separately. Baseline coverage is a completeness indicator: green at 100%, amber
below 100%, independent of performance. Unrelated source warnings remain
informational.

Matched-cohort diagnostics are explicitly custom and excluded from the score.
Coverage uses the current eligible activity cohort as its denominator; 100%
does not mean all original baseline activities have been retained. Baseline
activity codes absent from the current snapshot are disclosed separately.
When baseline activities disappear from the current snapshot, the dataset does
not establish whether they completed, were deleted or were renumbered. Their
unknown status must not be silently treated as complete or late. Coverage is
shown alongside the matched metrics; those metrics are not labelled full-cohort
DCMA Missed Tasks or BEI. The execution index can legitimately exceed 1, and the
gauge scale and format must preserve that value.

## Validation limits and repaired drill-through scope

The approved drill-through repair moves `Is Unscheduled = false` from the
report to the other 12 pages. Schedule Metrics and its two detail pages now
share the activity population, including unscheduled work. Governance and
security remain unchanged. The four Summary bookmark captures use the same local filter
placement. See [DRILLTHROUGH-VALIDATION.md](DRILLTHROUGH-VALIDATION.md) for the
implementation, loaded-model reconciliation and native Desktop evidence.

The speculative Date alignment diagnostic has been removed at the user's
request: its counts-table column, detail page, page-menu bookmarks, guide row
and dedicated measures are retired. Missing Predecessor and Missing Successor
remain the two activity detail routes. The guide now contains 18 rows. The
eight scored checks, Date integrity, all existing gauge/trend positions and
the remaining table fields are preserved. The imported classification is not
presented as a schedule-health metric; source queries remain unchanged.

Automated checks can evaluate proposed DAX against the loaded Desktop cache
using query-scoped overrides and isolated fixtures, or the actual loaded
measures with `-UseLoadedModel`. They do not refresh live sources or modify the
open model. Native Desktop checks and Service refresh are separate evidence.
