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

| Scored check | Target (1 point) | Limit (0 points) |
| --- | --- | --- |
| Missing predecessor or successor | <=5% | 10% |
| Leads | 0% | 1% |
| Lags over 5 working days | <=5% | 10% |
| Finish-to-start links | >=90% | 80% |
| Hard constraints | <=5% | 10% |
| Negative total float | 0% | 5% |
| Remaining duration above 44 working days | <=5% | 10% |
| Date integrity | 0% | 1% |
| Out-of-sequence progress (in-progress work) | 0% | 10% |
| Baseline coverage (whole project) | >=90% | 60% |

Points fall evenly from 1 at the target to 0 at the limit. Gauge colours follow
the points: green at target, amber between target and limit, red at or past the
limit. These are internal review settings, not a claim of DCMA certification;
lags deliberately depart from DCMA (see Score policy
revision below). The compact metric titles show target / limit; gauge markers
retain the target. Every gauge on the page is scored.

Out-of-sequence counts in-progress `TT_Task`/`TT_Rsrc` activities with an FS
predecessor not yet finished, or an SS predecessor not yet started; LOE and WBS
predecessors are ignored. `06 XER_PREDECESSOR` holds raw P6 status codes
(`TK_NotStart`, `TK_Active`, `TK_Complete`), unlike the task table. With no
in-progress work it shows 0%. It replaced high float, which
scored 0 on C6014 every month (22–42% against DCMA's 5%) even where the float
was genuine; `HighFloat%` and the zero-float measures remain in the model but
are no longer shown.

Relationship denominators use eligible links with a known lag or recognised
relationship type. Only lags over 5 working days count; shorter lags, mostly on
SS/FF overlap pairs, are assessed through the FS share instead. Negative float
counts every activity with total float below zero, however small (user decision,
19 October 2026). Hard constraints evaluate incomplete activities and milestones (excluding only Level of Effort and WBS Summary) using recognised primary constraint codes; blank means unconstrained and secondary constraints are unavailable. Float is already in working days.
Remaining duration uses known, nonnegative remaining days and remains a custom
work-definition check. Date integrity includes completed activities, milestones
and unscheduled work, using the meaningful milestone endpoints.

Invalid dates additionally catches missing required fields, future actual dates,
overdue forecasts, inconsistent finish status and reversed start/finish dates.
The imported status-aware `Start` field is used; a raw actual-start field is not
available. Missing float/duration/lag, negative duration and unknown relevant
enums are excluded from the denominator of their affected check. Other known
records remain assessable. Each rate is therefore an observed rate among known
records, with excluded counts disclosed in the tooltip. An affected rate shows
0% when no usable records remain and is BLANK only when the snapshot/identity
scope is invalid. Partial-input warnings are separate from severity: an observed priority
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
project/programme/update from one XER file, with row keys present, is required.
Activity codes may repeat: J5068's July 2026 file holds `APP_7460` twice (one is
`APP_7460-1` in every other update), and Power BI compares text without regard
to case. The single-snapshot checks key rows on `task_id_key`, so a repeat no
longer blanks the page (20 October 2026); baseline coverage discloses it. Health
measures override the old incomplete/type/unscheduled filters to apply their own
documented populations while retaining project/WBS scope, datalake exclusions
and RLS. Baseline detail diagnostics use the whole project/programme so WBS or
current-status selection cannot redefine the original commitment.

## Score and presentation

The **Schedule health score** averages the assessed checks' points (1 at
target, 0 at limit, proportional between). The ten scored checks are listed
above. Raw percentages are not averaged. Every check returns a number for a
valid project/update (user decision, 19 October 2026): a check with nothing to
count shows 0%, which earns a full point for the lower-is-better checks and no
points for FS and baseline coverage. Metrics are blank only when no single
valid project/update is selected; the score is also N/A when the selection has
no incomplete discrete work.

The overall colour follows the score: green at 95% or more, amber at 75% or
more, red below 75%. One check at its limit (90% at best) keeps the score below
green but cannot make it red on its own; two stay amber (80%), three turn it
red (70%). The check's own gauge stays red and the status card still counts it
as priority. A score of 100% means every assessed check is at target; it does
not imply complete evidence or assure delivery.

### Score policy revision — 19 October 2026

The 9 October step bands (1 / 0.5 / 0 points, worst-check colour) were reviewed
for fairness as a planner guide. On the four loaded C6014 updates the headline
was red every month (50–69%) although most checks were green:

