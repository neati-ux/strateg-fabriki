"""Budget whole calendar days for a prospective product experiment."""

import argparse
from fractions import Fraction
from datetime import date, timedelta
from math import ceil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--deadline", type=date.fromisoformat, help="последний день для готового решения")
    duration = parser.add_mutually_exclusive_group(required=True)
    duration.add_argument("--days", type=int)
    duration.add_argument("--weeks", type=int)
    parser.add_argument("--prep-days", required=True, type=int)
    parser.add_argument("--window-hours", required=True, type=int)
    parser.add_argument("--analysis-days", type=int, default=1)
    parser.add_argument("--weekly-starts", type=int, help="ожидаемое число стартов в неделю")
    parser.add_argument("--groups", type=int, default=2, help="число равных групп")
    args = parser.parse_args()
    days = args.weeks * 7 if args.weeks is not None else args.days
    if min(days, args.prep_days, args.analysis_days, args.window_hours) < 1:
        parser.error("All durations must be positive")
    if args.deadline is not None:
        days = min(days, (args.deadline - args.start).days + 1)
    if args.groups < 1 or (args.weekly_starts is not None and args.weekly_starts < 0):
        parser.error("Invalid group count or weekly volume")
    followup = ceil(args.window_hours / 24)
    enrollment = days - args.prep_days - followup - args.analysis_days
    if enrollment < 1:
        parser.error("No time for enrollment within the deadline")
    start = args.start
    for label, duration in (
        ("Подготовка", args.prep_days),
        ("Набор участников", enrollment),
        ("Завершение наблюдения", followup),
        ("Анализ и решение", args.analysis_days),
    ):
        end = start + timedelta(days=duration - 1)
        print(f"{label}: {start} — {end} ({duration})")
        start = end + timedelta(days=1)
    print(f"Весь цикл: {args.start} — {end}, {days} календарных дней включительно")
    if args.deadline is not None:
        print(f"Крайний срок показа: {args.deadline}; запас: {(args.deadline - end).days} дн.")
    if args.weekly_starts is not None:
        per_group = Fraction(args.weekly_starts * enrollment, 7 * args.groups)
        print(f"При равномерном потоке: {args.weekly_starts} × {enrollment} / 7 / {args.groups}"
              f" ≈ {round(per_group)} стартов на группу (оценка)")


if __name__ == "__main__":
    main()
