"""Persistent research questions and read-only lookup in the methodology."""
import http.client
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse

import strateg as S
from workflow import local_write, read_json, safe_path

EQUIVALENTS = (
    ('удержание', 'отток', 'retention', 'churn', 'cohort', 'когорта'),
    ('воронка', 'funnel', 'conversion', 'конверсия'),
    ('источник', 'provenance', 'evidence', 'доказательство', 'доказательность'),
    ('цена', 'маржа', 'economics', 'экономика', 'cac', 'ltv'),
    ('интервью', 'research', 'discovery', 'исследование'),
)


def words(text):
    return set(re.findall(r'[^\W_]{3,}', text.casefold().replace('ё', 'е')))


def knowledge(query, limit):
    terms = words(query)
    expanded = terms | {term for group in EQUIVALENTS if terms.intersection(group) for term in group}
    if not terms:
        raise ValueError('Добавь хотя бы одно слово для поиска')
    root = S.ROOT / 'knowledge'
    index = root / 'INDEX.md'
    summaries = {}
    if index.is_file():
        for row in index.read_text(encoding='utf-8').splitlines():
            match = re.match(r'^\| `([^`]+\.md)` \| (.*?) \|', row)
            if match:
                summaries[match[1]] = match[2]
    results = []
    for path in sorted(root.glob('*.md')):
        if path == index or path.is_symlink():
            continue
        lines = path.read_text(encoding='utf-8').splitlines()
        scored = [(3 * len(terms & words(line)) + len((expanded - terms) & words(line)), i, line.strip())
                  for i, line in enumerate(lines, 1)]
        score, number, snippet = max(scored, default=(0, 0, ''), key=lambda x: (x[0], -x[1]))
        score += 2 * len(expanded & words(path.stem + ' ' + summaries.get(path.name, '')))
        if score:
            results.append({'score': score, 'path': 'knowledge/' + path.name, 'line': number or 1,
                            'snippet': snippet[:300], 'summary': summaries.get(path.name)})
    return sorted(results, key=lambda row: (-row['score'], row['path']))[:limit]


def discover(query, limit):
    key = os.environ.get('BRAVE_SEARCH_API_KEY')
    if not key:
        raise ValueError('Используй поиск текущей среды либо настрой BRAVE_SEARCH_API_KEY')
    if not query.strip() or len(query) > 400:
        raise ValueError('Нужен поисковый запрос до 400 знаков')
    http = http.client.HTTPSConnection('api.search.brave.com', timeout=20)
    try:
        http.request('GET', '/res/v1/web/search?' + urllib.parse.urlencode({'q': query, 'count': limit}),
                     headers={'X-Subscription-Token': key, 'Accept': 'application/json'})
        response = http.getresponse()
        if response.status != 200:
            raise ValueError(f'Поиск отклонён: HTTP {response.status}')
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('Ответ поиска превышает 1 MiB')
        candidates = []
        for row in json.loads(body).get('web', {}).get('results', [])[:limit]:
            if isinstance(row.get('url'), str) and row['url'].startswith(('https://', 'http://')):
                candidates.append({k: row.get(k, '') for k in ('title', 'url', 'description')})
        return candidates
    finally:
        http.close()


def trace(project, claim_id, live=False, compare=None):
    from extra import locate_lines, numbers
    from fetch_page import fetch
    from extra import source_text

    sources, claims = S.load(project)
    claim = next((row for row in claims if row['id'] == claim_id), None)
    if not claim or claim['тип'] != 'факт' or claim['статус'] != 'активно':
        raise ValueError('Нужен действующий факт из реестра')
    source = next((row for row in sources if row['id'] == claim['источник']), None)
    if not source:
        raise ValueError('Источник отсутствует в реестре')
    external = source['адрес'].startswith(('https://', 'http://'))
    if external:
        body, snapshot = source_text(project, source, run=False)
    else:
        original = safe_path(project, source['адрес'])
        from ingest import extract
        body, _ = extract(original)
        snapshot = source['адрес']
        if live or compare:
            raise ValueError('Локальный оригинал уже прочитан напрямую')
    if body is None:
        raise ValueError(snapshot)
    where = claim['где_в_источнике']
    quote = locate_lines(body, where)
    if not quote or not quote.strip() or len(quote) > 1500:
        raise ValueError('Найдите точные строки командой locate, до 1500 знаков')
    statement = claim['утверждение']
    for quoted in re.findall(r'«([^»]+)»|"([^"]+)"', statement):
        fragment = next(piece for piece in quoted if piece)
        if ' '.join(fragment.split()) not in ' '.join(quote.split()):
            raise ValueError('Цитата утверждения отсутствует в указанных строках')
    values = numbers(statement)
    if not values and ' '.join(statement.split()) not in ' '.join(quote.split()):
        raise ValueError('Для дословной цитаты текст утверждения должен совпадать с источником')
    if not values.issubset(numbers(quote)):
        raise ValueError('Не все числа утверждения найдены в указанных строках')
    result = dict(claim=claim_id, statement=statement, source=source['id'],
                  title=source['название'], url=source['адрес'], location=where,
                  snapshot=snapshot, quote=quote, accessed=source['дата_обращения'],
                  verification='snapshot_excerpt' if external else 'original_file_excerpt')
    if live or compare:
        if live:
            published, raw, final_url, _ = fetch(source['адрес'])
            result.update(verification='live_quote', final_url=final_url)
        else:
            raw = Path(compare).read_bytes()
            published = raw.decode('utf-8-sig')
            result.update(verification='second_text_copy', compared_file=Path(compare).name)
        if ' '.join(quote.split()) not in ' '.join(published.split()):
            raise ValueError('Цитата отсутствует в повторно прочитанном документе')
        result['compared_sha256'] = hashlib.sha256(raw).hexdigest()
    return result


