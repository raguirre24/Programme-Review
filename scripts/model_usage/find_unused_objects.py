"""Report model objects that the Programme Review report does not use.

Reads a JSON document on stdin (written by Find-UnusedModelObjects.ps1 from the open
Desktop model): the engine's calculation dependencies, the table/column/measure
inventory, relationships, RLS permissions, M expressions and DAX expressions.

An object is used when the report reaches it: every Column/Measure field in the PBIR
report JSON (pages, visuals, bookmarks, filters, formatting) is a root, and use flows
through the engine's dependencies, sort-by columns, calculated table expressions and
relationships between used tables. Three references do not count as use:

- a column or table named only inside REMOVEFILTERS(...): deleting it deletes the clear;
- an RLS row filter on a table nothing else uses: it only protects that table;
- validation scripts in scripts/: they define helpers in their own queries.

Guard tables in usage_allowlist.json (refresh-time checks such as XER CSV Refresh
Audit) are roots; allow-listed M expressions are load-disabled diagnostics.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'Project Review - Programme (datalake).Report' / 'definition'


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def report_references(report: Path) -> set[tuple[str, str, str]]:
    """(kind, table, name) for every Column ('C') and Measure ('M') field in the report."""
    refs = set()
    for path in report.rglob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        aliases = {}
        for node in walk(data):
            if isinstance(node.get('From'), list):
                aliases.update({x['Name']: x['Entity'] for x in node['From'] if 'Name' in x and 'Entity' in x})
        for node in walk(data):
            for kind, key in (('C', 'Column'), ('M', 'Measure')):
                field = node.get(key)
                if isinstance(field, dict) and 'Property' in field:
                    source = field.get('Expression', {}).get('SourceRef', {})
                    refs.add((kind, source.get('Entity') or aliases.get(source.get('Source')), field['Property']))
    return refs


def strip_clearing(expression: str) -> str:
    """Remove every REMOVEFILTERS(...) call, so what is left are the references that read data."""
    out, i, upper = [], 0, expression.upper()
    while True:
        start = upper.find('REMOVEFILTERS', i)
        if start < 0:
            out.append(expression[i:])
            return ''.join(out)
        pos, depth = upper.find('(', start), 0
        while pos < len(expression):
            if expression[pos] == '(':
                depth += 1
            elif expression[pos] == ')':
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        out.append(expression[i:start])
        i = pos + 1


def reading_references(expression: str, own_table: str, table_names: list[str]):
    """Columns and tables an expression reads outside REMOVEFILTERS."""
    text = re.sub(r'"(?:[^"]|"")*"', '""', strip_clearing(expression or ''))
    columns, tables = set(), set()
    for match in re.finditer(r"'((?:[^']|'')+)'\s*(\[(?:[^\]]|\]\])+\])?", text):
        table = match.group(1).replace("''", "'")
        if match.group(2):
            columns.add((table, match.group(2)[1:-1].replace(']]', ']')))
        else:
            tables.add(table)
    for table in table_names:
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table):
            for match in re.finditer(r"(?<![\w'\[])" + re.escape(table) + r'\s*(\[(?:[^\]]|\]\])+\])?', text):
                if match.group(1):
                    columns.add((table, match.group(1)[1:-1]))
                else:
                    tables.add(table)
    for match in re.finditer(r"(?<![\w'\]])\[((?:[^\]]|\]\])+)\]", text):
        columns.add((own_table, match.group(1).replace(']]', ']')))
    return columns, tables


def node(kind: str, table: str | None, name: str | None):
    if kind == 'MEASURE':
        return ('M', table, name)
    if kind in ('COLUMN', 'CALC_COLUMN'):
        return ('C', table, name)
    if kind in ('TABLE', 'CALC_TABLE'):
        return ('T', table, None)
    if kind in ('ACTIVE_RELATIONSHIP', 'RELATIONSHIP'):
        return ('R', None, name)
    if kind == 'ROWS_ALLOWED':
        return ('RLS', table, name)
    return (kind, table, name)


def analyse(data: dict, report_refs: set, allow: dict) -> dict:
    tables = {t['name']: t for t in data['tables']}
    names = sorted(tables, key=len, reverse=True)
    sort_by = {(t['name'], c['name']): c['sortBy'] for t in data['tables'] for c in t['columns'] if c.get('sortBy')}
    reading = {}
    for item in data['expressions']:
        key = ('T', item['table'], None) if item['kind'] == 'T' else (item['kind'], item['table'], item['name'])
        reading[key] = reading_references(item['expression'], item['table'], names)

    edges, m_edges = collections.defaultdict(set), collections.defaultdict(set)
    for dep in data['dependencies']:
        if dep['ot'] in ('PARTITION', 'M_EXPRESSION'):
            m_edges[(dep['ot'], dep['o'])].add((dep['rt'], dep['ro']))
            continue
        a, b = node(dep['ot'], dep['t'], dep['o']), node(dep['rt'], dep['rtab'], dep['ro'])
        if a[0] == 'ATTRIBUTE_HIERARCHY':
            continue
        if a in reading and b[0] in ('C', 'T'):
            columns, read_tables = reading[a]
            if b[0] == 'C' and (b[1], b[2]) not in columns:
                continue
            if b[0] == 'T' and b[1] not in read_tables and not any(c[0] == b[1] for c in columns):
                continue
        edges[a].add(b)
    for rel in data['relationships']:
        edges[('R', None, rel['name'])] |= {('C', rel['from'], rel['fromCol']), ('C', rel['to'], rel['toCol'])}
    rls = [a for a in edges if a[0] == 'RLS']

    used, stack = set(), []

    def use(n):
        if n not in used:
            used.add(n)
            stack.append(n)

    for kind, table, name in report_refs:
        if table in tables:
            use((kind, table, name))
            use(('T', table, None))
    for table in allow.get('guardTables', []):
        use(('T', table, None))
    changed = True
    while changed:
        while stack:
            n = stack.pop()
            if n[0] in ('M', 'C'):
                use(('T', n[1], None))
            if n[0] == 'C' and (n[1], n[2]) in sort_by:
                use(('C', n[1], sort_by[(n[1], n[2])]))
            if n[0] == 'T' and tables[n[1]]['kind'] == 'calc':
                for column in tables[n[1]]['columns']:
                    use(('C', n[1], column['name']))
            for b in edges.get(n, ()):
                use(b)
        changed = False
        for a in rls:
            if ('T', a[1], None) in used and a not in used:
                use(a)
                changed = True
        for rel in data['relationships']:
            if ('T', rel['from'], None) in used and ('T', rel['to'], None) in used and ('R', None, rel['name']) not in used:
                use(('R', None, rel['name']))
                changed = True

    reached, stack_m = set(), [k for k in m_edges if k[0] == 'PARTITION']
    while stack_m:
        for b in m_edges.get(stack_m.pop(), ()):
            if b not in reached:
                reached.add(b)
                stack_m.append(b)

    result = {'tables': [], 'relationships': [], 'measures': [], 'calculatedColumns': [], 'importedColumns': [],
              'rlsPermissions': [], 'mExpressions': []}
    for name, table in tables.items():
        if ('T', name, None) not in used:
            result['tables'].append(name)
            continue
        result['measures'] += [(name, m) for m in table['measures'] if ('M', name, m) not in used]
        for column in table['columns']:
            if ('C', name, column['name']) in used:
                continue
            if column['type'] == 'Calculated':
                result['calculatedColumns'].append((name, column['name']))
            elif column['type'] == 'Data' and table['kind'] != 'calc':
                result['importedColumns'].append((name, column['name']))
    result['relationships'] = [f"{r['from']}[{r['fromCol']}] -> {r['to']}[{r['toCol']}]"
                               for r in data['relationships'] if ('R', None, r['name']) not in used]
    result['rlsPermissions'] = sorted({f'{a[2]}: {a[1]}' for a in rls if a not in used})
    result['mExpressions'] = [e for e in data['mExpressions']
                              if ('M_EXPRESSION', e) not in reached and e not in allow.get('mExpressions', [])]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--allowlist', type=Path, default=Path(__file__).with_name('usage_allowlist.json'))
    parser.add_argument('--fail-on-unused', action='store_true', help='Exit 1 when anything unused is found.')
    args = parser.parse_args()
    data = json.loads(sys.stdin.read())
    allow = json.loads(args.allowlist.read_text(encoding='utf-8'))
    result = analyse(data, report_references(REPORT), allow)
    total = 0
    for section, items in result.items():
        total += len(items)
        print(f'== Unused {section}: {len(items)}')
        grouped = collections.defaultdict(list)
        for item in items:
            if isinstance(item, (list, tuple)):
                grouped[item[0]].append(item[1])
            else:
                grouped[''].append(item)
        for table, objects in grouped.items():
            print(f'   {table + ": " if table else ""}{"; ".join(objects)}')
    print(f'Total unused objects: {total}')
    return 1 if args.fail_on_unused and total else 0


if __name__ == '__main__':
    sys.exit(main())
