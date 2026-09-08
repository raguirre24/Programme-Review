# Relationship allowance assessments

Use this reference when investigating `06.free_float` or a relationship whose progress state affects its meaning. The assessment uses the same signed predecessor-working-time inverse calculation as the exported value. It holds the selected successor endpoint fixed, applies the configured lag operation, and reports hours divided by positive predecessor hours/day. It does not reschedule the project or certify P6 driving status.

## Progress and endpoint matrix

N means not started; A means active. Supported endpoint types are `TT_Task`, `TT_Rsrc`, `TT_Mile` and `TT_FinMile`. A numeric relationship with either endpoint `TT_Rsrc` is explicitly `Estimated`, using TASK-calendar movement; the exporter does not solve all assigned-resource calendars or resource constraints. Other supported numeric relationships are `Finite`. All numeric cases still require unambiguous identities, valid endpoints, calendars, HPD and lag evidence.

| Predecessor -> successor | Type and exported mode | Assessment basis |
| --- | --- | --- |
| N -> N | FS, SS, FF, SF | Existing remaining endpoint mapping; progressed mode is not required. |
| A -> N | FS, FF | Predecessor remaining finish to successor remaining start or finish. |
| A -> N or A | SF | `FixedEvent`: predecessor actual start cannot move with remaining work. |
| A -> N or A | SS, explicit ActualStart basis under Retained Logic/Progress Override | `FixedEvent`: predecessor actual start is fixed. |
| A -> N | SS, EarlyStart or unresolved basis | `RequiresContext`: remaining/internal SS scheduling context is unavailable. |
| N or A -> A | FS, Retained Logic | Predecessor remaining finish to successor explicit remaining restart. |
| N or A -> A | FF, Retained Logic | Predecessor remaining finish to successor explicit remaining finish. |
| N -> A | SF, Retained Logic | Remaining predecessor start to successor remaining finish; `CalculatedRetainedStartToFinish`. |
| N or A -> A | SS, except the fixed-actual-start case above | `RequiresContext`: no substitution of successor remaining restart for its actual start. |
| N or A -> A | FS, Progress Override, zero lag | Ignored only when the successor has a valid actual start on or before the project Data Date. |
| N or A -> A | Other Progress Override case, excluding fixed starts above | `RequiresContext`; no remaining lag or phase is invented. |
| N or A -> A | Actual Dates, excluding fixed SF start above | `RequiresContext` under this remaining displacement model. |
| Any completed endpoint | Any | Historical: actual events are fixed. |
| Unfinished WBS-summary endpoint | Any | `NoFiniteBound` / `IgnoredSummaryRelationship`; direct summary relationships are ignored. |
| Unfinished LOE endpoint | Any | `RequiresContext`; movement depends on its linked activity network. |

When a progressed mode is required but not exported, the outcome is missing data. A malformed or contradictory required value is invalid data. Missing/invalid endpoint evidence can prevent an otherwise supported case from calculating. The audit's selected endpoint fields identify the timestamps actually used; the normal 01/06 display date policy remains separate.

The exported `sched_retained_logic` / `sched_progress_override` flags select Retained Logic with Y/N, Progress Override with N/Y, and Actual Dates with N/N. Blank/absent flags do not imply N/N. The exported `sched_lag_early_start_flag` records EarlyStart for Y and ActualStart for N; Actual Dates reports this basis as not applicable. Every active endpoint requires a valid actual start and an unambiguous owning-project Data Date, including when only the predecessor is active. Actual start after an available remaining start/finish is `InvalidData` / `ActualStartAfterRemainingEndpoint`. Actual start after its Data Date instead returns `RequiresContext` / `ActualStartAfterDataDate`; it is not declared invalid under every P6 scheduling mode. These checks precede fixed-event/mode decisions. An actual finish on unfinished work or an actual start on unstarted work is `InvalidData` / `InconsistentActivityState`; a reversed remaining period is `InvalidData` / `ReversedRemainingPeriod`.

