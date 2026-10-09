"""Apply the approved internal review bands to XER Metrics only.

Preserves existing measure identities, metadata, raw metrics and histories.
The eight points helpers own the policy; colour and score measures consume them.
This edits the saved TMDL, never a loaded Desktop model.
"""

from pathlib import Path
import re
import uuid


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "Project Review - Programme (datalake).SemanticModel/definition/tables/XER Metrics.tmdl"
POLICY = (
    ("SM Missing Logic Points", "SM Missing Logic %", "LE", "0.05", "0.10", "SM Missing Logic Colour"),
    ("SM Leads Points", "<0Lead%", "LE", "0", "0.01", "SM Leads Colour"),
    ("SM Lags Points", "Lags%", "LE", "0.05", "0.10", "SM Lags Colour"),
    ("SM FS Points", "SM FS %", "GE", "0.90", "0.80", "SM FS Colour"),
    ("SM Constraints Points", "Constraint%", "LE", "0.05", "0.10", "SM Constraints Colour"),
    ("SM Negative Float Points", "<0Float%", "LE", "0", "0.01", "SM Negative Float Colour"),
    ("SM High Duration Points", "HighDur%", "LE", "0.05", "0.10", "SM High Duration Colour"),
    ("SM Invalid Dates Points", "SM Invalid Dates %", "LE", "0", "0.001", "SM Invalid Dates Colour"),
)


def measure_span(source: str, name: str):
    escaped = name.replace("'", "''")
    pattern = rf"(?m)^\tmeasure (?:'{re.escape(escaped)}'|{re.escape(name)}) =[^\n]*\n"
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise ValueError(f"Expected one measure {name!r}, found {len(matches)}")
    match = matches[0]
    metadata = re.search(r"(?m)^\t\t(?=[^\t\n])", source[match.end():])
    if metadata is None:
        raise ValueError(f"Missing metadata for {name}")
    return match, match.end() + metadata.start()


def replace_expression(source: str, name: str, expression: str) -> str:
    match, end = measure_span(source, name)
    header = match.group().split(" =", 1)[0] + " =\n"
    body = "".join("\t\t\t" + line + "\n" for line in expression.strip().splitlines())
    return source[:match.start()] + header + body + source[end:]


def add_measure(source: str, name: str, expression: str, *, hidden=False,
                format_string="#,0", folder="Schedule Quality Score") -> str:
    if re.search(rf"(?m)^\tmeasure '{re.escape(name)}' =", source):
        return replace_expression(source, name, expression)
    lineage = uuid.uuid5(uuid.NAMESPACE_URL, "programme-review/schedule-review-bands/v3/" + name)
    block = "\tmeasure '" + name + "' =\n"
    block += "".join("\t\t\t" + line + "\n" for line in expression.strip().splitlines())
    block += f"\t\tformatString: {format_string}\n"
    if hidden:
        block += "\t\tisHidden\n"
    block += f"\t\tdisplayFolder: {folder}\n\t\tlineageTag: {lineage}\n\n"
    marker = "\tpartition 'XER Metrics' = m"
    if source.count(marker) != 1:
        raise ValueError("Expected the preserved XER Metrics source partition")
    return source.replace(marker, block + marker)


def points_table() -> str:
    return "VAR CheckPoints =\n{\n" + ",\n".join("    [" + row[0] + "]" for row in POLICY) + "\n}"


