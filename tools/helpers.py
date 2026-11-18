"""Проверка маршрутизации: кто из помощников обязан был работать на проекте.

Условия вызова измеримы и считаются программой по `materials/sources.csv`,
файлам материалов и папке `outputs/`. Пороги лежат в `routing/triggers.json`.

Правило одно: если условие помощника выполнено, в `helpers.csv` должна быть
запись — либо вызов, либо пропуск с причиной. Необъяснённый пропуск видно в
`helpers` и в `check`. Только стандартная библиотека.
"""
import datetime as dt
import json
import sys

import strateg as S

FIELDS = ["дата", "шаг", "помощник", "итог", "причина"]
NAMES = ["extractor", "researcher", "analyst", "respondent", "critic"]
RESULTS = ["вызван", "пропущен"]

DEFAULTS = {
    "extractor": {"шаг": 2, "порог_знаков": 6000},
    "researcher": {"шаг": 3},
    "analyst": {"шаг": 2},
    "respondent": {"шаг": 3},
    "critic": {"шаг": 4},
}


def triggers():
    p = S.ROOT / "routing" / "triggers.json"
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            S.die(f"routing/triggers.json не читается: {e}")
        for name, cfg in data.items():
            if name in out and isinstance(cfg, dict):
                out[name].update(cfg)
    return out


def log_path(proj):
    return proj / "helpers.csv"


def records(proj):
    return S.read_csv(log_path(proj), FIELDS)


def add_record(proj, name, step, result, reason=""):
    rows = records(proj)
    rows.append({"дата": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "шаг": str(step),
                 "помощник": name, "итог": result, "причина": reason})
    S.write_csv(log_path(proj), FIELDS, rows)
    return rows


# ---------- измеримые условия ----------

TEXT_EXT = {".md", ".txt", ".csv", ".tsv", ".json", ".html", ".htm"}
# Что разбирает извлекатель: тексты. Таблицы считает analyst, картинки смотрит дирижёр.
READABLE = {"документ", "сайт", "интервью"}


def _local(proj, src):
    """Путь к текстовому файлу источника, если это файл внутри проекта."""
    url = src.get("адрес", "")
    if not url or url.startswith(("http://", "https://")):
        return None
    p = (proj / url).resolve()
    return p if p.is_relative_to(proj.resolve()) and p.is_file() and p.suffix.lower() in TEXT_EXT else None


