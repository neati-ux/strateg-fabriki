"""Translate the JSONL output of one OpenCode run into usage evidence."""
import hashlib
import json
from pathlib import Path

from route_preview import money


def receipt(path):
    session, first, last = None, None, None
    steps, text = {}, []
    failed = False
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Журнал OpenCode превышает 16 MiB')
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event.get('type')
            if kind not in {'step_start', 'step_finish', 'text', 'error'}:
                continue
            identity, stamp = event.get('sessionID'), event.get('timestamp')
            if not isinstance(identity, str) or not identity or type(stamp) is not int or stamp <= 0:
                raise ValueError('Событие OpenCode без сессии или отметки времени')
            if session and session != identity:
                raise ValueError('Нужен один запуск OpenCode в одной сессии')
            session = identity
            first = stamp if first is None else min(first, stamp)
            last = stamp if last is None else max(last, stamp)
            if kind == 'error':
                failed = True
                continue
            part = event.get('part', {})
            if kind == 'text' and isinstance(part.get('text'), str):
                text.append(part['text'])
            if kind == 'step_finish':
                part_id = part.get('id') or part.get('messageID')
                if not isinstance(part_id, str) or not part_id:
                    raise ValueError('У завершённого шага OpenCode нет ID')
                if part_id in steps and steps[part_id] != part:
                    raise ValueError('Противоречивые повторы событий OpenCode')
                steps[part_id] = part
    if not steps:
        raise ValueError('В журнале нет завершённых шагов. Резерв сохраняется до уточнения расходов.')
    if failed:
        raise ValueError('Журнал содержит ошибку. Для расхода нужен сверенный результат; резерв сохраняется.')
    result = {'opencode_session': session, 'evidence': path.name, 'seconds': (last - first) / 1000,
              'result': '\n'.join(text) or None, 'steps': len(steps),
              'step_fingerprints': [hashlib.sha256(json.dumps([session, step], ensure_ascii=False).encode()).hexdigest() for step in sorted(steps)]}
    for key in ('input', 'output', 'reasoning'):
        values = [(step.get('tokens') or {}).get(key) for step in steps.values()]
        result[key + '_tokens'] = sum(values) if all(type(n) is int and n >= 0 for n in values) else None
    for key in ('read', 'write'):
        values = [((step.get('tokens') or {}).get('cache') or {}).get(key) for step in steps.values()]
        result['cache_' + key + '_tokens'] = sum(values) if all(type(n) is int and n >= 0 for n in values) else None
    costs = [step.get('cost') for step in steps.values()]
    result['cost_usd'] = str(sum(money(n) for n in costs)) if all(n is not None for n in costs) else None
    return result

def session_usage(project, session_id=None, database=None):
    """Read OpenCode's own counters, keeping workspace sessions and their children together."""
    import os
    import re
    import sqlite3
    from contextlib import closing

    dbfile = database or Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'opencode/opencode.db'
    if not dbfile.is_file():
        return None
    root = project.parent.parent.resolve()
    with closing(sqlite3.connect(dbfile.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        rows = {r['id']: r for r in db.execute(
            'SELECT id,parent_id,directory,cost,tokens_input,tokens_output FROM session_v2'
        ) if r['directory'] and Path(r['directory']).resolve() in (root, project.resolve())}
        if session_id and session_id not in rows:
            raise ValueError('Сессия OpenCode не найдена в этой рабочей папке')
        if not rows:
            return None
        groups = {}
        for key in rows:
            parent = key
            seen = set()
            while rows[parent]['parent_id'] in rows and parent not in seen:
                seen.add(parent)
                parent = rows[parent]['parent_id']
            groups.setdefault(parent, []).append(key)
        selected = []
        for parent, keys in groups.items():
            if session_id:
                if session_id in keys:
                    selected.extend(keys)
                continue
            names = set()
            written = set()
            for key in keys:
                if Path(rows[key]['directory']).resolve() == project.resolve():
                    names.add(project.name)
                # Only paths supplied to tools establish project attribution.
                for tool, status, path in db.execute("""SELECT json_extract(p.value,'$.name'),json_extract(p.value,'$.state.status'),coalesce(json_extract(p.value,'$.state.input.filePath'),
                    json_extract(p.value,'$.state.input.path'),json_extract(p.value,'$.state.input.file_path'))
                    FROM session_message m,json_each(m.data,'$.content') p
                    WHERE m.session_id=? AND m.type='assistant' AND json_extract(p.value,'$.type')='tool'""", (key,)):
                    if isinstance(path, str):
                        normalized = path.replace(chr(92), '/')
                        absolute = Path(normalized)
                        if absolute.is_absolute():
                            try:
                                normalized = absolute.resolve().relative_to(root).as_posix()
                            except ValueError:
                                continue
                        match = re.match(r'(?:\./)?projects/([^/]+)(?:/|$)', normalized)
                        if match and not match[1].startswith('.'):
                            names.add(match[1])
                            if tool in ('write', 'edit') and status not in ('error', 'pending', 'running'):
                                written.add(match[1])
            if (written or names) == {project.name}:
                selected.extend(keys)
        if not selected:
            return None
        intervals = []
        missing_time = False
        for key in selected:
            for start, end in db.execute("""SELECT json_extract(data,'$.time.created'),json_extract(data,'$.time.completed')
                    FROM session_message WHERE session_id=? AND type='assistant'""", (key,)):
                if isinstance(start, int) and isinstance(end, int) and end >= start:
                    intervals.append((start, end))
                else:
                    missing_time = True
        elapsed, until = 0, 0
        for start, end in sorted(intervals):
            elapsed += max(0, end - max(start, until))
            until = max(until, end)
        def total(column):
            values = [rows[k][column] for k in selected]
            return sum(values) if all(v is not None for v in values) else None
        return dict(sessions=len(selected), input=total('tokens_input'), output=total('tokens_output'),
                    cost=total('cost'), seconds=elapsed / 1000 if intervals and not missing_time else None)
