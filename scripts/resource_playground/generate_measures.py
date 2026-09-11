"""Generate the sparse table-11 scenario measures; no calendar/date expansion.

The generated TMDL supplies review-only drafts once a deployed table exists. Use
--output-dir and compare expressions with TOM before targeted integration, so
Desktop-saved metadata is preserved. This generator keeps the three
interval kernels identical apart from the daily weighting function, so fixes to
weekday arithmetic and exception replacement cannot drift between them.
"""

import argparse
from pathlib import Path
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "Project Review - Programme (datalake).SemanticModel/definition/tables/Resource Scenario Measures.tmdl"
TABLE = "'11 XER_CALENDAR_DETAILED'"
MEASURES = []


def add(name, expression, description, fmt="#,0.########", hidden=False, folder="Results"):
    MEASURES.append((name, dedent(expression).strip(), description, fmt, hidden, folder))


add("Scenario Selected Start", """
IF(NOT ISFILTERED('Scenario Start'), TODAY(), SELECTEDVALUE('Scenario Start'[Date]))
""", "Start defaults to today only when its entire input table is unfiltered. An unmatched or ambiguous typed date remains blank.", "dd-MM-yyyy", True, "Internal\\Inputs")
add("Scenario Selected Target", """
VAR StartDate = [Scenario Selected Start]
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN IF(NOT ISFILTERED('Scenario Target'), IF(NOT ISBLANK(StartDate), MIN(StartDate + 30, HorizonEnd)), SELECTEDVALUE('Scenario Target'[Date]))
""", "Target defaults to the earlier of start plus 30 days and the available date coverage end, only when its input table is unfiltered. Unmatched or ambiguous typed dates remain blank.", "dd-MM-yyyy", True, "Internal\\Inputs")

INPUT_HELPERS = {
    "Scenario Selected Rate": ("Scenario Rate", "Value", "100"),
    "Scenario Selected Limit": ("Scenario Limit", "Value", "100"),
    "Scenario Selected Mode": ("Scenario Mode", "Mode", '"Find finish date"'),
    "Scenario Selected Basis": ("Scenario Rate Basis", "Basis", '"Per working day"'),
    "Scenario Selected Limit Mode": ("Scenario Limit Mode", "Mode", '"No limit"'),
    "Scenario Selected Unit": ("Scenario Unit", "Unit", '"items"'),
}
for name, (table, column, default) in INPUT_HELPERS.items():
    add(name, f"IF(NOT ISFILTERED('{table}'), {default}, SELECTEDVALUE('{table}'[{column}]))",
        "Evaluated input defaults only when its entire table is unfiltered; invalid or ambiguous filtered selections remain blank.",
        "@" if default.startswith('"') else "#,0.##", True, "Internal\\Inputs")


SCOPE = f"""
VAR CalendarKey = SELECTEDVALUE('Scenario Calendar'[clndr_id_key])
VAR ProjectKey = SELECTEDVALUE('Scenario Calendar'[ProjectKey])
VAR CsvSource = SELECTEDVALUE('Scenario Calendar'[IsCsvSource])
VAR CalendarRows =
    CALCULATETABLE(
        {TABLE},
        KEEPFILTERS(TREATAS({{ CalendarKey }}, {TABLE}[clndr_id_key])),
        KEEPFILTERS(TREATAS({{ ProjectKey }}, {TABLE}[ProjectKey])),
        KEEPFILTERS(TREATAS({{ CsvSource }}, {TABLE}[IsCsvSource]))
    )
"""

VALID_HOURS = f"""
    NOT ISBLANK({TABLE}[work_hours])
    && {TABLE}[work_hours] >= 0 && {TABLE}[work_hours] <= 24
    && NOT ISBLANK({TABLE}[working_day_int])
    && IF({TABLE}[work_hours] > 0,
        {TABLE}[working_day] == "Y" && {TABLE}[working_day_int] == 1,
        {TABLE}[working_day] == "N" && {TABLE}[working_day_int] == 0)
""".strip()

add("Scenario Selected Quantity", """
VAR Quantity = IF(NOT ISFILTERED('Scenario Quantity'), 1000, SELECTEDVALUE('Scenario Quantity'[Value]))
VAR Scale = IF(NOT ISFILTERED('Scenario Quantity Scale'), 1, SELECTEDVALUE('Scenario Quantity Scale'[Multiplier]))
RETURN IF(NOT ISBLANK(Quantity) && NOT ISBLANK(Scale), CONVERT(Quantity * Scale, DOUBLE))
""", "Selected quantity multiplied by the explicit scale. Unfiltered defaults are 1000 and 1; invalid or ambiguous filtered selections remain blank.", folder="Inputs")

add("Scenario Quantity Tolerance", """
VAR Quantity = [Scenario Selected Quantity]
RETURN IF(NOT ISBLANK(Quantity), MAX(0.00000001, ABS(Quantity) * 0.00000000000001))
""", "Floating-point completion tolerance: max(1e-8, quantity times 1e-14). Used only when proving completion and snapping a numerically complete remainder to zero; daily capacities are not rounded.", hidden=True, folder="Internal\\Allocation")

add("Scenario Target Validation", """
VAR StartDate = [Scenario Selected Start]
VAR TargetDate = [Scenario Selected Target]
VAR HorizonStart = TODAY()
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN SWITCH(TRUE(),
    ISBLANK(TargetDate), "Enter one valid target date (DD-MM-YYYY).",
    ISBLANK(StartDate), "Enter one valid start date (DD-MM-YYYY).",
    TargetDate < HorizonStart || TargetDate > HorizonEnd,
        "Target date must be between " & FORMAT(HorizonStart, "dd-MM-yyyy") & " and " & FORMAT(HorizonEnd, "dd-MM-yyyy") & ".",
    TargetDate < StartDate, "Target finish is before the start date.",
    "")
""", "Require a valid target from today through the available date coverage, and on or after start in both calculation modes.", "@", True, "Internal\\Validation")

