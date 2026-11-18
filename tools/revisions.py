"""Mark source/claim revisions without rewriting past decisions."""
import json
from collections import defaultdict

import strateg as S
from workflow import local_write, read_json, safe_path


def changed_claims(claims, start):
    affected = set(start) | S.dependents(claims, start)
    for claim in claims:
        if claim['id'] in affected and claim['статус'] == 'активно':
            claim['статус'] = 'на пересмотре'
    return affected


def revise(project, before, after, reason):
    sources, claims = S.load(project)
    if not reason.strip():
        raise ValueError('Укажи, что изменилось и почему это важно')
    if after:
        if not before.startswith('S-') or not after.startswith('S-') or before == after:
            raise ValueError('Замена связывает два разных источника S-…')
        S.start_ids(claims, sources, after)
    start = S.start_ids(claims, sources, before)
    path = safe_path(project, 'revisions.json')
    history = read_json(path, [])
    if after:
        old_links = {item['before']: item['after'] for item in history if item.get('after')}
        if before in old_links:
            raise ValueError('У источника уже записана следующая версия. Используй последний источник цепочки.')
        cursor = after
        seen = {before}
        while cursor:
            if cursor in seen:
                raise ValueError('Версии источника образуют цикл')
            seen.add(cursor)
            cursor = old_links.get(cursor)
    affected = changed_claims(claims, start)
    documents = {name: refs for name, refs in S.files_mentioning(project, affected)}
    record = {'before': before, 'after': after, 'reason': reason.strip(), 'date': S.today(),
              'direct': sorted(start), 'claims': sorted(affected), 'documents': documents}
    if affected:
        S.write_csv(safe_path(project, 'claims.csv'), S.CLAIM_FIELDS, claims)
    history.append(record)
    local_write(path, json.dumps(history, ensure_ascii=False, indent=2) + '\n')
    return record


def command(a):
    project = S.project_dir(a.project)
    try:
        print(json.dumps(revise(project, a.target, a.superseded_by, a.reason), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Пересмотр не записан: {exc}') from None


def evidence_priority(project):
    """Rank sources and assumptions by their reach into current deliverables."""
    sources, claims = S.load(project)
    active = {c['id']: c for c in claims if c['статус'] == 'активно'}
    mentions = dict(S.files_mentioning(project, active))
    parents = {cid: set(S.split_ids(c['зависит_от'])) & active.keys()
               for cid, c in active.items()}
    source_names = {s['id']: s['название'] for s in sources}
    affected = defaultdict(lambda: defaultdict(set))
    for document, refs in mentions.items():
        for ref in refs:
            seen, stack = set(), [ref]
            while stack:
                cid = stack.pop()
                if cid in seen:
                    continue
                seen.add(cid)
                c = active[cid]
                if c['источник'] in source_names:
                    affected[c['источник']][document].add(ref)
                if c['тип'] in {'гипотеза', 'допущение', 'синтетика', 'пробел', 'прогноз'}:
                    affected[cid][document].add(ref)
                stack.extend(parents[cid] - seen)
    rows = []
    for basis, docs in affected.items():
        refs = set.union(*docs.values())
        rows.append(dict(id=basis, title=source_names.get(basis) or active.get(basis, {}).get('утверждение'),
                         kind='источник' if basis in source_names else active[basis]['тип'],
                         documents=len(docs), claims=len(refs),
                         references={k: sorted(v) for k, v in docs.items()}))
    return sorted(rows, key=lambda r: (-r['documents'], -r['claims'], r['id']))


def priority_command(a):
    rows = evidence_priority(S.project_dir(a.project))
    selected = rows[:a.limit]
    if not a.details:
        for row in selected:
            del row['references']
    print(json.dumps({'total': len(rows), 'priorities': selected}, ensure_ascii=False, indent=2))


def register(sub):
    p = sub.add_parser('evidence-priority', help='какие основания проверить первыми по охвату документов')
    p.add_argument('--limit', type=int, choices=range(1, 101), metavar='1..100', default=5)
    p.add_argument('--details', action='store_true', help='показать документы и номера утверждений')
    p.set_defaults(fn=priority_command)
    p = sub.add_parser('revise', help='связать версии источника и пометить зависимые выводы')
    p.add_argument('target')
    p.add_argument('--superseded-by')
    p.add_argument('--reason', required=True)
    p.set_defaults(fn=command)
