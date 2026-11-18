"""Расчёт по отчёту пилота от 14.11.2026 (S-021). Только арифметика, без модели.
Числа пилота: materials/otchet-pilota-2026-11-14.md.
Числа по каналам из реестра: C-007 (СМС 4753 подключения, 3 800 000 ₽ за 8 недель),
C-009/C-010 (СМС остались 1045), C-015 (сегмент 505 из 620), C-009 (салоны 1921, отключились 421),
C-070 (А: СМС 1 772 316 ₽ в месяц, оставшихся 2 220), C-073 (В: 2 820), C-077 (В0: 2 008)."""
from math import sqrt


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


print("== Пилот в салонах ==")
cons, conn, act = 310, 41, 36
lo, hi = wilson(conn, cons)
print(f"подключений на консультацию: {conn}/{cons} = {conn/cons:.1%} (95% интервал {lo:.1%}-{hi:.1%})")
lo, hi = wilson(act, conn)
print(f"активны на 30-й день: {act}/{conn} = {act/conn:.1%} (95% интервал {lo:.1%}-{hi:.1%})")
print(f"сегмент взрослые дети пожилых по всем каналам (C-015): 505/620 = {505/620:.1%}; разница {100*(act/conn-505/620):+.1f} п.п., внутри интервала")
print(f"салоны по всем клиентам (C-009): 1500/1921 = {1500/1921:.1%}; разница {100*(act/conn-1500/1921):+.1f} п.п.")
print(f"подключений в пилоте: {conn/2:.1f} в неделю всего, {conn/2/12:.2f} в неделю на салон")

print("\n== Остановка СМС на две недели ==")
sms_conn, sms_cost, sms_ret = 4753, 3_800_000, 1045
per2w = sms_conn / 8 * 2
lost_conn, lost_act = 1150, 60
avg_ret = sms_ret / sms_conn
print(f"СМС по таблице за две недели: {per2w:.0f} подключений; падение на 1150 = {lost_conn/per2w:.1%} от этого")
print(f"средняя доля оставшихся у СМС: {avg_ret:.1%}; при ней из 1150 осталось бы {lost_conn*avg_ret:.0f}")
marg = lost_act / lost_conn
print(f"по пилоту потеряно активных: {lost_act} из {lost_conn} = {marg:.1%}")
spend2w = sms_cost / 8 * 2
print(f"расход СМС за две недели (допущение: средний 475 000 ₽ в неделю): {spend2w:,.0f} ₽; на одного потерянного активного {spend2w/lost_act:,.0f} ₽ (по таблице в среднем {sms_cost/sms_ret:,.0f} ₽)")
print(f"в пересчёте на месяц (4,33 недели): потеря активных около {lost_act/2*4.33:.0f}, экономия около {sms_cost/8*4.33:,.0f} ₽")

print("\n== Чувствительность прогнозов к доле оставшихся у СМС (линейная отдача, как в C-068) ==")
cpc = sms_cost / sms_conn
A_sms_cost, B_sms_cost = 1_772_316, 1_000_000
A_total, B0_total, B_total = 2220, 2008, 2820
A_sms_conn, B_sms_conn = A_sms_cost / cpc, B_sms_cost / cpc
for name, r in (("как в таблице", avg_ret), ("как в пилоте", marg)):
    dA = A_sms_conn * (avg_ret - r)
    dB = B_sms_conn * (avg_ret - r)
    A, B0, B = A_total - dA, B0_total - dB, B_total - dB
    print(f"доля СМС {name} {r:.1%}: А {A:.0f}; В0 {B0:.0f} (против А {B0-A:+.0f}); В {B:.0f} (против А {B-A:+.0f})")
print(f"СМС-подключений в месяц: А {A_sms_conn:.0f}, при 1,0 млн ₽ {B_sms_conn:.0f}; отказ от {A_sms_conn-B_sms_conn:.0f} подключений")

print("\n== Порог по салонам: при какой вместимости В не хуже А (как C-085, но с долей СМС из пилота) ==")
salon_ret = 1500 / 1921
salon_base = 467_884 / 450
gap = (A_sms_conn - B_sms_conn) * marg
need = gap / salon_ret
thr = salon_base + need
print(f"нехватка оставшихся у В0 против А: {gap:.1f}; нужно добавить салонных подключений {need:.1f} при доле оставшихся {salon_ret:.1%}")
print(f"порог: {thr:.0f} подключений в месяц ({thr/salon_base:.2f} от нынешних {salon_base:.0f}), {thr/4.33:.0f} в неделю (в C-085: около 1 312 в месяц, 303 в неделю)")