add("Scenario Input Validation", """
VAR Quantity = [Scenario Selected Quantity]
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR TargetDate = SELECTEDVALUE('Scenario Target'[Date])
VAR Mode = SELECTEDVALUE('Scenario Mode'[Mode])
VAR Basis = SELECTEDVALUE('Scenario Rate Basis'[Basis])
VAR Rate = SELECTEDVALUE('Scenario Rate'[Value])
VAR LimitMode = SELECTEDVALUE('Scenario Limit Mode'[Mode])
VAR DailyLimit = SELECTEDVALUE('Scenario Limit'[Value])
VAR HorizonStart = TODAY()
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN
    SWITCH(TRUE(),
        ISBLANK(Quantity), "Select one quantity and quantity scale.",
        Quantity < 0, "Quantity must be zero or positive.",
        ISBLANK([Scenario Selected Unit]), "Select one unit.",
        NOT (Mode IN { "Find finish date", "Meet target date" }), "Select one calculation mode.",
        NOT (Basis IN { "Per working day", "Per working hour" }), "Select one production basis.",
        ISBLANK(StartDate), "Enter one valid start date (DD-MM-YYYY).",
        StartDate < HorizonStart || StartDate > HorizonEnd,
            "Start date must be between " & FORMAT(HorizonStart, "dd-MM-yyyy") & " and " & FORMAT(HorizonEnd, "dd-MM-yyyy") & ".",
        NOT (LimitMode IN { "No limit", "Daily limit" }), "Select one daily limit mode.",
        LimitMode = "Daily limit" && ISBLANK(DailyLimit), "Select one daily limit.",
        LimitMode = "Daily limit" && DailyLimit < 0, "Daily limit must be zero or positive.",
        Mode = "Find finish date" && ISBLANK(Rate), "Select one production rate.",
        Mode = "Find finish date" && Rate < 0, "Production rate must be zero or positive.",
        [Scenario Target Validation] <> "", [Scenario Target Validation],
        ""
    )
""", "Validate disconnected inputs without calling rate, target capacity or finish solvers.", "@", True, "Internal\\Validation")

add("Scenario Calendar Validation", SCOPE + f"""
VAR WeekRows = FILTER(CalendarRows, ISBLANK({TABLE}[date]) && {TABLE}[exception_type] == "Standard")
VAR UndatedMarkers = COUNTROWS(FILTER(CalendarRows, ISBLANK({TABLE}[date]) && {TABLE}[exception_type] <> "Standard"))
VAR ValidWeekRows = FILTER(WeekRows,
    NOT ISBLANK({TABLE}[day_of_week_num])
    && {TABLE}[day_of_week_num] >= 1 && {TABLE}[day_of_week_num] <= 7
    && ({VALID_HOURS}))
VAR UniqueWeekdays = COUNTROWS(SUMMARIZE(WeekRows, {TABLE}[day_of_week_num]))
VAR SourceMonths = COUNTROWS(SUMMARIZE(CalendarRows, {TABLE}[MonthUpdate]))
RETURN
    SWITCH(TRUE(),
        NOT HASONEVALUE('Project_Dimension'[ProjectKey]), "Select one project.",
        NOT HASONEVALUE('CurrentDate'[UpdateDate]) || ISBLANK(SELECTEDVALUE('CurrentDate'[UpdateDate])),
            "Select one report update month.",
        COUNTROWS('Scenario Calendar') > 1 && HASONEVALUE('Scenario Calendar'[Calendar]),
            "This calendar name identifies more than one calendar in the selected project and update. Select a unique calendar name.",
        COUNTROWS('Scenario Calendar') <> 1 || ISBLANK(CalendarKey) || ISBLANK(ProjectKey) || ISBLANK(CsvSource),
            "Select one calendar available for the selected project and update.",
        COUNTROWS(CalendarRows) = 0, "The selected calendar has no available table-11 rows in the current project scope.",
        SourceMonths <> 1, "The calendar identity contains conflicting source snapshots.",
        UndatedMarkers > 0, "Calendar exceptions include an unresolved date or inheritance marker.",
        COUNTROWS(WeekRows) <> 7 || UniqueWeekdays <> 7, "Calendar requires seven unique standard weekday rules.",
        COUNTROWS(ValidWeekRows) <> 7, "Calendar weekday hours or working flags are unknown or inconsistent.",
        ""
    )
""", "Require one secured identity, exactly seven valid Standard rules and no undated unknown exception marker. Source defects are not repaired.", "@", True, "Internal\\Validation")

add("Scenario First Unknown Date", SCOPE + f"""
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR Exceptions = FILTER(CalendarRows, NOT ISBLANK({TABLE}[date]) && {TABLE}[date] >= StartDate)
VAR InvalidRows = FILTER(Exceptions,
    NOT ({VALID_HOURS})
    || {TABLE}[date] <> INT({TABLE}[date])
    || ISBLANK({TABLE}[day_of_week_num])
    || {TABLE}[day_of_week_num] <> WEEKDAY({TABLE}[date], 2)
    || NOT ({TABLE}[exception_type] IN {{ "Exception - Working", "Exception - Non-Working" }})
    || ({TABLE}[exception_type] = "Exception - Working" && {TABLE}[work_hours] <= 0)
    || ({TABLE}[exception_type] = "Exception - Non-Working" && {TABLE}[work_hours] <> 0))
VAR DateCounts = GROUPBY(Exceptions, {TABLE}[date], "__Rows", COUNTX(CURRENTGROUP(), 1))
VAR DuplicateDates = FILTER(DateCounts, [__Rows] <> 1)
VAR FirstInvalid = MINX(InvalidRows, INT({TABLE}[date]))
VAR FirstDuplicate = MINX(DuplicateDates, INT({TABLE}[date]))
RETURN IF(ISBLANK(FirstInvalid), FirstDuplicate,
    IF(ISBLANK(FirstDuplicate), FirstInvalid, MIN(FirstInvalid, FirstDuplicate)))
""", "First invalid or duplicated dated replacement on or after the requested start. It limits proof but does not invalidate a prior proven completion.", "dd-MM-yyyy", True, "Internal\\Validation")

add("Scenario Safe Through", """
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
VAR UnknownDate = [Scenario First Unknown Date]
RETURN IF([Scenario Calendar Validation] = "",
    IF(ISBLANK(UnknownDate), HorizonEnd, MIN(HorizonEnd, UnknownDate - 1)))
""", "Last provable calendar date, capped at the final date of the full shared axis regardless of chart date, week or month filters.", "dd-MM-yyyy", True, "Internal\\Validation")


