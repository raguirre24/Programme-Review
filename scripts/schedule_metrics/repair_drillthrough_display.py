"""Deterministically build the 10 scored Schedule Metrics drill-through routes.

Idempotently updates:
1. 01 XER_TASK.tmdl (7 hidden storage-engine SM Fail * calculated columns)
2. XER Metrics.tmdl (4 activity-grain failing-count measures + 25 SM Drill * helpers;
   retires the 4 legacy SM Drill Missing Predecessor/Successor * helpers)
3. cultures/en-NZ.tmdl (removes stale Q&A bindings for the 4 retired helpers)
4. Sched. Metrics update table (58fbc09d197fe53515d8) & helper caption (a1970523de7632121d6b)
5. 10 hidden drill-through pages (HiddenInViewMode), pages.json, and bookmarks.json
   (retiring legacy pages 061f748900951ae92ba9 & 4f15f55676d2add4e922 and their
   4 orphaned project-menu bookmarks).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'Project Review - Programme (datalake).Report/definition'
MODEL = ROOT / 'Project Review - Programme (datalake).SemanticModel/definition'

LEGACY_PAGES = ('061f748900951ae92ba9', '4f15f55676d2add4e922')
LEGACY_BOOKMARKS = (
    '35c2baadfa05e673110e',
    'd85911f94d2be6576068',
    'aae4df89fc5cb53b08d6',
    'b78ddd824cdcaae69b89',
)
RETIRED_MEASURES = (
    'SM Drill Missing Predecessor Header',
    'SM Drill Missing Predecessor Flag',
    'SM Drill Missing Successor Header',
    'SM Drill Missing Successor Flag',
)
RETIRED_CULTURE_KEYS = (
    'XER_metrics.SM_drill_missing_successor_flag',
    'XER_metrics.SM_drill_missing_predecessor_flag',
    'XER_metrics.SM_drill_missing_predecessor_header',
    'XER_metrics.SM_drill_missing_successor_header',
)

TEMPLATE_ROLES = {
    'page_title': '03aac36f32b9682c3cb1',
    'date_title': '3b930ef59a608cb45f7e',
    'logo': '5072e51a588f886a049c',
    'state_slicer': '5128d0c07d8381cb3013',
    'project_slicer': '58467cd9e6f73b94e426',
    'matrix': '5a1178e4780765a33ec9',
    'file_title': '65c7d9ead2c400a75805',
    'back_button': '67809e8bad1ce4bdc878',
    'context_title': 'b03fcd1765485aa317d7',
    'heading': 'cba2d7d0374d5dc2d034',
}

RESTRICTIVE_CODES = (
    'CS_MSO',
    'CS_MSOB',
    'CS_MEO',
    'CS_MEOB',
    'CS_MANDSTART',
    'CS_MANDFIN',
)

ROUTES = [
    {
        'key': 'missing_logic',
        'page_name': 'Missing Logic',
        'table_header': 'Missing logic',
        'table_width': 78,
        'count_measure': 'SM Missing Logic Count',
        'link_expr': None,
        'header_measure': 'SM Drill Missing Logic Header',
        'detail_measure': 'SM Drill Missing Logic Detail',
        'detail_caption': 'Missing logic',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('nonblank_str', 'SM Fail Missing Logic', None),
        ],
    },
    {
        'key': 'leads',
        'page_name': 'Leads',
        'table_header': 'Leads <0d',
        'table_width': 72,
        'count_measure': 'SM Leads Activity Count',
        'link_expr': '[Leads<0d]',
        'header_measure': 'SM Drill Leads Header',
        'detail_measure': 'SM Drill Leads Detail',
        'detail_caption': 'Lead predecessors',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('gt_int', 'SM Fail Leads', 0),
        ],
    },
    {
        'key': 'lags',
        'page_name': 'Lags >5d',
        'table_header': 'Lags >5d',
        'table_width': 72,
        'count_measure': 'SM Lags Activity Count',
        'link_expr': '[Lags>5d]',
        'header_measure': 'SM Drill Lags Header',
        'detail_measure': 'SM Drill Lags Detail',
        'detail_caption': 'Lag >5d predecessors',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('gt_int', 'SM Fail Lags', 0),
        ],
    },
    {
        'key': 'non_fs',
        'page_name': 'Non-FS Relationships',
        'table_header': 'Non-FS',
        'table_width': 70,
        'count_measure': 'SM Non-FS Activity Count',
        'link_expr': '[SM Eligible Relationship Count] - [SM Unknown Relationship Type Count] - [SM FS Count]',
        'header_measure': 'SM Drill Non-FS Header',
        'detail_measure': 'SM Drill Non-FS Detail',
        'detail_caption': 'Non-FS predecessors',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('gt_int', 'SM Fail Non FS', 0),
        ],
    },
    {
        'key': 'restrictive_constraints',
        'page_name': 'Hard Constraints',
        'table_header': 'Hard constraints',
        'table_width': 82,
        'count_measure': 'SM Restrictive Primary Count',
        'link_expr': None,
        'header_measure': 'SM Drill Restrictive Constraints Header',
        'detail_measure': 'SM Drill Restrictive Constraints Detail',
        'detail_caption': 'Primary constraint',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('in', 'cstr_type', RESTRICTIVE_CODES),
        ],
    },
    {
        'key': 'out_of_sequence',
        'page_name': 'Out-of-Sequence',
        'table_header': 'Out of seq.',
        'table_width': 78,
        'count_measure': 'Out Of Sequence Count',
        'link_expr': None,
        'header_measure': 'SM Drill Out-of-Sequence Header',
        'detail_measure': 'SM Drill Out-of-Sequence Detail',
        'detail_caption': 'Driving predecessors',
        'filters': [
            ('in', 'status_code', ('In Progress',)),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('gt_int', 'SM Fail Out Of Sequence', 0),
        ],
    },
    {
        'key': 'negative_float',
        'page_name': 'Negative Float',
        'table_header': 'Float <0',
        'table_width': 70,
        'count_measure': 'Task_Count_Negative_Float',
        'link_expr': None,
        'header_measure': 'SM Drill Negative Float Header',
        'detail_measure': 'SM Drill Negative Float Detail',
        'detail_caption': 'Negative float',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('lt_num', 'total_float', 0),
        ],
    },
    {
        'key': 'remaining_duration',
        'page_name': 'Remaining Duration >44d',
        'table_header': 'Dur. >44d',
        'table_width': 74,
        'count_measure': 'Dur >44',
        'link_expr': None,
        'header_measure': 'SM Drill Remaining Duration Header',
        'detail_measure': 'SM Drill Remaining Duration Detail',
        'detail_caption': 'Remaining duration',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('gt_num', 'remaining_duration', 44),
        ],
    },
    {
        'key': 'date_integrity',
        'page_name': 'Date Integrity',
        'table_header': 'Invalid dates',
        'table_width': 84,
        'count_measure': 'SM Invalid Dates Count',
        'link_expr': None,
        'header_measure': 'SM Drill Date Integrity Header',
        'detail_measure': 'SM Drill Date Integrity Detail',
        'detail_caption': 'Date issue',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('nonblank_str', 'SM Fail Invalid Dates', None),
        ],
    },
    {
        'key': 'baseline_coverage',
        'page_name': 'Baseline Coverage',
        'table_header': 'No baseline',
        'table_width': 82,
        'count_measure': 'SM Baseline Unmatched Activity Count',
        'link_expr': None,
        'header_measure': 'SM Drill Baseline Coverage Header',
        'detail_measure': 'SM Drill Baseline Coverage Detail',
        'detail_caption': 'Baseline issue',
        'filters': [
            ('in', 'status_code', ('Not Started', 'In Progress')),
            ('in', 'task_type', ('TT_Task', 'TT_Rsrc', 'TT_Mile', 'TT_FinMile')),
            ('nonblank_str', 'SM Fail Baseline Coverage', None),
        ],
    },
]


def hid(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, 'programme-review/sm-drill/' + seed).hex[:20]


def lineage(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'programme-review/' + name))


def page_id(route_key: str) -> str:
    return hid(f'page/{route_key}')


def visual_id(route_key: str, role: str) -> str:
    return hid(f'visual/{route_key}/{role}')


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_tmdl(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in raw else '\n'
    return raw.replace('\r\n', '\n'), newline


def write_tmdl(path: Path, text: str, newline: str) -> None:
    normalised = text.replace('\r\n', '\n')
    if newline == '\r\n':
        normalised = normalised.replace('\n', '\r\n')
    path.write_bytes(normalised.encode('utf-8'))


def literal(value: str) -> dict:
    return {'expr': {'Literal': {'Value': value}}}


def measure_ref(name: str, entity: str = 'XER Metrics') -> dict:
    return {'Measure': {'Expression': {'SourceRef': {'Entity': entity}}, 'Property': name}}


def column_ref(prop: str, entity: str = '01 XER_TASK', source: str | None = None) -> dict:
    ref = {'Source': source} if source is not None else {'Entity': entity}
    return {'Column': {'Expression': {'SourceRef': ref}, 'Property': prop}}


def text_properties(visual: dict) -> dict:
    return next(x['properties'] for x in visual['visual']['objects']['text'] if 'text' in x['properties'])


def build_task_columns() -> list[tuple[str, str, str | None, str]]:
    """Return (name, description, format_string, dax_expression) for 01 XER_TASK."""
    return [
        (
            'SM Fail Missing Logic',
            'Hidden storage-engine failure reason for the scored Missing logic check on incomplete discrete activities.',
            None,
            """IF (
    '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    SWITCH (
        TRUE (),
        '01 XER_TASK'[No Predecessor] = 1 && '01 XER_TASK'[No Successor] = 1, "No pred. & no succ.",
        '01 XER_TASK'[No Predecessor] = 1, "No predecessor",
        '01 XER_TASK'[No Successor] = 1, "No successor",
        BLANK ()
    )
)""",
        ),
        (
            'SM Fail Leads',
            'Hidden storage-engine count of incoming negative-lag relationships on an incomplete discrete activity.',
            '#,0',
            """IF (
    '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    COALESCE (
        COUNTROWS (
            FILTER (
                RELATEDTABLE ( '06 XER_PREDECESSOR' ),
                NOT ISBLANK ( '06 XER_PREDECESSOR'[lag] ) && '06 XER_PREDECESSOR'[lag] < 0
            )
        ),
        0
    ),
    0
)""",
        ),
        (
            'SM Fail Lags',
            'Hidden storage-engine count of incoming relationships with lag > 5 working days on an incomplete discrete activity.',
            '#,0',
            """IF (
    '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    COALESCE (
        COUNTROWS (
            FILTER (
                RELATEDTABLE ( '06 XER_PREDECESSOR' ),
                NOT ISBLANK ( '06 XER_PREDECESSOR'[lag] ) && '06 XER_PREDECESSOR'[lag] > 5
            )
        ),
        0
    ),
    0
)""",
        ),
        (
            'SM Fail Non FS',
            'Hidden storage-engine count of incoming non-FS recognised relationships (SS/FF/SF) on an incomplete discrete activity.',
            '#,0',
            """IF (
    '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    COALESCE (
        COUNTROWS (
            FILTER (
                RELATEDTABLE ( '06 XER_PREDECESSOR' ),
                '06 XER_PREDECESSOR'[pred_type] IN { "PR_SS", "PR_FF", "PR_SF" }
            )
        ),
        0
    ),
    0
)""",
        ),
        (
            'SM Fail Out Of Sequence',
            'Hidden storage-engine count of unfinished driving incoming predecessors on an in-progress discrete activity.',
            '#,0',
            """IF (
    '01 XER_TASK'[status_code] = "In Progress"
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    COALESCE (
        COUNTROWS (
            FILTER (
                RELATEDTABLE ( '06 XER_PREDECESSOR' ),
                '06 XER_PREDECESSOR'[predecessor_task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }
                    && (
                        ( '06 XER_PREDECESSOR'[pred_type] IN { "PR_FS", "PR_FS1" } && '06 XER_PREDECESSOR'[predecessor_status_code] IN { "TK_NotStart", "TK_Active" } )
                            || ( '06 XER_PREDECESSOR'[pred_type] = "PR_SS" && '06 XER_PREDECESSOR'[predecessor_status_code] = "TK_NotStart" )
                    )
            )
        ),
        0
    ),
    0
)""",
        ),
        (
            'SM Fail Invalid Dates',
            'Hidden storage-engine failure reason for the scored Date integrity check across incomplete activities and milestones (excluding LOE and WBS Summary).',
            None,
            """IF (
    '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    VAR S = '01 XER_TASK'[status_code]
    VAR T = '01 XER_TASK'[task_type]
    VAR DD = '01 XER_TASK'[data_date]
    VAR StartDate = '01 XER_TASK'[Start]
    VAR FinishDate = '01 XER_TASK'[Finish]
    VAR ActualFinish = '01 XER_TASK'[act_end_date]
    VAR NeedsStart = T <> "TT_FinMile"
    VAR NeedsFinish = T <> "TT_Mile"
    VAR IsOpen = S IN { "Not Started", "In Progress" }
    RETURN SWITCH (
        TRUE (),
        ISBLANK ( DD ), "Missing data date",
        NOT ( S IN { "Not Started", "In Progress", "Complete" } ), "Unrecognised status",
        NeedsStart && ISBLANK ( StartDate ) && S IN { "In Progress", "Complete" }, "Missing actual start date",
        NeedsStart && ISBLANK ( StartDate ), "Missing start date",
        NeedsFinish && ISBLANK ( FinishDate ), "Missing finish date",
        NeedsStart && S = "Not Started" && StartDate < DD, "Not Started before data date",
        NeedsStart && S IN { "In Progress", "Complete" } && StartDate > DD, "Actual start after data date",
        NeedsFinish && IsOpen && FinishDate < DD, "Remaining finish before data date",
        NeedsFinish && S = "Complete" && ISBLANK ( ActualFinish ), "Completed without actual finish",
        NOT ISBLANK ( ActualFinish ) && ActualFinish > DD, "Actual finish after data date",
        IsOpen && NOT ISBLANK ( ActualFinish ), "Open activity with actual finish",
        NeedsStart && NeedsFinish && FinishDate < StartDate, "Finish before start",
        BLANK ()
    )
)""",
        ),
        (
            'SM Fail Baseline Coverage',
            'Hidden storage-engine failure reason for the scored Baseline coverage check on incomplete activities and milestones against the latest -BL update or earliest loaded update fallback.',
            None,
            """IF (
    NOT '01 XER_TASK'[IsExcludedFromDataLake]
        && '01 XER_TASK'[status_code] IN { "Not Started", "In Progress" }
        && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" },
    VAR P = '01 XER_TASK'[ProjectCode]
    VAR PT = '01 XER_TASK'[ProgrammeType]
    VAR U = '01 XER_TASK'[UpdateDate]
    VAR Code = '01 XER_TASK'[task_code]
    RETURN IF (
        ISBLANK ( P ) || ISBLANK ( PT ) || ISBLANK ( U ),
        "Invalid baseline snapshot",
        VAR SnapMeta =
            FILTER (
                ALL (
                    '01 XER_TASK'[ProjectCode],
                    '01 XER_TASK'[ProgrammeType],
                    '01 XER_TASK'[UpdateDate],
                    '01 XER_TASK'[filename],
                    '01 XER_TASK'[data_date],
                    '01 XER_TASK'[IsExcludedFromDataLake]
                ),
                NOT '01 XER_TASK'[IsExcludedFromDataLake]
                    && '01 XER_TASK'[ProjectCode] = P
                    && '01 XER_TASK'[ProgrammeType] = PT
                    && '01 XER_TASK'[UpdateDate] <= U
            )
        VAR CurrentMeta = FILTER ( SnapMeta, '01 XER_TASK'[UpdateDate] = U )
        VAR CurrentValid =
            COUNTROWS ( CurrentMeta ) = 1
                && COUNTROWS ( FILTER ( CurrentMeta, ISBLANK ( '01 XER_TASK'[data_date] ) ) ) = 0
        VAR BlDate =
            MAXX (
                FILTER ( SnapMeta, CONTAINSSTRING ( '01 XER_TASK'[filename], "-BL" ) ),
                '01 XER_TASK'[UpdateDate]
            )
        VAR EarliestDate = MINX ( SnapMeta, '01 XER_TASK'[UpdateDate] )
        VAR TargetBL = COALESCE ( BlDate, EarliestDate )
        VAR BlMeta = FILTER ( SnapMeta, '01 XER_TASK'[UpdateDate] = TargetBL )
        VAR BaselineFile = IF ( COUNTROWS ( BlMeta ) = 1, MAXX ( BlMeta, '01 XER_TASK'[filename] ) )
        VAR FileNameUpper = UPPER ( BaselineFile )
        VAR TagStart = SEARCH ( "-BL", FileNameUpper, 1, 0 )
        VAR TagEnd = IF ( TagStart > 0, SEARCH ( "_", FileNameUpper, TagStart + 3, 0 ), 0 )
        VAR Tag = IF ( TagEnd > TagStart + 3, MID ( FileNameUpper, TagStart + 3, TagEnd - TagStart - 3 ), "" )
        VAR RevisionAt = SEARCH ( "-", Tag, 1, 0 )
        VAR NumberText = IF ( RevisionAt > 0, LEFT ( Tag, RevisionAt - 1 ), Tag )
        VAR Revision = IF ( RevisionAt > 0, MID ( Tag, RevisionAt + 1, LEN ( Tag ) ), "" )
        VAR DigitsOnly =
            LEN ( NumberText ) > 0
                && LEN (
                    SUBSTITUTE (
                        SUBSTITUTE (
                            SUBSTITUTE (
                                SUBSTITUTE (
                                    SUBSTITUTE (
                                        SUBSTITUTE (
                                            SUBSTITUTE (
                                                SUBSTITUTE (
                                                    SUBSTITUTE (
                                                        SUBSTITUTE ( NumberText, "0", "" ),
                                                        "1", ""
                                                    ),
                                                    "2", ""
                                                ),
                                                "3", ""
                                            ),
                                            "4", ""
                                        ),
                                        "5", ""
                                    ),
                                    "6", ""
                                ),
                                "7", ""
                            ),
                            "8", ""
                        ),
                        "9", ""
                    )
                ) = 0
        VAR ValidBlTag =
            TagEnd > 0
                && DigitsOnly
                && ( RevisionAt = 0 || ( LEN ( Revision ) = 1 && Revision >= "A" && Revision <= "Z" ) )
        VAR HasProvenance =
            NOT ISBLANK ( TargetBL )
                && NOT ISBLANK ( BaselineFile )
                && LEN ( TRIM ( BaselineFile ) ) > 0
                && ( TagStart = 0 || ValidBlTag )
        RETURN IF (
            NOT CurrentValid || NOT HasProvenance,
            "Invalid baseline snapshot",
            IF (
                TargetBL = U && NOT ISBLANK ( '01 XER_TASK'[Finish] ),
                BLANK (),
                VAR TC = '01 XER_TASK'[TaskType_Classified]
                VAR FastLookup =
                    IFERROR (
                        LOOKUPVALUE (
                            '01 XER_TASK'[Finish],
                            '01 XER_TASK'[ProjectCode], P,
                            '01 XER_TASK'[ProgrammeType], PT,
                            '01 XER_TASK'[UpdateDate], TargetBL,
                            '01 XER_TASK'[IsExcludedFromDataLake], FALSE (),
                            '01 XER_TASK'[TaskType_Classified], TC,
                            '01 XER_TASK'[task_code], Code,
                            DATE ( 1899, 12, 30 )
                        ),
                        DATE ( 1899, 12, 31 )
                    )
                RETURN SWITCH (
                    TRUE (),
                    ISBLANK ( FastLookup ), "Baseline finish missing",
                    FastLookup <> DATE ( 1899, 12, 30 ) && FastLookup <> DATE ( 1899, 12, 31 ), BLANK (),
                    VAR DupRows =
                        FILTER (
                            ALL (
                                '01 XER_TASK'[ProjectCode],
                                '01 XER_TASK'[ProgrammeType],
                                '01 XER_TASK'[UpdateDate],
                                '01 XER_TASK'[IsExcludedFromDataLake],
                                '01 XER_TASK'[task_type],
                                '01 XER_TASK'[task_code],
                                '01 XER_TASK'[Finish]
                            ),
                            NOT '01 XER_TASK'[IsExcludedFromDataLake]
                                && '01 XER_TASK'[ProjectCode] = P
                                && '01 XER_TASK'[ProgrammeType] = PT
                                && '01 XER_TASK'[UpdateDate] = TargetBL
                                && '01 XER_TASK'[task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }
                                && '01 XER_TASK'[task_code] == Code
                        )
                    RETURN IF (
                        COUNTROWS ( DupRows ) = 0,
                        "Added after baseline",
                        IF ( ISBLANK ( MAXX ( DupRows, '01 XER_TASK'[Finish] ) ), "Baseline finish missing", BLANK () )
                    )
                )
            )
        )
    )
)""",
        ),
    ]


def update_task_tmdl() -> int:
    path = MODEL / 'tables/01 XER_TASK.tmdl'
    text, newline = read_tmdl(path)
    columns = build_task_columns()
    for name, _, _, _ in columns:
        pattern = (
            r"(?:\n\t///[^\n]*)*\n\tcolumn '"
            + re.escape(name)
            + r"' =.*?(?=\n\t///|\n\tcolumn |\n\tpartition |\Z)"
        )
        text = re.sub(pattern, '', text, flags=re.S)
        assert f"\tcolumn '{name}'" not in text, f'Residual column block for {name}'

    blocks = []
    for name, description, fmt, expression in columns:
        lines = [f'\t/// {description}', f"\tcolumn '{name}' ="]
        lines += ['\t\t\t' + line for line in expression.splitlines()]
        lines.append('\t\tisHidden')
        if fmt:
            lines.append(f'\t\tformatString: {fmt}')
        lines += [
            '\t\tdisplayFolder: Schedule Quality',
            f'\t\tlineageTag: {lineage("01 XER_TASK/" + name)}',
            '\t\tsummarizeBy: none',
            '',
            '\t\tannotation SummarizationSetBy = Automatic',
        ]
        blocks.append('\n'.join(lines))

    insertion = text.index("\n\tpartition '01 XER_TASK'")
    text = text[:insertion].rstrip('\n') + '\n\n' + '\n\n'.join(blocks) + '\n' + text[insertion:]
    write_tmdl(path, text, newline)
    return len(columns)


def build_measures() -> list[tuple[str, str, str, str, str]]:
    """Return (name, description, format_string, folder, dax_expression) for XER Metrics."""
    clear = """REMOVEFILTERS (
        '01 XER_TASK'[No Predecessor],
        '01 XER_TASK'[No Successor],
        '01 XER_TASK'[Driven_DataDate],
        '01 XER_TASK'[SM Fail Missing Logic],
        '01 XER_TASK'[SM Fail Leads],
        '01 XER_TASK'[SM Fail Lags],
        '01 XER_TASK'[SM Fail Non FS],
        '01 XER_TASK'[SM Fail Out Of Sequence],
        '01 XER_TASK'[SM Fail Invalid Dates],
        '01 XER_TASK'[SM Fail Baseline Coverage],
        '01 XER_TASK'[cstr_type],
        '01 XER_TASK'[total_float],
        '01 XER_TASK'[remaining_duration],
        '01 XER_TASK'[status_code],
        '01 XER_TASK'[StatusCategory],
        '01 XER_TASK'[task_type],
        '01 XER_TASK'[TaskType_Classified],
        '01 XER_TASK'[Is Unscheduled]
    ),
    REMOVEFILTERS ( Filter_Activity_Status ),
    REMOVEFILTERS ( Filter_TaskType ),
    REMOVEFILTERS ( '00 CALENDAR' ),
    REMOVEFILTERS ( '00 PLANNED DATE TABLE (PV)' )"""

    scope_reset = """REMOVEFILTERS (
        '01 XER_TASK'[status_code],
        '01 XER_TASK'[StatusCategory],
        '01 XER_TASK'[task_type],
        '01 XER_TASK'[TaskType_Classified],
        '01 XER_TASK'[Is Unscheduled]
    ),
    REMOVEFILTERS ( Filter_Activity_Status ),
    REMOVEFILTERS ( Filter_TaskType ),
    REMOVEFILTERS ( '00 CALENDAR' ),
    REMOVEFILTERS ( '00 PLANNED DATE TABLE (PV)' )"""

    measures: list[tuple[str, str, str, str, str]] = [
        (
            'SM Leads Activity Count',
            'Incomplete discrete activities with at least one incoming negative-lag relationship (activity-grain companion to Leads<0d).',
            '#,0',
            'Schedule Quality Table',
            f"""VAR N = [Task_Count]