- the SS/FF overlap style was penalised twice (FS share and all lags, 94–98% of
  lags being 5 days or less);
- single items triggered half-point losses (one lead in 2,841 links), and
  rates a hair either side of a band edge jumped half a point;
- negative float of a day or two on 45 activities cost a full point, so
  truthful reporting of small slips was penalised;
- eight date records in 3,119 (0.26%) cost a full point.

The revision introduced graduated points, counted only lags over 5 days and
negative float beyond 5 days (zero points at 5%), moved the date limit from
0.1% to 1%, and coloured the headline from the score. The same updates now
score 81.5–86.7%, all amber, with FS (74–79%) still at 0 points as the clear
review item. A schedule with every check at its limit still scores 0%. All
history recalculates under the revised rules.

### Ten scored checks — 19 October 2026

Every metric presented is now scored. Baseline coverage was added (target 90%,
limit 60%, against the latest BL-tagged file on or before the selected update
so an approved re-baseline resets it), and high float was replaced by
out-of-sequence progress (target 0%, limit 10%). With ten checks the headline
thresholds moved to 95% / 75% to keep the same meaning. Negative float then
reverted to counting every activity below zero (no 5-day tolerance). On C6014
the score is 89.3% (Jul-25, out-of-sequence 0% with nothing in progress), 66.7% (Jul-26), 71.2%
(Aug-26) and 75.2% (Sep-26). Baseline coverage (68% → 44% against BL01, with
no re-baseline loaded), July's 15 of 40 out-of-sequence activities and July's
45 activities with negative float (2.6%) are the new review items.

The existing status card shows within/review/priority counts on its first line
and `SM Score Coverage` on its second. Coverage reports assessed/applicable
checks (always 10/10 for a valid selection) and partial inputs independently of
severity. `SM Partial Checks` counts checks where some, but not all, inputs are
missing. Coverage does not replace a red or amber severity colour. The score
denominator is the ten checks.

The scored set is explicit: changes must stay aligned across points, severity,
assessed/applicable counts, coverage, colour measures, guide bands and tests.

The existing gauge/trend positions and IDs remain unchanged; the former
high-float panel now shows out-of-sequence progress in the standard trend
style. Trend styles are otherwise unchanged; their history-aware
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
earlier history. The 11-column counts table (`58fbc09d197fe53515d8`)
binds task `UpdateDate` (`MMM yyyy`) and the 10 scored checks' failing-activity
count measures (`SM Missing Logic Count`, `SM Leads Activity Count`,
`SM Lags Activity Count`, `SM Non-FS Activity Count`,
`SM Restrictive Primary Count`, `Out Of Sequence Count`,
`Task_Count_Negative_Float`, `Dur >44`, `SM Invalid Dates Count`,
`SM Baseline Unmatched Activity Count`); each displayed row is evaluated at its
own snapshot and right-clicking any metric cell offers only that metric's
dedicated drill-through page.
Trend categories retain available but unassessed snapshot dates, so unknown
periods can be displayed as gaps. A separate history-scope filter removes future
dates and dates at which the selected project has no snapshot.

## Baseline detail

The detail panel shows one metric from current Table 01 data: current activity
coverage by a matching dated baseline (100% means every current eligible
activity matches a baseline activity with a finish date). The earlier missed
dates, execution index and longest-path share options were removed with their
measures; `Schedule Metric Detail` now hosts a single Baseline coverage row.

The baseline is the latest BL-tagged update on or before the selected update for
the selected project and programme (so an approved re-baseline resets the
comparison), falling back to the earliest loaded snapshot on or before the
selected update when no BL-tagged file exists (matching `04 XER_BASELINE`, so a
single-update project without a `-BL` tag evaluates against itself rather than
forcing 0%, and the tooltip discloses `(earliest update, no BL file)`). When a
`-BL` filename tag is present, strict `-BL<digits>(-<A-Z>)?_` provenance
validation applies; a malformed `-BL` tag or missing/ambiguous baseline snapshot
leaves coverage at 0% with an explicit tooltip reason.
Cross-snapshot matching uses activity code within project/programme, never
snapshot-local task IDs. Repeated or blank activity codes are disclosed in
the tooltip, not penalised: the baseline side is reduced to one row per code,
so each current activity counts at most once.

