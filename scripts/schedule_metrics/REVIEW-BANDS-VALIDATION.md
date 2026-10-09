# Schedule review bands — 9 October 2026

The user approved practical internal review bands and a graded score. This
supersedes the binary nine-check scoring policy in earlier validation records.
The underlying activity and relationship calculations are unchanged.

## Policy implemented

| Check | Within target: 1 point | Review: 0.5 points | Priority: 0 points |
| --- | --- | --- | --- |
| Missing logic | <=5% | >5% to 10% | >10% |
| Leads | 0% | >0% to 1% | >1% |
| Positive lags | <=5% | >5% to 10% | >10% |
| Finish-to-start | >=90% | >=80% to <90% | <80% |
| Restrictive constraints | <=5% | >5% to 10% | >10% |
| Negative float | 0% | >0% to 1% | >1% |
| Remaining duration >44 working days | <=5% | >5% to 10% | >10% |
| Date integrity defects | 0% | >0% to 0.1% | >0.1% |

These are provisional management review bands, not empirical predictions of
delivery risk. Review status does not excuse a source-data defect. High float
above 44 working days remains visible as a blue diagnostic, without a scored
threshold or gauge target marker. Its measurement alone does not establish
whether the flexibility is justified or the network logic is incomplete.

`Score` averages the nonblank points from the eight checks. The existing
`SM Passed Checks` measure counts checks within target; the new review and
priority helpers count the other two bands. The score card lists these counts
and, with explicit separators, assessed/applicable checks and input coverage. A
priority check makes the score red; otherwise a review check makes it amber,
and all assessed checks within target make it green. Coverage warnings remain
separate and cannot conceal a priority result. No usable inputs remains N/A.

All historical score points use this same policy. A difference from the previous
score is a reclassification, not evidence that the source schedule improved.
The matched execution index and missed-date targets remain 0.95 and 5%.
Baseline coverage remains a completeness indicator. Detail benchmark colours
also retain their severity when inputs are partial; their status/tooltips
continue to disclose the excluded inputs.

## Implementation and preservation

- Eight points helpers centralise numerical bands in `XER Metrics.tmdl`.
  Three additional helpers provide review count, priority count and coverage.
  Existing raw metric expressions, populations, history wrappers and drill
  helpers are preserved, together with their names, formats and lineage.
- The Schedule Metrics page retains all 56 visual identities and positions,
  all 11 history bindings and existing interactions. The high-float trend is
  blue; other trends keep their established styles and history-aware tooltips.
- Guide JSON, calculated-table text, introduction, legend and titles explain
  eight scored checks and the separate diagnostic. `--content-only` updates
  guide content without rebuilding the page or bookmark state.
- All bookmarks, other pages, governance filters and security definitions
  remain unchanged by this policy update. The earlier drill-through repairs
  remain in place, including the full right-click instruction.
- Desktop's final save updated suggested visual-title terms in `en-NZ.tmdl`
  to match the revised captions. Those are the only native-generated changes
  outside the three metric tables and the Schedule Metrics visuals.
- Native Desktop was saved before edits. Both pre-edit and saved-state
  definition archives are in `../.reviewbands-20261009-155937/`.

## Validation evidence

The final focused engine fixtures passed 2,903 assertions across
78 core policy cases and nine detail severity/coverage cases. They test exact
and adjacent boundaries, zero versus BLANK, partial inputs, unavailable checks,
score denominators and high-float exclusion. These are isolated query-scoped
fixtures; no source data or production model records were changed.

Full TMDL deserialisation, seven static regression tests, page/binding checks
and whitespace validation passed. The core updater and content-only guide
builder are idempotent. Independent review confirmed that all numerical bands
match across the measures, report captions and guide.

Direct loaded-model reconciliation passed 893 assertions across all 16
project/update snapshots. This includes all 93 core expressions and formats,
each rate, grade and colour, assessed/applicable/partial coverage, score band
counts, high-float exclusion and the score's historical endpoints. The latest
J4007 score is 87.5% (6 within, 2 review, 0 priority); the latest Malabar/J5064
score is 62.5% (3 within, 4 review, 1 priority).

The loaded guide's 19 rows match the authored text in every content column,
including targets, scoring rules and coverage notes, and remain disconnected.
Four focused checks after the final separator change verified expression
parity and the live September text without changing its 62.5% score.

Native Power BI Desktop acceptance passed in the main project:

- Malabar August displayed 56.25%, three within, three review and two priority,
  with eight assessed checks and two partial-input warnings. Trends ended at
  the selected August cutoff.
- September displayed 62.50%, three within, four review and one priority,
  eight assessed checks and complete inputs. High float showed 48.91% in blue;
  FS 83.02%, leads 0.06%, lags 7.03% and dates 0.02% were amber; negative float
  24.03% was red. The three within-band checks were green.
- Desktop initially reused cached visual results after loading external changes.
  Optimize > Refresh visuals updated both the gauges and the guide table.
  This refreshed visual queries only; no source refresh was run.
- The guide opened, scrolled and closed correctly. Native inspection confirmed
  updated bands, diagnostic high-float wording, score weights and coverage notes.
  Closing it preserved Malabar, September, WBS All and baseline coverage 81.6%.
- The report was saved at 4:24 pm NZ time with the guide closed. Final comparison
  to the saved pre-change archive found no changed visual identities/positions,
  other pages, bookmarks, governance filters or security definitions.

Source refresh, Power BI Service, View As/RLS impersonation and publication
are outside this policy change and are not claimed as tested.
