"""Build the static, same-page metric guide without changing metric calculations.

Content lives in metric_guide.json. Existing visual positions and measure
definitions are left intact; guide bookmarks only change display state.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'Project Review - Programme (datalake).SemanticModel/definition'
REPORT = ROOT / 'Project Review - Programme (datalake).Report/definition'
PAGE = '327b48a7fbd37ce0a51c'
PAGE_DIR = REPORT / 'pages' / PAGE
TABLE = 'Schedule Metric Guide'
NAMESPACE = uuid.UUID('9bcb9710-5137-49d5-b9a8-09b5207a7b42')


def identifier(name):
    return uuid.uuid5(NAMESPACE, name).hex[:20]


def lineage(name):
    return str(uuid.uuid5(NAMESPACE, name))


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def lit(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, (float, int)):
        value = str(value) + 'D'
    else:
        value = "'" + value.replace("'", "''") + "'"
    return {'expr': {'Literal': {'Value': value}}}


def colour(value):
    return {'solid': {'color': lit(value)}}


def props(**values):
    return [{'properties': values}]


def column(name):
    return {'Column': {'Expression': {'SourceRef': {'Entity': TABLE}}, 'Property': name}}


def container(key, kind, x, y, width, height, z, hidden=True, tab=0):
    return {
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.13.0/schema.json',
        'name': identifier(key),
        'position': {'x': x, 'y': y, 'width': width, 'height': height, 'z': z, 'tabOrder': tab},
        'visual': {'visualType': kind, 'objects': {}, 'visualContainerObjects': {
            'background': props(show=lit(False)),
            'general': props(altText=lit(key.replace('-', ' ')), keepLayerOrder=lit(True)),
            'visualHeader': props(show=lit(False)),
        }, 'drillFilterOtherVisuals': False},
        'isHidden': hidden,
    }


def textbox(key, text, x, y, width, height, size, bold=False, colour_value='#252525', z=62000):
    result = container(key, 'textbox', x, y, width, height, z)
    result['visual']['objects'] = {'general': props(paragraphs=[{
        'textRuns': [{'value': text, 'textStyle': {'fontSize': f'{size}pt',
                     'fontFamily': 'Segoe UI', 'fontWeight': 'bold' if bold else 'normal',
                     'color': colour_value}}]
    }])}
    result['visual']['visualContainerObjects']['border'] = props(show=lit(False))
    return result


def button(key, text, bookmark, x, y, width, height, hidden, tab):
    template = read(PAGE_DIR / 'visuals/e417356479b02aac4464/visual.json')
    result = container(key, 'actionButton', x, y, width, height, 64000 if hidden else 40500, hidden, tab)
    result['visual']['objects'] = copy.deepcopy(template['visual']['objects'])
    objects = result['visual']['objects']
    objects['text'][1]['properties'].update(text=lit(text), fontSize=lit(17), fontColor=colour('#FFFFFF'))
    objects['fill'][0]['properties']['fillColor'] = colour('#BE281D')
    objects['outline'][0]['properties']['lineColor'] = colour('#8D1D16')
    objects['fill'].append({'selector': {'id': 'hover'}, 'properties': {'fillColor': colour('#8D1D16')}})
    explanation = 'Close the guide and return to your current selections.' if hidden else 'Open the metric reference table: definitions, calculations, targets and coverage notes.'
    result['visual']['visualContainerObjects']['general'][0]['properties']['altText'] = lit(explanation)
    result['visual']['visualContainerObjects']['background'] = props(show=lit(True), color=colour('#BE281D'), transparency=lit(0))
    result['visual']['visualContainerObjects']['visualLink'] = props(show=lit(True), type=lit('Bookmark'), bookmark=lit(bookmark), tooltip=lit(explanation))
    return result


def write_reference_table(content):
    columns = ['Metric', 'Meaning and calculation', 'Target / score', 'Scope and notes']
    rows = [{
        'Metric': row['metric'],
        'Meaning and calculation': row['meaning'] + '\nWhy it matters: ' + row['rationale'] + '\nCalculation: ' + row['calculation'],
        'Target / score': row['threshold'] + '\n' + row['score_note'],
        'Scope and notes': row['population'] + '\n' + row['limitations'],
    } for row in sorted(content['rows'], key=lambda row: row['sort_order'])]
    assert rows and all(set(columns).issubset(row) for row in rows)
    assert len({row['Metric'] for row in rows}) == len(rows)
    dax_text = lambda value: '"' + str(value).replace('\n', ' ').replace('"', '""') + '"'
    declarations = [('Order', 'int64')] + [(name, 'string') for name in columns]
    lines = ['/// Reader reference for the implemented Schedule Metrics page; static and disconnected.',
             f"table '{TABLE}'", '\tisHidden', f'\tlineageTag: {lineage(TABLE)}', '']
    for name, datatype in declarations:
        quoted = "'" + name.replace("'", "''") + "'"
        lines += [f'\tcolumn {quoted}', f'\t\tdataType: {datatype}', f'\t\tlineageTag: {lineage(name)}', '\t\tsummarizeBy: none', f'\t\tsourceColumn: [{name}]']
        if name == 'Order':
            lines += ['\t\tisHidden', '\t\tformatString: 0']
        if name == 'Metric':
            lines += ['\t\tsortByColumn: Order']
        lines.append('')
    lines += [f"\tpartition '{TABLE}' = calculated", '\t\tmode: import', '\t\tsource =', '\t\t\tDATATABLE (', '\t\t\t    "Order", INTEGER,']
    lines += [f'\t\t\t    {dax_text(name)}, STRING,' for name in columns]
    lines.append('\t\t\t    {')
    for i, row in enumerate(rows, 1):
        lines.append('\t\t\t        { ' + str(i) + ', ' + ', '.join(dax_text(row[name]) for name in columns) + ' }' + (',' if i < len(rows) else ''))
    lines += ['\t\t\t    }', '\t\t\t)', '']
    (MODEL / 'tables' / f'{TABLE}.tmdl').write_text('\n'.join(lines), encoding='utf-8')
    return len(rows)


def build(content):
    row_count = write_reference_table(content)
    model_path = MODEL / 'model.tmdl'
    text = model_path.read_text(encoding='utf-8-sig')
    reference = f"ref table '{TABLE}'"
    if reference not in text:
        text = text.replace("ref table 'Schedule Metric Detail'", "ref table 'Schedule Metric Detail'\n" + reference)
        model_path.write_text(text, encoding='utf-8')

    open_id, close_id = identifier('open-bookmark'), identifier('close-bookmark')
    guide = []
    guide.append(button('guide-opener', 'Metric guide', open_id, 1510, 86, 260, 44, False, 500))
    panel = container('guide-background', 'shape', 0, 0, 1920, 1080, 60000)
    panel['visual']['objects'] = {'shape': props(tileShape=lit('rectangle')), 'fill': props(show=lit(True), fillColor=colour('#FFFFFF'), transparency=lit(0)), 'outline': props(show=lit(True), lineColor=colour('#BE281D'), weight=lit(2))}
    for state_object in ('fill', 'outline'):
        panel['visual']['objects'][state_object][0]['selector'] = {'id': 'default'}
    panel['visual']['visualContainerObjects']['background'] = props(show=lit(True), color=colour('#FFFFFF'), transparency=lit(0))
    guide.append(panel)
    guide.append(textbox('guide-heading', 'Schedule Metrics | Metric guide', 30, 20, 1420, 64, 28, True, '#BE281D'))
    guide.append(textbox('guide-introduction', content['introduction'], 30, 90, 1855, 116, 15))
    guide.append(button('guide-close', 'Close guide', close_id, 1610, 24, 276, 50, True, 100))
    table = container('guide-table', 'tableEx', 30, 220, 1860, 710, 61000, True, 200)
    table['visual']['query'] = {'queryState': {'Values': {'projections': [
        {'field': column(name), 'queryRef': f'{TABLE}.{name}', 'nativeQueryRef': name} for name in columns]}},
        'sortDefinition': {'sort': [{'field': column('Metric'), 'direction': 'Ascending'}], 'isDefaultSort': True}}
    table['visual']['objects'] = {
        'total': props(totals=lit(False)),
        'columnHeaders': props(fontSize=lit(16), fontColor=colour('#FFFFFF'), backColor=colour('#BE281D'), alignment=lit('Left'), wordWrap=lit(True), autoSizeColumnWidth=lit(True), columnAdjustment=lit('fitToContent'), defaultColumnWidth=lit(90)),
        'values': props(fontSize=lit(16), fontColor=colour('#252525'), backColor=colour('#FFFFFF'), wordWrap=lit(True)),
        'grid': props(rowPadding=lit(10), gridHorizontal=lit(True), gridHorizontalColor=colour('#DDDDDD'), gridHorizontalWeight=lit(1), gridVertical=lit(False)),
        'columnWidth': [{'properties': {'value': lit(width)}, 'selector': {'metadata': f'{TABLE}.{name}'}} for name, width in zip(columns, [275, 650, 210, 675])],
    }
    table['visual']['visualContainerObjects']['general'][0]['properties']['altText'] = lit('Scrollable reference table covering all metrics, their calculations, targets, score contribution and scope. Use Close guide to return to the charts.')
    table['visual']['visualContainerObjects']['background'] = props(show=lit(True), color=colour('#FFFFFF'), transparency=lit(0))
    guide.append(table)
    guide.append(textbox('guide-reading-notes', content['reading_legend'], 30, 950, 1855, 120, 17))
    for key, tab in [('guide-heading', 10), ('guide-introduction', 20), ('guide-reading-notes', 300), ('guide-background', 1000)]:
        next(v for v in guide if v['name'] == identifier(key))['position']['tabOrder'] = tab

    new_ids = {v['name'] for v in guide}
    existing = [read(path) for path in (PAGE_DIR / 'visuals').glob('*/visual.json') if path.parent.name not in new_ids]
    for visual in guide:
        write(PAGE_DIR / 'visuals' / visual['name'] / 'visual.json', visual)
    all_visuals = existing + guide
    for is_open, name, title in [(True, open_id, 'Open Metric Guide - Sched. Metrics'), (False, close_id, 'Close Metric Guide - Sched. Metrics')]:
        states = {}
        for visual in all_visuals:
            visible = visual['name'] in new_ids and visual['name'] != identifier('guide-opener') if is_open else not visual.get('isHidden', False)
            state = {'visualType': visual['visual']['visualType'], 'objects': {}}
            if not visible:
                state['display'] = {'mode': 'hidden'}
            states[visual['name']] = {'singleVisual': state}
        bookmark = {'$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/bookmark/2.1.0/schema.json',
                    'displayName': title, 'name': name, 'options': {'targetVisualNames': list(states), 'suppressData': True, 'applyOnlyToTargetVisuals': True},
                    'explorationState': {'version': '1.0', 'activeSection': PAGE, 'sections': {PAGE: {'visualContainers': states}}}}
        write(REPORT / 'bookmarks' / f'{name}.bookmark.json', bookmark)
    metadata_path = REPORT / 'bookmarks/bookmarks.json'
    metadata = read(metadata_path)
    group_id = identifier('guide-bookmark-group')
    if not any(item['name'] == group_id for item in metadata['items']):
        metadata['items'].append({'name': group_id, 'displayName': 'Schedule metric guide', 'children': [open_id, close_id]})
    write(metadata_path, metadata)
    # Restore the whole page when a project bookmark is invoked directly from
    # the Bookmarks pane while the guide has hidden the ordinary report visuals.
    project_popup_ids = {'9003403baa60d58e5d3b', 'd778f258649d6153fd4c',
                         '39bf0f694c30cb5529b0', 'e417356479b02aac4464'}
    for project_bookmark, menu_open in [('1a93e9bf0e2fc3eaa8d3', True), ('cb5d862970d6a9512370', False)]:
        bookmark_path = REPORT / 'bookmarks' / f'{project_bookmark}.bookmark.json'
        bookmark = read(bookmark_path)
        bookmark['options']['applyOnlyToTargetVisuals'] = True
        states = {}
        for visual in all_visuals:
            if visual['name'] in project_popup_ids:
                visible = menu_open
            elif visual['name'] in new_ids:
                visible = visual['name'] == identifier('guide-opener') and not menu_open
            else:
                visible = not visual.get('isHidden', False)
            state = {'visualType': visual['visual']['visualType'], 'objects': {}}
            if not visible:
                state['display'] = {'mode': 'hidden'}
            states[visual['name']] = {'singleVisual': state}
        bookmark['explorationState']['sections'][PAGE]['visualContainers'] = states
        bookmark['options']['targetVisualNames'] = list(states)
        write(bookmark_path, bookmark)
    page = read(PAGE_DIR / 'page.json')
    pairs = {(i['source'], i['target']) for i in page['visualInteractions']}
    table_id = identifier('guide-table')
    for visual in all_visuals:
        if visual['name'] == table_id:
            continue
        for source, target in [(table_id, visual['name']), (visual['name'], table_id)]:
            if (source, target) not in pairs:
                page['visualInteractions'].append({'source': source, 'target': target, 'type': 'NoFilter'})
    write(PAGE_DIR / 'page.json', page)
    write(Path(__file__).with_name('metric_guide_manifest.json'), {'table': TABLE, 'rows': row_count, 'page': PAGE,
          'openBookmark': open_id, 'closeBookmark': close_id, 'visuals': {key: identifier(key) for key in ['guide-opener', 'guide-background', 'guide-heading', 'guide-introduction', 'guide-close', 'guide-table', 'guide-reading-notes']}})
    print(json.dumps({'guideRows': row_count, 'newVisuals': len(guide), 'totalPageVisuals': len(all_visuals), 'newBookmarks': 2}))


def refresh_content(content):
    """Refresh reference text only; preserve saved layout, bookmarks and filters."""
    row_count = write_reference_table(content)
    for key, field in [('guide-introduction', 'introduction'),
                       ('guide-reading-notes', 'reading_legend')]:
        path = PAGE_DIR / 'visuals' / identifier(key) / 'visual.json'
        visual = read(path)
        paragraphs = visual['visual']['objects']['general'][0]['properties']['paragraphs']
        assert len(paragraphs) == 1 and len(paragraphs[0]['textRuns']) == 1
        if paragraphs[0]['textRuns'][0]['value'] != content[field]:
            paragraphs[0]['textRuns'][0]['value'] = content[field]
            write(path, visual)
    manifest_path = Path(__file__).with_name('metric_guide_manifest.json')
    if manifest_path.exists():
        manifest = read(manifest_path)
        if manifest['rows'] != row_count:
            manifest['rows'] = row_count
            write(manifest_path, manifest)
    print(json.dumps({'guideRows': row_count, 'contentOnly': True}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-only', action='store_true',
                        help='Update the reference table and guide text without rebuilding report state.')
    args = parser.parse_args()
    content = read(Path(__file__).with_name('metric_guide.json'))
    (refresh_content if args.content_only else build)(content)
