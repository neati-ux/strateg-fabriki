#!/usr/bin/env python3
"""Анализ продаж по каналам «Рядом». Данные вымышлены.
Запуск: python3 -I projects/ryadom-prodazhi/analysis/analyze.py
Читает materials/sales.csv и segments.csv, ничего не меняет, печатает результат."""
import csv
import statistics
from datetime import date, timedelta
from pathlib import Path

MAT = Path(__file__).resolve().parent.parent / "materials"
TODAY = date(2026, 11, 16)
PLAN = 30000
BUDGET_MONTH = 2_500_000
PLAN_SMS_MONTH = 1_900_000
WEEKS_IN_MONTH = 4.33
PRICE = 199
MAPS = 14
CHANNELS = ["баннер в приложении", "СМС-рассылка", "салоны связи", "сайт"]
NUM = ["показы", "переходы", "подключения", "отключились_за_30_дней", "расходы_канала_руб"]


def pct(a, b):
    return f"{100 * a / b:.1f}% ({a} из {b})" if b else "н/д"


def rub(x):
    return f"{x:,.0f}".replace(",", " ")


# ---------- чтение ----------
with open(MAT / "sales.csv", encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    raw = []
    for i, r in enumerate(rd, start=2):  # строка 1 — заголовок
        raw.append((i, r))

print("=" * 70)
print("1. ПРОВЕРКА ДАННЫХ (knowledge/data-checks.md)")
print("=" * 70)
print("Строка = одна неделя одного канала. Столбцы:", ", ".join(rd.fieldnames))
print("Единицы: показы, переходы, подключения, отключились — штуки; расходы — рубли; неделя_с — дата начала недели.")
print(f"Строк данных: {len(raw)} (номера считаются по файлу, заголовок — строка 1)")

problems = []
rows = []
seen = {}
for ln, r in raw:
    d = date.fromisoformat(r["неделя_с"])
    rec = {"line": ln, "week": d, "ch": r["канал"]}
    for k in NUM:
        v = (r[k] or "").strip()
        rec[k] = int(v) if v != "" else None
    # пропуски
    miss = [k for k in NUM if rec[k] is None]
    if miss:
        problems.append(f"строка {ln}: пропуск ({', '.join(miss)}), {rec['ch']}, неделя {d}. "
                        "Не заменён нулём; строка остаётся в показах/переходах/расходах, "
                        "в подключениях и отключениях эта неделя не учитывается")
    key = (rec["week"], rec["ch"])
    full = tuple(r[k] for k in r)
    if key in seen:
        first_ln, first_full = seen[key]
        kind = "полный дубль" if first_full == full else "повтор ключа с другими числами"
        problems.append(f"строка {ln}: {kind} строки {first_ln} ({rec['ch']}, неделя {d}). Исключена")
        continue
    seen[key] = (ln, full)
    rows.append(rec)

weeks = sorted({r["week"] for r in rows})
print(f"Период: {weeks[0]} … {weeks[-1]} (начала недель), недель: {len(weeks)}; "
      f"последняя неделя заканчивается {weeks[-1] + timedelta(days=6)}")
bad_step = [w for a, w in zip(weeks, weeks[1:]) if (w - a).days != 7]
print("Шаг между неделями 7 дней везде:", "да" if not bad_step else f"нет, {bad_step}")
unknown = {r["ch"] for r in rows} - set(CHANNELS)
print("Неизвестные каналы:", unknown or "нет")
# комплектность: канал × неделя
for ch in CHANNELS:
    have = {r["week"] for r in rows if r["ch"] == ch}
    for w in weeks:
        if w not in have:
            problems.append(f"нет строки: {ch}, неделя {w}")

# логика: подключения <= переходов <= показов, отключения <= подключений
for r in rows:
    if r["переходы"] is not None and r["показы"] is not None and r["переходы"] > r["показы"]:
        problems.append(f"строка {r['line']}: переходов больше, чем показов")
    if r["подключения"] is not None and r["переходы"] is not None and r["подключения"] > r["переходы"]:
        problems.append(f"строка {r['line']}: подключений больше, чем переходов")
    if None not in (r["подключения"], r["отключились_за_30_дней"]) and r["отключились_за_30_дней"] > r["подключения"]:
        problems.append(f"строка {r['line']}: отключений больше, чем подключений")

# особенности по каналам
sal = [r for r in rows if r["ch"] == "салоны связи"]
if all(r["показы"] == r["переходы"] for r in sal):
    problems.append("салоны связи: показы = переходы в каждой из "
                    f"{len(sal)} строк (строки {', '.join(str(r['line']) for r in sal)}). "
                    "Показов в салоне не существует, столбец повторяет переходы; конверсию по показам не считать")
# сверка цен с costs.md
for r in rows:
    exp = None
    if r["ch"] == "салоны связи" and r["подключения"] is not None:
        exp = 300 * r["подключения"]
        if exp != r["расходы_канала_руб"]:
            problems.append(f"строка {r['line']}: салоны, расходы {r['расходы_канала_руб']} ≠ 300 ₽ × {r['подключения']} = {exp}")
    if r["ch"] == "баннер в приложении" and r["расходы_канала_руб"] != 40000:
        problems.append(f"строка {r['line']}: баннер, расходы {r['расходы_канала_руб']} ≠ 320 тыс. ₽ / 8 нед. = 40 000")
sms = [r for r in rows if r["ch"] == "СМС-рассылка"]
sms_ok = all(r["расходы_канала_руб"] == 475000 for r in sms)
print(f"СМС: расходы 475 000 ₽ в неделю = 1,9 ₽ × 250 000 сообщений во всех {len(sms)} неделях: {'да' if sms_ok else 'нет'}")
site = [r for r in rows if r["ch"] == "сайт"]
site_total = sum(r["расходы_канала_руб"] for r in site)
site_costs_md = 60000
if site_total != site_costs_md * 8 / 13:
    problems.append(f"сайт: в sales.csv {rub(site_total)} ₽ за {len(site)} нед. (по 20 000 в неделю), "
                    f"а в costs.md 60 тыс. ₽ за квартал (≈{rub(site_costs_md * 8 / 13)} ₽ за 8 недель при 13 неделях в квартале). "
                    "Расхождение в 4,3 раза; в расчётах использованы данные sales.csv")
# выбросы: отклонение от медианы канала > 30%
for ch in CHANNELS:
    for k in ["показы", "переходы", "подключения"]:
        vals = [r[k] for r in rows if r["ch"] == ch and r[k] is not None]
        med = statistics.median(vals)
        for r in rows:
            if r["ch"] == ch and r[k] is not None and med and abs(r[k] - med) / med > 0.30:
                problems.append(f"выброс? строка {r['line']}: {ch}, {k} = {r[k]} при медиане {med}")
print("Выбросы: проверено отклонение >30% от медианы канала по показам, переходам и подключениям")

print("\nСписок проблем данных:")
if not problems:
    print("  нет")
for p in problems:
    print("  -", p)
print("Определения: «отключились_за_30_дней» не описано в файле (считается ли отключение с момента подключения; "
      "что считать отключением) — пробел.")
print("Изменения в учёте внутри периода: сведений нет (проверить нельзя) — пробел.")

# ---------- 2. по каналам ----------
print()
print("=" * 70)
print("2. ПО КАНАЛАМ, 8 недель после чистки (дубль исключён, пропуск не заменён нулём)")
print("=" * 70)


def complete30(w):
    """Все 30 дней после последнего дня недели прошли к TODAY."""
    return w + timedelta(days=6 + 30) <= TODAY


full_weeks = [w for w in weeks if complete30(w)]
inc_weeks = [w for w in weeks if not complete30(w)]
print(f"Недели с полными 30 днями к {TODAY} (конец недели + 30 дней ≤ {TODAY}): "
      f"{', '.join(map(str, full_weeks))} ({len(full_weeks)} из {len(weeks)})")
print(f"Недели, у которых 30 дней ещё не прошли: {', '.join(map(str, inc_weeks))} ({len(inc_weeks)})")

stat = {}
for ch in CHANNELS:
    rs = [r for r in rows if r["ch"] == ch]
    s = {}
    s["n_weeks"] = len(rs)
    for k in ["показы", "переходы", "расходы_канала_руб"]:
        s[k] = sum(r[k] for r in rs if r[k] is not None)
    s["n_sub_weeks"] = sum(1 for r in rs if r["подключения"] is not None)
    s["подключения"] = sum(r["подключения"] for r in rs if r["подключения"] is not None)
    # переходы за те же недели, что и подключения
    s["перех_для_конв"] = sum(r["переходы"] for r in rs if r["подключения"] is not None)
    s["расх_для_cac"] = sum(r["расходы_канала_руб"] for r in rs if r["подключения"] is not None)
    both = [r for r in rs if r["подключения"] is not None and r["отключились_за_30_дней"] is not None]
    s["both_n"] = len(both)
    s["both_sub"] = sum(r["подключения"] for r in both)
    s["both_off"] = sum(r["отключились_за_30_дней"] for r in both)
    bf = [r for r in both if complete30(r["week"])]
    s["full_n"] = len(bf)
    s["full_sub"] = sum(r["подключения"] for r in bf)
    s["full_off"] = sum(r["отключились_за_30_дней"] for r in bf)
    bi = [r for r in both if not complete30(r["week"])]
    s["inc_n"] = len(bi)
    s["inc_sub"] = sum(r["подключения"] for r in bi)
    s["inc_off"] = sum(r["отключились_за_30_дней"] for r in bi)
    s["off_total_all"] = sum(r["отключились_за_30_дней"] for r in rs if r["отключились_за_30_дней"] is not None)
    stat[ch] = s

tot_sub = sum(s["подключения"] for s in stat.values())

print("\nТаблица А. Суммы (показы, переходы, расходы — все недели с данными; подключения — недели с данными)")
print(f"{'канал':22}{'нед.':>5}{'нед. с подкл.':>14}{'показы':>10}{'переходы':>10}{'подкл.':>8}{'расходы, ₽':>13}")
for ch, s in stat.items():
    print(f"{ch:22}{s['n_weeks']:>5}{s['n_sub_weeks']:>14}{rub(s['показы']):>10}{rub(s['переходы']):>10}"
          f"{rub(s['подключения']):>8}{rub(s['расходы_канала_руб']):>13}")

print("\nТаблица Б. Конверсия, цена подключения, доля канала")
print("(конверсия и расход на подключение — только по неделям, где есть подключения)")
print(f"{'канал':22}{'конверсия переход→подкл.':>34}{'₽ на подкл.':>13}{'доля в подкл.':>26}")
for ch, s in stat.items():
    conv = pct(s["подключения"], s["перех_для_конв"])
    cac = s["расх_для_cac"] / s["подключения"]
    share = pct(s["подключения"], tot_sub)
    s["cac"] = cac
    s["conv_txt"] = conv
    print(f"{ch:22}{conv:>34}{cac:>13.0f}{share:>26}")
    s["share_txt"] = share

print("\nТаблица В. Отключившиеся за 30 дней (только строки, где есть и подключения, и отключения)")
print("ВНИМАНИЕ: у недель, чьи 30 дней не прошли к 2026-11-16, показатель занижен или неполон.")
print(f"{'канал':22}{'все недели с данными':>30}{'только полные 30 дней':>30}{'неполные недели':>26}")
for ch, s in stat.items():
    a = f"{pct(s['both_off'], s['both_sub'])} н={s['both_n']}"
    b = f"{pct(s['full_off'], s['full_sub'])} н={s['full_n']}"
    c = f"{pct(s['inc_off'], s['inc_sub'])} н={s['inc_n']}"
    print(f"{ch:22}{a:>30}{b:>30}{c:>26}")
print("(н = число недель в расчёте)")

print("\nТаблица Г. Расход на одно оставшееся подключение = расходы / (подключения − отключившиеся)")
print("Строки с пропуском исключены целиком; считаны две базы: все недели с обоими числами и только полные 30 дней")
print(f"{'канал':22}{'все недели с обоими':>34}{'только полные 30 дней':>34}")
for ch, s in stat.items():
    rs = [r for r in rows if r["ch"] == ch and r["подключения"] is not None and r["отключились_за_30_дней"] is not None]
    cost_all = sum(r["расходы_канала_руб"] for r in rs)
    rem_all = s["both_sub"] - s["both_off"]
    rf = [r for r in rs if complete30(r["week"])]
    cost_f = sum(r["расходы_канала_руб"] for r in rf)
    rem_f = s["full_sub"] - s["full_off"]
    s["cost_all"], s["rem_all"], s["cost_f"], s["rem_f"] = cost_all, rem_all, cost_f, rem_f
    ta = f"{cost_all / rem_all:.0f} ₽ ({rub(cost_all)} / {rem_all})"
    tf = f"{cost_f / rem_f:.0f} ₽ ({rub(cost_f)} / {rem_f})"
    print(f"{ch:22}{ta:>34}{tf:>34}")

# ---------- 3. итог ----------
print()
print("=" * 70)
print("3. ИТОГ ПО ВСЕМ КАНАЛАМ")
print("=" * 70)
seg = []
with open(MAT / "segments.csv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        seg.append(r)
seg_sub = sum(int(r["подключили"]) for r in seg)
tot_cost = sum(s["расходы_канала_руб"] for s in stat.values())
n_sub_weeks_missing = len(weeks) * len(CHANNELS) - sum(s["n_sub_weeks"] for s in stat.values())
print(f"Подключений всего по sales.csv: {tot_sub} (учтено недель×каналов: {sum(s['n_sub_weeks'] for s in stat.values())} из {len(weeks) * len(CHANNELS)}; "
      f"без недели сайта 2026-10-05, поэтому сумма не включает её)")
print(f"К плану 30 000: {pct(tot_sub, PLAN)}")
print(f"Сумма «подключили» в segments.csv: {seg_sub}; разница с sales.csv: {tot_sub - seg_sub} "
      f"({'совпадает' if tot_sub == seg_sub else 'НЕ совпадает'})")
print(f"Расходы всего за 8 недель: {rub(tot_cost)} ₽")
print(f"  из них СМС: {rub(stat['СМС-рассылка']['расходы_канала_руб'])} ₽ ({pct(stat['СМС-рассылка']['расходы_канала_руб'], tot_cost)})")
print("Расходы по сайту: в расчёте 8 недель × 20 000 ₽ (пропуск касается только подключений; расходы за неделю 2026-10-05 есть)")
nw = len(weeks)
sms_w = stat["СМС-рассылка"]["расходы_канала_руб"] / nw
all_w = tot_cost / nw
print(f"\n{'':28}{'за неделю, ₽':>16}{'за месяц (×4,33), ₽':>24}")
print(f"{'СМС-рассылка':28}{rub(sms_w):>16}{rub(sms_w * WEEKS_IN_MONTH):>24}")
print(f"{'все каналы':28}{rub(all_w):>16}{rub(all_w * WEEKS_IN_MONTH):>24}")
print(f"Бюджет продвижения 2,5 млн ₽ в месяц: все каналы за месяц = {pct(int(round(all_w * WEEKS_IN_MONTH)), BUDGET_MONTH)}; "
      f"разница {rub(BUDGET_MONTH - all_w * WEEKS_IN_MONTH)} ₽ ниже бюджета")
print(f"Цифра маркетинга 1,9 млн ₽ в месяц (marketing-plan.md): по таблице СМС за месяц = {rub(sms_w * WEEKS_IN_MONTH)} ₽; "
      f"разница {rub(sms_w * WEEKS_IN_MONTH - PLAN_SMS_MONTH)} ₽ ({100 * (sms_w * WEEKS_IN_MONTH / PLAN_SMS_MONTH - 1):.1f}%)")
print("Примечание: 1,9 ₽ — это цена одного сообщения в costs.md; число 1,9 млн в marketing-plan.md совпадает с ней по цифре, но не по смыслу (возможная путаница).")

# ---------- 4. segments ----------
print()
print("=" * 70)
print("4. СЕГМЕНТЫ (segments.csv)")
print("=" * 70)
act_sum = sum(int(r["активны_на_30_й_день"]) for r in seg)
print(f"{'сегмент':36}{'подключили':>11}{'активны на 30-й день':>22}   {'доля активных':<26}{'доля среди подключивших'}")
for r in seg:
    n, a = int(r["подключили"]), int(r["активны_на_30_й_день"])
    share_act = pct(a, n) if n >= 30 else f"{a} из {n} (меньше 30, без %)"
    share_seg = pct(n, seg_sub)
    print(f"{r['сегмент']:36}{n:>11}{a:>22}   {share_act:<26}{share_seg}")
print(f"{'ВСЕГО':36}{seg_sub:>11}{act_sum:>22}   {pct(act_sum, seg_sub)}")
print("«активны_на_30_й_день» в файле не определено (вход, действие, оплата? на какую дату?) — пробел; нужен ответ руководителя.")
print("Подключения, активные на 30-й день, и «не отключились» — разные показатели, прямо не сравнивать.")
print(f"Совпадение с sales.csv: segments {seg_sub} против sales.csv {tot_sub} ({'совпадает' if seg_sub == tot_sub else 'не совпадает, разница ' + str(tot_sub - seg_sub)})")
undefined = [r for r in seg if r["сегмент"] == "сегмент не определён"][0]
print(f"Сегмент не определён: {pct(int(undefined['подключили']), seg_sub)} подключивших")
print(f"Недели в segments.csv не указаны — период не определён (пробел). Сумма активных {act_sum} из {seg_sub} подключивших.")

# ---------- 5. экономика ----------
print()
print("=" * 70)
print("5. ЭКОНОМИКА ОДНОГО ПОДПИСЧИКА (условный расчёт, не прогноз)")
print("=" * 70)
margin = PRICE - MAPS
print(f"Условие: подписчик остаётся и платит {PRICE} ₽ в месяц, картографический сервис {MAPS} ₽ на активного в месяц; "
      f"{PRICE} − {MAPS} = {margin} ₽ в месяц на подписчика.")
print("Не учтено: поддержка и серверы 450 тыс. ₽ в месяц (не зависят от числа пользователей), отток, налоги, комиссии магазинов приложений.")
print(f"{'канал':22}{'₽ на подкл.':>12}{'месяцев (на подкл.)':>21}{'₽ на оставшегося (полные нед.)':>32}{'месяцев (на оставшегося)':>26}")
for ch, s in stat.items():
    m1 = s["cac"] / margin
    c2 = s["cost_f"] / s["rem_f"]
    m2 = c2 / margin
    print(f"{ch:22}{s['cac']:>12.0f}{m1:>21.1f}{c2:>32.0f}{m2:>26.1f}")

# ---------- 6. тезисы маркетинга ----------
print()
print("=" * 70)
print("6. СВЕРКА ТЕЗИСОВ МАРКЕТИНГА С ТАБЛИЦЕЙ")
print("=" * 70)
sm = stat["СМС-рассылка"]
bn = stat["баннер в приложении"]
print(f"«СМС даёт больше половины всех подключений»: по таблице {sm['share_txt']}")
print(f"«Конверсия СМС 12%»: по таблице {sm['conv_txt']}")
print(f"«Вдвое выше баннера»: баннер {bn['conv_txt']}; отношение СМС/баннер = "
      f"{(sm['подключения'] / sm['перех_для_конв']) / (bn['подключения'] / bn['перех_для_конв']):.2f}")
print("Конверсия остальных каналов для сравнения:",
      "; ".join(f"{ch} {s['conv_txt']}" for ch, s in stat.items() if ch not in ("СМС-рассылка", "баннер в приложении")))
print(f"Доля СМС без чистки дубля (для справки): "
      f"{pct(sm['подключения'] + 599, tot_sub + 599)}")
print("\nКОНЕЦ")