VAR Result = CALCULATE (
    COUNTROWS ( '01 XER_TASK' ),
    {scope_reset},
    '01 XER_TASK'[status_code] IN {{ "Not Started", "In Progress" }},
    '01 XER_TASK'[task_type] IN {{ "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }},
    KEEPFILTERS ( '01 XER_TASK'[SM Fail Leads] > 0 )
)
RETURN IF ( N > 0, COALESCE ( Result, 0 ) )""",
        ),
        (
            'SM Lags Activity Count',
            'Incomplete discrete activities with at least one incoming relationship whose lag exceeds 5 working days (activity-grain companion to Lags>5d).',
            '#,0',
            'Schedule Quality Table',
            f"""VAR N = [Task_Count]
VAR Result = CALCULATE (
    COUNTROWS ( '01 XER_TASK' ),
    {scope_reset},
    '01 XER_TASK'[status_code] IN {{ "Not Started", "In Progress" }},
    '01 XER_TASK'[task_type] IN {{ "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }},
    KEEPFILTERS ( '01 XER_TASK'[SM Fail Lags] > 0 )
)
RETURN IF ( N > 0, COALESCE ( Result, 0 ) )""",
        ),
        (
            'SM Non-FS Activity Count',
            'Incomplete discrete activities with at least one incoming non-FS recognised relationship (SS, FF, or SF).',
            '#,0',
            'Schedule Quality Table',
            f"""VAR N = [Task_Count]
VAR Result = CALCULATE (
    COUNTROWS ( '01 XER_TASK' ),
    {scope_reset},
    '01 XER_TASK'[status_code] IN {{ "Not Started", "In Progress" }},
    '01 XER_TASK'[task_type] IN {{ "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }},
    KEEPFILTERS ( '01 XER_TASK'[SM Fail Non FS] > 0 )
)
RETURN IF ( N > 0, COALESCE ( Result, 0 ) )""",
        ),
        (
            'SM Baseline Unmatched Activity Count',
            'Incomplete activities and milestones (excluding LOE and WBS Summary) lacking a dated finish in the project baseline snapshot (or when baseline provenance is invalid).',
            '#,0',
            'Schedule Quality Table',
            f"""VAR N = [Task_Count]
VAR Result = CALCULATE (
    COUNTROWS ( '01 XER_TASK' ),
    {scope_reset},
    '01 XER_TASK'[status_code] IN {{ "Not Started", "In Progress" }},
    '01 XER_TASK'[task_type] IN {{ "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }},
    KEEPFILTERS ( NOT ISBLANK ( '01 XER_TASK'[SM Fail Baseline Coverage] ) )
)
RETURN IF ( N > 0, COALESCE ( Result, 0 ) )""",
        ),
        (
            'SM Drill Snapshot Available',
            'True only for one available project snapshot, including a valid snapshot with zero diagnostic matches.',
            '@',
            'Schedule Quality Drill-through',
            f"""CALCULATE (
    [SM Snapshot Valid],
    {clear}
)""",
        ),
        (
            'SM Drill Context',
            'Project and clicked update for drill-through labels, including a zero-match result.',
            '@',
            'Schedule Quality Drill-through',
            f"""CALCULATE (
    VAR ProjectLabel = COALESCE (
        SELECTEDVALUE ( '01 XER_TASK'[ProjectName] ),
        SELECTEDVALUE ( Project_Dimension[Project] ),
        "Multiple projects"
    )
    VAR Snapshot = COALESCE (
        SELECTEDVALUE ( '01 XER_TASK'[UpdateDate] ),
        SELECTEDVALUE ( CurrentDate[UpdateDate] )
    )
    RETURN ProjectLabel & " | " & IF ( ISBLANK ( Snapshot ), "Select one update", FORMAT ( Snapshot, "MMMM yyyy" ) ),
    {clear}
)""",
        ),
        (
            'SM Drill Data Date',
            'Actual source data date for the clicked snapshot, rather than the export/update timestamp.',
            '@',
            'Schedule Quality Drill-through',
            f"""VAR SourceDate = CALCULATE ( SELECTEDVALUE ( '01 XER_TASK'[data_date] ), {clear} )
RETURN "Data date: " & IF ( ISBLANK ( SourceDate ), "Unavailable or multiple", FORMAT ( SourceDate, "dd MMM yyyy" ) )""",
        ),
        (
            'SM Drill Source File',
            'Selected source filename retained when the diagnostic has no matching activities.',
            '@',
            'Schedule Quality Drill-through',
            f"""CALCULATE ( SELECTEDVALUE ( '01 XER_TASK'[FileName], "Multiple or unavailable source files" ), {clear} )""",
        ),
        (
            'SM Drill Status',
            'Source diagnostic status at the activity row; blank at WBS summary levels.',
            '@',
            'Schedule Quality Drill-through',
            "IF ( ISINSCOPE ( '01 XER_TASK'[task_code] ), SELECTEDVALUE ( '01 XER_TASK'[status_code] ) )",
        ),
    ]

    for route in ROUTES:
        label = route['page_name']
        source = route['count_measure']
        if route['link_expr']:
            header_dax = f"""VAR Matches = COALESCE ( CALCULATE ( [{source}], {clear} ), 0 )
VAR Links = COALESCE ( CALCULATE ( {route['link_expr']}, {clear} ), 0 )
RETURN IF (
    NOT [SM Drill Snapshot Available],
    "Select one project and available update",
    "{label}: " & FORMAT ( Matches, "#,0" )
        & IF ( Matches = 1, " matching activity (", " matching activities (" )
        & FORMAT ( Links, "#,0" )
        & IF ( Links = 1, " relationship) | ", " relationships) | " )
        & [SM Drill Context]
)"""
        else:
            header_dax = f"""VAR Matches = COALESCE ( CALCULATE ( [{source}], {clear} ), 0 )
RETURN IF (
    NOT [SM Drill Snapshot Available],
    "Select one project and available update",
    "{label}: " & FORMAT ( Matches, "#,0" )
        & IF ( Matches = 1, " matching activity | ", " matching activities | " )
        & [SM Drill Context]
)"""
        measures.append(
            (
                route['header_measure'],
                f'Diagnostic activity count and snapshot context for {label}; WBS grouping rows are not counted.',
                '@',
                'Schedule Quality Drill-through',
                header_dax,
            )
        )

    def link_detail_dax(predicate: str, show_lag: str) -> str:
        return f"""IF (
    ISINSCOPE ( '01 XER_TASK'[task_code] ),
    VAR Links =
        FILTER (
            RELATEDTABLE ( '06 XER_PREDECESSOR' ),
            {predicate}
        )
    VAR TotalLinks = COUNTROWS ( Links )
    VAR TopLinks =
        TOPN (
            3,
            Links,
            '06 XER_PREDECESSOR'[predecessor_task_code], ASC,
            '06 XER_PREDECESSOR'[pred_type], ASC,
            '06 XER_PREDECESSOR'[pred_task_id_key], ASC
        )
    VAR Extra = TotalLinks - COUNTROWS ( TopLinks )
    RETURN IF (
        TotalLinks > 0,
        FORMAT ( TotalLinks, "#,0" ) & ": "
            & CONCATENATEX (
                TopLinks,
                VAR Code = COALESCE ( '06 XER_PREDECESSOR'[predecessor_task_code], '06 XER_PREDECESSOR'[pred_task_id_key], "?" )
                VAR Rel = SWITCH (
                    '06 XER_PREDECESSOR'[pred_type],
                    "PR_FS", "FS",
                    "PR_FS1", "FS",
                    "PR_SS", "SS",
                    "PR_FF", "FF",
                    "PR_SF", "SF",
                    COALESCE ( '06 XER_PREDECESSOR'[pred_type], "?" )
                )
                VAR LagVal = '06 XER_PREDECESSOR'[lag]
                VAR LagTxt = {show_lag}
                RETURN Code & " (" & Rel & LagTxt & ")",
                ", ",
                '06 XER_PREDECESSOR'[predecessor_task_code], ASC,
                '06 XER_PREDECESSOR'[pred_type], ASC,
                '06 XER_PREDECESSOR'[pred_task_id_key], ASC
            )
            & IF ( Extra > 0, " (+" & FORMAT ( Extra, "#,0" ) & " more)", "" )
    )
)"""

    always_lag = (
        'IF ( ISBLANK ( LagVal ), "", " " & IF ( LagVal = INT ( LagVal ), '
        'FORMAT ( LagVal, "+#,0;-#,0;0" ), FORMAT ( LagVal, "+#,0.0;-#,0.0;0.0" ) ) & "d" )'
    )
    nonzero_lag = (
        'IF ( ISBLANK ( LagVal ) || LagVal = 0, "", " " & IF ( LagVal = INT ( LagVal ), '
        'FORMAT ( LagVal, "+#,0;-#,0;0" ), FORMAT ( LagVal, "+#,0.0;-#,0.0;0.0" ) ) & "d" )'
    )

    detail_expressions = {
        'SM Drill Missing Logic Detail': (
            "IF ( ISINSCOPE ( '01 XER_TASK'[task_code] ), SELECTEDVALUE ( '01 XER_TASK'[SM Fail Missing Logic] ) )"
        ),
        'SM Drill Leads Detail': link_detail_dax(
            "NOT ISBLANK ( '06 XER_PREDECESSOR'[lag] ) && '06 XER_PREDECESSOR'[lag] < 0",
            always_lag,
        ),
        'SM Drill Lags Detail': link_detail_dax(
            "NOT ISBLANK ( '06 XER_PREDECESSOR'[lag] ) && '06 XER_PREDECESSOR'[lag] > 5",
            always_lag,
        ),
        'SM Drill Non-FS Detail': link_detail_dax(
            "'06 XER_PREDECESSOR'[pred_type] IN { \"PR_SS\", \"PR_FF\", \"PR_SF\" }",
            nonzero_lag,
        ),
        'SM Drill Restrictive Constraints Detail': """IF (
    ISINSCOPE ( '01 XER_TASK'[task_code] ),
    VAR CstrCode = SELECTEDVALUE ( '01 XER_TASK'[cstr_type] )
    VAR CstrDate = SELECTEDVALUE ( '01 XER_TASK'[cstr_date] )
    VAR Label = SWITCH (
        CstrCode,
        "CS_MSO", "Must Start On",
        "CS_MSOB", "Start On or Before",
        "CS_MEO", "Must Finish On",
        "CS_MEOB", "Finish On or Before",
        "CS_MANDSTART", "Mandatory Start",
        "CS_MANDFIN", "Mandatory Finish",
        CstrCode
    )
    RETURN IF (
        NOT ISBLANK ( Label ),
        Label & IF ( NOT ISBLANK ( CstrDate ), " (" & FORMAT ( CstrDate, "dd MMM yyyy" ) & ")", "" )
    )
)""",
        'SM Drill Out-of-Sequence Detail': """IF (
    ISINSCOPE ( '01 XER_TASK'[task_code] ),
    VAR Links =
        FILTER (
            RELATEDTABLE ( '06 XER_PREDECESSOR' ),
            '06 XER_PREDECESSOR'[predecessor_task_type] IN { "TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile" }
                && (
                    ( '06 XER_PREDECESSOR'[pred_type] IN { "PR_FS", "PR_FS1" } && '06 XER_PREDECESSOR'[predecessor_status_code] IN { "TK_NotStart", "TK_Active" } )
                        || ( '06 XER_PREDECESSOR'[pred_type] = "PR_SS" && '06 XER_PREDECESSOR'[predecessor_status_code] = "TK_NotStart" )
                )
        )
    VAR TotalLinks = COUNTROWS ( Links )
    VAR TopLinks =
        TOPN (
            3,
            Links,
            '06 XER_PREDECESSOR'[predecessor_task_code], ASC,
            '06 XER_PREDECESSOR'[pred_type], ASC,
            '06 XER_PREDECESSOR'[pred_task_id_key], ASC
        )
    VAR Extra = TotalLinks - COUNTROWS ( TopLinks )
    RETURN IF (
        TotalLinks > 0,
        FORMAT ( TotalLinks, "#,0" ) & ": "
            & CONCATENATEX (
                TopLinks,
                VAR Code = COALESCE ( '06 XER_PREDECESSOR'[predecessor_task_code], '06 XER_PREDECESSOR'[pred_task_id_key], "?" )
                VAR Rel = IF ( '06 XER_PREDECESSOR'[pred_type] = "PR_SS", "SS", "FS" )
                VAR PredState = SWITCH (
                    '06 XER_PREDECESSOR'[predecessor_status_code],
                    "TK_NotStart", "Not Started",
                    "TK_Active", "In Progress",
                    COALESCE ( '06 XER_PREDECESSOR'[predecessor_status_code], "?" )
                )
                RETURN Code & " (" & Rel & ", " & PredState & ")",
                ", ",
                '06 XER_PREDECESSOR'[predecessor_task_code], ASC,
                '06 XER_PREDECESSOR'[pred_type], ASC,
                '06 XER_PREDECESSOR'[pred_task_id_key], ASC
            )
            & IF ( Extra > 0, " (+" & FORMAT ( Extra, "#,0" ) & " more)", "" )
    )
)""",
        'SM Drill Negative Float Detail': """IF (
    ISINSCOPE ( '01 XER_TASK'[task_code] ),
    VAR Val = SELECTEDVALUE ( '01 XER_TASK'[total_float] )
    RETURN IF (
        NOT ISBLANK ( Val ),
        IF ( Val = INT ( Val ), FORMAT ( Val, "#,0" ), FORMAT ( Val, "#,0.0" ) ) & "d"
    )
)""",
        'SM Drill Remaining Duration Detail': """IF (
    ISINSCOPE ( '01 XER_TASK'[task_code] ),
    VAR Val = SELECTEDVALUE ( '01 XER_TASK'[remaining_duration] )
    VAR Excess = Val - 44
    RETURN IF (
        NOT ISBLANK ( Val ),
        IF ( Val = INT ( Val ), FORMAT ( Val, "#,0" ), FORMAT ( Val, "#,0.0" ) ) & "d (+"
            & IF ( Excess = INT ( Excess ), FORMAT ( Excess, "#,0" ), FORMAT ( Excess, "#,0.0" ) ) & "d)"
    )
)""",
        'SM Drill Date Integrity Detail': (
            "IF ( ISINSCOPE ( '01 XER_TASK'[task_code] ), SELECTEDVALUE ( '01 XER_TASK'[SM Fail Invalid Dates] ) )"
        ),
        'SM Drill Baseline Coverage Detail': (
            "IF ( ISINSCOPE ( '01 XER_TASK'[task_code] ), SELECTEDVALUE ( '01 XER_TASK'[SM Fail Baseline Coverage] ) )"
        ),
    }

    for route in ROUTES:
        name = route['detail_measure']
        measures.append(
            (
                name,
                f"Activity-grain diagnostic evidence for {route['page_name']}; blank at WBS summary levels.",
                '@',
                'Schedule Quality Drill-through',
                detail_expressions[name],
            )
        )
    return measures


def update_metrics_tmdl() -> int:
    path = MODEL / 'tables/XER Metrics.tmdl'
    text, newline = read_tmdl(path)
    measures = build_measures()
    target_names = [*RETIRED_MEASURES, *(m[0] for m in measures)]
    for name in target_names:
        pattern = (
            r"(?:\n\t///[^\n]*)*\n\tmeasure '"
            + re.escape(name)
            + r"' =.*?(?=\n\t///|\n\tmeasure |\n\tcolumn |\n\tpartition |\Z)"
        )
        text = re.sub(pattern, '', text, flags=re.S)
        assert f"\tmeasure '{name}' =" not in text, f'Residual measure block for {name}'

    blocks = []
    for name, description, fmt, folder, expression in measures:
        lines = [f'\t/// {description}', f"\tmeasure '{name}' ="]
        lines += ['\t\t\t' + line for line in expression.splitlines()]
        lines += [
            f'\t\tformatString: {fmt}',
            f'\t\tdisplayFolder: {folder}',
            f'\t\tlineageTag: {lineage(name)}',
        ]
        blocks.append('\n'.join(lines))

    insertion = text.index('\n\tcolumn ') if '\n\tcolumn ' in text else text.index('\n\tpartition ')
    text = text[:insertion].rstrip('\n') + '\n\n' + '\n\n'.join(blocks) + '\n' + text[insertion:]
    write_tmdl(path, text, newline)
    return len(measures)


def clean_culture_tmdl() -> int:
    path = MODEL / 'cultures/en-NZ.tmdl'
    if not path.exists():
        return 0
    text, newline = read_tmdl(path)
    removed = 0
    for key in RETIRED_CULTURE_KEYS:
        pattern = r'\n\t\t\t    "' + re.escape(key) + r'": \{\n.*?\n\t\t\t    \},'
        updated, count = re.subn(pattern, '', text, flags=re.S)
        text = updated
        removed += count
    write_tmdl(path, text, newline)
    return removed


def build_page_filter(route_key: str, ordinal: int, kind: str, col: str, arg) -> dict:
    name = hid(f'pflt/{route_key}/{ordinal}/{col}')
    if kind == 'in':
        return {
            'name': name,
            'ordinal': ordinal,
            'field': column_ref(col),
            'type': 'Categorical',
            'filter': {
                'Version': 2,
                'From': [{'Name': 't', 'Entity': '01 XER_TASK', 'Type': 0}],
                'Where': [
                    {
                        'Condition': {
                            'In': {
                                'Expressions': [column_ref(col, source='t')],
                                'Values': [[{'Literal': {'Value': f"'{val}'"}}] for val in arg],
                            }
                        }
                    }
                ],
            },
            'howCreated': 'User',
        }
    if kind == 'gt_int':
        condition = {
            'Comparison': {
                'ComparisonKind': 1,
                'Left': column_ref(col, source='t'),
                'Right': {'Literal': {'Value': f'{int(arg)}L'}},
            }
        }
    elif kind in ('lt_num', 'gt_num'):
        cmp_kind = 3 if kind == 'lt_num' else 1
        condition = {
            'And': {
                'Left': {
                    'Not': {
                        'Expression': {
                            'Comparison': {
                                'ComparisonKind': 0,
                                'Left': column_ref(col, source='t'),
                                'Right': {'Literal': {'Value': 'null'}},
                            }
                        }
                    }
                },
                'Right': {
                    'Comparison': {
                        'ComparisonKind': cmp_kind,
                        'Left': column_ref(col, source='t'),
                        'Right': {'Literal': {'Value': f'{arg}D'}},
                    }
                },
            }
        }
    elif kind == 'nonblank_str':
        condition = {
            'And': {
                'Left': {
                    'Not': {
                        'Expression': {
                            'Comparison': {
                                'ComparisonKind': 0,
                                'Left': column_ref(col, source='t'),
                                'Right': {'Literal': {'Value': 'null'}},
                            }
                        }
                    }
                },
                'Right': {
                    'Not': {
                        'Expression': {
                            'Comparison': {
                                'ComparisonKind': 0,
                                'Left': column_ref(col, source='t'),
                                'Right': {'Literal': {'Value': "''"}},
                            }
                        }
                    }
                },
            }
        }
    else:
        raise ValueError(f'Unknown filter kind: {kind}')

    return {
        'name': name,
        'ordinal': ordinal,
        'field': column_ref(col),
        'type': 'Advanced',
        'filter': {
            'Version': 2,
            'From': [{'Name': 't', 'Entity': '01 XER_TASK', 'Type': 0}],
            'Where': [{'Condition': condition}],
        },
        'howCreated': 'User',
    }


def load_template_visuals() -> tuple[dict, dict[str, dict]]:
    legacy_dir = REPORT / 'pages' / LEGACY_PAGES[0]
    first_new_dir = REPORT / 'pages' / page_id(ROUTES[0]['key'])
    if (legacy_dir / 'page.json').exists():
        page_tpl = load_json(legacy_dir / 'page.json')
        visuals_tpl = {
            role: load_json(legacy_dir / 'visuals' / vid / 'visual.json')
            for role, vid in TEMPLATE_ROLES.items()
        }
        return page_tpl, visuals_tpl
    if (first_new_dir / 'page.json').exists():
        page_tpl = load_json(first_new_dir / 'page.json')
        visuals_tpl = {
            role: load_json(first_new_dir / 'visuals' / visual_id(ROUTES[0]['key'], role) / 'visual.json')
            for role in TEMPLATE_ROLES
        }
        return page_tpl, visuals_tpl
    raise FileNotFoundError('Neither legacy nor generated drill-through template page exists.')


def build_drillthrough_pages() -> list[str]:
    page_tpl, visuals_tpl = load_template_visuals()
    created_pages: list[str] = []

    for route in ROUTES:
        rkey = route['key']
        pid = page_id(rkey)
        created_pages.append(pid)
        pdir = REPORT / 'pages' / pid
        vdir = pdir / 'visuals'
        if pdir.exists():
            shutil.rmtree(pdir)
        vdir.mkdir(parents=True, exist_ok=True)

        bound_filter_id = hid(f'bound/{rkey}')
        filters = [
            {
                'name': bound_filter_id,
                'ordinal': 0,
                'field': measure_ref(route['count_measure']),
                'type': 'Categorical',
                'howCreated': 'Drillthrough',
            }
        ]
        for idx, (fkind, fcol, farg) in enumerate(route['filters'], start=1):
            filters.append(build_page_filter(rkey, idx, fkind, fcol, farg))

        page_doc = {
            '$schema': page_tpl['$schema'],
            'name': pid,
            'displayName': route['page_name'],
            'displayOption': page_tpl.get('displayOption', 'FitToPage'),
            'height': page_tpl.get('height', 1080),
            'width': page_tpl.get('width', 1920),
            'filterConfig': {
                'filters': filters,
                'filterSortOrder': 'Custom',
            },
            'pageBinding': {
                'name': hid(f'binding/{rkey}'),
                'type': 'Drillthrough',
                'parameters': [
                    {
                        'name': hid(f'param/{rkey}'),
                        'boundFilter': bound_filter_id,
                        'fieldExpr': measure_ref(route['count_measure']),
                    }
                ],
            },
            'objects': copy.deepcopy(page_tpl['objects']),
            'visibility': 'HiddenInViewMode',
            'type': 'Drillthrough',
            'visualInteractions': [
                {
                    'source': visual_id(rkey, 'project_slicer'),
                    'target': visual_id(rkey, 'state_slicer'),
                    'type': 'NoFilter',
                }
            ],
        }
        save_json(pdir / 'page.json', page_doc)

        for role, tpl in visuals_tpl.items():
            vis = copy.deepcopy(tpl)
            vid = visual_id(rkey, role)
            vis['name'] = vid
            if 'filterConfig' in vis and 'filters' in vis['filterConfig']:
                for fidx, vflt in enumerate(vis['filterConfig']['filters']):
                    vflt['name'] = hid(f'vflt/{rkey}/{role}/{fidx}')

            if role == 'page_title':
                text_properties(vis)['text'] = literal("'" + route['page_name'].replace("'", "''") + "'")
            elif role == 'heading':
                vis['position'].update(x=115, y=84, width=1785, height=46)
                props = text_properties(vis)
                props['text'] = {'expr': measure_ref(route['header_measure'])}
                props['fontSize'] = literal('17D')
                props['fontColor'] = {'solid': {'color': literal("'#252525'")}}
            elif role == 'context_title':
                text_properties(vis)['text'] = {'expr': measure_ref('SM Drill Context')}
            elif role == 'date_title':
                text_properties(vis)['text'] = {'expr': measure_ref('SM Drill Data Date')}
            elif role == 'file_title':
                text_properties(vis)['text'] = {'expr': measure_ref('SM Drill Source File')}
            elif role == 'matrix':
                vis.pop('filterConfig', None)
                projections = vis['visual']['query']['queryState']['Values']['projections']
                projections[:] = [
                    x for x in projections if not x.get('queryRef', '').startswith('XER Metrics.SM Drill ')
                ]
                values_obj = vis['visual']['objects'].setdefault('values', [])
                values_obj[:] = [
                    x
                    for x in values_obj
                    if not str(x.get('selector', {}).get('metadata', '')).startswith('XER Metrics.SM Drill ')
                ]
                diagnostics = [
                    ('SM Drill Status', 'Status', 100, False),
                    (route['detail_measure'], route['detail_caption'], 230, True),
                ]
                for offset, (helper, caption, width, wrap_text) in enumerate(diagnostics):
                    qref = 'XER Metrics.' + helper
                    projections.insert(
                        1 + offset,
                        {
                            'field': measure_ref(helper),
                            'queryRef': qref,
                            'nativeQueryRef': caption,
                            'displayName': caption,
                        },
                    )
                    vprops = {'width': literal(f'{width}D'), 'customWidth': literal('true')}
                    if wrap_text:
                        vprops['wrap'] = literal('true')
                    values_obj.append({'properties': vprops, 'selector': {'metadata': qref}})

            save_json(vdir / vid / 'visual.json', vis)

    for legacy in LEGACY_PAGES:
        legacy_path = REPORT / 'pages' / legacy
        if legacy_path.exists():
            shutil.rmtree(legacy_path)

    pages_meta_path = REPORT / 'pages/pages.json'
    pages_meta = load_json(pages_meta_path)
    retired_and_new = set(LEGACY_PAGES) | set(created_pages)
    visible_order = [p for p in pages_meta['pageOrder'] if p not in retired_and_new]
    pages_meta['pageOrder'] = visible_order + created_pages
    save_json(pages_meta_path, pages_meta)

    bookmarks_dir = REPORT / 'bookmarks'
    for bmid in LEGACY_BOOKMARKS:
        bm_file = bookmarks_dir / f'{bmid}.bookmark.json'
        if bm_file.exists():
            bm_file.unlink()
    bookmarks_meta_path = bookmarks_dir / 'bookmarks.json'
    bookmarks_meta = load_json(bookmarks_meta_path)
    bookmarks_meta['items'] = [
        item for item in bookmarks_meta['items'] if item.get('name') not in LEGACY_BOOKMARKS
    ]
    save_json(bookmarks_meta_path, bookmarks_meta)
    return created_pages


def update_sched_metrics_page() -> None:
    table_path = REPORT / 'pages/327b48a7fbd37ce0a51c/visuals/58fbc09d197fe53515d8/visual.json'
    table_vis = load_json(table_path)
    projections = [
        {
            'field': column_ref('UpdateDate'),
            'queryRef': '01 XER_TASK.UpdateDate',
            'nativeQueryRef': 'Update',
            'displayName': 'Update',
            'format': 'MMM yyyy',
        }
    ]
    widths = [
        {
            'properties': {'value': literal('78D')},
            'selector': {'metadata': '01 XER_TASK.UpdateDate'},
        }
    ]
    formatting = []
    for route in ROUTES:
        mname = route['count_measure']
        qref = f'XER Metrics.{mname}'
        projections.append(
            {
                'field': measure_ref(mname),
                'queryRef': qref,
                'nativeQueryRef': mname,
                'displayName': route['table_header'],
            }
        )
        widths.append(
            {
                'properties': {'value': literal(f"{route['table_width']}D")},
                'selector': {'metadata': qref},
            }
        )
        formatting.append(
            {
                'properties': {'alignment': literal("'Center'")},
                'selector': {'metadata': qref},
            }
        )

    table_vis['visual']['query']['queryState']['Values']['projections'] = projections
    objects = table_vis['visual']['objects']
    objects['columnWidth'] = widths
    objects['columnFormatting'] = formatting
    col_headers = objects['columnHeaders'][0]['properties']
    col_headers['wordWrap'] = literal('true')
    col_headers['defaultColumnWidth'] = literal('78D')
    save_json(table_path, table_vis)

    caption_path = REPORT / 'pages/327b48a7fbd37ce0a51c/visuals/a1970523de7632121d6b/visual.json'
    caption_vis = load_json(caption_path)
    caption_vis['position']['width'] = 810
    props = text_properties(caption_vis)
    props['text'] = literal(
        "'Bands: see titles | Hover: coverage | Table: failing activities — right-click a cell → Drill through.'"
    )
    props['fontSize'] = literal('10D')
    props['fontFamily'] = literal("'Segoe UI'")
    save_json(caption_path, caption_vis)


def main() -> None:
    col_count = update_task_tmdl()
    meas_count = update_metrics_tmdl()
    culture_removed = clean_culture_tmdl()
    created_pages = build_drillthrough_pages()
    update_sched_metrics_page()
    print(
        json.dumps(
            {
                'task_columns': col_count,
                'metrics_measures': meas_count,
                'retired_culture_entries_removed': culture_removed,
                'drillthrough_pages': len(created_pages),
                'page_ids': created_pages,
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