def command(a):
    try:
        if a.research_action == 'knowledge':
            result = knowledge(a.query, a.limit)
        elif a.research_action == 'trace':
            result = trace(S.project_dir(a.project), a.id, a.live, a.compare)
        elif a.research_action == 'discover':
            result = {'candidates': discover(a.query, a.limit), 'note': 'Кандидаты. Для доказательства сохранить через collect и сверить содержание.'}
        else:
            project = S.project_dir(a.project)
            path = safe_path(project, 'research-plan.json')
            rows = read_json(path, [])
            if a.research_action == 'add':
                if not a.question.strip() or not a.decision.strip():
                    raise ValueError('Нужны вопрос и решение, которое он меняет')
                if any(row['question'].casefold() == a.question.strip().casefold() for row in rows):
                    raise ValueError('Вопрос уже есть в плане')
                row = {'id': f'Q-{len(rows) + 1:03d}', 'question': a.question.strip(), 'decision': a.decision.strip(),
                       'queries': list(dict.fromkeys(a.query)), 'status': 'open', 'refs': []}
                rows.append(row)
                result = row
            elif a.research_action == 'close':
                row = next((x for x in rows if x['id'] == a.id), None)
                if row is None:
                    raise ValueError('Вопрос не найден')
                sources, claims = S.load(project)
                by_claim = {c['id']: c for c in claims if c['статус'] == 'активно'}
                if not a.note.strip():
                    raise ValueError('Укажи, как ответ влияет на решение или почему остался пробел')
                refs = list(dict.fromkeys(a.ref))
                kinds = {by_claim[i]['тип'] for i in refs if i in by_claim}
                if a.status == 'answered' and (any(i not in by_claim for i in refs) or not kinds.intersection({'факт', 'вывод', 'прогноз'})):
                    raise ValueError('Для ответа нужны действующие утверждения из реестра')
                if a.status == 'gap' and (not refs or any(i not in by_claim or by_claim[i]['тип'] != 'пробел' for i in refs)):
                    raise ValueError('Для пробела нужны действующие записи типа пробел из реестра')
                row.update(status=a.status, refs=refs, note=a.note.strip())
                result = row
            else:
                _, claims = S.load(project)
                active = {c['id'] for c in claims if c['статус'] == 'активно'}
                result = [{**row, 'needs_review': sorted(set(row['refs']) - active)} for row in rows]
            if a.research_action != 'list':
                local_write(path, json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as exc:
        raise SystemExit(f'Исследование: {exc}') from None


def register(sub):
    actions = sub.add_parser('research', help='вопросы к решению и поиск оснований').add_subparsers(dest='research_action', required=True)
    actions.add_parser('list').set_defaults(fn=command)
    p = actions.add_parser('trace', help='показать исходную строку числового факта и URL публикации')
    p.add_argument('id')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='повторно открыть URL и проверить цитату')
    mode.add_argument('--compare', metavar='TEXT', help='сверить с отдельно полученной текстовой копией')
    p.set_defaults(fn=command)
    for name in ('knowledge', 'discover'):
        p = actions.add_parser(name)
        p.add_argument('query')
        p.add_argument('--limit', type=int, choices=range(1, 11), default=5)
        p.set_defaults(fn=command)
    p = actions.add_parser('add')
    p.add_argument('question')
    p.add_argument('--decision', required=True)
    p.add_argument('--query', action='append', default=[])
    p.set_defaults(fn=command)
    p = actions.add_parser('close')
    p.add_argument('id')
    p.add_argument('--status', choices=('answered', 'gap'), required=True)
    p.add_argument('--ref', action='append', default=[])
    p.add_argument('--note', required=True)
    p.set_defaults(fn=command)
