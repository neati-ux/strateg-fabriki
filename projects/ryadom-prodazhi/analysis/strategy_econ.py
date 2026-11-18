#!/usr/bin/env python3
"""Экономика варианта В по шагам для шага 5. Данные вымышлены.
Запуск: python3 -I projects/ryadom-prodazhi/analysis/strategy_econ.py
Читает materials/sales.csv, ничего не меняет. Допущения те же, что в options.py:
линейная отдача каналов, доля оставшихся через 30 дней как за 8 недель, месяц = 4,33 недели (слова руководителя),
баннер и сайт не масштабируются. Результат — верхняя оценка."""
import csv
from pathlib import Path

MAT = Path(__file__).resolve().parent.parent / "materials"
W = 4.33
BUDGET = 2_500_000
MARGIN = 199 - 14  # маржа с оставшегося в месяц, как в C-042


def n(x):
    return f"{x:,.0f}".replace(",", " ")


seen, rows = set(), []
with open(MAT / "sales.csv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        k = (r["неделя_с"], r["канал"])
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)

CH = ["СМС-рассылка", "баннер в приложении", "салоны связи", "сайт"]
base = {}
for ch in CH:
    rs = [r for r in rows if r["канал"] == ch]
    sub_rs = [r for r in rs if r["подключения"] != ""]
    both = [r for r in rs if r["подключения"] != "" and r["отключились_за_30_дней"] != ""]
    sub = sum(int(r["подключения"]) for r in sub_rs)
    off = sum(int(r["отключились_за_30_дней"]) for r in both)
    sub_both = sum(int(r["подключения"]) for r in both)
    cost_w = sum(int(r["расходы_канала_руб"]) for r in rs) / len(rs)
    base[ch] = {"conn": sub / len(sub_rs) * W, "cost": cost_w * W, "keep": 1 - off / sub_both}

# Поправка руководителя (S-020): комиссия салонам 450 ₽ за подключение, а не 300 ₽, как в costs.md и sales.csv.
SALON_FEE = 450
base["салоны связи"]["cost"] = base["салоны связи"]["conn"] * SALON_FEE

sms = base["СМС-рассылка"]
sms_per_rub = sms["conn"] / sms["cost"]
salon = base["салоны связи"]


def scen(sms_rub, salon_mult):
    conn = sms_rub * sms_per_rub + salon["conn"] * salon_mult
    cost = sms_rub + salon["cost"] * salon_mult
    kept = sms_rub * sms_per_rub * sms["keep"] + salon["conn"] * salon_mult * salon["keep"]
    for ch in ("баннер в приложении", "сайт"):
        conn += base[ch]["conn"]
        cost += base[ch]["cost"]
        kept += base[ch]["conn"] * base[ch]["keep"]
    return conn, kept, cost


a_sms = BUDGET - (base["баннер в приложении"]["cost"] + salon["cost"] + base["сайт"]["cost"])
S = {
    "А. Как есть в границах бюджета": scen(a_sms, 1.0),
    "В, шаг 1: СМС 1,0 млн ₽, салоны как сейчас": scen(1_000_000, 1.0),
    "В, шаг 2: СМС 1,0 млн ₽, салоны вдвое": scen(1_000_000, 2.0),
}

print("Месячные величины по каналам и сценариям (верхняя оценка)")
print(f"{'сценарий':46}{'подкл.':>8}{'остан.':>8}{'расход ₽':>12}{'₽ на оставш.':>14}{'окупаемость, мес':>18}")
for k, (c, kp, co) in S.items():
    print(f"{k:46}{n(c):>8}{n(kp):>8}{n(co):>12}{n(co / kp):>14}{co / kp / MARGIN:>18.1f}")

print("\nТо же с учётом сметы проверок: весь бюджет 2,5 млн ₽ расходуется (свободные деньги уходят на проверки)")
for k, (c, kp, co) in S.items():
    print(f"{k:46}{n(BUDGET / kp):>14} ₽ на оставшегося, окупаемость {BUDGET / kp / MARGIN:.1f} мес")

a_kept = S["А. Как есть в границах бюджета"][1]
s1 = S["В, шаг 1: СМС 1,0 млн ₽, салоны как сейчас"]
s2 = S["В, шаг 2: СМС 1,0 млн ₽, салоны вдвое"]
print(f"\nШаг 1 против А: оставшихся {n(s1[1] - a_kept)} в месяц ({100 * (s1[1] / a_kept - 1):.0f}%), расход меньше на {n(S['А. Как есть в границах бюджета'][2] - s1[2])} ₽")
print(f"Шаг 2 против А: оставшихся {n(s2[1] - a_kept)} в месяц ({100 * (s2[1] / a_kept - 1):.0f}%)")

# Порог вместимости салонов: при каком множителе В не хуже А по оставшимся
lo, hi = 1.0, 3.0
for _ in range(60):
    mid = (lo + hi) / 2
    if scen(1_000_000, mid)[1] >= a_kept:
        hi = mid
    else:
        lo = mid
print(f"\nПорог: В не хуже А по оставшимся, если салоны принимают не меньше {hi:.2f} от нынешнего, "
      f"то есть около {n(salon['conn'] * hi)} подключений в месяц (сейчас около {n(salon['conn'])}), расход салонов {n(salon['cost'] * hi)} ₽")

print("\nЕсли главный прогноз окажется вдвое хуже (подключений и оставшихся вдвое меньше при том же расходе):")
for k in ("В, шаг 1: СМС 1,0 млн ₽, салоны как сейчас", "В, шаг 2: СМС 1,0 млн ₽, салоны вдвое"):
    c, kp, co = S[k]
    print(f"   {k}: оставшихся {n(kp / 2)}, расход на оставшегося {n(co / (kp / 2))} ₽, окупаемость {co / (kp / 2) / MARGIN:.1f} мес")
print(f"   А при той же поправке: {n(a_kept / 2)} оставшихся, {n(S['А. Как есть в границах бюджета'][2] / (a_kept / 2))} ₽, "
      f"окупаемость {S['А. Как есть в границах бюджета'][2] / (a_kept / 2) / MARGIN:.1f} мес")

print("\nСравнение при одинаковом расходе: весь бюджет 2,5 млн ₽ в месяц (свободные деньги уходят на проверки)")
for k, (c, kp, co) in S.items():
    print(f"   {k}: оставшихся {n(kp)}, {n(BUDGET / kp)} ₽ на оставшегося, окупаемость {BUDGET / kp / MARGIN:.1f} мес; "
          f"если вдвое хуже: оставшихся {n(kp / 2)}, {n(BUDGET / (kp / 2))} ₽, окупаемость {BUDGET / (kp / 2) / MARGIN:.1f} мес")
print(f"   Свободно на проверки: шаг 1 {n(BUDGET - s1[2])} ₽ в месяц, шаг 2 {n(BUDGET - s2[2])} ₽ в месяц")

print("\nДоля оставшихся по каналам:", ", ".join(f"{ch} {100 * base[ch]['keep']:.1f}%" for ch in CH))
print(f"Маржа с одного оставшегося в месяц: {MARGIN} ₽ (199 ₽ минус 14 ₽ карты, C-042); срок жизни подписки дольше первого месяца неизвестен (C-060)")
