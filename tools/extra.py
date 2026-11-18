"""Дополнительные команды Стратега: сверка с источником, цепочка оснований,
развилки человека, отчёт одной страницей. Только стандартная библиотека."""
import contextlib
import datetime as dt
import html
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import strateg as S

TEXT_EXT = {".md", ".txt", ".csv", ".tsv", ".json", ".html", ".htm", ".py"}
NUM = re.compile(r"\d+(?:[.,]\d+)?")
GATES = {"1": "Постановка задачи подтверждена", "4": "Вариант выбран",
         "7": "Решение принято"}


# ---------- сверка фактов с источником ----------

def _glue_thousands(text):
    return re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)


def _norm_num(x):
    x = x.replace(",", ".")
    if "." in x:
        x = x.rstrip("0").rstrip(".")
    return x.lstrip("0") or "0"


def numbers(text, glue=True):
    """Числа из текста. glue=True читает «12 400» как 12400."""
    return {_norm_num(n) for n in NUM.findall(_glue_thousands(text) if glue else text)}


def _squash(text):
    return re.sub(r"[\s_]+", " ", text).strip().lower().replace("ё", "е")


def _read(p):
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".csv", ".tsv"):
        text = re.sub(r"[,;\t]", " ", text)  # иначе «12400,44» читается как одно дробное число
    return text


def source_text(proj, src, run=False):
    """Текст источника, с которым можно сверять: файл, его копия или вывод расчёта."""
    cands = [src["адрес"]] + re.findall(r"((?:materials|analysis)/[^\s,;)]+)", src["примечание"])
    for c in cands:
        c = c.rstrip(".")
        for base in (proj, S.ROOT):
            p = (base / c).resolve()
            if not p.is_relative_to(proj.resolve()):
                continue
            if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
                continue
            if src["вид"] == "расчёт" and p.suffix == ".py":
                saved = p.with_suffix(".out.txt")
                if saved.is_file():
                    return _read(saved), str(saved.name)
                if not run or not p.is_relative_to((proj / "analysis").resolve()):
                    return None, "расчёт не перезапускался (--no-run)"
                for cwd in (S.ROOT, proj):
                    try:
                        r = subprocess.run([sys.executable, str(p)], cwd=cwd, capture_output=True,
                                           text=True, encoding="utf-8", errors="replace", timeout=120)
                    except (OSError, subprocess.TimeoutExpired):
                        continue
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout, f"повторный запуск {p.name}"
                return None, f"скрипт {p.name} не запустился"
            return _read(p), p.name
    return None, "источник не сохранён в проекте в текстовом виде"


EXACT_LINES = re.compile(r'^строк[аи]\s+(\d+)(?:\s*[-–—]\s*(\d+))?\s*$', re.IGNORECASE)


def locate_lines(text, locator):
    found = EXACT_LINES.fullmatch(locator.strip())
    if not found:
        return None
    first = int(found[1])
    last = int(found[2] or first)
    lines = text.splitlines()
    if first < 1 or last < first or last > len(lines):
        raise ValueError('Место выходит за пределы сохранённого источника')
    return '\n'.join(lines[first - 1:last])


