#!/usr/bin/env python3
"""Команды Стратега: проекты, реестр утверждений, проверки, пересмотр, расходы.

Только стандартная библиотека Python 3.9+. Запуск из корня репозитория:
    python3 tools/strateg.py <команда> [параметры]
"""
import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
ACTIVE = PROJECTS / ".active"
TEMPLATE = ROOT / "templates" / "project"

TYPES = ["факт", "гипотеза", "допущение", "прогноз", "вывод", "синтетика", "пробел"]
STATUSES = ["активно", "на пересмотре", "отозвано"]
KINDS = ["документ", "таблица", "сайт", "интервью", "модельное интервью",
         "скриншот", "расчёт", "слова руководителя", "ответ агента"]
# Источники, которые не могут подтверждать факт.
AGENT_KINDS = {"модельное интервью", "ответ агента"}

CLAIM_FIELDS = ["id", "утверждение", "тип", "источник", "где_в_источнике",
                "зависит_от", "статус", "дата", "примечание"]
SOURCE_FIELDS = ["id", "название", "адрес", "вид", "дата_обращения", "примечание"]


def die(msg):
    print("Ошибка: " + msg, file=sys.stderr)
    sys.exit(1)


def today():
    return dt.date.today().isoformat()


def read_csv(path, fields):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{k: (r.get(k) or "").strip() for k in fields} for r in rows]


def write_csv(path, fields, rows):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def project_dir(name=None):
    if not name:
        if not ACTIVE.exists():
            die("нет активного проекта. Создай: python3 tools/strateg.py new <имя>")
        name = ACTIVE.read_text(encoding="utf-8").strip()
    p = PROJECTS / name
    if p.resolve().parent != PROJECTS.resolve() or not p.is_dir():
        die(f"проект «{name}» не найден в projects/")
    return p


def load(proj):
    return (read_csv(proj / "materials" / "sources.csv", SOURCE_FIELDS),
            read_csv(proj / "claims.csv", CLAIM_FIELDS))


def find_refs(path):
    """Номера утверждений, упомянутые в тексте. Комментарии <!-- --> не считаются."""
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    return set(re.findall(r"C-\d{3,}", text))


def split_ids(s):
    return [x for x in re.split(r"[;,\s]+", s or "") if x]