Treat the matrix as conditional coverage, not a replacement for assessment precedence. Explicitly ignored external settings (`sched_outer_depend_type=SD_None`) can establish `NoFiniteBound` / `IgnoredExternalRelationship`; otherwise progressed cross-project cases return `RequiresContext` / `UnverifiedMultiProjectProgressContext` before fixed-event interpretation. Matching project flags alone cannot establish the governing scheduling project. Historical and ignored-summary branches precede calendar/lag checks that are unnecessary for those outcomes; fixed-start cases also need no lag value to establish that the event cannot move. These labels do not certify all unused source fields as valid. The new Retained Logic N -> A SF allowance uses the successor's explicit remaining finish: changing its valid historical actual start while preserving chronology does not change the allowance.

## Reading an audit

`XerTransformer.AssessRelationships()` returns one assessment per raw TASKPRED row, including rows with no numeric allowance. The optional `XerToCsvConverter.RelationshipAudit.Cli` accepts repeated `--input` arguments and an explicit `--output <chosen-file.csv>`, with `--overwrite` for an existing audit target. The output parent folder must exist; no default filename is selected. Inputs remain ordered occurrences. Running an audit does not add normal CSVs, alter numbered schemas or extend review manifests.

The public `free_float_status` values are `Finite`, `Estimated`, `NoFiniteBound`, `Historical`, `FixedEvent`, `RequiresContext`, `MissingData` and `InvalidData`. Only `Finite` and `Estimated` carry a number; every other status leaves `free_float` blank. `NoFiniteBound` describes an ignored relationship and never serializes infinity or a large sentinel. `FixedEvent` distinguishes a valid actual start from a movable remaining endpoint. Zero is a real numeric result, not a substitute for any blank status.

Table 06 adds `free_float_status`, `free_float_basis` and `free_float_reason` immediately after `free_float`. The assessment API exposes these as `AllowanceStatus`, `CalculationBasis` and `ReasonCode`. Numeric bases are `TaskCalendarRemainingEndpoint`, `TaskCalendarSuspensionAdjusted`, `TaskCalendarResourceEstimate` and `TaskCalendarResourceEstimateSuspensionAdjusted`. Nonnumeric bases are `HistoricalActualEvent`, `FixedActualStart`, `IgnoredRelationship`, `UnresolvedContext` and `None` for missing/invalid evidence. Preserve the status, basis and reason with the number in reports.

The optional audit retains legacy classifications for compatibility:

| Public status | Legacy audit classification | Meaning of the blank or number |
| --- | --- | --- |
| `Finite` | `Calculated` | Numeric supported endpoint allowance. |
| `Estimated` | `Calculated` | Numeric TASK-calendar allowance involving a resource-dependent endpoint. |
| `NoFiniteBound` | `Ignored` | Blank: this ignored relationship imposes no finite bound of its own. |
| `Historical` | `Historical` | Blank: at least one endpoint activity is complete. |
| `FixedEvent` | `Unsupported` | Blank: the relevant predecessor actual start has already occurred. |
| `RequiresContext` | `Unsupported` | Blank: a scheduling rule, movement model or governing context is unresolved. |
| `MissingData` | `MissingData` | Blank: required source evidence is absent. |
| `InvalidData` | `InvalidData` | Blank: required evidence is malformed, ambiguous or contradictory. |

Use `ReasonCode` for grouping and `Message` for explanation. Preserve negative and subday values. Another successor, a constraint or a resource could still restrict the predecessor in a full scheduling run. A historical predecessor can impose a fixed release or unexpired lag; a blank movement allowance does not imply that the relationship has no scheduling effect.

Identify a row by its public source namespace and one-based source TASKPRED row ordinal, with the qualified relationship ID when available. Native relationship IDs and original filenames can repeat across inputs. The internal parser occurrence token is not a durable report key and is not exposed as an audit identity.

The optional audit schema is version 1.1 with 46 columns: version 1.0's provenance, assessment fields, scheduling-option raw/state pairs and `input_evidence`, plus `free_float_status` and `free_float_basis` immediately after `free_float`. The existing `reason_code` remains the audit reason field. Raw input evidence preserves field distinctions: `AbsentHeader` means that occurrence never exported the column; `OmittedCell` means its row ended before the column; `Blank` is an explicitly empty cell; `Present` retains a supplied value. Typed assessment can label an unusable supplied value `Malformed`. A later input's schema must not turn an earlier absent field into an explicit blank default. Inspect scheduling mode, lag-calendar/SS basis, Data Date, endpoints and HPD together with raw evidence. Import raw evidence as text.