Baseline coverage is scored like the other checks (green at 90% or more, red at
60% or less) and stays whole-project: the WBS selection does not change it. It uses the current
eligible activity cohort as its denominator; 100% does not mean all original
baseline activities have been retained. Baseline activity codes absent from the
current snapshot are disclosed separately in the tooltip. When baseline
activities disappear from the current snapshot, the dataset does not establish
whether they completed, were deleted or were renumbered.

## Validation limits and 10-route scored drill-through scope

`Is Unscheduled = false` is placed at the page level on the 9 operational
visible pages (and the four Summary bookmark captures) and omitted on `Home`,
`Sched. Metrics` and all 10 hidden drill-through pages so schedule-health checks
and their activity detail lists evaluate the same population, including
unscheduled work. Governance and security remain unchanged.

Every scored check has a failing-activity count column in `58fbc09d197fe53515d8`
and a dedicated `HiddenInViewMode` single-measure drill-through page maintained
by `scripts/schedule_metrics/repair_drillthrough_display.py`:

| Drill-through page | Page ID | Bound count measure | Storage-engine `01 XER_TASK` filter |
| --- | --- | --- | --- |
| `Missing Logic` | `4da217e10ae952b9b4a4` | `SM Missing Logic Count` | `SM Fail Missing Logic` is not blank |
| `Leads` | `566c6f848f9c58ccae18` | `SM Leads Activity Count` | `SM Fail Leads > 0` |
| `Lags >5d` | `2dc1210d106d519e8c33` | `SM Lags Activity Count` | `SM Fail Lags > 0` |
| `Non-FS Relationships` | `a4aae77cfb0f528bb352` | `SM Non-FS Activity Count` | `SM Fail Non FS > 0` |
| `Hard Constraints` | `4e84ddebb9405ac18f9d` | `SM Restrictive Primary Count` | Incomplete non-LOE/non-WBS (`TT_Task`, `TT_Rsrc`, `TT_Mile`, `TT_FinMile`) + 6 hard `cstr_type` codes |
| `Out-of-Sequence` | `0ce34782f4f350ad83b5` | `Out Of Sequence Count` | `SM Fail Out Of Sequence > 0` |
| `Negative Float` | `1650221e71f2522ca403` | `Task_Count_Negative_Float` | Incomplete discrete + `total_float < 0` |
| `Remaining Duration >44d` | `381cf6286aea5f0a94f6` | `Dur >44` | Incomplete discrete + `remaining_duration > 44` |
| `Date Integrity` | `7a03ed9cacd75d91903e` | `SM Invalid Dates Count` | `SM Fail Invalid Dates` is not blank |
| `Baseline Coverage` | `68cba7045a475d22afb7` | `SM Baseline Unmatched Activity Count` | `SM Fail Baseline Coverage` is not blank |

Gauges for Leads, Lags >5d and FS relationships continue to score at
relationship grain; their counts-table columns count distinct incomplete
discrete successor activities with at least one failing incoming link, and their
`SM Drill <Route> Detail` columns list up to three offending predecessors (`+N
more`). Baseline coverage continues to score whole-project; `SM Baseline
Unmatched Activity Count` and its `Baseline Coverage` drill-through page list
unmatched eligible activities within the drilled WBS/update scope and identify
whether the activity code is absent from the baseline, lacks a baseline finish
date, or is blank, or whether no valid baseline snapshot exists.

Each drill-through `P6WBSMatrix` carries zero visual-level measure filters and is
keyed by WBS `Level_1`–`Level_7` + `task_code`, so two failing activities
sharing a code in the same WBS leaf show as one row; `Validate-Drillthrough.ps1`
checks and reports any `task_code` collapse across all 10 routes.

The legacy unscored `Missing Predecessor` and `Missing Successor` drill-through
pages (together with their four project-menu bookmarks and `SM Drill Missing
Predecessor/Successor *` measures) and the earlier speculative Date alignment
diagnostic are retired; `SM Drill Missing Logic Detail` explicitly labels each
failing activity as `Missing both (no pred. or succ.)`, `Missing predecessor`,
or `Missing successor`. The guide contains 10 rows (the 10 scored checks, with
colour-accented `Green (1 pt)`, `Amber (0–1 pt)` and `Red (0 pt)` band columns).
All existing gauge/trend positions are preserved, and source queries remain
unchanged.

Automated checks can evaluate proposed DAX against the loaded Desktop cache
using query-scoped overrides and isolated fixtures, or the actual loaded
measures with `-UseLoadedModel`. They do not refresh live sources or modify the
open model. Native Desktop checks and Service refresh are separate evidence.