def kernel(name, weight, description, production=False):
    rate_vars = """
VAR Rate = [Scenario Applied Rate]
VAR Basis = SELECTEDVALUE('Scenario Rate Basis'[Basis])
VAR LimitEnabled = SELECTEDVALUE('Scenario Limit Mode'[Mode]) = "Daily limit"
VAR DailyLimit = SELECTEDVALUE('Scenario Limit'[Value])
""" if production else ""
    def weighted(h):
        if production:
            return f"VAR RawCapacity = IF(Hours > 0, IF(Basis = \"Per working hour\", Rate * Hours, Rate), 0)\nRETURN IF(LimitEnabled, MIN(RawCapacity, DailyLimit), RawCapacity)"
        return "VAR WeightResult = " + weight + "\nRETURN WeightResult"
    add(name, SCOPE + f"""
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR Endpoint = MAX('Scenario Date'[Date])
VAR SafeThrough = [Scenario Safe Through]
{rate_vars}
VAR WeekRows = FILTER(CalendarRows, ISBLANK({TABLE}[date]) && {TABLE}[exception_type] == "Standard")
VAR Exceptions = FILTER(CalendarRows, NOT ISBLANK({TABLE}[date]) && {TABLE}[date] >= StartDate && {TABLE}[date] <= Endpoint)
VAR SpanDays = MAX(0, INT(Endpoint - StartDate) + 1)
VAR FullWeeks = QUOTIENT(SpanDays, 7)
VAR ExtraDays = MOD(SpanDays, 7)
VAR StartWeekday = WEEKDAY(StartDate, 2)
VAR WeeklyTotal = SUMX(WeekRows,
    VAR RuleWeekday = {TABLE}[day_of_week_num]
    VAR Occurrences = FullWeeks + IF(MOD(RuleWeekday - StartWeekday, 7) < ExtraDays, 1, 0)
    VAR Hours = {TABLE}[work_hours]
    VAR DailyWeight = {weighted('Hours')}
    RETURN Occurrences * DailyWeight)
VAR ExceptionCorrection = SUMX(Exceptions,
    VAR ExceptionWeekday = WEEKDAY({TABLE}[date], 2)
    VAR NormalHours = MAXX(FILTER(WeekRows, {TABLE}[day_of_week_num] = ExceptionWeekday), {TABLE}[work_hours])
    VAR ReplacementHours = {TABLE}[work_hours]
    VAR NormalWeight =
        VAR Hours = NormalHours
        {weighted('Hours')}
    VAR ReplacementWeight =
        VAR Hours = ReplacementHours
        {weighted('Hours')}
    RETURN ReplacementWeight - NormalWeight)
RETURN
    IF(NOT ISBLANK(StartDate) && NOT ISBLANK(Endpoint)
        && StartDate >= TODAY() && StartDate <= CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
        && Endpoint >= TODAY() && Endpoint <= CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
        && [Scenario Calendar Validation] = ""
        {('&& NOT ISBLANK(Rate)' if production else '')},
        IF(Endpoint < StartDate, 0,
            IF(Endpoint <= SafeThrough, MAX(0, WeeklyTotal + ExceptionCorrection))))
""", description, hidden=True, folder="Internal\\Sparse interval kernels")


kernel("Scenario Hours Through", "Hours", "Cumulative working hours from the selected start to the axis endpoint: seven weekday counts plus dated replacement deltas. Never iterates all prior dates.")
kernel("Scenario Working Days Through", "IF(Hours > 0, 1, 0)", "Cumulative count of positive-hour working dates using weekday arithmetic and exception deltas; this is not hours divided by eight.")

add("Scenario Required Rate", """
VAR Quantity = [Scenario Selected Quantity]
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR TargetDate = SELECTEDVALUE('Scenario Target'[Date])
VAR Basis = SELECTEDVALUE('Scenario Rate Basis'[Basis])
VAR HourlyCapped = Basis = "Per working hour" && SELECTEDVALUE('Scenario Limit Mode'[Mode]) = "Daily limit"
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
VAR AvailableWork =
    IF(Basis = "Per working day",
        CALCULATE([Scenario Working Days Through], REMOVEFILTERS('Scenario Date'), TREATAS({ TargetDate }, 'Scenario Date'[Date])),
        CALCULATE([Scenario Hours Through], REMOVEFILTERS('Scenario Date'), TREATAS({ TargetDate }, 'Scenario Date'[Date])))
RETURN IF([Scenario Input Validation] = "" && [Scenario Calendar Validation] = "" && [Scenario Target Validation] = ""
    && NOT ISBLANK(TargetDate) && TargetDate >= StartDate && TargetDate <= HorizonEnd
    && NOT HourlyCapped && NOT ISBLANK(Quantity),
    IF(Quantity = 0, 0, DIVIDE(CONVERT(Quantity, DOUBLE), CONVERT(AvailableWork, DOUBLE))))
""", "Production required by the inclusive target date: quantity per working date, or per working hour without a daily cap. Capped hourly inverse is explicitly unsupported.")

add("Scenario Applied Rate", """
VAR Mode = SELECTEDVALUE('Scenario Mode'[Mode])
RETURN IF([Scenario Input Validation] = "",
    CONVERT(IF(Mode = "Meet target date", [Scenario Required Rate], SELECTEDVALUE('Scenario Rate'[Value])), DOUBLE))
""", "Rate used by forward capacity; inverse mode supplies its required rate. Does not depend on capacity or finish.", hidden=True, folder="Internal\\Inputs")

kernel("Scenario Capacity Through", "", "Cumulative production capacity from seven weekday counts plus dated replacement deltas. Each daily capacity is capped before aggregation.", production=True)

add("Scenario Allocated Through", """
VAR Quantity = [Scenario Selected Quantity]
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR Endpoint = MAX('Scenario Date'[Date])
VAR SafeThrough = [Scenario Safe Through]
VAR Tolerance = [Scenario Quantity Tolerance]
VAR Capacity =
    IF(Endpoint <= SafeThrough, [Scenario Capacity Through],
        IF(SafeThrough < StartDate, 0,
            CALCULATE([Scenario Capacity Through], REMOVEFILTERS('Scenario Date'), TREATAS({ SafeThrough }, 'Scenario Date'[Date]))))
RETURN IF(Endpoint >= TODAY() && Endpoint <= CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
    && [Scenario Input Validation] = "" && [Scenario Calendar Validation] = "",
    SWITCH(TRUE(),
        Quantity = 0, 0,
        Endpoint < StartDate, 0,
        ISBLANK(Capacity), BLANK(),
        Capacity >= Quantity - Tolerance, Quantity,
        Endpoint > SafeThrough, BLANK(),
        MIN(Quantity, Capacity)))
""", "Quantity allocated through an axis endpoint. Before today or beyond the available date coverage it is blank. Within that coverage, after unknown availability it remains Q only when completion is already proven; blanks are never coerced into zero capacity.", hidden=True, folder="Internal\\Allocation")