def main():
    original = TARGET.read_bytes()
    newline = "\r\n" if b"\r\n" in original else "\n"
    source = original.decode("utf-8").replace("\r\n", "\n")
    before_partition = source[source.index("\tpartition 'XER Metrics' = m"):]
    before_lineage = dict(re.findall(r"(?m)^\tmeasure (.+?) =.*?\n(?:(?!^\tmeasure ).)*?^\t\tlineageTag: ([^\n]+)", source, re.DOTALL))

    for name, metric, direction, green, amber, colour in POLICY:
        symbol = ">=" if direction == "GE" else "<="
        grade = (
            f"VAR MetricValue = [{metric}]\n"
            "RETURN IF ( NOT ISBLANK ( MetricValue ),\n"
            f"    SWITCH ( TRUE (), MetricValue {symbol} {green}, 1, MetricValue {symbol} {amber}, 0.5, 0 )\n"
            ")"
        )
        source = add_measure(source, name, grade, hidden=True, format_string="0.0",
                             folder="Schedule Quality Score\\Internal bands")
        source = replace_expression(source, colour,
            f"VAR GradeValue = [{name}]\n"
            'RETURN SWITCH ( TRUE (), ISBLANK ( GradeValue ), "#687078",\n'
            '    GradeValue = 1, "#4b6110", GradeValue = 0.5, "#9C6500", "#6f0516" )')

    source = replace_expression(source, "Score", points_table() + "\n"
        "VAR AssessedPoints = FILTER ( CheckPoints, NOT ISBLANK ( [Value] ) )\n"
        "RETURN IF ( [Task_Count] > 0, AVERAGEX ( AssessedPoints, [Value] ) )")
    source = replace_expression(source, "SM Assessed Checks", points_table() + "\n"
        "RETURN IF ( [Task_Count] > 0, COALESCE ( COUNTROWS ( FILTER ( CheckPoints, NOT ISBLANK ( [Value] ) ) ), 0 ) )")
    for name, grade, existing in (
        ("SM Passed Checks", "1", True),
        ("SM Review Checks", "0.5", False),
        ("SM Priority Checks", "0", False),
    ):
        expression = points_table() + "\n" + (
            "RETURN IF ( [Task_Count] > 0, COALESCE ( COUNTROWS ( FILTER ( CheckPoints,\n"
            f"    NOT ISBLANK ( [Value] ) && [Value] == {grade} ) ), 0 ) )"
        )
        source = replace_expression(source, name, expression) if existing else add_measure(source, name, expression)
    source = replace_expression(source, "SM Applicable Checks", """
// Four work checks, three relationship checks and one date-integrity check. High float is diagnostic only.
VAR HasWork = [Task_Count] > 0
VAR HasLinks = [SM Eligible Relationship Count] > 0
VAR HasEvents = [SM Date Eligible Count] > 0
RETURN IF ( HasWork, 4 + IF ( HasLinks, 3, 0 ) + IF ( HasEvents, 1, 0 ) )
""")
    # Missing float affects only the scored negative-float check. High float
    # remains visible in the raw coverage tooltip without a second score weight.
    match, end = measure_span(source, "SM Partial Checks")
    partial = source[match.end():end]
    partial = partial.replace("IF ( MissingFloat > 0 && MissingFloat < N, 2, 0 )",
                              "IF ( MissingFloat > 0 && MissingFloat < N, 1, 0 )")
    if "IF ( MissingFloat > 0 && MissingFloat < N, 1, 0 )" not in partial:
        raise ValueError("Unexpected partial-float coverage expression")
    source = source[:match.end()] + partial + source[end:]

    source = add_measure(source, "SM Score Coverage", """
VAR ApplicableChecks = [SM Applicable Checks]
VAR AssessedChecks = [SM Assessed Checks]
VAR PartialChecks = [SM Partial Checks]
VAR UnassessedChecks = ApplicableChecks - AssessedChecks
VAR CoverageLabel = FORMAT ( AssessedChecks, "0" ) & "/" & FORMAT ( ApplicableChecks, "0" ) & " assessed"
RETURN SWITCH ( TRUE (),
    NOT [SM Snapshot Valid], "Input coverage unavailable",
    NOT ( [Task_Count] > 0 ), "N/A - no incomplete discrete work",
    CoverageLabel
        & IF ( UnassessedChecks > 0, " | " & FORMAT ( UnassessedChecks, "0" ) & " unassessed", "" )
        & IF ( PartialChecks > 0, " | " & FORMAT ( PartialChecks, "0" ) & " partial inputs", "" )
        & IF ( UnassessedChecks = 0 && PartialChecks = 0, " | complete inputs", "" )
)
""", format_string="@", folder="Schedule Quality Coverage")
    source = replace_expression(source, "SM Score Status", """
VAR AssessedChecks = [SM Assessed Checks]
VAR SeverityLabel = FORMAT ( [SM Passed Checks], "0" ) & " within | "
    & FORMAT ( [SM Review Checks], "0" ) & " review | "
    & FORMAT ( [SM Priority Checks], "0" ) & " priority"
RETURN SWITCH ( TRUE (),
    NOT [SM Snapshot Valid], "Select one project/programme and an available update",
    NOT ( [Task_Count] > 0 ), "N/A - no incomplete discrete work",
    NOT ( AssessedChecks > 0 ), "N/A - no checks assessable" & " | " & [SM Score Coverage],
    SeverityLabel & " | " & [SM Score Coverage]
)
""")
    source = replace_expression(source, "SM High Float Colour", """
IF ( ISBLANK ( [HighFloat%] ), "#687078", "#3979A6" )
""")
    source = replace_expression(source, "SM Score Colour", """
VAR MetricValue = [Score]
RETURN SWITCH ( TRUE (), ISBLANK ( MetricValue ), "#687078",
    [SM Priority Checks] > 0, "#6f0516",
    [SM Review Checks] > 0, "#9C6500", "#4b6110" )
""")

    # Keep all denominator/count coverage evidence; change only its explanation.
    source = source.replace(
        '"Float, duration, relationship and constraint ratios use known inputs only. Amber = partial data; no usable inputs = N/A."',
        '"Known-input ratios: green = within target; amber = review; red = priority. Input coverage is separate; no usable inputs = N/A."')
    source = source.replace('& " | High float: "', '& " | High float (diagnostic): "')
    source = source.replace('" (all statuses; includes milestones)"',
                            '" (all statuses; includes milestones; nonzero defects require correction)"')
    source = source.replace(
        '"Definition v2: score = passed/assessed checks, equal weights; incomplete evidence is provisional. Remaining duration and expanded date checks are custom. Unscheduled work is included; datalake exclusions are retained."',
        '"Internal review bands: logic/lags/constraints/duration <=5% within, >5-10% review, >10% priority; FS >=90% within, 80-<90% review, <80% priority. Leads/negative float: 0 within, >0-1% review, >1% priority. Dates: 0 within, >0-0.1% review, >0.1% priority."\n'
        '\t\t\t    & UNICHAR ( 10 ) & "Definition v3: score averages eight assessed grades (within=1, review=0.5, priority=0). High float >44 working days is diagnostic only. Any priority check makes the score red; otherwise review is amber and all within is green. Coverage is reported separately; missing inputs are not passes. These are provisional internal review bands. Unscheduled work is included; datalake exclusions are retained."')
    source = source.replace(
        '/// Checks passed / assessed checks, equally weighted. Partial inputs and unassessed checks are disclosed; target 100%.',
        '/// Average of eight assessed internal review grades: within=1, review=0.5, priority=0. High float is diagnostic only; coverage is separate.')
    source = source.replace(
        '/// Float >44 working days / work with known float; pass at or below 5%. Missing inputs are disclosed separately.',
        '/// Float >44 working days / work with known float; a context-dependent diagnostic, excluded from the score. Missing inputs are disclosed separately.')
    source = source.replace(
        '/// Zero tolerance; includes complete activities and milestones. Start is the imported status-aware actual/forecast field, not a raw actual-start field.',
        '/// Zero target with frequency-based review bands; every defect still requires correction. Includes complete activities and milestones. Start is the imported status-aware actual/forecast field, not a raw actual-start field.')

    after_lineage = dict(re.findall(r"(?m)^\tmeasure (.+?) =.*?\n(?:(?!^\tmeasure ).)*?^\t\tlineageTag: ([^\n]+)", source, re.DOTALL))
    if any(after_lineage.get(name) != lineage for name, lineage in before_lineage.items()):
        raise ValueError("An existing measure lineage changed")
    if source[source.index("\tpartition 'XER Metrics' = m"):] != before_partition:
        raise ValueError("The source partition changed")
    if "Definition v2: score = passed/assessed checks" in source:
        raise ValueError("Old score explanation remains")
    output = source.replace("\n", newline).encode("utf-8")
    TARGET.write_bytes(output)
    print(f"Updated {TARGET.name}; {len(POLICY)} centrally graded checks; existing lineage and source partition preserved.")


if __name__ == "__main__":
    main()