def next_id(rows, prefix):
    nums = [int(m.group(1)) for r in rows
            if (m := re.fullmatch(prefix + r"-(\d+)", r["id"]))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


# ---------- проверки ----------

def check_data(sources, claims):
    """Возвращает (ошибки, предупреждения) как списки пар (id, текст)."""
    errs, warns = [], []
    sid, cid = {}, {}
    for s in sources:
        i = s["id"]
        if not re.fullmatch(r"S-\d{3,}", i):
            errs.append((i, "номер источника должен быть вида S-001"))
        if i in sid:
            errs.append((i, "номер источника повторяется"))
        sid[i] = s
        if not s["адрес"]:
            errs.append((i, "у источника нет адреса (ссылки или пути к файлу)"))
        if s["вид"] not in KINDS:
            errs.append((i, f"вид источника «{s['вид']}» не из списка: {', '.join(KINDS)}"))
    for c in claims:
        i = c["id"]
        if not re.fullmatch(r"C-\d{3,}", i):
            errs.append((i, "номер утверждения должен быть вида C-001"))
        if i in cid:
            errs.append((i, "номер утверждения повторяется"))
        cid[i] = c

    for c in claims:
        i, t, src = c["id"], c["тип"], c["источник"]
        deps = split_ids(c["зависит_от"])
        kind = sid.get(src, {}).get("вид")
        if not c["утверждение"]:
            errs.append((i, "пустой текст утверждения"))
        if t not in TYPES:
            errs.append((i, f"тип «{t}» не из списка: {', '.join(TYPES)}"))
        if c["статус"] not in STATUSES:
            errs.append((i, f"статус «{c['статус']}» не из списка: {', '.join(STATUSES)}"))
        if src and src not in sid:
            errs.append((i, f"источник {src} не зарегистрирован в sources.csv"))
        for d in deps:
            if d == i:
                errs.append((i, "утверждение зависит от самого себя"))
            elif d not in cid:
                errs.append((i, f"зависит от {d}, которого нет в реестре"))
        if t == "факт":
            if not src:
                errs.append((i, "факт без источника"))
            elif kind in AGENT_KINDS:
                errs.append((i, f"факт не может опираться на источник вида «{kind}»: "
                                "это не доказательство"))
            if not c["где_в_источнике"]:
                errs.append((i, "у факта не указано место в источнике (страница, раздел, ячейка, цитата)"))
            if deps:
                errs.append((i, "у факта не бывает зависимостей: рассуждение или расчёт "
                                "из других утверждений — это «вывод»"))
        if t == "синтетика" and kind != "модельное интервью":
            errs.append((i, "синтетика должна ссылаться на источник вида «модельное интервью»"))
        if kind == "модельное интервью" and t not in ("синтетика", "гипотеза"):
            errs.append((i, "из модельного интервью можно получить только «синтетику» или «гипотезу»"))
        if t in ("вывод", "прогноз") and not deps:
            errs.append((i, f"{t} без оснований: укажи в «зависит_от», из каких утверждений он следует"))
        if t == "допущение" and not c["примечание"]:
            errs.append((i, "у допущения не указано в примечании, почему оно принято и кто может его подтвердить"))
        if t == "пробел" and not c["примечание"]:
            errs.append((i, "у пробела не указано в примечании, почему это не удалось узнать"))
        if c["статус"] == "активно":
            for d in deps:
                st = cid.get(d, {}).get("статус")
                if st == "отозвано":
                    errs.append((i, f"активное утверждение опирается на отозванное {d}"))
                elif st == "на пересмотре":
                    warns.append((i, f"опирается на {d}, которое на пересмотре"))

    # циклы
    color = {}
    def visit(start):
        stack = [(start, iter(split_ids(cid[start]["зависит_от"])))]
        color[start] = 1
        while stack:
            node, it = stack[-1]
            for d in it:
                if d not in cid:
                    continue
                if color.get(d) == 1:
                    errs.append((node, f"круговая зависимость через {d}"))
                elif d not in color:
                    color[d] = 1
                    stack.append((d, iter(split_ids(cid[d]["зависит_от"]))))
                    break
            else:
                color[node] = 2
                stack.pop()
    for i in cid:
        if i not in color:
            visit(i)

    # вывод или прогноз, под которым нет ни одного факта
    def bases(i, seen):
        for d in split_ids(cid[i]["зависит_от"]):
            if d in cid and d not in seen:
                seen.add(d)
                bases(d, seen)
        return seen
    if not any("круговая" in m for _, m in errs):
        for c in claims:
            if c["тип"] in ("вывод", "прогноз") and c["статус"] == "активно":
                b = bases(c["id"], set())
                if b and not any(cid[x]["тип"] == "факт" for x in b):
                    warns.append((c["id"], f"{c['тип']} не опирается ни на один факт: "
                                           "только гипотезы, синтетика или другие выводы"))
    return errs, warns


def check_texts(proj, claims):
    errs, warns = [], []
    cid = {c["id"]: c for c in claims}
    files = sorted((proj / "outputs").glob("*.md")) if (proj / "outputs").is_dir() else []
    for f in files:
        refs = find_refs(f)
        name = f"outputs/{f.name}"
        if not refs:
            warns.append((name, "в тексте нет ни одной ссылки на реестр вида [C-001]"))
        for r in sorted(refs):
            if r not in cid:
                errs.append((name, f"ссылка на {r}, которого нет в реестре"))
            elif cid[r]["статус"] == "отозвано":
                errs.append((name, f"текст опирается на отозванное {r}"))
            elif cid[r]["статус"] == "на пересмотре":
                warns.append((name, f"текст опирается на {r}, которое на пересмотре"))
    d = proj / "decisions.md"
    if d.exists():
        for r in sorted(find_refs(d)):
            st = cid.get(r, {}).get("статус")
            if st is None:
                errs.append(("decisions.md", f"ссылка на {r}, которого нет в реестре"))
            elif st in ("отозвано", "на пересмотре"):
                warns.append(("decisions.md", f"решение опирается на {r} со статусом «{st}»: "
                                              "пора пересмотреть"))
    return errs, warns


def run_check(proj):
    sources, claims = load(proj)
    e1, w1 = check_data(sources, claims)
    e2, w2 = check_texts(proj, claims)
    import extra
    import helpers
    revision_path = proj / 'revisions.json'
    stale = set()
    if revision_path.is_file():
        history = json.loads(revision_path.read_text(encoding='utf-8'))
        stale = {item['before'] for item in history if item.get('after')}
    obsolete = [(claim['id'], f"основание {claim['источник']} заменено; укажи версию источника")
                for claim in claims if claim['источник'] in stale and claim['статус'] == 'активно']
    return (e1 + e2 + obsolete + extra.gate_problems(proj, claims),
            w1 + w2 + helpers.problems(proj))


# ---------- зависимости ----------

def dependents(claims, start):
    rev = defaultdict(set)
    for c in claims:
        for d in split_ids(c["зависит_от"]):
            rev[d].add(c["id"])
    seen, stack = set(), list(start)
    while stack:
        x = stack.pop()
        for y in rev[x]:
            if y not in seen and y not in start:
                seen.add(y)
                stack.append(y)
    return seen


def start_ids(claims, sources, ident):
    if ident.startswith("S-"):
        if ident not in {s["id"] for s in sources}:
            die(f"источник {ident} не найден")
        return [c["id"] for c in claims if c["источник"] == ident]
    if ident not in {c["id"] for c in claims}:
        die(f"утверждение {ident} не найдено")
    return [ident]


def files_mentioning(proj, ids):
    out = []
    paths = sorted((proj / "outputs").glob("*.md")) + [proj / "decisions.md"]
    for f in paths:
        if not f.exists():
            continue
        found = sorted(find_refs(f) & set(ids))
        if found:
            out.append((f.relative_to(proj).as_posix(), found))
    return out


def print_impact(proj, claims, start, dep):
    cid = {c["id"]: c for c in claims}
    def line(i):
        c = cid[i]
        return f"  {i} [{c['тип']}, {c['статус']}] {c['утверждение']}"
    print("Затронуто напрямую:")
    print("\n".join(line(i) for i in sorted(start)) or "  ничего")
    print("Зависит от них:")
    print("\n".join(line(i) for i in sorted(dep)) or "  ничего")
    files = files_mentioning(proj, set(start) | dep)
    print("Тексты, которые нужно обновить:")
    print("\n".join(f"  {n}: {', '.join(r)}" for n, r in files) or "  нет")


# ---------- команды ----------

def cmd_new(a):
    if not re.fullmatch(r"[\w\-]+", a.name):
        die("имя проекта: только буквы, цифры, дефис и подчёркивание")
    dst = PROJECTS / a.name
    if dst.exists():
        die(f"проект «{a.name}» уже есть. Переключиться: python3 tools/strateg.py use {a.name}")
    shutil.copytree(TEMPLATE, dst)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for f in dst.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        f.write_text(t.replace("{{имя}}", a.name).replace("{{дата}}", now), encoding="utf-8")
    ACTIVE.write_text(a.name + "\n", encoding="utf-8")
    print(f"Создан проект projects/{a.name}/ и сделан активным. Дальше: шаг 1, skills/1-zadacha.md")


def cmd_use(a):
    project_dir(a.name)
    ACTIVE.write_text(a.name + "\n", encoding="utf-8")
    print(f"Активный проект: {a.name}")


def section(text, title):
    m = re.search(r"^## " + re.escape(title) + r"\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def cmd_status(a):
    proj = project_dir(a.project)
    print(f"Проект: {proj.name}")
    st = proj / "state.md"
    if st.exists():
        text = st.read_text(encoding="utf-8")
        for t in ("Текущий шаг", "Следующее действие", "Открытые вопросы к руководителю"):
            s = section(text, t)
            if s:
                print(f"\n{t}:\n{s}")
    sources, claims = load(proj)
    by = defaultdict(int)
    for c in claims:
        by[(c["тип"], c["статус"])] += 1
    print(f"\nИсточников: {len(sources)}. Утверждений: {len(claims)}.")
    for (t, s), n in sorted(by.items()):
        print(f"  {t}, {s}: {n}")


def cmd_source_add(a):
    proj = project_dir(a.project)
    path = proj / "materials" / "sources.csv"
    rows = read_csv(path, SOURCE_FIELDS)
    for r in rows:
        if r["адрес"] == a.url:
            print(r["id"])
            print("этот адрес уже зарегистрирован, номер прежний", file=sys.stderr)
            return
    row = {"id": next_id(rows, "S"), "название": a.title, "адрес": a.url, "вид": a.kind,
           "дата_обращения": today(), "примечание": a.note or ""}
    rows.append(row)
    write_csv(path, SOURCE_FIELDS, rows)
    print(row["id"])


def validate_row(sources, claims, ident):
    errs, _ = check_data(sources, claims)
    mine = [m for i, m in errs if i == ident]
    if mine:
        die(f"{ident} не записано:\n  - " + "\n  - ".join(mine))


def cmd_claim_add(a):
    proj = project_dir(a.project)
    sources, claims = load(proj)
    row = {"id": next_id(claims, "C"), "утверждение": a.text.strip(), "тип": a.type,
           "источник": a.source or "", "где_в_источнике": a.where or "",
           "зависит_от": ";".join(split_ids(a.depends)), "статус": "активно",
           "дата": today(), "примечание": a.note or ""}
    claims.append(row)
    validate_row(sources, claims, row["id"])
    write_csv(proj / "claims.csv", CLAIM_FIELDS, claims)
    print(row["id"])


def read_batch(path):
    """Файл с пачкой записей: JSON-массив или по одному JSON-объекту в строке."""
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    try:
        items = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
    except ValueError as e:
        die(f"файл {path} не читается как JSON: {e}")
    if not items or not all(isinstance(x, dict) for x in items):
        die("в файле нет записей или запись не является объектом")
    return items


def cmd_source_add_many(a):
    proj = project_dir(a.project)
    path = proj / "materials" / "sources.csv"
    rows = read_csv(path, SOURCE_FIELDS)
    by_url = {r["адрес"]: r["id"] for r in rows}
    out = []
    for n, it in enumerate(read_batch(a.file), 1):
        url, kind = str(it.get("url") or "").strip(), str(it.get("kind") or "").strip()
        if not url or not it.get("title") or kind not in KINDS:
            die(f"запись {n}: нужны title, url и kind из списка: {', '.join(KINDS)}. Ничего не записано.")
        if url not in by_url:
            row = {"id": next_id(rows, "S"), "название": str(it["title"]).strip(), "адрес": url, "вид": kind,
                   "дата_обращения": today(), "примечание": str(it.get("note") or "").strip()}
            rows.append(row)
            by_url[url] = row["id"]
        out.append(f"{it.get('key') or n}: {by_url[url]}")
    write_csv(path, SOURCE_FIELDS, rows)
    print("\n".join(out))


def cmd_claim_add_many(a):
    """Добавляет пачку утверждений за один вызов: либо все, либо ни одного."""
    proj = project_dir(a.project)
    sources, claims = load(proj)
    items = read_batch(a.file)
    keys, new = {}, []
    for n, it in enumerate(items, 1):
        row = {"id": next_id(claims + new, "C"), "утверждение": str(it.get("text") or "").strip(),
               "тип": str(it.get("type") or "").strip(), "источник": str(it.get("source") or "").strip(),
               "где_в_источнике": str(it.get("where") or "").strip(), "зависит_от": str(it.get("depends") or ""),
               "статус": "активно", "дата": today(), "примечание": str(it.get("note") or "").strip()}
        new.append(row)
        keys[str(it.get("key") or n)] = row["id"]
    for row in new:   # в depends можно ссылаться на записи той же пачки по их key
        row["зависит_от"] = ";".join(keys.get(d, d) for d in split_ids(row["зависит_от"]))
    errs, _ = check_data(sources, claims + new)
    ids = {r["id"] for r in new}
    back = {v: k for k, v in keys.items()}
    mine = [f"запись {back[i]}: {m}" for i, m in errs if i in ids]
    if mine:
        die("пачка не записана, исправь и повтори целиком:\n  - " + "\n  - ".join(mine))
    write_csv(proj / "claims.csv", CLAIM_FIELDS, claims + new)
    print("\n".join(f"{k}: {v}" for k, v in keys.items()))


def cmd_claim_edit(a):
    proj = project_dir(a.project)
    sources, claims = load(proj)
    row = next((c for c in claims if c["id"] == a.id), None)
    if not row:
        die(f"утверждение {a.id} не найдено")
    before = dict(row)
    for key, val in (("утверждение", a.text), ("тип", a.type), ("источник", a.source),
                     ("где_в_источнике", a.where), ("статус", a.status), ("примечание", a.note)):
        if val is not None:
            row[key] = val.strip()
    if a.depends is not None:
        row["зависит_от"] = ";".join(split_ids(a.depends))
    relevant = ("утверждение", "тип", "источник", "где_в_источнике", "зависит_от", "статус")
    affected = set()
    if any(before[key] != row[key] for key in relevant):
        affected = dependents(claims, [a.id])
        for item in claims:
            if item['id'] in affected and item['статус'] == 'активно':
                item['статус'] = 'на пересмотре'
    validate_row(sources, claims, a.id)
    write_csv(proj / "claims.csv", CLAIM_FIELDS, claims)
    if affected:
        print("Зависимые утверждения требуют пересмотра: " + ", ".join(sorted(affected)))
    print(f"{a.id} изменено. Проверь, что зависит от него: python3 tools/strateg.py impact {a.id}")


def cmd_check(a):
    proj = project_dir(a.project)
    errs, warns = run_check(proj)
    for i, m in errs:
        print(f"ОШИБКА  {i}: {m}")
    for i, m in warns:
        print(f"ВНИМАНИЕ  {i}: {m}")
    print(f"\nОшибок: {len(errs)}. Предупреждений: {len(warns)}.")
    sys.exit(1 if errs else 0)


def cmd_impact(a):
    proj = project_dir(a.project)
    sources, claims = load(proj)
    start = start_ids(claims, sources, a.id)
    print_impact(proj, claims, start, dependents(claims, start))


def cmd_revoke(a):
    proj = project_dir(a.project)
    sources, claims = load(proj)
    start = start_ids(claims, sources, a.id)
    dep = dependents(claims, start)
    for c in claims:
        if c["id"] in start:
            c["статус"] = "отозвано"
            c["примечание"] = (c["примечание"] + " | " if c["примечание"] else "") + \
                f"отозвано {today()}: {a.reason}"
        elif c["id"] in dep and c["статус"] == "активно":
            c["статус"] = "на пересмотре"
    write_csv(proj / "claims.csv", CLAIM_FIELDS, claims)
    print_impact(proj, claims, start, dep)
    print("\nОтозванное помечено, зависимое переведено в статус «на пересмотре». "
          "Обнови каждое зависимое утверждение (claim edit --status активно после проверки) и тексты.")


# ---------- расход из журналов Кодекса ----------

SECRET = re.compile(r"(?i)(key|token|secret|password|passwd|authorization)(\s*[=:]\s*)\S+")
CODEX_TOOL_ITEMS = {"function_call", "custom_tool_call", "local_shell_call", "web_search_call"}


def parse_ts(s):
    d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo:
        d = d.astimezone().replace(tzinfo=None)
    return d


def codex_sessions_dir():
    """Папка журналов Кодекса или None, если домашнюю папку определить нельзя."""
    import os
    if os.environ.get("CODEX_HOME"):
        return Path(os.environ["CODEX_HOME"]) / "sessions"
    try:
        return Path.home() / ".codex" / "sessions"
    except (RuntimeError, KeyError, OSError):
        return None


def project_started(proj):
    lm = proj / "log.md"
    if lm.exists():
        m = re.search(r"Начат:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", lm.read_text(encoding="utf-8"))
        if m:
            return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
    return None


def read_codex_rollout(path):
    """Читает один файл сеанса Кодекса: токены по моделям, действия, время."""
    sid, cwd, model = path.stem, None, "codex-model-unknown"
    keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    prev = dict.fromkeys(keys, 0)
    usage, events = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict) or not isinstance(obj.get("payload"), dict):
                continue
            typ, pl = obj.get("type"), obj["payload"]
            try:
                ts = parse_ts(obj["timestamp"]) if obj.get("timestamp") else None
            except ValueError:
                ts = None
            if typ == "session_meta":
                sid, cwd = pl.get("id") or sid, pl.get("cwd") or cwd
            elif typ == "turn_context":
                model, cwd = pl.get("model") or model, cwd or pl.get("cwd")
            elif typ == "event_msg" and pl.get("type") == "token_count":
                tot = (pl.get("info") or {}).get("total_token_usage")
                if not isinstance(tot, dict):
                    continue
                d = {}
                for k in keys:
                    c = tot.get(k) or 0
                    d[k] = c - prev[k] if c >= prev[k] else c  # счётчик накопительный
                    prev[k] = c
                if any(d.values()):
                    u = usage.setdefault(model, {"input": 0, "output": 0,
                                                 "cache_read": 0, "cache_write": 0})
                    cached = min(d["cached_input_tokens"], d["input_tokens"])
                    u["input"] += d["input_tokens"] - cached
                    u["cache_read"] += cached
                    u["output"] += d["output_tokens"]
                    if ts:
                        events.append({"ts": ts, "event": "codex-turn"})
            elif typ == "response_item" and pl.get("type") in CODEX_TOOL_ITEMS and ts:
                target = ""
                try:
                    args = json.loads(pl.get("arguments") or "{}")
                    cmd = args.get("command") if isinstance(args, dict) else None
                    target = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
                except (ValueError, TypeError):
                    pass
                events.append({"ts": ts, "event": "codex", "tool": pl.get("name") or pl["type"],
                               "target": SECRET.sub(r"\1\2***", target)[:160]})
    return "codex:" + sid, cwd, usage, events


def import_codex(proj, src=None):
    """Подтягивает токены и действия из сеансов Кодекса, запущенных в этой папке.

    Повторный запуск ничего не удваивает: данные сеанса перезаписываются.
    """
    base = Path(src) if src else codex_sessions_dir()
    if base is None:
        return 0
    if base.is_file():
        files = [base]
    elif base.is_dir():
        files = sorted(base.rglob("rollout-*.jsonl"))
    else:
        return 0
    root, started = ROOT.resolve(), project_started(proj)
    found = {}
    for f in files:
        try:
            sid, cwd, usage, events = read_codex_rollout(f)
        except OSError:
            continue
        if not src:
            try:
                p = Path(cwd).resolve() if cwd else None
            except (OSError, ValueError):
                p = None
            if not p or (p != root and root not in p.parents):
                continue
            if started and events and max(e["ts"] for e in events) < started:
                continue
        if usage or events:
            found[sid] = (usage, events)
    if not found:
        return 0
    up = proj / "usage.json"
    all_usage = json.loads(up.read_text(encoding="utf-8")) if up.exists() else {}
    lp = proj / "log.jsonl"
    keep = []
    if lp.exists():
        for line in lp.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("session") in found:
                    continue
            except (ValueError, AttributeError):
                pass
            keep.append(line)
    for sid, (usage, events) in found.items():
        all_usage[sid] = usage
        for e in events:
            e["ts"] = e["ts"].isoformat(timespec="seconds")
            e["session"] = sid
            keep.append(json.dumps(e, ensure_ascii=False))
    up.write_text(json.dumps(all_usage, ensure_ascii=False, indent=1), encoding="utf-8")
    lp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return len(found)


def cmd_import_usage(a):
    proj = project_dir(a.project)
    n = import_codex(proj, a.path)
    if n:
        print(f"Подтянуто сеансов Кодекса: {n}. Итог: python3 tools/strateg.py cost")
    else:
        where = a.path or codex_sessions_dir() or "домашней папке (её не удалось определить, задай CODEX_HOME)"
        print(f"Сеансов Кодекса для этой папки не найдено в {where}. "
              "Укажи файл сеанса явно: import-usage --path <файл rollout-….jsonl>")


def price_for(model, table):
    hits = [k for k in table if k in model]
    return table[max(hits, key=len)] if hits else None


def priced(u, price):
    keys = ("input", "output", "cache_read", "cache_write")
    if price and all(isinstance(price.get(k), (int, float)) for k in keys):
        return sum(u[k] * price[k] for k in keys) / 1_000_000
    return None


def budget_limit(proj, prices):
    p = proj / "budget.json"
    if p.exists():
        try:
            return float(json.loads(p.read_text(encoding="utf-8")).get("лимит") or 0)
        except (ValueError, TypeError):
            return 0
    return float(prices.get("бюджет_по_умолчанию") or 0)


def cmd_budget(a):
    proj = project_dir(a.project)
    if a.set is not None:
        (proj / "budget.json").write_text(json.dumps({"лимит": a.set}, ensure_ascii=False), encoding="utf-8")
        print(f"Бюджет проекта: {a.set:.2f}. Расход: python3 tools/strateg.py cost")
    else:
        pp = ROOT / "routing" / "prices.json"
        prices = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
        print(f"Бюджет проекта: {budget_limit(proj, prices):.2f} {prices.get('валюта', '')}")


def cmd_cost(a):
    proj = project_dir(a.project)
    print(f"## Время и расходы: {proj.name}\n")
    if not a.no_codex:
        n = import_codex(proj)
        if n:
            print(f"- Подтянуто из журналов Кодекса сеансов: {n}")
    events = []
    lp = proj / "log.jsonl"
    if lp.exists():
        for line in lp.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    if events:
        ts = sorted(parse_ts(e["ts"]) for e in events if e.get("ts"))
        active = sum((b - a_).total_seconds() for a_, b in zip(ts, ts[1:])
                     if (b - a_).total_seconds() < 300)
        tools = defaultdict(int)
        for e in events:
            if e.get("tool"):
                tools[e["tool"]] += 1
        fails = sum(1 for e in events if e.get("ok") is False)
        sessions = len({e.get("session") for e in events})
        print(f"- Сеансов: {sessions}")
        print(f"- Первое действие: {ts[0]:%Y-%m-%d %H:%M}, последнее: {ts[-1]:%Y-%m-%d %H:%M}")
        print(f"- Активная работа агента: около {round(active / 60)} мин "
              "(паузы дольше 5 минут не считаются)")
        print(f"- Действий: {sum(tools.values())}, из них с ошибкой: {fails}")
        print("- По инструментам: " + ", ".join(f"{k} {v}" for k, v in
                                               sorted(tools.items(), key=lambda x: -x[1])))
    else:
        print("- Журнал действий пуст: хуки не работали. Время смотри в log.md.")

    up = proj / "usage.json"
    usage = json.loads(up.read_text(encoding="utf-8")) if up.exists() else {}
    total = defaultdict(lambda: defaultdict(int))
    for per_model in usage.values():
        for model, u in per_model.items():
            for k, v in u.items():
                total[model][k] += v
    total = {m: u for m, u in total.items() if any(u.values())}
    pp = ROOT / "routing" / "prices.json"
    prices = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
    table = prices.get("за_миллион_токенов", {})
    cur = prices.get("валюта", "")
    if total:
        print("\n| Модель | Вход | Выход | Кэш: чтение | Кэш: запись | Стоимость |")
        print("|---|---|---|---|---|---|")
        grand, unknown = 0.0, []
        for model, u in sorted(total.items()):
            cost = priced(u, price_for(model, table))
            if cost is None:
                unknown.append(model)
                cost_s = "цена не задана"
            else:
                grand += cost
                cost_s = f"{cost:.4f} {cur}"
            print(f"| {model} | {u['input']} | {u['output']} | {u['cache_read']} | "
                  f"{u['cache_write']} | {cost_s} |")
        if not unknown:
            print(f"\nИтого: {grand:.4f} {cur}")
        else:
            print("\nИтого: неизвестно")
            if len(unknown) < len(total):
                print(f"Оценённая часть: {grand:.4f} {cur}")
        if unknown:
            print("Не посчитаны, нет цены в routing/prices.json: " + ", ".join(unknown))
        base = prices.get("база_для_сравнения")
        claude = {m: u for m, u in total.items() if "claude" in m}
        if base and len(claude) > 1 and price_for(base, table):
            fact = [priced(u, price_for(m, table)) for m, u in claude.items()]
            if None not in fact:
                bp = price_for(base, table)
                all_strong = sum(priced(u, bp) for u in claude.values())
                saved = all_strong - sum(fact)
                share = f" ({saved / all_strong:.0%})" if all_strong else ""
                print(f"Если бы все токены Claude шли на {base}: {all_strong:.4f} {cur}. "
                      f"Экономия маршрутизации: {saved:.4f} {cur}{share}")
        limit = budget_limit(proj, prices)
        if limit:
            share = grand / limit
            if unknown:
                print(f"Бюджет проекта: {limit:.2f} {cur}; общая доля расхода неизвестна.")
            else:
                print(f"Бюджет проекта: {grand:.2f} из {limit:.2f} {cur} ({share:.0%}).")
            if share >= 1:
                print("БЮДЖЕТ ИСЧЕРПАН: остановись и спроси руководителя, продолжать ли "
                      "(новый лимит: budget --set N).")
            elif share >= 0.8:
                print("ВНИМАНИЕ: израсходовано больше 80% бюджета. Предупреди руководителя и экономь: "
                      "меньше повторных чтений, простую работу на дешёвую модель.")
    else:
        print("\nИтого: неизвестно. Данных о токенах нет. В Claude Code они появляются после ответа агента, "
              "в Кодексе — после первого сеанса в этой папке.")


def dispatch(args):
    from contextlib import closing
    is_registry_write = args.cmd in {'source', 'sources-add-many', 'claim', 'claims-add-many', 'revoke', 'revise', 'collect', 'ingest'}
    is_workflow_write = args.cmd == 'workflow' and args.workflow_action == 'apply'
    is_gate_write = args.cmd == 'gate' and args.sub == 'confirm'
    is_research_write = args.cmd == 'research' and args.research_action in {'add', 'close'}
    if not any((is_registry_write, is_workflow_write, is_gate_write, is_research_write)):
        return args.fn(args)
    project = project_dir(args.project)
    args.project = project.name
    lock_path = project / '.registry-lock.sqlite3'
    if lock_path.is_symlink():
        die('файл блокировки не должен быть ссылкой')
    with closing(sqlite3.connect(lock_path, timeout=10)) as lock, lock:
        try:
            lock.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            die('проект занят другой записью: ' + str(exc))
        return args.fn(args)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Команды Стратега Фабрики продуктов")
    p.add_argument("-p", "--project", help="имя проекта (по умолчанию активный)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="создать проект")
    s.add_argument("name"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("use", help="сделать проект активным")
    s.add_argument("name"); s.set_defaults(fn=cmd_use)
    sub.add_parser("status", help="где остановились").set_defaults(fn=cmd_status)

    s = sub.add_parser("source", help="источники").add_subparsers(dest="sub", required=True)
    s = s.add_parser("add", help="зарегистрировать источник")
    s.add_argument("--title", required=True, help="название")
    s.add_argument("--url", required=True, help="ссылка или путь к файлу в materials/")
    s.add_argument("--kind", required=True, choices=KINDS, help="вид источника")
    s.add_argument("--note", help="примечание: насколько надёжен, чьи данные")
    s.set_defaults(fn=cmd_source_add)

    s = sub.add_parser("sources-add-many", help="зарегистрировать пачку источников из файла JSON")
    s.add_argument("file", help="JSON-массив или строки JSON: title, url, kind, note, key")
    s.set_defaults(fn=cmd_source_add_many)
    s = sub.add_parser("claims-add-many", help="добавить пачку утверждений из файла JSON за один вызов")
    s.add_argument("file", help="JSON-массив или строки JSON: type, text, source, where, depends, note, key")
    s.set_defaults(fn=cmd_claim_add_many)

    c = sub.add_parser("claim", help="утверждения").add_subparsers(dest="sub", required=True)
    s = c.add_parser("add", help="добавить утверждение")
    s.add_argument("--type", required=True, choices=TYPES)
    s.add_argument("--text", required=True, help="одно проверяемое утверждение")
    s.add_argument("--source", help="номер источника, S-001")
    s.add_argument("--where", help="место в источнике: страница, раздел, ячейка, цитата")
    s.add_argument("--depends", help="из каких утверждений следует: C-001;C-002")
    s.add_argument("--note", help="примечание; для пробела — почему не удалось узнать")
    s.set_defaults(fn=cmd_claim_add)
    s = c.add_parser("edit", help="изменить утверждение")
    s.add_argument("id")
    s.add_argument("--type", choices=TYPES); s.add_argument("--text")
    s.add_argument("--source"); s.add_argument("--where"); s.add_argument("--depends")
    s.add_argument("--status", choices=STATUSES); s.add_argument("--note")
    s.set_defaults(fn=cmd_claim_edit)

    sub.add_parser("check", help="проверить реестр и тексты").set_defaults(fn=cmd_check)
    s = sub.add_parser("impact", help="что зависит от утверждения C-… или источника S-…")
    s.add_argument("id"); s.set_defaults(fn=cmd_impact)
    s = sub.add_parser("revoke", help="отозвать утверждение или все утверждения источника")
    s.add_argument("id"); s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_revoke)
    s = sub.add_parser("cost", help="время, действия, токены, расходы")
    s.add_argument("--no-codex", action="store_true", help="не подтягивать журналы Кодекса")
    s.set_defaults(fn=cmd_cost)
    s = sub.add_parser("budget", help="лимит расходов проекта")
    s.add_argument("--set", type=float, help="новый лимит в валюте из routing/prices.json")
    s.set_defaults(fn=cmd_budget)
    s = sub.add_parser("import-usage", help="подтянуть токены и действия из журналов Кодекса")
    s.add_argument("--path", help="файл rollout-….jsonl или папка с ними "
                                  "(по умолчанию ~/.codex/sessions или $CODEX_HOME/sessions)")
    s.set_defaults(fn=cmd_import_usage)

    import extra
    import capabilities
    import route_preview
    import execution
    import workflow
    import research
    import revisions
    import table_profile
    import fetch_page
    import media
    import ingest
    import ux_capture
    import calculations
    import delivery
    import trials
    import helpers
    extra.register(sub)
    capabilities.register(sub)
    route_preview.register(sub)
    execution.register(sub)
    workflow.register(sub)
    research.register(sub)
    revisions.register(sub)
    table_profile.register(sub)
    fetch_page.register(sub)
    media.register(sub)
    ingest.register(sub)
    ux_capture.register(sub)
    calculations.register(sub)
    delivery.register(sub)
    trials.register(sub)
    helpers.register(sub)

    a = p.parse_args()
    dispatch(a)


if __name__ == "__main__":
    main()