add("Scenario Boundary Quantity", """
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR PeriodStart = MIN('Scenario Date'[Date])
VAR PeriodEnd = MAX('Scenario Date'[Date])
VAR Quantity = [Scenario Selected Quantity]
VAR KnownPeriodEnd = MIN(PeriodEnd, [Scenario Safe Through])
VAR ThroughEnd = IF(KnownPeriodEnd >= StartDate,
    CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({ KnownPeriodEnd }, 'Scenario Date'[Date])))
VAR ThroughBefore = IF(PeriodStart <= StartDate, 0,
    CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({ PeriodStart - 1 }, 'Scenario Date'[Date])))
RETURN IF(PeriodEnd >= StartDate && PeriodStart <= KnownPeriodEnd && NOT ISBLANK(ThroughEnd) && NOT ISBLANK(ThroughBefore)
    && ThroughBefore < Quantity,
    MAX(0, ThroughEnd - ThroughBefore))
""", "Exact allocation over one contiguous visible bucket using two cumulative endpoints, clipped to known coverage.", hidden=True, folder="Internal\\Allocation")

add("Scenario Bucket Quantity", """
VAR __ScenarioBucketStart = MIN('Scenario Date'[Date])
VAR __ScenarioBucketEnd = MAX('Scenario Date'[Date])
VAR VisibleDates = VALUES('Scenario Date'[Date])
VAR IsContiguous = COUNTROWS(VisibleDates) = INT(__ScenarioBucketEnd - __ScenarioBucketStart) + 1
RETURN IF(IsContiguous, [Scenario Boundary Quantity],
    SUMX(VisibleDates, CALCULATE([Scenario Boundary Quantity])))
""", "Use two endpoints for a contiguous bucket. Explicitly sparse date filters sum only those selected dates, never all historical dates.", hidden=True, folder="Internal\\Allocation")

add("Scenario Cumulative Quantity", """
VAR StartDate = [Scenario Selected Start]
VAR PeriodStart = MIN('Scenario Date'[Date])
VAR PeriodEnd = MAX('Scenario Date'[Date])
VAR SafeThrough = [Scenario Safe Through]
VAR KnownPeriodEnd = MIN(PeriodEnd, SafeThrough)
VAR Allocated = IF(KnownPeriodEnd >= StartDate,
    CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({ KnownPeriodEnd }, 'Scenario Date'[Date])))
RETURN IF(PeriodEnd >= StartDate && PeriodStart <= CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date')) && NOT ISBLANK(Allocated)
    && (PeriodStart <= SafeThrough || Allocated = [Scenario Selected Quantity]), Allocated)
""", "Cumulative allocated quantity at the latest visible endpoint. Partial periods stop at known coverage; a proven completed quantity remains complete beyond later unknown dates only inside the available date coverage.")


def date_solver(name, kernel_name, threshold, description):
    add(name, f"""
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR SafeThrough = [Scenario Safe Through]
VAR Threshold = {threshold}
VAR Tolerance = {'[Scenario Quantity Tolerance]' if kernel_name == 'Scenario Capacity Through' else '0'}
VAR MonthValues = CALCULATETABLE(VALUES('Scenario Date'[Month]), REMOVEFILTERS('Scenario Date'))
VAR MonthCandidates = SELECTCOLUMNS(
    FILTER(MonthValues, EOMONTH('Scenario Date'[Month], 0) >= StartDate && 'Scenario Date'[Month] <= SafeThrough),
    "__Endpoint", MIN(EOMONTH('Scenario Date'[Month], 0), SafeThrough))
VAR MonthCapacity = ADDCOLUMNS(MonthCandidates, "__Capacity",
    VAR ProbeDate = [__Endpoint]
    RETURN CALCULATE([{kernel_name}], REMOVEFILTERS('Scenario Date'), TREATAS({{ ProbeDate }}, 'Scenario Date'[Date])))
VAR FirstBoundary = MINX(FILTER(MonthCapacity, NOT ISBLANK([__Capacity]) && [__Capacity] >= Threshold - Tolerance), [__Endpoint])
VAR MonthStart = IF(NOT ISBLANK(FirstBoundary), MAX(StartDate, EOMONTH(FirstBoundary, -1) + 1))
VAR DatesInMonth = CALCULATETABLE(
    VALUES('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'),
    'Scenario Date'[Date] >= MonthStart, 'Scenario Date'[Date] <= FirstBoundary)
VAR DailyCapacity = ADDCOLUMNS(DatesInMonth, "__Capacity",
    VAR ProbeDate = 'Scenario Date'[Date]
    RETURN CALCULATE([{kernel_name}], REMOVEFILTERS('Scenario Date'), TREATAS({{ ProbeDate }}, 'Scenario Date'[Date])))
RETURN IF([Scenario Input Validation] = "" && [Scenario Calendar Validation] = ""
    && NOT ISBLANK(Threshold) && Threshold > 0 && SafeThrough >= StartDate && NOT ISBLANK(FirstBoundary),
    MINX(FILTER(DailyCapacity, NOT ISBLANK([__Capacity]) && [__Capacity] >= Threshold - Tolerance), 'Scenario Date'[Date]))
""", description, "dd-MM-yyyy")


date_solver("Scenario Finish Date", "Scenario Capacity Through", "[Scenario Selected Quantity]", "Earliest proven completion day: month-end checkpoints clipped to known coverage, followed by at most 31 daily probes. Independent of chart zoom.")
date_solver("Scenario Effective Start", "Scenario Working Days Through", "IF([Scenario Selected Quantity] > 0, 1)", "First eligible working date on or after the selected start, found with the same bounded month-then-day search.")

add("Scenario Working Days", """
VAR FinishDate = [Scenario Finish Date]
RETURN IF(NOT ISBLANK(FinishDate),
    CALCULATE([Scenario Working Days Through], REMOVEFILTERS('Scenario Date'), TREATAS({ FinishDate }, 'Scenario Date'[Date])))
""", "Positive-hour working dates from the requested start through the proven finish, including the partial final working date.", "#,0")
add("Scenario Elapsed Days", """
VAR FinishDate = [Scenario Finish Date]
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
RETURN IF(NOT ISBLANK(FinishDate), INT(FinishDate - StartDate) + 1)
""", "Inclusive civil days from the requested start through proven finish, including initial nonworking dates.", "#,0")

