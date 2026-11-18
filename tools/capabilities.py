"""Local capability inventory and explicit, advisory model routing (stdlib only)."""
import argparse
import importlib.util
import sqlite3
import json
import re
import math
import shutil
import sys
import tempfile
import os
import subprocess
from contextlib import closing
from pathlib import Path

ROLES = ("extractor", "analyst", "researcher", "critic", "strategist")
PRICE_BASIS = "USD per 1M input + 1M output tokens, excluding cache"


def detect_host(env):
    markers = {'opencode': ('OPENCODE', 'OPENCODE_CLIENT'), 'codex': ('CODEX_THREAD_ID',),
               'claude': ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT'), 'cursor': ('CURSOR_TRACE_ID', 'CURSOR_AGENT')}
    signals = [host for host, keys in markers.items() if any(env.get(k) not in (None, '', '0', 'false') for k in keys)]
    if env.get('TERM_PROGRAM', '').lower() == 'cursor' and 'cursor' not in signals:
        signals.append('cursor')
    return {'host': signals[0] if len(signals) == 1 else 'unknown', 'signals': signals}


def discover(args):
    detected = detect_host(os.environ)
    host = args.host or detected['host']
    result = dict(detected, host=host, source='explicit' if args.host else 'environment',
                  catalog_status='unknown', listed=[], verified_for_billing=False)
    if host == 'opencode':
        executable = shutil.which('opencode')
        if executable:
            try:
                response = subprocess.run([executable, 'models'], capture_output=True, text=True,
                                          encoding='utf-8', errors='replace', timeout=12, check=True)
                listed = sorted({line.strip() for line in response.stdout.splitlines()
                                 if re.fullmatch(r'[\w.-]+/[\w./:-]+', line.strip())})
                result.update(listed=listed, catalog_status='listed' if listed else 'unknown')
            except (OSError, subprocess.SubprocessError):
                result['reason'] = 'Команда каталога недоступна'
        else:
            result['reason'] = 'CLI opencode отсутствует в PATH этого процесса'
    emit(result)


def inspect_local():
    return {
        "python": {"path": sys.executable, "version": sys.version.split()[0]},
        "sqlite": sqlite3.sqlite_version,
        "pdf_available": importlib.util.find_spec("pypdf") is not None,
        "executables": {name: shutil.which(name) for name in
                        ("ffmpeg", "whisper", "cursor", "claude", "codex", "opencode")},
        "media_environment": str(Path(__file__).resolve().parents[1] / ".venv-media") if (Path(__file__).resolve().parents[1] / ".venv-media").is_dir() else None,
        "media_notice": "Наличие среды не подтверждает установку зависимостей; проверка: media на тестовой записи.",
        "models": "unknown",
        "notice": "Наличие CLI не доказывает вход в аккаунт, доступ к модели или права на инструменты.",
    }


def template():
    return {
        "environment": "укажите среду и версию, например Cursor",
        "price_basis": PRICE_BASIS,
        "models": [],
        "instructions": "Добавьте только точные ID из вашей среды. См. docs/model-routing.md. "
                        "Семейства DeepSeek, Gemini, Grok, Claude, GPT не являются ID моделей.",
    }


def validate_inventory(data):
    if not isinstance(data, dict):
        raise ValueError("inventory должен быть объектом JSON")
    if not isinstance(data.get("environment"), str) or not data["environment"].strip():
        raise ValueError("environment: нужна непустая строка")
    if data.get("price_basis") != PRICE_BASIS:
        raise ValueError("price_basis должен совпадать с шаблоном для сравнимости цен")
    models = data.get("models")
    if not isinstance(models, list):
        raise ValueError("models должен быть списком")
    ids = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("каждая модель должна быть объектом")
        for key in ("id", "provider", "evidence"):
            if not isinstance(model.get(key), str):
                raise ValueError(key + ": нужна строка")
        if not model["id"].strip() or not model["provider"].strip():
            raise ValueError("id и provider не должны быть пустыми")
        key = (model["provider"], model["id"])
        if key in ids:
            raise ValueError("повтор модели: " + model["id"])
        ids.add(key)
        if type(model.get("available")) is not bool:
            raise ValueError("available должен быть true или false")
        if model["available"] and not model["evidence"].strip():
            raise ValueError("для доступной модели требуется evidence: основание и дата проверки")
        roles = model.get("roles")
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            raise ValueError("roles: допустимы " + ", ".join(ROLES))
        price = model.get("price")
        if price is not None and (type(price) not in (int, float) or
                                  not math.isfinite(price) or price < 0):
            raise ValueError("price: неотрицательное конечное число или null")
    return data


def choose_model(data, role):
    validate_inventory(data)
    if role not in ROLES:
        raise ValueError("неизвестная роль")
    eligible = [m for m in data["models"] if m["available"] and role in m["roles"]]
    result = {"environment": data["environment"], "role": role,
              "selected": None, "status": "unavailable", "switched": False,
              "price_basis": PRICE_BASIS,
              "notice": "Рекомендация по заявленному inventory. Модель не переключена; "
                        "права на инструменты и актуальную доступность проверяет среда."}
    if not eligible:
        result["reason"] = "Нет подтверждённой доступной модели с этой ролью. Нужен выбор пользователя или обновление inventory."
        return result
    priced = [m for m in eligible if m.get("price") is not None]
    unknown = [m["id"] for m in eligible if m.get("price") is None]
    chosen = min(priced, key=lambda m: (m["price"], m["provider"], m["id"])) if priced else eligible[0]
    if len(eligible) == 1:
        reason = "Единственная доступная модель для роли; запасной режим без сравнения альтернатив."
    elif not priced:
        reason = "Цены неизвестны: выбрана первая подходящая модель в inventory. Экономичность не установлена."
    elif unknown:
        reason = "Минимальная указанная цена среди моделей с известной ценой. Сравнение с моделями без цены невозможно."
    else:
        reason = "Минимальная указанная цена среди доступных моделей с нужной ролью при единой расчётной нагрузке."
    result.update(status="recommended", selected={k: chosen.get(k) for k in
                  ("id", "provider", "price", "evidence")}, reason=reason,
                  unknown_prices=unknown, single_model_fallback=len(eligible) == 1)
    return result


def emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_inspect(args):
    emit(inspect_local())


def cmd_template(args):
    path = Path(args.output)
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(template(), f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as exc:
        raise SystemExit("Не удалось создать inventory (существующий файл не перезаписывается): " + str(exc))
    print(str(path))


def cmd_route(args):
    try:
        data = json.loads(Path(args.inventory).read_text(encoding="utf-8-sig"))
        result = choose_model(data, args.role)
    except (OSError, ValueError) as exc:
        print("Ошибка inventory: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
    emit(result)
    if result["selected"] is None:
        raise SystemExit(1)


def cmd_mcp_config(args):
    python = str(Path(sys.executable).resolve())
    server = str(Path(__file__).resolve().with_name('mcp_server.py'))
    if args.host == 'opencode':
        config = {'mcp': {'servers': {'strateg': {'type': 'local', 'command': [python, server], 'codemode': False}}}}
    elif args.host == 'opencode-v1':
        config = {'mcp': {'strateg': {'type': 'local', 'command': [python, server], 'enabled': True}}}
    else:
        config = {'mcpServers': {'strateg': {'command': python, 'args': [server]}}}
    if args.playwright_executable:
        executable = Path(args.playwright_executable).resolve()
        if not executable.is_file():
            raise SystemExit('Укажи существующий исполняемый файл Playwright MCP')
        command = [str(executable), '--isolated', '--block-service-workers']
        if args.host == 'opencode':
            config['mcp']['servers']['playwright'] = {'type': 'local', 'command': command, 'codemode': False}
        elif args.host == 'opencode-v1':
            config['mcp']['playwright'] = {'type': 'local', 'command': command, 'enabled': True}
        else:
            config['mcpServers']['playwright'] = {'command': command[0], 'args': command[1:]}
    if args.output:
        try:
            with Path(args.output).open('x', encoding='utf-8') as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
                file.write('\n')
        except OSError as exc:
            raise SystemExit(f'Конфигурация не сохранена: {exc}') from None
    else:
        emit(config)


def cmd_claude_profile(args):
    try:
        assignments = json.loads(Path(args.assignments).read_text(encoding='utf-8-sig'))
        roles = ('extractor', 'analyst', 'researcher', 'critic', 'respondent')
        if not isinstance(assignments, dict) or not assignments or set(assignments) - set(roles):
            raise ValueError('Нужна карта ролей: extractor, analyst, researcher, critic, respondent')
        generated = {}
        for role, model in assignments.items():
            if not isinstance(model, str) or not re.fullmatch(r'(?:haiku|sonnet|opus|inherit|claude-[a-z0-9.-]+)', model):
                raise ValueError(f'{role}: нужен допустимый Claude ID либо alias роли')
            template_file = Path(__file__).resolve().parents[1] / '.claude' / 'agents' / (role + '.md')
            original = template_file.read_text(encoding='utf-8')
            config = re.sub(r'(?m)^model: [^\n]+$', 'model: ' + model, original, count=1)
            if 'model: ' + model not in config.split('---', 2)[1]:
                raise ValueError(f'{role}: шаблон не содержит model')
            generated[role] = config
        destination = Path(args.output_dir)
        destination.mkdir()
        for role, config in generated.items():
            (destination / (role + '.md')).write_text(config, encoding='utf-8')
        emit({'directory': str(destination), 'configured_roles': sorted(generated)})
    except (OSError, ValueError) as exc:
        raise SystemExit(f'Профиль Claude не создан: {exc}') from None


def sync_claude(root, assignments, dry_run=False):
    """Apply only frontmatter models; validate the entire batch before writing."""
    root = Path(root).resolve()
    lock_path = root / '.claude-sync.sqlite3'
    if lock_path.is_symlink():
        raise ValueError('Файл блокировки не должен быть ссылкой')
    with closing(sqlite3.connect(lock_path, timeout=10)) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        return _sync_claude_locked(root, assignments, dry_run)


def _sync_claude_locked(root, assignments, dry_run):
    roles = {'extractor', 'analyst', 'researcher', 'critic', 'respondent'}
    if not isinstance(assignments, dict) or not assignments or set(assignments) - roles:
        raise ValueError('Нужна непустая карта известных ролей Claude')
    pending = {}
    for role, model in assignments.items():
        if not isinstance(model, str) or not re.fullmatch(r'(?:haiku|sonnet|opus|inherit|claude-[a-z0-9.-]+)', model):
            raise ValueError(f'{role}: недопустимая модель Claude')
        file = root / '.claude' / 'agents' / (role + '.md')
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('Профиль должен находиться внутри рабочей копии')
        original = file.read_bytes()
        text = original.decode('utf-8')
        front = re.match(r'\A(?:\ufeff)?---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
        if not front or len(re.findall(r'(?m)^model:[^\r\n]*', front[1])) != 1:
            raise ValueError(f'{role}: требуется ровно одно поле model в frontmatter')
        header = re.sub(r'(?m)^model:[^\r\n]*', 'model: ' + model, front[1])
        updated = (text[:front.start(1)] + header + text[front.end(1):]).encode('utf-8')
        if original != updated:
            pending[role] = (file, original, updated)
    if not dry_run and pending:
        # Atomic replacement per file, rollback on ordinary write failures.
        with tempfile.TemporaryDirectory(dir=root, prefix='.claude-sync-') as temp:
            staged = {}
            for role, (file, original, updated) in pending.items():
                stage = Path(temp) / role
                stage.write_bytes(updated)
                staged[role] = stage
            changed = []
            try:
                for role, (file, original, updated) in pending.items():
                    if file.read_bytes() != original:
                        raise ValueError(f'{role}: профиль изменён другим процессом')
                    staged[role].replace(file)
                    changed.append(role)
            except (OSError, ValueError) as exc:
                conflicts = []
                for role in reversed(changed):
                    file, original, updated = pending[role]
                    if file.read_bytes() != updated:
                        conflicts.append(role)
                        continue  # Never overwrite an intervening user's edit.
                    backup = Path(temp) / role
                    backup.write_bytes(original)
                    backup.replace(file)
                if conflicts:
                    raise ValueError(f'{exc}; чужие правки сохранены без отката: {", ".join(conflicts)}') from exc
                raise
    return {'changed': sorted(pending), 'applied': not dry_run,
            'notice': 'Назначения для следующих запусков субагентов; текущая модель чата не переключается.'}


def cmd_claude_sync(args):
    try:
        assignments = json.loads(Path(args.assignments).read_text(encoding='utf-8-sig'))
        emit(sync_claude(Path(__file__).resolve().parents[1], assignments, args.dry_run))
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f'Профиль не применён: {exc}') from None


def register(sub):
    cap = sub.add_parser("capabilities", help="локальные инструменты и явный список моделей")
    actions = cap.add_subparsers(dest="capabilities_action", required=True)
    p = actions.add_parser('discover', help='определить хост и запросить каталог без вызова модели')
    p.add_argument('--host', choices=['opencode', 'cursor', 'claude', 'codex'])
    p.set_defaults(fn=discover)
    actions.add_parser("inspect", help="проверить исполняемые файлы без входа в сервисы").set_defaults(fn=cmd_inspect)
    p = actions.add_parser("template", help="создать пустой inventory")
    p.add_argument("--output", required=True)
    p.set_defaults(fn=cmd_template)
    p = actions.add_parser('mcp-config', help='сгенерировать конфигурацию MCP для рабочей копии')
    p.add_argument('--host', choices=['cursor', 'claude', 'opencode', 'opencode-v1'], required=True)
    p.add_argument('--output')
    p.add_argument('--playwright-executable', help='дополнительно подключить уже установленный Playwright MCP')
    p.set_defaults(fn=cmd_mcp_config)
    p = actions.add_parser('claude-profile', help='собрать отдельный профиль моделей субагентов')
    p.add_argument('--assignments', required=True)
    p.add_argument('--output-dir', required=True)
    p.set_defaults(fn=cmd_claude_profile)
    p = actions.add_parser('claude-sync', help='применить модели к активным файлам .claude/agents')
    p.add_argument('--assignments', required=True)
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(fn=cmd_claude_sync)
    p = sub.add_parser("route", help="рекомендовать доступную модель для роли")
    p.add_argument("--inventory", required=True)
    p.add_argument("--role", choices=ROLES, required=True)
    p.set_defaults(fn=cmd_route)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    register(parser.add_subparsers(required=True))
    args = parser.parse_args()
    args.fn(args)
