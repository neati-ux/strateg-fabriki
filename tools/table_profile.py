"""Describe table shape and data quality before interpreting it."""
from collections import Counter
import csv
import io
import json
from pathlib import Path


MISSING = {'', 'na', 'n/a', 'null', 'nan'}


def profile(path, delimiter=None, key=None, group_by=None):
    from ingest import LIMIT
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Лимит таблицы 32 MiB')
    value = raw.decode('utf-8-sig')
    if delimiter is None:
        try:
            delimiter = '\t' if Path(path).suffix.lower() == '.tsv' else csv.Sniffer().sniff(value[:8192], delimiters=',;\t').delimiter
        except csv.Error:
            delimiter = ','
    reader = csv.reader(io.StringIO(value), delimiter=delimiter, strict=True)
    columns = [col.strip() for col in next(reader, [])]
    if not columns or any(not name for name in columns) or len(set(columns)) != len(columns):
        raise ValueError('Нужна строка уникальных непустых названий колонок')
    if key is not None and key not in columns:
        raise ValueError(f'Нет колонки {key}')
    key_index = columns.index(key) if key is not None else None
    if group_by is not None and (group_by not in columns or key is None):
        raise ValueError('Для группировки укажите существующие колонки ключа и категории')
    group_index = columns.index(group_by) if group_by is not None else None
    categories = {}
    conflicts = set()
    missing = Counter()
    shapes, duplicate_rows, count = [], 0, 0
    duplicates, keys = set(), set()
    duplicate_keys = 0
    for line in reader:
        count += 1
        if len(line) != len(columns):
            if len(shapes) < 20:
                shapes.append({'row_end': reader.line_num, 'cells': len(line)})
        normalized = tuple(cell.strip() for cell in line)
        if normalized in duplicates:
            duplicate_rows += 1
        duplicates.add(normalized)
        if key_index is not None:
            if key_index < len(normalized) and normalized[key_index].lower() not in MISSING:
                value = normalized[key_index]
                if value in keys:
                    duplicate_keys += 1
                keys.add(value)
                if group_index is not None and group_index < len(normalized):
                    group = normalized[group_index]
                    if group.lower() not in MISSING and categories.setdefault(value, group) != group:
                        conflicts.add(value)
        for i, name in enumerate(columns):
            if i >= len(normalized) or normalized[i].lower() in MISSING:
                missing[name] += 1
    result = {'columns': columns, 'rows': count, 'delimiter': delimiter,
            'missing_by_column': {name: missing[name] for name in columns},
            'duplicate_rows_after_first': duplicate_rows, 'key': key,
            'duplicate_keys_after_first': duplicate_keys if key is not None else None,
            'first_irregular_rows': shapes}
    if group_by is not None:
        result.update(unique_records=len(keys), group_by=group_by,
                      unique_counts=dict(Counter(label for k, label in categories.items() if k not in conflicts)),
                      conflicting_records=len(conflicts), uncategorized_records=len(keys) - len(categories))
    return result


def command(a):
    try:
        delimiter = '\t' if a.delimiter == 'tab' else a.delimiter
        result = profile(a.file, delimiter, a.key, a.group_by)
        folder = Path(a.file).parent
        if folder.name.casefold() == 'materials':
            result['other_materials'] = sorted(
                item.name for item in folder.iterdir()
                if item.name != Path(a.file).name and not item.name.startswith('.')
                and not item.is_symlink() and item.is_file()
            )
    except (OSError, ValueError, csv.Error) as exc:
        raise SystemExit(f'Таблица: {exc}') from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


def register(sub):
    p = sub.add_parser('profile-table', help='проверить UTF-8 CSV/TSV на пропуски, дубли и ширину строк')
    p.add_argument('file')
    p.add_argument('--key')
    p.add_argument('--group-by', help='сосчитать категории по уникальным ключам')
    p.add_argument('--delimiter', choices=(',', ';', 'tab'))
    p.set_defaults(fn=command)