add("Scenario Daily Hours", SCOPE + f"""
VAR AxisDate = SELECTEDVALUE('Scenario Date'[Date])
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR SafeThrough = [Scenario Safe Through]
VAR ExceptionRows = FILTER(CalendarRows, {TABLE}[date] == AxisDate)
VAR WeekRows = FILTER(CalendarRows, ISBLANK({TABLE}[date]) && {TABLE}[exception_type] == "Standard"
    && {TABLE}[day_of_week_num] = WEEKDAY(AxisDate, 2))
RETURN IF(NOT ISBLANK(AxisDate) && AxisDate >= StartDate && AxisDate <= SafeThrough
    && [Scenario Input Validation] = "" && [Scenario Calendar Validation] = "",
    IF(COUNTROWS(ExceptionRows) = 1, MAXX(ExceptionRows, {TABLE}[work_hours]), MAXX(WeekRows, {TABLE}[work_hours])))
""", "Selected date's resolved table-11 hours: dated replacement first, otherwise its validated weekday rule. Unknown days stay blank.")
add("Scenario Daily Capacity", """
VAR Hours = [Scenario Daily Hours]
VAR Rate = [Scenario Applied Rate]
VAR RawCapacity = IF(Hours > 0, IF(SELECTEDVALUE('Scenario Rate Basis'[Basis]) = "Per working hour", Rate * Hours, Rate), 0)
RETURN IF(NOT ISBLANK(Hours) && NOT ISBLANK(Rate),
    IF(SELECTEDVALUE('Scenario Limit Mode'[Mode]) = "Daily limit", MIN(RawCapacity, SELECTEDVALUE('Scenario Limit'[Value])), RawCapacity))
""", "Available production on the selected date before remaining quantity truncates the final allocation.")
add("Scenario Daily Remaining", """
VAR Allocated = [Scenario Allocated Through]
RETURN IF(HASONEVALUE('Scenario Date'[Date]) && NOT ISBLANK(Allocated), MAX(0, [Scenario Selected Quantity] - Allocated))
""", "Unallocated scenario quantity after the selected date, retaining unknown rather than inventing zero.")
add("Scenario Show Daily Row", """
VAR AxisDate = SELECTEDVALUE('Scenario Date'[Date])
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
RETURN IF(ISBLANK(AxisDate) || ISBLANK(StartDate) || AxisDate < StartDate
    || StartDate < TODAY() || AxisDate > CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date')), 0,
    VAR ThroughBefore = IF(AxisDate <= StartDate, 0,
        CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({ AxisDate - 1 }, 'Scenario Date'[Date])))
    RETURN IF([Scenario Input Validation] = "" && [Scenario Calendar Validation] = ""
        && NOT ISBLANK(ThroughBefore) && ThroughBefore < [Scenario Selected Quantity], 1, 0))
""", "Retained daily row predicate, including the first unresolved day. Native daily detail uses bounded display measures without a visual-level measure filter.", "0", True, "Internal\\Display")

add("Scenario Show Period Row", """
VAR PeriodStart = MIN('Scenario Date'[Date])
VAR PeriodEnd = MAX('Scenario Date'[Date])
VAR StartDate = [Scenario Selected Start]
VAR PeriodOrder = SELECTEDVALUE('Scenario Period'[Period Order])
RETURN IF(NOT HASONEVALUE('Scenario Period'[Period Order]) || NOT (PeriodOrder IN { 1, 2 }) || ISBLANK(StartDate)
    || StartDate < TODAY() || PeriodEnd < StartDate || PeriodStart > CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date')), 0,
    VAR ThroughBefore = IF(PeriodStart <= StartDate, 0,
        CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({ PeriodStart - 1 }, 'Scenario Date'[Date])))
    RETURN IF([Scenario Input Validation] = "" && [Scenario Calendar Validation] = ""
        && NOT ISBLANK(ThroughBefore) && ThroughBefore < [Scenario Selected Quantity], 1, 0))
""", "Retained period row predicate with early date guards and one required display period. Native charts use bounded display measures without a visual-level measure filter.", "0", True, "Internal\\Display")

