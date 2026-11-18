"""Preview a model budget before starting project work."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from capabilities import ROLES, validate_inventory

MODES = ('economy', 'balanced', 'maximum')


def money(value):
    if type(value) not in (str, int, float):
        raise ValueError('Цена должна быть числом или десятичной строкой')
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Цена должна быть конечной и неотрицательной')
    return result


def preview(inventory, request, budget=None):
    validate_inventory(inventory)
    models = []
    for model in inventory['models']:
        level = model.get('level', 'economy')
        if level not in MODES:
            raise ValueError(f'{model["id"]}: неизвестный level')
        rates = model.get('rates_usd_per_million')
        if rates is not None:
            rates = (money(rates['input']), money(rates['output']))
        context = model.get('context_tokens')
        if context is not None and (type(context) is not int or context <= 0):
            raise ValueError('context_tokens должен быть положительным целым числом')
        models.append((model, level, rates, context))
        features = model.get('features', [])
        if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
            raise ValueError('features должен быть списком строк')
    tasks = request['operations']
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('operations должен быть непустым списком')
    recommended = request.get('suggested_mode', 'balanced')
    if recommended not in MODES:
        raise ValueError('Неизвестный suggested_mode')
    ids = set()
    for task in tasks:
        name = task['id']
        if not isinstance(name, str) or not name.strip() or '#' in name or name in ids:
            raise ValueError('Операциям нужны уникальные непустые ID')
        ids.add(name)
        if task['role'] not in (*ROLES, 'code') or task.get('from_mode', 'economy') not in MODES:
            raise ValueError(f'{name}: неизвестная роль или режим')
        requires = task.get('requires', [])
        if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
            raise ValueError(f'{name}: requires должен быть списком строк')
        for field in ('input_tokens', 'max_output_tokens'):
            if task['role'] != 'code' and (type(task[field]) is not int or task[field] <= 0):
                raise ValueError(f'{name}: {field} должен быть положительным целым числом')
    custom = request.get('custom')
    if custom is not None:
        if not isinstance(custom, dict) or set(custom) != {t['id'] for t in tasks if t['role'] != 'code'}:
            raise ValueError('custom должен назначать модель каждой модельной операции')
        for identity in custom.values():
            if not isinstance(identity, list) or len(identity) != 2 or not all(isinstance(v, str) for v in identity):
                raise ValueError('Назначение custom: [provider, model_id]')
    plans = {}
    manual_choices = {}
    for task in tasks:
        if task['role'] == 'code':
            continue
        manual_choices[task['id']] = [
            [m['provider'], m['id']] for m, _, _, context in models
            if m['available'] and task['role'] in m['roles']
            and context is not None and context >= task['input_tokens'] + task['max_output_tokens']
            and set(task.get('requires', [])) <= set(m.get('features', []))]
    for mode in (*MODES, 'custom') if custom is not None else MODES:
        steps = []
        total = Decimal(0)
        for task in tasks:
            if mode != 'custom' and MODES.index(task.get('from_mode', 'economy')) > MODES.index(mode):
                continue
            row = {'id': task['id'], 'role': task['role']}
            if task['role'] == 'code':
                steps.append(dict(row, status='planned', executor='code', estimated_usd='0'))
                continue
            needed = task['input_tokens'] + task['max_output_tokens']
            candidates = []
            for m, level, rates, context in models:
                if not m['available'] or task['role'] not in m['roles']:
                    continue
                if mode == 'custom' and [m['provider'], m['id']] != custom[task['id']]:
                    continue
                if mode != 'custom' and MODES.index(level) > MODES.index(mode):
                    continue
                if set(task.get('requires', [])) - set(m.get('features', [])):
                    continue
                if context is None or context < needed or rates is None:
                    continue
                budget_input = context if m['provider'] == 'deepseek' else task['input_tokens']
                price = (rates[0] * budget_input + rates[1] * task['max_output_tokens']) / 1_000_000
                depth = MODES.index(level) if task['role'] in ('critic', 'strategist') else 0
                candidates.append((-depth, price, m['provider'], m['id']))
            if not candidates:
                steps.append(dict(row, status='unpriced_or_unavailable'))
                continue
            _, price, provider, model_id = min(candidates)
            fallback = task.get('fallback')
            alternative = None
            if fallback is not None:
                if not isinstance(fallback, list) or len(fallback) != 2 or not all(isinstance(v, str) for v in fallback):
                    raise ValueError('fallback: [provider, model_id]')
                alternative = next((c for c in candidates if list(c[2:]) == fallback and c[2:] != (provider, model_id)), None)
                if mode == 'custom' and fallback != [provider, model_id]:
                    for m, _, rates, context in models:
                        if [m['provider'], m['id']] != fallback or not m['available'] or task['role'] not in m['roles']:
                            continue
                        if rates is None or context is None or context < needed or set(task.get('requires', [])) - set(m.get('features', [])):
                            continue
                        budget_input = context if m['provider'] == 'deepseek' else task['input_tokens']
                        extra_cost = (rates[0] * budget_input + rates[1] * task['max_output_tokens']) / 1_000_000
                        alternative = (0, extra_cost, *fallback)
                        break
            total += price
            steps.append(dict(row, status='planned', executor='model', model=model_id, provider=provider, estimated_usd=str(price), input_tokens=task['input_tokens'], max_output_tokens=task['max_output_tokens']))
            if alternative is not None:
                steps[-1]['fallback'] = {'provider': alternative[2], 'model': alternative[3], 'estimated_usd': str(alternative[1])}
        complete = bool(steps) and all(s['status'] == 'planned' for s in steps)
        status = 'incomplete' if not complete else 'over_budget' if budget is not None and total > budget else 'within_estimate'
        fallback_total = sum((Decimal(s['fallback']['estimated_usd']) for s in steps if s.get('fallback')), Decimal(0))
        plans[mode] = dict(status=status, estimated_usd=str(total) if complete else None,
                           estimated_with_one_fallback_each_usd=str(total + fallback_total) if complete else None,
                           operations=steps)
    available = [m for m in MODES[:MODES.index(recommended)+1] if plans[m]['status'] == 'within_estimate']
    return {'model_suggested_mode': recommended, 'reason': request.get('reason'),
            'recommended_mode': available[-1] if available else None,
            'budget_usd': str(budget) if budget is not None else None,
            'plans': plans,
            'custom_choices_by_operation': manual_choices,
            'notice': 'Оценка по заданным токенам и тарифам. Без повторов, кэша и расходов текущего чата. Нужен выбор пользователя.'}


def command(args):
    try:
        inventory = json.loads(Path(args.inventory).read_text(encoding='utf-8-sig'))
        request = json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
        result = preview(inventory, request, money(args.budget_usd) if args.budget_usd is not None else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, InvalidOperation, KeyError, TypeError) as exc:
        raise SystemExit(f'Оценка маршрута не выполнена: {exc}') from None


def register(sub):
    parser = sub.add_parser('route-preview', help='рассчитать варианты глубины и расходы до запуска')
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--request', required=True)
    parser.add_argument('--budget-usd')
    parser.set_defaults(fn=command)
