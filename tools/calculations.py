"""Portable product calculations from explicit, comparable inputs."""
import json
import math
from pathlib import Path


def number(value, label, count=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (count and int(value) != value):
        raise ValueError(f'{label}: нужно конечное неотрицательное число' + (' целых единиц' if count else ''))
    return int(value) if count else value


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


KINDS = ('economics', 'funnel', 'retention', 'retention-change', 'growth', 'market-size', 'decision-regret')


def decision_regret(data):
    """Compare options across common scenarios in integer units of one metric."""
    direction = data.get('direction')
    if direction not in ('max', 'min') or not isinstance(data.get('metric'), str) or not data['metric'].strip():
        raise ValueError('Укажите общую метрику с единицей и периодом и direction: max или min')
    options = data.get('options')
    if not isinstance(options, dict) or len(options) < 2:
        raise ValueError('Нужны как минимум два варианта')
    states = None
    for name, values in options.items():
        if not name.strip() or not isinstance(values, dict) or len(values) < 2:
            raise ValueError('У каждого именованного варианта должно быть минимум два сценария')
        if any(not state.strip() or type(value) is not int for state, value in values.items()):
            raise ValueError('Нужны именованные сценарии и целые значения в общей единице')
        if states is None:
            states = list(values)
        elif set(values) != set(states):
            raise ValueError('Набор сценариев должен совпадать у всех вариантов')
    best = max if direction == 'max' else min
    benchmarks = {s: best(row[s] for row in options.values()) for s in states}
    regrets = {name: {s: abs(row[s] - benchmarks[s]) for s in states} for name, row in options.items()}
    worst = {name: max(row.values()) for name, row in regrets.items()}
    smallest = min(worst.values())
    return {'best_by_scenario': benchmarks, 'regret_by_option': regrets, 'worst_regret': worst,
            'minimax_options': [name for name in options if worst[name] == smallest]}


def retention_change(data):
    cohorts = data['segments']
    if not isinstance(cohorts, list) or not cohorts:
        raise ValueError('Нужны сопоставимые segments для двух периодов')
    named = set()
    parsed = []
    for segment in cohorts:
        name = segment['name']
        if not isinstance(name, str) or not name.strip() or name in named:
            raise ValueError('Нужны уникальные названия сегментов')
        named.add(name)
        pairs = []
        for period in ('before', 'after'):
            base = number(segment[period]['size'], f'{name} {period} size', True)
            kept = number(segment[period]['retained'], f'{name} {period} retained', True)
            if not base or kept > base:
                raise ValueError(f'{name}: в обоих периодах нужна ненулевая база, удержание ≤ базы')
            pairs.append((base, kept))
        parsed.append((name, *pairs))
    bases = [sum(row[i][0] for row in parsed) for i in (1, 2)]
    kept = [sum(row[i][1] for row in parsed) for i in (1, 2)]
    parts = []
    for name, before, after in parsed:
        w0, w1 = before[0] / bases[0], after[0] / bases[1]
        r0, r1 = before[1] / before[0], after[1] / after[0]
        parts.append(dict(name=name, before_rate=r0, after_rate=r1, before_weight=w0, after_weight=w1,
                          mix_pp=100 * (w1 - w0) * (r0 + r1) / 2,
                          within_pp=100 * (r1 - r0) * (w0 + w1) / 2))
    old, new = kept[0] / bases[0], kept[1] / bases[1]
    return dict(before_rate=old, after_rate=new, before_base=bases[0], after_base=bases[1], change_pp=(new-old)*100,
                mix_pp=math.fsum(p['mix_pp'] for p in parts), within_pp=math.fsum(p['within_pp'] for p in parts),
                segments=parts, interpretation='Разложение описывает изменение при заданных сегментах и периодах; причинность не установлена')


def proportion(value, label):
    value = number(value, label)
    if value > 1:
        raise ValueError(f'{label}: ожидается доля от 0 до 1')
    return value


def growth(data):
    opening = number(data['initial_customers'], 'initial_customers')
    price = number(data['price_per_period'], 'price_per_period')
    rows = data['periods']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 120:
        raise ValueError('Нужно от 1 до 120 периодов')
    periods = []
    for row in rows:
        eligible = number(row['eligible_visitors'], 'eligible_visitors', True)
        activation = proportion(row['activation_rate'], 'activation_rate')
        conversion = proportion(row['activated_to_paid'], 'activated_to_paid')
        churn = proportion(row['churn_rate'], 'churn_rate')
        new = eligible * activation * conversion
        lost = opening * churn
        closing = opening - lost + new
        periods.append({'name': row['name'], 'opening_customers': opening, 'new_customers': new,
                        'lost_customers': lost, 'closing_customers': closing, 'closing_run_rate': closing * price})
        opening = closing
    return {'periods': periods, 'assumption': 'Прогноз по заданным долям. Новые платящие начинают уходить со следующего периода.'}


def market_size(data):
    base = number(data['eligible_accounts'], 'eligible_accounts', True)
    served = proportion(data['serviceable_share'], 'serviceable_share')
    adoption = proportion(data['obtainable_share'], 'obtainable_share')
    price = number(data['revenue_per_account_period'], 'revenue_per_account_period')
    return {'eligible_accounts': base, 'serviceable_accounts': base * served,
            'obtainable_accounts': base * served * adoption, 'total_revenue_potential': base * price,
            'serviceable_revenue_potential': base * served * price,
            'obtainable_revenue_scenario': base * served * adoption * price,
            'assumption': 'Доли заданы пользователем, доля охвата не означает подтверждённый спрос.'}


def calculate(kind, data):
    if kind not in KINDS:
        raise ValueError('Неизвестный вид расчёта')
    if kind == 'decision-regret':
        return decision_regret(data)
    if kind == 'retention-change':
        return retention_change(data)
    if kind == 'growth':
        return growth(data)
    if kind == 'market-size':
        return market_size(data)
    if kind == 'economics':
        price, variable, fixed, users, spend, acquired = (
            number(data[k], k, k in {'paying_users', 'new_customers'}) for k in
            ('price', 'variable_cost_per_user', 'fixed_cost', 'paying_users', 'acquisition_spend', 'new_customers'))
        margin = price - variable
        cac = rate(spend, acquired)
        output = dict(revenue=price * users, contribution_per_user=margin,
                    operating_result=margin * users - fixed - spend,
                    break_even_users=math.ceil((fixed + spend) / margin) if margin > 0 else None,
                    acquisition_cost_per_customer=cac,
                    payback_periods=cac / margin if cac is not None and margin > 0 else None)
        if 'period_churn' in data:
            churn = proportion(data['period_churn'], 'period_churn')
            ltv = margin / churn if churn > 0 else None
            output.update(ltv_constant_churn=ltv, ltv_to_cac=ltv / cac if ltv is not None and cac else None)
        return output
    if kind == 'retention':
        rows = data['cohorts']
        if not isinstance(rows, list) or not rows:
            raise ValueError('Нужен непустой список cohorts одного возраста')
        results = []
        for row in rows:
            base = number(row['size'], 'size', True)
            retained = number(row['retained'], 'retained', True)
            if retained > base:
                raise ValueError('Число оставшихся превышает размер когорты')
            results.append(dict(name=row['name'], size=base, retained=retained, rate=rate(retained, base)))
        base = sum(r['size'] for r in results)
        retained = sum(r['retained'] for r in results)
        return dict(cohorts=results, size=base, retained=retained, weighted_rate=rate(retained, base))
    stages = data['stages']
    if not isinstance(stages, list) or len(stages) < 2:
        raise ValueError('Для воронки нужны минимум два этапа одной группы')
    results = []
    previous = None
    for item in stages:
        count = number(item['count'], 'count', True)
        if previous is not None and count > previous:
            raise ValueError('Вложенная воронка не может расти между этапами')
        results.append(dict(name=item['name'], count=count,
                            from_previous=rate(count, previous) if previous is not None else None,
                            lost=previous - count if previous is not None else None))
        previous = count
    return dict(stages=results, overall_rate=rate(previous, results[0]['count']))


def cmd(a):
    try:
        data = json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
        result = calculate(a.kind, data)
        report = {'calculation': a.kind, 'inputs': data, 'result': result}
        if 'scenarios' in data:
            if not isinstance(data['scenarios'], dict):
                raise ValueError('scenarios — объект с именованными вариантами расчёта')
            report['scenarios'] = {}
            for name, changes in data['scenarios'].items():
                if not isinstance(changes, dict) or set(changes) - (data.keys() - {'scenarios'}):
                    raise ValueError(f'Сценарий {name}: используйте поля базового расчёта')
                inputs = {**data, **changes}
                inputs.pop('scenarios')
                report['scenarios'][name] = {'inputs': inputs, 'result': calculate(a.kind, inputs)}
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if a.output:
            with Path(a.output).open('x', encoding='utf-8') as f:
                f.write(output + '\n')
        else:
            print(output)
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise SystemExit(f'Расчёт не выполнен: {exc}') from None


def register(sub):
    parser = sub.add_parser('calc', help='экономика, воронка и удержание по явным исходным данным')
    parser.add_argument('kind', choices=KINDS)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output')
    parser.set_defaults(fn=cmd)