CHART_DISPLAY_KERNEL = r"""
VAR StartDate = [Scenario Selected Start]
VAR PeriodStart = MIN('Scenario Date'[Date])
VAR PeriodEnd = MAX('Scenario Date'[Date])
VAR HorizonStart = TODAY()
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
@PERIOD_DECLARATIONS@
VAR Quantity = [Scenario Selected Quantity]
RETURN IF(@SELECTION_GUARD@ || ISBLANK(StartDate)
    || ISBLANK(Quantity) || Quantity <= 0 || PeriodEnd < StartDate
    || StartDate < HorizonStart || StartDate > HorizonEnd || PeriodStart > HorizonEnd, BLANK(),
    IF([Scenario Input Validation] <> "" || [Scenario Calendar Validation] <> "", BLANK(),
        VAR SafeThrough = [Scenario Safe Through]
        RETURN IF(ISBLANK(SafeThrough) || SafeThrough < StartDate || PeriodStart > SafeThrough, BLANK(),
            VAR CalendarKey = SELECTEDVALUE('Scenario Calendar'[clndr_id_key])
            VAR ProjectKey = SELECTEDVALUE('Scenario Calendar'[ProjectKey])
            VAR CsvSource = SELECTEDVALUE('Scenario Calendar'[IsCsvSource])
            VAR CalendarRows = CALCULATETABLE(
                '11 XER_CALENDAR_DETAILED',
                KEEPFILTERS(TREATAS({CalendarKey}, '11 XER_CALENDAR_DETAILED'[clndr_id_key])),
                KEEPFILTERS(TREATAS({ProjectKey}, '11 XER_CALENDAR_DETAILED'[ProjectKey])),
                KEEPFILTERS(TREATAS({CsvSource}, '11 XER_CALENDAR_DETAILED'[IsCsvSource])))
            VAR WeekRows = FILTER(CalendarRows, ISBLANK('11 XER_CALENDAR_DETAILED'[date]) && '11 XER_CALENDAR_DETAILED'[exception_type] == "Standard")
            VAR Exceptions = FILTER(CalendarRows, NOT ISBLANK('11 XER_CALENDAR_DETAILED'[date])
                && '11 XER_CALENDAR_DETAILED'[date] >= StartDate && '11 XER_CALENDAR_DETAILED'[date] <= SafeThrough)
            VAR Basis = [Scenario Selected Basis]
            VAR Mode = [Scenario Selected Mode]
            VAR DailyLimit = CONVERT([Scenario Selected Limit], DOUBLE)
            VAR LimitEnabled = [Scenario Selected Limit Mode] = "Daily limit"
            VAR TargetDate = [Scenario Selected Target]
            VAR StartWeekday = WEEKDAY(StartDate, 2)
            VAR TargetSpan = MAX(0, INT(TargetDate - StartDate) + 1)
            VAR TargetWeeks = QUOTIENT(TargetSpan, 7)
            VAR TargetExtra = MOD(TargetSpan, 7)
            VAR TargetWeekWork = SUMX(WeekRows,
                VAR RuleWeekday = '11 XER_CALENDAR_DETAILED'[day_of_week_num]
                VAR Occurrences = TargetWeeks + IF(MOD(RuleWeekday - StartWeekday, 7) < TargetExtra, 1, 0)
                VAR Hours = '11 XER_CALENDAR_DETAILED'[work_hours]
                RETURN Occurrences * IF(Basis = "Per working day", IF(Hours > 0, 1, 0), Hours))
            VAR TargetExceptionWork = SUMX(FILTER(Exceptions, '11 XER_CALENDAR_DETAILED'[date] <= TargetDate),
                VAR ExceptionWeekday = WEEKDAY('11 XER_CALENDAR_DETAILED'[date], 2)
                VAR NormalHours = MAXX(FILTER(WeekRows, '11 XER_CALENDAR_DETAILED'[day_of_week_num] = ExceptionWeekday), '11 XER_CALENDAR_DETAILED'[work_hours])
                VAR Hours = '11 XER_CALENDAR_DETAILED'[work_hours]
                RETURN IF(Basis = "Per working day", IF(Hours > 0, 1, 0) - IF(NormalHours > 0, 1, 0), Hours - NormalHours))
            VAR TargetWork = IF(TargetDate <= SafeThrough, MAX(0, TargetWeekWork + TargetExceptionWork))
            VAR Rate = IF(Mode = "Meet target date",
                IF(NOT (Basis = "Per working hour" && LimitEnabled), DIVIDE(CONVERT(Quantity, DOUBLE), CONVERT(TargetWork, DOUBLE))),
                CONVERT([Scenario Selected Rate], DOUBLE))
            RETURN IF(ISBLANK(Rate), BLANK(),
                VAR WeekCapacity = SELECTCOLUMNS(WeekRows,
                    "__Weekday", '11 XER_CALENDAR_DETAILED'[day_of_week_num],
                    "__Weight",
                        VAR Hours = '11 XER_CALENDAR_DETAILED'[work_hours]
                        VAR RawCapacity = IF(Hours > 0, IF(Basis = "Per working hour", Rate * Hours, Rate), 0)
                        RETURN IF(LimitEnabled, MIN(RawCapacity, DailyLimit), RawCapacity))
                VAR ExceptionCapacity = SELECTCOLUMNS(Exceptions,
                    "__ExceptionDate", '11 XER_CALENDAR_DETAILED'[date],
                    "__Correction",
                        VAR ExceptionWeekday = WEEKDAY('11 XER_CALENDAR_DETAILED'[date], 2)
                        VAR NormalCapacity = MAXX(FILTER(WeekCapacity, [__Weekday] = ExceptionWeekday), [__Weight])
                        VAR Hours = '11 XER_CALENDAR_DETAILED'[work_hours]
                        VAR RawCapacity = IF(Hours > 0, IF(Basis = "Per working hour", Rate * Hours, Rate), 0)
                        VAR ReplacementCapacity = IF(LimitEnabled, MIN(RawCapacity, DailyLimit), RawCapacity)
                        RETURN ReplacementCapacity - NormalCapacity)
                VAR KnownPeriodEnd = MIN(PeriodEnd, SafeThrough)
                VAR VisibleDates = VALUES('Scenario Date'[Date])
                VAR IsContiguous = COUNTROWS(VisibleDates) = INT(PeriodEnd - PeriodStart) + 1
                VAR SparseDates = FILTER(VisibleDates, NOT IsContiguous && 'Scenario Date'[Date] >= StartDate && 'Scenario Date'[Date] <= SafeThrough)
                VAR NeededEndpoints = DISTINCT(UNION(
                    ROW("__Endpoint", PeriodStart - 1),
                    ROW("__Endpoint", KnownPeriodEnd),
                    SELECTCOLUMNS(SparseDates, "__Endpoint", 'Scenario Date'[Date]),
                    SELECTCOLUMNS(SparseDates, "__Endpoint", 'Scenario Date'[Date] - 1)))
                VAR EndpointCapacity = ADDCOLUMNS(NeededEndpoints, "__Capacity",
                    VAR Endpoint = [__Endpoint]
                    VAR SpanDays = MAX(0, INT(Endpoint - StartDate) + 1)
                    VAR FullWeeks = QUOTIENT(SpanDays, 7)
                    VAR ExtraDays = MOD(SpanDays, 7)
                    VAR WeeklyTotal = SUMX(WeekCapacity, [__Weight] * (FullWeeks + IF(MOD([__Weekday] - StartWeekday, 7) < ExtraDays, 1, 0)))
                    VAR ExceptionTotal = SUMX(FILTER(ExceptionCapacity, [__ExceptionDate] <= Endpoint), [__Correction])
                    RETURN IF(Endpoint < StartDate, 0, MAX(0, WeeklyTotal + ExceptionTotal)))
                VAR Tolerance = [Scenario Quantity Tolerance]
                VAR EndpointAllocation = ADDCOLUMNS(EndpointCapacity, "__Allocated",
                    VAR Capacity = [__Capacity]
                    RETURN IF(Capacity >= Quantity - Tolerance, Quantity, MIN(Quantity, Capacity)))
                VAR AllocatedBefore = MAXX(FILTER(EndpointAllocation, [__Endpoint] = PeriodStart - 1), [__Allocated])
                VAR AllocatedEnd = MAXX(FILTER(EndpointAllocation, [__Endpoint] = KnownPeriodEnd), [__Allocated])
                VAR SparseQuantity = SUMX(SparseDates,
                    VAR AxisDate = 'Scenario Date'[Date]
                    VAR AllocatedDayEnd = MAXX(FILTER(EndpointAllocation, [__Endpoint] = AxisDate), [__Allocated])
                    VAR AllocatedDayBefore = MAXX(FILTER(EndpointAllocation, [__Endpoint] = AxisDate - 1), [__Allocated])
                    RETURN MAX(0, AllocatedDayEnd - AllocatedDayBefore))
                RETURN IF(AllocatedBefore < Quantity, @RESULT@)
            )
        )
    )
)
"""


def add_chart_display_measure(name, result, description, daily=False, require_period=True, folder="Display", early_guard=None):
    # Daily audit fields share the allocation arithmetic but remain independent
    # of the chart's period selector and suppress totals or ambiguous dates.
    declarations = "" if daily or not require_period else "VAR PeriodOrder = SELECTEDVALUE('Scenario Period'[Period Order])"
    guard = "NOT HASONEVALUE('Scenario Date'[Date])" if daily else (
        "NOT HASONEVALUE('Scenario Period'[Period Order]) || NOT (PeriodOrder IN { 1, 2 })" if require_period else "FALSE()")
    if early_guard:
        guard = "(" + guard + ") || (" + early_guard + ")"
    expression = (CHART_DISPLAY_KERNEL.replace("@PERIOD_DECLARATIONS@", declarations)
        .replace("@SELECTION_GUARD@", guard).replace("@RESULT@", result))
    add(name, expression, description, folder=folder)


