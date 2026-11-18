#!/usr/bin/env python3
"""Чувствительность теста экрана 1: половина подключений видит новый экран, половина старый, 4 недели.
Данные вымышлены. Запуск: python3 -I projects/ryadom-prodazhi/analysis/test_power.py
Читает materials/sales.csv, ничего не меняет.
Допущения: подключения поровну между группами, доля оставшихся в контроле как за 8 недель (по строкам, где известны
и подключения, и отключения), двусторонний уровень значимости 5%, мощность 80%, нормальное приближение для двух долей."""
import csv
from math import sqrt
from pathlib import Path

MAT = Path(__file__).resolve().parent.parent / "materials"
seen, rows = set(), []
with open(MAT / "sales.csv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        k = (r["неделя_с"], r["канал"])
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)

weeks = len({r["неделя_с"] for r in rows})
sub = sum(int(r["подключения"]) for r in rows if r["подключения"] != "")
both = [r for r in rows if r["подключения"] != "" and r["отключились_за_30_дней"] != ""]
keep = 1 - sum(int(r["отключились_за_30_дней"]) for r in both) / sum(int(r["подключения"]) for r in both)

per_week = sub / weeks
n_total = per_week * 4
n_arm = n_total / 2
z_a, z_b = 1.96, 0.84
se = sqrt(2 * keep * (1 - keep) / n_arm)
mde = (z_a + z_b) * se

print(f"Подключений в неделю в среднем: {per_week:,.0f}; за 4 недели {n_total:,.0f}; в каждой группе около {n_arm:,.0f}")
print(f"Доля оставшихся через 30 дней сейчас: {100 * keep:.1f}%")
print(f"Стандартная ошибка разницы долей: {100 * se:.2f} п.п.")
print(f"Разница, которую тест замечает с мощностью 80% при уровне 5%: около {100 * mde:.1f} п.п.")
print(f"Разница, заметная при уровне 5% с мощностью 50%: около {100 * z_a * se:.1f} п.п.")
print(f"Для ориентира C-074: +10 п.п. при 4 855 подключениях в месяц = 486 оставшихся; тест такую разницу замечает уверенно")
print("Группа набирается 4 недели; доля оставшихся известна через 30 дней после набора последнего подключившего")
