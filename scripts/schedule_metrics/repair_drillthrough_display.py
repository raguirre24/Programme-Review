"""Apply the approved drill-through display changes without changing metric logic.

Run only against a backed-up PBIP. Filter migration is separate; this script
preserves page/visual identities and the existing matrix hierarchy and dates.
"""
from pathlib import Path
import json
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'Project Review - Programme (datalake).Report/definition'
MODEL = ROOT / 'Project Review - Programme (datalake).SemanticModel/definition'
PAGES = [
    ('061f748900951ae92ba9', 'Missing Predecessor', 'Missing Predecessor',
     '5a1178e4780765a33ec9', 'cba2d7d0374d5dc2d034', '03aac36f32b9682c3cb1',
     '3b930ef59a608cb45f7e', '65c7d9ead2c400a75805', 'SM Drill Missing Predecessor Flag', 'Missing predecessor'),
    ('4f15f55676d2add4e922', 'Missing Successor', 'Missing Successor',
     '2103bb020910855d213e', 'c5503be9b5b38bcb7462', '1d322dafe5ee305c6bae',
     '0b82d52226aa6abd982b', 'b5e8551c96293cac30d1', 'SM Drill Missing Successor Flag', 'Missing successor'),
]
CONTEXT_TITLES = {
    '061f748900951ae92ba9': 'b03fcd1765485aa317d7',
    '4f15f55676d2add4e922': 'f9902bd421e608265960',
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def literal(value):
    return {'expr': {'Literal': {'Value': value}}}


def measure(name):
    return {'Measure': {'Expression': {'SourceRef': {'Entity': 'XER Metrics'}}, 'Property': name}}


def text_properties(visual):
    return next(x['properties'] for x in visual['visual']['objects']['text'] if 'text' in x['properties'])


def main():
    # Clear only detail-population predicates for context labels, retaining the
    # clicked snapshot, project, WBS, governance filters and access restrictions.
    clear = """REMOVEFILTERS ( '01 XER_TASK'[No Predecessor], '01 XER_TASK'[No Successor],
        '01 XER_TASK'[Driven_DataDate], '01 XER_TASK'[status_code],
        '01 XER_TASK'[StatusCategory], '01 XER_TASK'[task_type],
        '01 XER_TASK'[TaskType_Classified], '01 XER_TASK'[Is Unscheduled] ),
    REMOVEFILTERS ( Filter_Activity_Status ), REMOVEFILTERS ( Filter_TaskType ),
    REMOVEFILTERS ( '00 CALENDAR' ), REMOVEFILTERS ( '00 PLANNED DATE TABLE (PV)' )"""
    helpers = {
        'SM Drill Snapshot Available': (
            'True only for one available project snapshot, including a valid snapshot with zero diagnostic matches.',
            f'''CALCULATE (
    [SM Snapshot Valid],
    {clear}
)'''),
        'SM Drill Context': (
            'Project and clicked update for drill-through labels, including a zero-match result.',
            f'''CALCULATE (
    VAR ProjectLabel = COALESCE ( SELECTEDVALUE ( '01 XER_TASK'[ProjectName] ),
        SELECTEDVALUE ( Project_Dimension[Project] ), "Multiple projects" )
    VAR Snapshot = COALESCE ( SELECTEDVALUE ( '01 XER_TASK'[UpdateDate] ),
        SELECTEDVALUE ( CurrentDate[UpdateDate] ) )
    RETURN ProjectLabel & " | " & IF ( ISBLANK ( Snapshot ), "Select one update", FORMAT ( Snapshot, "MMMM yyyy" ) ),
    {clear}
)'''),
        'SM Drill Data Date': (
            'Actual source data date for the clicked snapshot, rather than the export/update timestamp.',
            f'''VAR SourceDate = CALCULATE ( SELECTEDVALUE ( '01 XER_TASK'[data_date] ), {clear} )
RETURN "Data date: " & IF ( ISBLANK ( SourceDate ), "Unavailable or multiple", FORMAT ( SourceDate, "dd MMM yyyy" ) )'''),
        'SM Drill Source File': (
            'Selected source filename retained when the diagnostic has no matching activities.',
            f'''CALCULATE ( SELECTEDVALUE ( '01 XER_TASK'[FileName], "Multiple or unavailable source files" ), {clear} )'''),
    }
    for _, label, source, *_ in PAGES:
        helpers[f'SM Drill {label} Header'] = (
            'Diagnostic activity count and snapshot context; WBS grouping rows are not counted.',
            f'''VAR Matches = COALESCE ( [{source}], 0 )
RETURN IF ( NOT [SM Drill Snapshot Available], "Select one project and available update", 
    "{label}: " & FORMAT ( Matches, "#,0" ) &
    IF ( Matches = 1, " matching activity", " matching activities" ) & " | " & [SM Drill Context] )''')
    for name, col, numeric in [
        ('SM Drill Status', 'status_code', False),
        ('SM Drill Missing Predecessor Flag', 'No Predecessor', True),
        ('SM Drill Missing Successor Flag', 'No Successor', True),
    ]:
        helpers[name] = ('Source diagnostic evidence at the activity row; blank at WBS summary levels.',
                         f"IF ( ISINSCOPE ( '01 XER_TASK'[task_code] ), SELECTEDVALUE ( '01 XER_TASK'[{col}] ) )")
    path = MODEL / 'tables/XER Metrics.tmdl'
    text = path.read_text(encoding='utf-8-sig')
    # Idempotently replace only this script's display helpers.
    for name, (description, expression) in helpers.items():
        pattern = r'\n\t///[^\n]*\n\tmeasure \'' + re.escape(name) + r"' =.*?(?=\n\t///|\n\tmeasure |\n\tcolumn |\n\tpartition |\Z)"
        text = re.sub(pattern, '', text, flags=re.S)
        assert f"\tmeasure '{name}' =" not in text, f'Unexpected existing helper definition: {name}'
        fmt = '0' if name.endswith(' Flag') else '@'
        block = f"\t/// {description}\n\tmeasure '{name}' =\n" + ''.join('\t\t\t' + line + '\n' for line in expression.splitlines())
        block += f'\t\tformatString: {fmt}\n\t\tdisplayFolder: Schedule Quality Drill-through\n'
        block += f'\t\tlineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, "programme-review/" + name)}\n\n'
        insertion = text.index('\n\tcolumn ') if '\n\tcolumn ' in text else text.index('\n\tpartition ')
        text = text[:insertion] + '\n' + block.rstrip('\n') + '\n' + text[insertion:]
    path.write_text(text, encoding='utf-8')

    for page, label, _, matrix, heading, title, date_title, file_title, evidence, evidence_label in PAGES:
        folder = REPORT / 'pages' / page / 'visuals'
        p = folder / heading / 'visual.json'; v = load(p)
        # Use the existing spare strip alongside Back so a long project name
        # does not collide with the source/date labels in the red masthead.
        v['position'].update(x=115, y=84, width=1785, height=46)
        props = text_properties(v)
        props['text'] = {'expr': measure(f'SM Drill {label} Header')}
        props['fontSize'] = literal('17D')
        props['fontColor'] = {'solid': {'color': literal("'#252525'")}}
        save(p, v)
        p = folder / title / 'visual.json'; v = load(p)
        text_properties(v)['text'] = literal("'" + label + "'")
        save(p, v)
        for visual_id, helper in [(date_title, 'SM Drill Data Date'), (file_title, 'SM Drill Source File'),
                                  (CONTEXT_TITLES[page], 'SM Drill Context')]:
            p = folder / visual_id / 'visual.json'; v = load(p)
            text_properties(v)['text'] = {'expr': measure(helper)}
            save(p, v)
        p = folder / matrix / 'visual.json'; v = load(p)
        projections = v['visual']['query']['queryState']['Values']['projections']
        projections[:] = [x for x in projections if not x.get('queryRef', '').startswith('XER Metrics.SM Drill ')]
        diagnostics = [('SM Drill Status', 'Status', 100), (evidence, evidence_label, 90)]
        for offset, (helper, caption, width) in enumerate(diagnostics):
            projections.insert(1 + offset, {'field': measure(helper), 'queryRef': 'XER Metrics.' + helper,
                                          'nativeQueryRef': caption, 'displayName': caption})
            values = v['visual']['objects'].setdefault('values', [])
            values[:] = [x for x in values if x.get('selector', {}).get('metadata') != 'XER Metrics.' + helper]
            values.append({'properties': {'width': literal(f'{width}D'), 'customWidth': literal('true')},
                           'selector': {'metadata': 'XER Metrics.' + helper}})
        save(p, v)

    p = REPORT / 'pages/327b48a7fbd37ce0a51c/visuals/a1970523de7632121d6b/visual.json'
    v = load(p)
    # The same helper strip already sits above the table; use its available width.
    v['position']['width'] = 810
    props = text_properties(v)
    props['text'] = literal("'Bands: see titles | Hover: coverage | Right-click an update → Drill through → choose a detail view.'")
    props['fontSize'] = literal('10D')
    props['fontFamily'] = literal("'Segoe UI'")
    save(p, v)
    print(f'Updated {len(helpers)} display helpers and existing drill-through visuals.')


if __name__ == '__main__':
    main()