add_chart_display_measure("Scenario Chart Quantity", "IF(IsContiguous, MAX(0, AllocatedEnd - AllocatedBefore), SparseQuantity)",
    "Chart allocation from one resolved calendar and rate per bucket. Two endpoint capacities normally suffice; sparse selected dates use only their own boundaries.")

add_chart_display_measure("Scenario Chart Cumulative Quantity", "AllocatedEnd",
    "Chart cumulative allocation using the same generated calendar and rate calculation as chart quantity; inactive and wholly unknown buckets remain blank.")

add_chart_display_measure("Scenario Period Quantity", "IF(IsContiguous, MAX(0, AllocatedEnd - AllocatedBefore), SparseQuantity)",
    "Selected allocations from one resolved sparse calendar and rate. Contiguous totals use two endpoints; sparse totals retain only selected dates. Independent of chart period selection and avoids nested inverse-rate expansion.",
    require_period=False, folder="Results",
    early_guard='[Scenario Selected Mode] = "Meet target date" && [Scenario Selected Basis] = "Per working hour" && [Scenario Selected Limit Mode] = "Daily limit"')

add_chart_display_measure("Scenario Daily Display Hours", """
VAR DayExceptions = FILTER(Exceptions, '11 XER_CALENDAR_DETAILED'[date] = PeriodEnd)
RETURN IF(COUNTROWS(DayExceptions) = 1,
    MAXX(DayExceptions, '11 XER_CALENDAR_DETAILED'[work_hours]),
    MAXX(FILTER(WeekRows, '11 XER_CALENDAR_DETAILED'[day_of_week_num] = WEEKDAY(PeriodEnd, 2)), '11 XER_CALENDAR_DETAILED'[work_hours]))
""", "Known calendar hours for an active daily audit row. Uses the shared display kernel, ignores chart period, and is bounded by today and the final date of the shared axis.", daily=True)

add_chart_display_measure("Scenario Daily Display Capacity", """
MAXX(FILTER(WeekCapacity, [__Weekday] = WEEKDAY(PeriodEnd, 2)), [__Weight])
    + SUMX(FILTER(ExceptionCapacity, [__ExceptionDate] = PeriodEnd), [__Correction])
""", "Known daily production capacity before final quantity truncation. Hidden after completion or unknown coverage; shares the chart allocation arithmetic.", daily=True)

add_chart_display_measure("Scenario Daily Display Quantity", "MAX(0, AllocatedEnd - AllocatedBefore)",
    "Known allocated quantity for an active date inside the available date coverage from today. Independent of chart period; no visual-level measure filter is needed.", daily=True)

add_chart_display_measure("Scenario Daily Display Cumulative", "AllocatedEnd",
    "Known cumulative allocation on an active daily audit row, from the same generated endpoint calculation as daily quantity.", daily=True)

add_chart_display_measure("Scenario Daily Display Remaining", "MAX(0, Quantity - AllocatedEnd)",
    "Quantity remaining after an active known date. Unknown coverage remains blank and is diagnosed by Scenario Status.", daily=True)


for name, endpoint, remaining in [
    ("Scenario Target Quantity", "SELECTEDVALUE('Scenario Target'[Date])", False),
    ("Scenario Target Remaining", "SELECTEDVALUE('Scenario Target'[Date])", True),
    ("Scenario Horizon Remaining", "[Scenario Safe Through]", True),
]:
    add(name, f"""
VAR Endpoint = {endpoint}
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR Allocated = IF(Endpoint < StartDate, 0,
    CALCULATE([Scenario Allocated Through], REMOVEFILTERS('Scenario Date'), TREATAS({{ Endpoint }}, 'Scenario Date'[Date])))
RETURN IF([Scenario Input Validation] = "" && [Scenario Calendar Validation] = ""
    {'&& [Scenario Target Validation] = ""' if name != 'Scenario Horizon Remaining' else ''}
    && NOT ISBLANK(Endpoint) && NOT ISBLANK(Allocated), {'MAX(0, [Scenario Selected Quantity] - Allocated)' if remaining else 'Allocated'})
""", "Remaining quantity at the last provable calendar date; may be a partial forecast." if name == "Scenario Horizon Remaining" else "Quantity remaining after the inclusive target date." if remaining else "Quantity allocated by the inclusive selected target date.")

add("Scenario Status", """
VAR InputIssue = [Scenario Input Validation]
VAR CalendarIssue = [Scenario Calendar Validation]
VAR TargetIssue = [Scenario Target Validation]
VAR Quantity = [Scenario Selected Quantity]
VAR Mode = SELECTEDVALUE('Scenario Mode'[Mode])
VAR Basis = SELECTEDVALUE('Scenario Rate Basis'[Basis])
VAR LimitEnabled = SELECTEDVALUE('Scenario Limit Mode'[Mode]) = "Daily limit"
VAR DailyLimit = SELECTEDVALUE('Scenario Limit'[Value])
VAR TargetDate = SELECTEDVALUE('Scenario Target'[Date])
VAR UnknownDate = [Scenario First Unknown Date]
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
VAR RequiredRate = [Scenario Required Rate]
VAR Rate = [Scenario Applied Rate]
VAR FinishDate = [Scenario Finish Date]
RETURN
    SWITCH(TRUE(),
        InputIssue <> "", InputIssue,
        Quantity = 0, "No work to distribute.",
        CalendarIssue <> "", CalendarIssue,
        Mode = "Meet target date" && Basis = "Per working hour" && LimitEnabled,
            "Target-date mode with hourly production and a daily cap is not supported. Use per working day or remove the cap.",
        Mode = "Meet target date" && NOT ISBLANK(UnknownDate) && TargetDate >= UnknownDate,
            "Target-rate calculation is unavailable: calendar data is unknown from " & FORMAT(UnknownDate, "dd-MM-yyyy") & ".",
        Mode = "Meet target date" && ISBLANK(RequiredRate), "The target interval contains no available working time.",
        LimitEnabled && DailyLimit = 0, "Daily limit is zero; no quantity can be produced.",
        NOT ISBLANK(Rate) && Rate = 0, "Production rate is zero; no finish date can be calculated.",
        Mode = "Meet target date" && Basis = "Per working day" && LimitEnabled && RequiredRate > DailyLimit,
            "Target is infeasible at the daily limit. Required: " & FORMAT(RequiredRate, "#,0.##") & " per working day.",
        NOT ISBLANK(FinishDate), "Hypothetical forecast: completion " & FORMAT(FinishDate, "dd-MM-yyyy") & "."
            & IF(Mode = "Find finish date" && TargetIssue <> "", " Target comparison unavailable: " & TargetIssue, ""),
        NOT ISBLANK(UnknownDate) && UnknownDate <= HorizonEnd,
            "Completion is unavailable: calendar data is unknown from " & FORMAT(UnknownDate, "dd-MM-yyyy") & ". Known allocation is retained.",
        "Quantity exceeds the available capacity through " & FORMAT(HorizonEnd, "dd-MM-yyyy") & "."
    )
""", "User-facing explanation for input errors, source unknowns, unsupported inverse mode, target infeasibility and proven hypothetical completion.", "@")

