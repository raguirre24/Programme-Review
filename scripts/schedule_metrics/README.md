# Schedule Metrics validation

These checks read the proposed source and the already loaded Power BI Desktop
model. They do not refresh sources, save Desktop edits, deploy a model, or call
`SaveChanges`. Candidate runtime checks use XMLA `Statement` queries with
`DEFINE MEASURE` overrides to evaluate proposed expressions without changing the
open model. Direct-loaded checks omit those overrides and validate the measures
actually running in Desktop. See [DISPLAY-VALIDATION.md](DISPLAY-VALIDATION.md)
for the historical native visual results and cutoff fix. Current Date alignment
removal scope and checks are recorded in [REMOVAL-VALIDATION.md](REMOVAL-VALIDATION.md).

From the repository root:

```powershell
python scripts/schedule_metrics/validate_static.py
python -B -m unittest discover -s scripts/schedule_metrics -p test_static.py
pwsh -File scripts/schedule_metrics/Validate-Live.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Validate-Live.ps1 -ServerAddress localhost:61810 -UseLoadedModel
pwsh -File scripts/schedule_metrics/Validate-ReviewBands.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Validate-ReviewBands.ps1 -ServerAddress localhost:61810 -UseLoadedModel
pwsh -File scripts/schedule_metrics/Validate-Detail-Loaded.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-History-Cutoff.ps1 -ServerAddress localhost:61810 -UseLoadedModel
pwsh -File scripts/schedule_metrics/Validate-Drillthrough.ps1 -ServerAddress localhost:61810 -UseLoadedModel -SkipWbs
pwsh -File scripts/schedule_metrics/Test-Fixtures.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-Populations.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-DateRules.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-Scope.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-History-Scope.ps1 -ServerAddress localhost:61810
pwsh -File scripts/schedule_metrics/Test-Detail.ps1 -ServerAddress localhost:61810
```

The port above is an example: use the current Desktop Analysis Services port.
Omit `-ServerAddress` to discover a single local model containing `01 XER_TASK`
and `XER Metrics`. Specify `-Catalog` if needed. A local .NET 8 TOM assembly is
required; supply `-AssemblyDirectory` if it is not in the local NuGet cache.
Nothing is installed by the validator.

`-OutputPath` optionally saves numeric snapshot results and the check summary;
use a task-specific temporary path, not a checked-in business-data snapshot.
`-CompileOnly` checks proposed expressions and finite values before all new
metrics have been authored. Full validation also compares every metric's base
value with its history endpoint for every loaded project/snapshot, verifies an
earlier cutoff, and checks missing-snapshot BLANK behaviour.

The direct detail runner checks all four selector options under label-only,
ID-only and combined filters across all loaded snapshots and cutoffs. The cutoff
runner uses the report's actual project dimension to test available, unavailable,
earlier, multiple and absent explicit date selections. An unavailable selected
update must leave current gauges BLANK while retaining valid earlier history.

The drill-through runner validates the two retained Missing Predecessor and
Missing Successor routes. `-SkipWbs` retains snapshot count, fixture, leaf-evidence,
context and guard checks while skipping the exhaustive per-WBS count sweep.
Date alignment has been removed without a replacement; invalid dates remains
an independent scored check.

The fixture script executes the actual proposed ratios and score expressions,
substituting aggregate inputs through query-scoped measures. It checks the eight
scored checks, band boundaries, zero versus BLANK populations,
available-record denominators, all-missing inputs, partial coverage labels and
colours, and that false predicates do not count as passes. The review-band
runner independently checks green = 1, amber = 0.5 and red = 0 scoring, high
float's exclusion from the score, and separate input-coverage disclosure. Score
uses only assessed checks while separately reporting applicable and partial checks.
It does not replace physical task tables or pretend to simulate P6 scheduling.

The population fixture redirects actual aggregate expressions to two query-local
tables. It checks activity/milestone/LOE/WBS/completed exclusions, recovery of a
row hidden by the old unscheduled filter, exactly 44 versus above 44, null versus
zero float, union logic counting, hard versus soft constraints, positive lags
below/equal/above five days, leads, the user-confirmed `PR_FS1` alias and a truly
unknown relationship encoding. Known records remain in each rate's denominator;
unusable records are excluded only from the affected check.

The date fixture redirects the actual date-check expressions to 22 independent
activity cases, covering completed and unscheduled rows, actuals after the data
date, forecasts before it, missing fields, unknown statuses, reversed intervals,
and meaningful versus irrelevant milestone endpoints.

Static checks parse page/visual JSON, confirm model field references, preserve
the existing page identity, check bounds, and match history/base references.
They also reject measures that specify both `formatString` and
`formatStringDefinition` anywhere in the model. The offline regression fixture
proves this check rejects the pre-fix metadata and accepts the corrected form.
The runtime validator formally deserialises TMDL with Microsoft's TOM library.
These do not replace native Desktop visual rendering, interactions, or Service
refresh validation. The loaded cache may be older than the source systems.

## In-report metric guide

The **Metric guide** button on Sched. Metrics opens a scrollable reference table
on the same page. Its 18 rows cover eight scored checks, high float as a
diagnostic, the overall score, four detail options and four supporting counts.
Each row explains what the metric measures,
why it matters, its calculation, target and interpretation. **Close guide** restores the charts without
resetting project, update, WBS or detail selections. The guide uses a disconnected
constant table and does not change any metric calculations or data sources.

Edit `metric_guide.json` to maintain the definitions, then run
`python scripts/schedule_metrics/build_metric_guide.py --content-only` to update
the existing guide content without rebuilding visuals or bookmarks. The full
builder is reserved for explicitly approved guide creation or layout work.
`metric_guide_manifest.json` records the existing guide IDs.
Use `pwsh -File scripts/schedule_metrics/Validate-Guide.ps1` to check the loaded
guide's 18 rows, content parity and disconnected state. If more than one report
containing the guide is open, specify `-ServerAddress` and `-Catalog`.

Native acceptance: open the guide, scroll through the execution-index and
supporting-count rows, close it, and confirm the selected project/update/detail
and chart values remain intact. In Desktop edit mode, use Ctrl+click on buttons;
report readers use a normal click.
