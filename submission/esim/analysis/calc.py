from math import sqrt
start = {("A", "Android"): 300, ("A", "iOS"): 700, ("B", "Android"): 700, ("B", "iOS"): 300}
ok = {("A", "Android"): 180, ("A", "iOS"): 630, ("B", "Android"): 455, ("B", "iOS"): 276}
for w in "AB":
    s = sum(start[w, o] for o in ("Android", "iOS"))
    k = sum(ok[w, o] for o in ("Android", "iOS"))
    print(w, "всего", k, "из", s, round(100 * k / s, 1))
se = {}
for o in ("Android", "iOS"):
    pa, pb = ok["A", o] / start["A", o], ok["B", o] / start["B", o]
    se[o] = sqrt(pa * (1 - pa) / start["A", o] + pb * (1 - pb) / start["B", o])
    print(o, "A", round(100 * pa, 1), "B", round(100 * pb, 1), "разница п.п.", round(100 * (pb - pa), 1), "+-95%", round(196 * se[o], 1))
d = 0.5 * sum(ok["B", o] / start["B", o] - ok["A", o] / start["A", o] for o in se)
e = 0.5 * sqrt(sum(v * v for v in se.values()))
print("при 50/50 разница п.п.", round(100 * d, 1), "интервал", round(100 * (d - 1.96 * e), 1), round(100 * (d + 1.96 * e), 1))
print("A при 50/50", round(100 * 0.5 * (0.6 + 0.9), 1), "B при 50/50", round(100 * 0.5 * (455 / 700 + 276 / 300), 1))