add("Scenario Chart Title", """
IF(NOT HASONEVALUE('Scenario Period'[Period Order]) || NOT (SELECTEDVALUE('Scenario Period'[Period Order]) IN { 1, 2 }), "Select one display period: Week or Month.",
VAR Unit = COALESCE([Scenario Selected Unit], "quantity")
VAR Basis = COALESCE([Scenario Selected Basis], "select production basis")
VAR UnknownDate = [Scenario First Unknown Date]
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN "Hypothetical resource distribution | " & Unit & " | " & Basis
    & " | Date coverage through " & FORMAT(HorizonEnd, "dd-MM-yyyy")
    & IF(NOT ISBLANK(UnknownDate) && UnknownDate <= HorizonEnd,
        " | Known allocation through " & FORMAT(UnknownDate - 1, "dd-MM-yyyy"), ""))
""", "Visible forecast and production-basis label for the resource distribution chart.", "@", folder="Display")
add("Scenario Evaluation Window", """
VAR WindowStart = TODAY()
VAR WindowEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN "Start from today, " & FORMAT(WindowStart, "dd-MM-yyyy")
    & " | Date coverage through " & FORMAT(WindowEnd, "dd-MM-yyyy") & " inclusive. Enter dates as DD-MM-YYYY."
""", "Today's minimum start and the full shared date-axis coverage end. The upper boundary is independent of date, week and month filters.", "@", folder="Display")

add("Scenario Input Summary", """
VAR Quantity = [Scenario Selected Quantity]
VAR Unit = COALESCE([Scenario Selected Unit], "select unit")
VAR CalendarName = IF(COUNTROWS('Scenario Calendar') = 1,
    COALESCE(SELECTEDVALUE('Scenario Calendar'[Calendar Name]), "unnamed calendar"), "select one calendar")
VAR StartDate = SELECTEDVALUE('Scenario Start'[Date])
VAR Rate = [Scenario Applied Rate]
VAR Basis = COALESCE([Scenario Selected Basis], "select basis")
VAR LimitEnabled = SELECTEDVALUE('Scenario Limit Mode'[Mode]) = "Daily limit"
VAR HorizonEnd = CALCULATE(MAX('Scenario Date'[Date]), REMOVEFILTERS('Scenario Date'))
RETURN
    IF(ISBLANK(Quantity), "Select quantity", FORMAT(Quantity, "#,0.##") & " " & Unit)
    & " | " & CalendarName
    & " | Start: " & IF(ISBLANK(StartDate), "select date", FORMAT(StartDate, "dd-MM-yyyy"))
    & " | Rate: " & IF(ISBLANK(Rate), "unavailable", FORMAT(Rate, "#,0.##") & " " & Basis)
    & IF(LimitEnabled, " | Daily cap: " & FORMAT(SELECTEDVALUE('Scenario Limit'[Value]), "#,0.##"), " | No daily cap")
    & " | Date coverage: " & FORMAT(TODAY(), "dd-MM-yyyy") & " to " & FORMAT(HorizonEnd, "dd-MM-yyyy")
    & " | Target: " & IF(ISBLANK([Scenario Selected Target]), "select date", FORMAT([Scenario Selected Target], "dd-MM-yyyy"))
    & ". Future exceptions are limited to those present in the selected source. Daily detail ends at completion or the date coverage limit."
""", "Evaluated quantity, calendar name, dates and capacity assumptions inside the available date coverage from today.", "@", folder="Display")


def uid(name):
    return str(uuid5(NAMESPACE_URL, "programme-review/resource-playground/" + name))


def generate(output_dir: Path | None = None):
    target = OUTPUT if output_dir is None else output_dir.resolve() / OUTPUT.name
    if output_dir is not None and target.resolve() == OUTPUT.resolve():
        raise RuntimeError("--output-dir must differ from the production tables directory.")
    if output_dir is None and target.exists():
        raise RuntimeError(
            "Refusing to overwrite the existing Desktop-saved measures table. "
            "Use --output-dir for a review-only draft and compare it with TOM."
        )
    lines = ["/// Hypothetical resource forecasts calculated directly from table-11 rules and exceptions. No calendar-by-date rows are materialised.",
             "table 'Resource Scenario Measures'", f"\tlineageTag: {uid('Resource Scenario Measures')}", ""]
    for name, expression, description, fmt, hidden, folder in MEASURES:
        expression = expression.replace('"#,0.##"', '"#,0.########"')
        if fmt == "#,0.##":
            fmt = "#,0.########"
        if name not in {"Scenario Selected Start", "Scenario Selected Target"}:
            expression = expression.replace("SELECTEDVALUE('Scenario Start'[Date])", "[Scenario Selected Start]")
            expression = expression.replace("SELECTEDVALUE('Scenario Target'[Date])", "[Scenario Selected Target]")
        if name not in INPUT_HELPERS:
            for helper, (table, column, _) in INPUT_HELPERS.items():
                expression = expression.replace(f"SELECTEDVALUE('{table}'[{column}])", f"[{helper}]")
        lines.extend([f"\t/// {description}", f"\tmeasure '{name}' = ```"])
        lines.extend("\t\t\t" + line if line else "" for line in expression.splitlines())
        lines.extend(["\t\t\t```", f"\t\tformatString: {fmt}"])
        if hidden:
            lines.append("\t\t isHidden".replace("\t ", "\t"))
        lines.extend([f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {uid(name)}", ""])
    lines.extend(["\tpartition 'Resource Scenario Measures' = m", "\t\tmode: import", "\t\tsource = #table(type table [], {})", "", "\tannotation PBI_ResultType = Table", ""])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Generated {len(MEASURES)} measures in {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Write a review-only table draft here without changing production model files.")
    generate(parser.parse_args().output_dir)
