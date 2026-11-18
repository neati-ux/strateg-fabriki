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