def _size(proj, src):
    p = _local(proj, src)
    if p is None:
        return 0
    try:
        return len(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def conditions(proj):
    """Для каждого помощника: выполнено ли условие и чем это измерено."""
    cfg = triggers()
    sources, _ = S.load(proj)
    out = proj / "outputs"
    texts = sorted(f.name for f in out.glob("*.md")) if out.is_dir() else []

    limit = int(cfg["extractor"].get("порог_знаков", 6000))
    long_src = [(s["id"], _size(proj, s)) for s in sources if s["вид"] in READABLE]
    long_src = sorted([x for x in long_src if x[1] > limit], key=lambda x: -x[1])
    pages = [s["id"] for s in sources if s["вид"] == "сайт"]
    tables = [s["id"] for s in sources if s["вид"] == "таблица"]
    talks = [s["id"] for s in sources if s["вид"] == "интервью"]
    external = [s["id"] for s in sources if s["адрес"].startswith(("http://", "https://"))
                or (s["вид"] == "сайт" and "URL: https://" in s["примечание"])
                or (s["вид"] == "сайт" and "URL: http://" in s["примечание"])]
    ready = [t for t in texts if t[:2] in ("2-", "3-", "4-")]

    started = bool(sources)  # пока источников нет, шаги 2 и 3 ещё не начинались
    res = {}
    res["extractor"] = (
        bool(long_src or pages),
        f"источников длиннее {limit} знаков: {len(long_src)}"
        + (f" ({', '.join(i for i, _ in long_src[:3])})" if long_src else "")
        + f"; сохранённых страниц: {len(pages)}")
    res["researcher"] = (
        started and not external,
        f"источников из открытой сети: {len(external)}")
    res["analyst"] = (
        bool(tables),
        f"таблиц среди источников: {len(tables)}"
        + (f" ({', '.join(tables[:3])})" if tables else ""))
    res["respondent"] = (
        started and not talks,
        f"реальных интервью среди источников: {len(talks)}")
    res["critic"] = (
        bool(ready),
        f"готовых документов в outputs: {len(ready)}"
        + (f" ({', '.join(ready[:3])})" if ready else ""))
    return {k: {"нужен": v[0], "измерение": v[1], "шаг": cfg[k].get("шаг")} for k, v in res.items()}


WHY = {
    "extractor": "длинные документы и сохранённые страницы разбирает дешёвая модель",
    "researcher": "внешние источники ищет и сопоставляет средняя модель",
    "analyst": "таблицы проверяет и считает скриптом средняя модель",
    "respondent": "без реальных интервью гипотезы ищут модельные беседы",
    "critic": "готовый текст проверяет сильная модель в отдельном контексте",
}


def state(proj):
    """Строки для таблицы: помощник, шаг, нужен, измерение, записи, итог."""
    cond = conditions(proj)
    by_name = {}
    for r in records(proj):
        by_name.setdefault(r["помощник"], []).append(r)
    rows = []
    for name in NAMES:
        c = cond[name]
        rec = by_name.get(name, [])
        used = [r for r in rec if r["итог"] == "вызван"]
        skipped = [r for r in rec if r["итог"] == "пропущен"]
        if used:
            verdict, ok = "вызван", True
        elif skipped:
            verdict, ok = "пропуск объяснён: " + (skipped[-1]["причина"] or "без причины"), True
        elif not c["нужен"]:
            verdict, ok = "условие не выполнено, вызов не нужен", True
        else:
            verdict, ok = "НЕ ОБЪЯСНЁН", False
        rows.append({"помощник": name, "шаг": c["шаг"], "нужен": c["нужен"],
                     "измерение": c["измерение"], "итог": verdict, "хорошо": ok,
                     "записей": len(rec)})
    return rows


def problems(proj):
    """Предупреждения для `check`: условие выполнено, а записи нет."""
    out = []
    for r in state(proj):
        if not r["хорошо"]:
            out.append((f"помощник {r['помощник']}",
                        f"условие выполнено ({r['измерение']}), вызов не записан. "
                        f"{WHY[r['помощник']]}. Вызови его или объясни пропуск: "
                        f"helper {r['помощник']} --step {r['шаг']} --skipped --reason \"…\""))
    return out


# ---------- команды ----------

def cmd_helpers(a):
    proj = S.project_dir(a.project)
    rows = state(proj)
    width = max(len(r["помощник"]) for r in rows)
    for r in rows:
        mark = " " if r["хорошо"] else "!"
        need = "нужен" if r["нужен"] else "не нужен"
        print(f"{mark} {r['помощник']:<{width}}  шаг {r['шаг']}  {need:<9} {r['итог']}")
        print(f"  {' ' * width}  {r['измерение']}")
    bad = [r for r in rows if not r["хорошо"]]
    print(f"\nПомощников с невыполненным условием: "
          f"{sum(1 for r in rows if not r['нужен'])}. Необъяснённых пропусков: {len(bad)}.")
    if bad and not a.soft:
        sys.exit(1)


def cmd_helper(a):
    proj = S.project_dir(a.project)
    if a.name not in NAMES:
        S.die(f"помощник должен быть одним из: {', '.join(NAMES)}")
    result = "вызван" if a.used else "пропущен"
    reason = (a.reason or a.note or "").strip()
    if result == "пропущен" and len(reason) < 3:
        S.die("у пропуска должна быть причина: --reason \"…\"")
    add_record(proj, a.name, a.step, result, reason)
    print(f"Записано: {a.name}, шаг {a.step}, {result}" + (f" — {reason}" if reason else "") + ".")


def register(sub):
    s = sub.add_parser("helpers", help="кто из помощников обязан был работать и записан ли вызов")
    s.add_argument("--soft", action="store_true", help="не возвращать код 1 при пропусках")
    s.set_defaults(fn=cmd_helpers)
    s = sub.add_parser("helper", help="записать вызов помощника или объяснить пропуск")
    s.add_argument("name", help="|".join(NAMES))
    s.add_argument("--step", required=True, help="номер шага")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--used", action="store_true", help="помощник работал")
    g.add_argument("--skipped", action="store_true", help="помощник не вызывался")
    s.add_argument("--reason", help="почему пропущен")
    s.add_argument("--note", help="что сделал помощник")
    s.set_defaults(fn=cmd_helper)