def verify(proj, run=False):
    sources, claims = S.load(proj)
    sid = {s["id"]: s for s in sources}
    cache, rows = {}, []
    for c in claims:
        if c["тип"] != "факт" or c["статус"] == "отозвано":
            continue
        src = sid.get(c["источник"])
        if not src:
            rows.append((c["id"], "нет", "источник не найден", ""))
            continue
        if src["id"] not in cache:
            cache[src["id"]] = source_text(proj, src, run)
        text, how = cache[src["id"]]
        if text is None:
            rows.append((c["id"], "не проверено", how, src["id"]))
            continue
        try:
            excerpt = locate_lines(text, c['где_в_источнике']) if not str(how).lower().endswith('.csv') else None
        except ValueError as exc:
            rows.append((c['id'], 'проверь', str(exc), src['id']))
            continue
        if excerpt is not None:
            text = excerpt
            how = f"{how}, {c['где_в_источнике']}"
        # пробел бывает и разделителем разрядов, и границей между числами: принимаем оба чтения
        have = numbers(text) | numbers(text, glue=False)
        want = numbers(c["утверждение"])
        miss_a = want - have
        miss_b = numbers(c["утверждение"], glue=False) - have
        missing = sorted(min(miss_a, miss_b, key=len), key=lambda x: (len(x), x))
        quotes = [q for q in re.findall(r"«([^»]{12,})»", c["утверждение"] + " " + c["где_в_источнике"])]
        sq = _squash(text)
        bad_q = [q for q in quotes if _squash(q) not in sq]
        if not missing and not bad_q:
            note = f"числа: {len(want)}, цитаты: {len(quotes)} — всё найдено ({how})"
            rows.append((c["id"], "подтверждено", note, src["id"]))
        else:
            parts = []
            if missing:
                parts.append("в источнике нет чисел: " + ", ".join(missing))
            if bad_q:
                parts.append("нет цитаты: «" + bad_q[0][:60] + "»")
            rows.append((c["id"], "проверь", "; ".join(parts) + f" ({how})", src["id"]))
    (proj / "verify.json").write_text(json.dumps(
        {"at": dt.datetime.now().isoformat(timespec="seconds"),
         "rows": [dict(zip(("id", "итог", "пояснение", "источник"), r)) for r in rows]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def cmd_verify(a):
    proj = S.project_dir(a.project)
    rows = verify(proj, run=a.run_calculations and not a.no_run)
    for i, res, note, src in rows:
        mark = {"подтверждено": "OK      ", "проверь": "ПРОВЕРЬ ", "не проверено": "ПРОПУСК ",
                "нет": "ОШИБКА  "}[res]
        print(f"{mark}{i} {src}: {note}")
    n = {k: sum(1 for r in rows if r[1] == k) for k in ("подтверждено", "проверь", "не проверено")}
    print(f"\nФактов: {len(rows)}. Подтверждено кодом: {n['подтверждено']}. "
          f"Проверить вручную: {n['проверь']}. Не с чем сверить: {n['не проверено']}.")
    print("Сверка без модели: ищет числа и цитаты факта в сохранённом источнике. "
          "«Проверь» не значит «неверно»: число могло быть пересчитано или записано иначе.")
    if a.strict and n["проверь"]:
        sys.exit(1)


# ---------- цепочка оснований ----------

def cmd_why(a):
    proj = S.project_dir(a.project)
    sources, claims = S.load(proj)
    sid = {s["id"]: s for s in sources}
    cid = {c["id"]: c for c in claims}
    if a.id not in cid:
        S.die(f"утверждение {a.id} не найдено")
    seen = set()

    def show(i, depth):
        c = cid.get(i)
        pad = "  " * depth
        if not c:
            print(f"{pad}{i}: нет в реестре")
            return
        print(f"{pad}{i} [{c['тип']}, {c['статус']}] {c['утверждение']}")
        if c["источник"]:
            s = sid.get(c["источник"], {})
            print(f"{pad}  ← источник {c['источник']}: {s.get('название', '?')} "
                  f"({s.get('адрес', '?')}); место: {c['где_в_источнике'] or 'не указано'}")
        if i in seen:
            return
        seen.add(i)
        for d in S.split_ids(c["зависит_от"]):
            show(d, depth + 1)

    show(a.id, 0)


# ---------- развилки человека ----------

def load_gates(proj):
    p = proj / "gates.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def gate_problems(proj, claims):
    """Что сделано без подтверждения человека на развилке."""
    g = load_gates(proj)
    out = proj / "outputs"
    errs = []
    has_outputs = out.is_dir() and any(out.glob("*.md"))
    if "1" not in g and (claims or has_outputs):
        errs.append(("развилка 1", "работа идёт без подтверждённой постановки задачи. "
                     "Когда руководитель подтвердит: gate confirm 1 --by \"его слова\""))
    if "4" not in g and out.is_dir() and (list(out.glob("3-*.md")) or list(out.glob("4-*.md"))):
        errs.append(("развилка 4", "стратегии написаны, а выбор варианта руководителем не записан: "
                     "gate confirm 4 --by \"его слова\""))
    d = proj / "decisions.md"
    if "7" not in g and d.exists():
        body = re.sub(r"<!--.*?-->", "", d.read_text(encoding="utf-8"), flags=re.S)
        if re.search(r"^## D-\d+", body, re.M):
            errs.append(("развилка 7", "решение записано, а слова руководителя о нём нет: "
                         "gate confirm 7 --by \"его слова\""))
    return errs


def cmd_gate(a):
    proj = S.project_dir(a.project)
    g = load_gates(proj)
    if a.sub == "list":
        for k, title in GATES.items():
            v = g.get(k)
            print(f"Шаг {k}. {title}: " + (f"да, {v['at']} — «{v['by']}»" if v else "НЕТ"))
        return
    if not a.by or len(a.by.strip()) < 2:
        S.die("укажи слова руководителя: --by \"…\"")
    metric = getattr(a, "metric", None)
    if metric is not None and (a.step != "1" or not metric.strip()):
        S.die("--metric: укажи согласованный показатель на шаге 1")
    previous_metric = g.get(a.step, {}).get("metric")
    g[a.step] = {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "by": a.by.strip()}
    if metric or previous_metric:
        g[a.step]["metric"] = metric.strip() if metric else previous_metric
    (proj / "gates.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Развилка шага {a.step} закрыта: {GATES[a.step].lower()}.")


# ---------- отчёт одной страницей ----------

def _inline(t, claim_titles):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)

    def ref(m):
        i = m.group(0)
        title = html.escape(claim_titles.get(i, "нет в реестре"), quote=True)
        return f'<a class="ref" href="#{i}" title="{title}">{i}</a>'
    t = re.sub(r"(?<![#\w-])C-\d{3,}", ref, t)
    t = re.sub(r"(?<![#\w-])(S-\d{3,})", r'<a class="ref src" href="#\1">\1</a>', t)
    return t


def md_to_html(md, claim_titles):
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out, para, lst, table, code = [], [], None, [], None

    def flush():
        nonlocal para, lst, table
        if para:
            out.append("<p>" + _inline(" ".join(para), claim_titles) + "</p>")
            para = []
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{_inline(x, claim_titles)}</li>" for x in lst[1]) + f"</{lst[0]}>")
            lst = None
        if table:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table]
            body = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r)]
            if body:
                h = "<table><thead><tr>" + "".join(f"<th>{_inline(c, claim_titles)}</th>" for c in body[0]) + "</tr></thead><tbody>"
                for r in body[1:]:
                    h += "<tr>" + "".join(f"<td>{_inline(c, claim_titles)}</td>" for c in r) + "</tr>"
                out.append('<div class="tw">' + h + "</tbody></table></div>")
            table = []

    for line in md.splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
                code = None
            else:
                code.append(line)
            continue
        s = line.strip()
        if s.startswith("```"):
            flush()
            code = []
        elif not s:
            flush()
        elif s.startswith("|"):
            if para or lst:
                flush()
            table.append(s)
        elif m := re.match(r"(#{1,4})\s+(.*)", s):
            flush()
            n = min(len(m.group(1)) + 1, 5)
            out.append(f"<h{n}>{_inline(m.group(2), claim_titles)}</h{n}>")
        elif m := re.match(r"([-*]|\d+[.)])\s+(.*)", s):
            kind = "ul" if m.group(1) in "-*" else "ol"
            if para or table or (lst and lst[0] != kind):
                flush()
            if not lst:
                lst = [kind, []]
            lst[1].append(m.group(2))
        elif lst and line.startswith(("  ", "\t")):
            lst[1][-1] += " " + s
        elif s.startswith(">"):
            flush()
            out.append("<blockquote>" + _inline(s.lstrip("> "), claim_titles) + "</blockquote>")
        else:
            if lst or table:
                flush()
            para.append(s)
    flush()
    if code is not None:
        out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
    return "\n".join(out)


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#17202b;--mut:#5b6777;--line:#d5dbe4;--acc:#1f5fd0;
--fact:#0a7a5c;--hyp:#b0590a;--inf:#6a3fc4;--gap:#b3261e;--syn:#8a6d00}
@media (prefers-color-scheme:dark){:root{--bg:#10151c;--card:#19212b;--ink:#e7ecf3;--mut:#9aa6b6;
--line:#334052;--acc:#7fb0ff;--fact:#46caa8;--hyp:#f0a252;--inf:#bb97f8;--gap:#ff8a80;--syn:#e2c14a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px}h2{font-size:22px;margin:36px 0 10px;padding-top:14px;
border-top:2px solid var(--line)}h3{font-size:18px;margin:24px 0 8px}h4,h5{font-size:16px;margin:18px 0 6px}
p{margin:0 0 10px;max-width:72ch}li{margin:3px 0;max-width:72ch}.mut{color:var(--mut);font-size:14px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:14px 0 6px;font-size:14px}a{color:var(--acc)}
.tw{overflow-x:auto;margin:10px 0}table{border-collapse:collapse;font-size:14px;width:100%}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--card);font-weight:600}code,pre{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
pre{background:var(--card);border:1px solid var(--line);padding:10px;overflow-x:auto;border-radius:6px}
blockquote{margin:8px 0;padding:4px 12px;border-left:3px solid var(--line);color:var(--mut)}
a.ref{font:600 12px ui-monospace,Menlo,Consolas,monospace;text-decoration:none;border:1px solid var(--line);
border-radius:4px;padding:0 4px;white-space:nowrap}a.ref:hover{border-color:var(--acc)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.tile span{font-size:13px;color:var(--mut)}
.t{font-weight:600;white-space:nowrap}.t-факт{color:var(--fact)}.t-гипотеза,.t-прогноз{color:var(--hyp)}
.t-вывод{color:var(--inf)}.t-пробел{color:var(--gap)}.t-синтетика{color:var(--syn)}
tr.off td{opacity:.55;text-decoration:line-through}tr.rev td{background:color-mix(in srgb,var(--hyp) 12%,transparent)}
td b{white-space:nowrap}tr:target td{outline:2px solid var(--acc);outline-offset:-2px}section{scroll-margin-top:12px}
"""


def build_report(proj):
    sources, claims = S.load(proj)
    titles = {c["id"]: f"[{c['тип']}, {c['статус']}] {c['утверждение']}" for c in claims}
    esc = html.escape
    out_dir = proj / "outputs"
    docs = sorted(p for p in out_dir.glob("*.md")) if out_dir.is_dir() else []
    ver = {}
    vp = proj / "verify.json"
    if vp.exists():
        ver = {r["id"]: r for r in json.loads(vp.read_text(encoding="utf-8")).get("rows", [])}
    errs, warns = S.run_check(proj)
    gates = load_gates(proj)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            S.cmd_cost(SimpleNamespace(project=proj.name, no_codex=False))
        except SystemExit:
            pass
    cost_md = buf.getvalue()

    by_type = {}
    for c in claims:
        if c["статус"] != "отозвано":
            by_type[c["тип"]] = by_type.get(c["тип"], 0) + 1
    ok = sum(1 for r in ver.values() if r["итог"] == "подтверждено")
    m = re.search(r"Итого: ([\d.]+ \S+)", cost_md)
    tiles = [(len(sources), "источников"), (by_type.get("факт", 0), "фактов"),
             (f"{ok} из {len(ver)}" if ver else "—", "фактов сверено кодом"),
             (by_type.get("гипотеза", 0) + by_type.get("прогноз", 0), "гипотез и прогнозов"),
             (by_type.get("пробел", 0), "пробелов"),
             (len(errs), "ошибок проверки"), (m.group(1) if m else "—", "расход")]

    nav, body = [], []
    for p in docs:
        anchor = "doc-" + re.sub(r"\W+", "-", p.stem)
        text = p.read_text(encoding="utf-8")
        h = re.search(r"^#\s+(.+)", text, re.M)
        nav.append((anchor, h.group(1) if h else p.stem))
        body.append(f'<section id="{anchor}">' + md_to_html(text, titles) + "</section>")

    def row(c):
        cls = {"отозвано": "off", "на пересмотре": "rev"}.get(c["статус"], "")
        deps = " ".join(f'<a class="ref" href="#{d}">{d}</a>' for d in S.split_ids(c["зависит_от"]))
        src = f'<a class="ref src" href="#{c["источник"]}">{c["источник"]}</a>' if c["источник"] else ""
        v = ver.get(c["id"])
        vs = f'{esc(v["итог"])}<div class="mut">{esc(v["пояснение"])}</div>' if v else ""
        return (f'<tr id="{c["id"]}" class="{cls}"><td><b>{c["id"]}</b></td>'
                f'<td class="t t-{esc(c["тип"])}">{esc(c["тип"])}</td><td>{esc(c["утверждение"])}'
                + (f'<div class="mut">{esc(c["примечание"])}</div>' if c["примечание"] else "")
                + f'</td><td>{src} {esc(c["где_в_источнике"])}</td><td>{deps}</td>'
                f'<td>{esc(c["статус"])}</td><td>{vs}</td></tr>')

    reg = ('<div class="tw"><table><thead><tr><th>№</th><th>Тип</th><th>Утверждение</th><th>Источник и место</th>'
           '<th>Из чего следует</th><th>Статус</th><th>Сверка кодом</th></tr></thead><tbody>'
           + "".join(row(c) for c in claims) + "</tbody></table></div>")
    srcs = ('<div class="tw"><table><thead><tr><th>№</th><th>Название</th><th>Адрес</th><th>Вид</th><th>Дата</th>'
            '<th>Примечание</th></tr></thead><tbody>'
            + "".join(f'<tr id="{s["id"]}"><td><b>{s["id"]}</b></td><td>{esc(s["название"])}</td>'
                      f'<td>{esc(s["адрес"])}</td><td>{esc(s["вид"])}</td><td>{esc(s["дата_обращения"])}</td>'
                      f'<td>{esc(s["примечание"])}</td></tr>' for s in sources) + "</tbody></table></div>")
    gate_html = "<ul>" + "".join(
        f"<li>Шаг {k}. {t}: " + (f"<b>да</b>, {esc(gates[k]['at'])} — «{esc(gates[k]['by'])}»" if k in gates
                                 else "<b>нет</b>") + "</li>" for k, t in GATES.items()) + "</ul>"
    import helpers as H
    rout = ('<div class="tw"><table><thead><tr><th>Помощник</th><th>Шаг</th><th>Условие вызова</th>'
            '<th>Чем измерено</th><th>Итог</th></tr></thead><tbody>'
            + "".join(f'<tr><td><b>{esc(r["помощник"])}</b></td><td>{esc(str(r["шаг"]))}</td>'
                      f'<td>{"выполнено" if r["нужен"] else "не выполнено"}</td>'
                      f'<td>{esc(r["измерение"])}</td><td>{esc(r["итог"])}</td></tr>'
                      for r in H.state(proj)) + "</tbody></table></div>")
    chk = "<p>Ошибок: <b>%d</b>. Предупреждений: <b>%d</b>.</p>" % (len(errs), len(warns))
    if errs or warns:
        chk += "<ul>" + "".join(f"<li>{esc(i)}: {esc(t)}</li>" for i, t in errs + warns) + "</ul>"

    def opt(name, title, anchor):
        p = proj / name
        if p.exists():
            nav.append((anchor, title))
            return f'<section id="{anchor}"><h2>{title}</h2>' + md_to_html(
                re.sub(r"^# .*\n", "", p.read_text(encoding="utf-8"), count=1), titles) + "</section>"
        return ""

    tail = opt("decisions.md", "Журнал решений", "decisions")
    nav += [("registry", "Реестр утверждений"), ("sources", "Источники"), ("trust", "Проверки и развилки"),
            ("cost", "Время и расходы")]
    tail += (f'<section id="registry"><h2>Реестр утверждений</h2><p class="mut">Номер в тексте ведёт сюда. '
             f'Зачёркнутое отозвано, подсвеченное на пересмотре.</p>{reg}</section>'
             f'<section id="sources"><h2>Источники</h2>{srcs}</section>'
             f'<section id="trust"><h2>Проверки и развилки</h2><h3>Решения человека</h3>{gate_html}'
             f'<h3>Кто из помощников работал</h3><p class="mut">Условие вызова измеряет программа по '
             f'источникам и готовым документам. Если условие выполнено, в проекте должна быть запись: '
             f'вызов или пропуск с причиной.</p>{rout}'
             f'<h3>Проверка реестра и текстов</h3>{chk}</section>'
             f'<section id="cost"><h2>Время и расходы</h2>'
             + md_to_html(re.sub(r"^## .*\n", "", cost_md, count=1), titles) + "</section>")
    tail += opt("log.md", "Журнал работы", "log")

    page = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Отчёт: {esc(proj.name)}</title><style>{CSS}</style></head><body><div class="wrap">'
            f'<h1>Отчёт по проекту «{esc(proj.name)}»</h1>'
            f'<p class="mut">Собран {dt.datetime.now():%Y-%m-%d %H:%M} командой report из файлов проекта. '
            f'Каждый номер вида C-012 ведёт к строке реестра с источником.</p>'
            '<div class="tiles">' + "".join(f'<div class="tile"><b>{esc(str(v))}</b><span>{esc(t)}</span></div>'
                                             for v, t in tiles) + "</div>"
            "<nav>" + "".join(f'<a href="#{a}">{esc(t)}</a>' for a, t in nav) + "</nav>"
            + "\n".join(body) + tail + "</div></body></html>")
    dst = proj / "outputs" / "REPORT.html"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(page, encoding="utf-8")
    return dst


def cmd_report(a):
    proj = S.project_dir(a.project)
    if not a.no_verify:
        verify(proj)
    dst = build_report(proj)
    print(f"Отчёт собран: {dst.relative_to(S.ROOT)}. Открой файл в браузере.")


# ---------- что пора пересмотреть ----------

DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _dates(text):
    out = []
    for m in DATE.finditer(text):
        try:
            out.append(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m.group(1)
                       else dt.date(int(m.group(6)), int(m.group(5)), int(m.group(4))))
        except ValueError:
            pass
    return out


def _field(text, name):
    m = re.search(r"^[-*]\s*" + name + r"[^:\n]*:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def decisions(proj):
    p = proj / "decisions.md"
    if not p.exists():
        return []
    body = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    out = []
    for m in re.finditer(r"^## (D-\d+)\.?[ \t]*(.*?)\n(.*?)(?=^## |\Z)", body, re.S | re.M):
        text = m.group(3)
        out.append({"id": m.group(1), "title": m.group(2).strip(), "status": _field(text, "Статус"),
                    "when": _field(text, "Срок наблюдения") + " " + _field(text, "Условие пересмотра"),
                    "refs": sorted(set(re.findall(r"C-\d{3,}", text)))})
    return out


def cmd_due(a):
    proj = S.project_dir(a.project)
    _, claims = S.load(proj)
    cid = {c["id"]: c for c in claims}
    today, found = dt.date.today(), 0
    for d in decisions(proj):
        if re.search(r"заменено|отменено", d["status"], re.I):
            continue
        reasons = []
        weak = [r for r in d["refs"] if cid.get(r, {}).get("статус") in ("отозвано", "на пересмотре")]
        if weak:
            reasons.append("основания изменились: " + ", ".join(f"{r} ({cid[r]['статус']})" for r in weak))
        past = [x for x in _dates(d["when"]) if x <= today]
        if past:
            reasons.append("наступил срок: " + ", ".join(x.isoformat() for x in past))
        soon = [x for x in _dates(d["when"]) if today < x <= today + dt.timedelta(days=14)]
        if soon:
            reasons.append("срок в ближайшие две недели: " + ", ".join(x.isoformat() for x in soon))
        if reasons:
            found += 1
            print(f"{d['id']}. {d['title']}\n  " + "\n  ".join(reasons))
    if not found:
        print("Решений, которые пора пересматривать, нет: сроки не наступили, основания не менялись.")


# ---------- проверка окружения ----------

def cmd_doctor(a):
    ok = True

    def line(good, text, hint=""):
        nonlocal ok
        ok = ok and good
        print(("OK       " if good else "ПРОБЛЕМА ") + text + ("" if good or not hint else f" — {hint}"))
    v = sys.version_info
    line(v >= (3, 9), f"Python {v.major}.{v.minor}", "нужен 3.9 или новее")
    for rel in ("AGENTS.md", "templates/project/state.md", "routing/prices.json",
                "routing/triggers.json", "skills/1-zadacha.md",
                "knowledge/INDEX.md", ".claude/settings.json"):
        line((S.ROOT / rel).exists(), rel, "файл отсутствует, скачай репозиторий заново")
    try:
        S.PROJECTS.mkdir(exist_ok=True)
        t = S.PROJECTS / ".write-test"
        t.write_text("ок", encoding="utf-8")
        t.unlink()
        line(True, "в папку projects/ можно писать")
    except OSError as e:
        line(False, "в папку projects/ нельзя писать", str(e))
    try:
        "проверка".encode(sys.stdout.encoding or "utf-8")
        line(True, f"вывод в терминал: {sys.stdout.encoding}")
    except (UnicodeEncodeError, LookupError):
        line(False, "терминал не показывает русский текст", "задай переменную PYTHONUTF8=1")
    act = S.ACTIVE.read_text(encoding="utf-8").strip() if S.ACTIVE.exists() else ""
    print(f"Активный проект: {act or 'нет, будет создан при первой задаче'}")
    print("\nВсё готово. Открой папку в Claude Code, Cursor или Кодексе и напиши задачу." if ok
          else "\nИсправь отмеченное и запусти проверку снова.")
    sys.exit(0 if ok else 1)


def cmd_locate(a):
    project = S.project_dir(a.project)
    sources, _ = S.load(project)
    source = next((s for s in sources if s['id'] == a.source), None)
    if source is None:
        S.die('источник не зарегистрирован')
    text, how = source_text(project, source, run=False)
    if text is None:
        S.die(how)
    term = a.quote.strip()
    if not term:
        S.die('укажи цитату или фрагмент строки')
    matches = [{'line': i, 'text': line[:500]} for i, line in enumerate(text.splitlines(), 1)
               if _squash(term).casefold() in _squash(line).casefold()]
    print(json.dumps({'source': a.source, 'snapshot': how, 'matches': matches[:10], 'total': len(matches)},
                     ensure_ascii=False, indent=2))


def register(sub):
    s = sub.add_parser('locate', help='найти номера строк сохранённого источника по цитате')
    s.add_argument('source')
    s.add_argument('quote')
    s.set_defaults(fn=cmd_locate)
    sub.add_parser("due", help="какие решения пора пересмотреть").set_defaults(fn=cmd_due)
    sub.add_parser("doctor", help="проверить окружение перед первым запуском").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("verify", help="сверить числа и цитаты фактов с источниками, без модели")
    s.add_argument("--no-run", action="store_true", help="не перезапускать скрипты расчётов")
    s.add_argument("--run-calculations", action="store_true", help="явно перезапустить доверенные скрипты из analysis/")
    s.add_argument("--strict", action="store_true", help="код выхода 1, если есть расхождения")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("why", help="цепочка оснований утверждения до источников")
    s.add_argument("id")
    s.set_defaults(fn=cmd_why)
    g = sub.add_parser("gate", help="развилки, где решает человек").add_subparsers(dest="sub", required=True)
    s = g.add_parser("confirm", help="записать решение руководителя на развилке")
    s.add_argument("step", choices=list(GATES))
    s.add_argument("--by", required=True, help="слова руководителя, как он их написал")
    s.add_argument("--metric", help="подтверждённая формулировка основной метрики шага 1")
    s.set_defaults(fn=cmd_gate)
    g.add_parser("list", help="состояние развилок").set_defaults(fn=cmd_gate)
    s = sub.add_parser("report", help="собрать отчёт одной страницей outputs/REPORT.html")
    s.add_argument("--no-verify", action="store_true", help="не запускать сверку перед сборкой")
    s.set_defaults(fn=cmd_report)