Parsed-data callers can edit existing cells before assessment. Original field presence and raw text remain immutable evidence; evaluation uses the caller's current value for an originally present/blank cell. The audit adds `evaluation_value` and `evaluation_state` only when they differ from the original evidence. Audit evidence maps supplied values to `Valid`, or `Malformed` when a recognized typed field fails validation; untyped supplied text is also labelled `Valid`, not `Present`. That label is not proof that an untyped identifier resolves uniquely. The underlying parser still retains `Present` as its source-presence state. A padded or caller-created value cannot fabricate source evidence for an originally absent header or omitted cell. Distinguish raw source evidence from an explicit parsed-data edit when reconciling an audit.

Missing calendar identities produce `MissingData` with `UnresolvedPredecessorCalendar` or `UnresolvedLagCalendar`; a present calendar that cannot be resolved produces `InvalidData` with `InvalidPredecessorCalendar` or `InvalidLagCalendar` and its parse/inheritance failure. Nonzero lag with a missing setting is `MissingData`, while a malformed supplied setting or ambiguous options is `InvalidData`; both use `UnresolvedLagCalendarSetting`, so inspect classification and raw evidence together. A genuinely exported blank lag-calendar setting retains the successor-calendar default; absent headers and omitted cells do not.

A valid closed predecessor suspension removes `[suspend.Date, resume.Date)` from an immutable movement-calendar overlay used for working-time counting and inverse/forward movement. The independently configured lag calendar is unchanged, including `rcal_Predecessor`; the shared base calendar, other activities, shifts and inherited exceptions remain intact. A same-civil-day pair excludes no time and retains the ordinary basis, even if its intraday clocks are reversed. A valid nonempty interval selects the suspension-adjusted basis even when the calculated movement is zero or does not cross it. Recorded closed future intervals are usable; no additional suspension-before-Data-Date restriction is imposed.

Suspension requires an active `TT_Task` or `TT_Rsrc` predecessor and a suspend date on or after its actual-start date; otherwise the result is `InvalidData` / `InconsistentSuspensionState`. A missing suspend/resume bound gives `RequiresContext` / `UnresolvedSuspensionBounds`, including at zero movement. Malformed bounds or resume.Date before suspend.Date give `InvalidData` / `InvalidSuspensionBounds`. No resume date or zero allowance is invented. These checks apply to a candidate movable allowance; independently established historical, ignored or fixed-event outcomes do not require a movement overlay. This is an activity-specific movement calculation, not a reschedule.

Normal Standard Enhanced exports contain the selected numbered tables and `XER_DATA_QUALITY.csv`; raw-only exports do not acquire that companion. Programme 4.0 and Tender 2.0 retain their ten numbered tables, companion and manifest, with the expanded table 06 contract. Loaders that require Programme 3.0/Tender 1.0 or exact old headers must migrate before refreshing these new bundles. This repository does not change external Power BI reports, SharePoint loaders or LongestPathVisual. Header-only table 06 retains the metadata columns; last-resort table recovery preserves available rows with blank float and `RequiresContext` / `UnresolvedContext` / `TableGenerationFailed`. Imported columns colliding with calculated metadata retain their evidence under collision-safe `raw_...` aliases. The companion reports affected fields and source evidence; the optional audit additionally records every successful relationship and its complete selected calculation basis. Review date-only columns cannot reconstruct intraday arithmetic.

## Evidence boundaries

Source reconciliation, synthetic forward-feasibility tests, file/stream equality, fixed-profile comparisons and a successful CLI run establish the implemented contract at the tested inputs. They do not certify native P6 scheduling parity, a browser-saved ZIP, report refresh or deployed UI behavior. Keep original XER files unchanged and local unless the user authorizes an upload. Do not change a report's least-float policy merely because a relationship is ignored, historical, unsupported or positive.
