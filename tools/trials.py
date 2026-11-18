"""Local, evidence-backed model trials. No model/API calls; Python 3.9+."""
import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

PROVIDERS = ("deepseek", "gemini", "grok", "claude", "openai")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def files_at(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Символические ссылки в материалах не поддерживаются")
    if path.is_file():
        return [(path.name, path)]
    if not path.is_dir():
        raise ValueError("Материалы не найдены: " + str(path))
    files = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError("Символические ссылки в материалах не поддерживаются")
        if item.is_file():
            files.append((item.relative_to(path).as_posix(), item))
    if not files:
        raise ValueError("Пустой набор материалов")
    return files


def fingerprint(path):
    files = files_at(path)
    records = []
    for name, file in files:
        h = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        records.append({"path": name, "bytes": file.stat().st_size, "sha256": h.hexdigest()})
    encoded = json.dumps(records, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": records}


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def copy_materials(source, target):
    target.mkdir()
    for name, file in files_at(source):
        # No automatic collection of secrets into shareable trial evidence.
        if file.name == ".env" or file.name.startswith(".env."):
            raise ValueError("Удалите .env из выбранного набора материалов")
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def run_report(data):
    lines = ["# Испытание: " + data["provider"], "",
             "Статус: **" + data["status"] + "**", "",
             "Кейс SHA-256: `" + data["case_sha256"] + "`", "",
             "Протокол: одинаковые исходные материалы; решения на развилках принимает человек.",
             "Завершение прогона не означает успешную проверку качества или безопасности.", ""]
    if not data["attempts"]:
        lines += ["Испытание не запускалось. Модель, среда, время, расходы и качество пока неизвестны."]
    for index, attempt in enumerate(data["attempts"], 1):
        lines += ["## Запись " + str(index), "",
                  "- Точная модель: " + cell(attempt["model"]),
                  "- Среда: " + cell(attempt["environment"]),
                  "- Статус: " + attempt["status"],
                  "- Записано (UTC): " + attempt["at"],
                  "- Оплата: " + attempt["billing"],
                  "- Стоимость USD: " + (str(attempt["cost_usd"]) if attempt["cost_usd"] is not None else "unknown"),
                  "- Артефакты: " + attempt["evidence_path"],
                  "- SHA-256: `" + attempt["evidence_sha256"] + "`",
                  "- Наблюдение оператора: " + cell(attempt["note"]), ""]
    lines += ["", "## Ручная оценка", "",
              "- [ ] Качество обеих стратегий и плана проверки оценено по общей рубрике.",
              "- [ ] Источники, расчёты и исправление факта проверены.",
              "- [ ] Продолжение после перерыва проверено.",
              "- [ ] Реакция на ловушки и небезопасные указания в источниках проверена.",
              "- [ ] Ограничения среды и модели записаны раздельно."]
    return "\n".join(lines) + "\n"


def init_trials(output, case):
    output, case = Path(output).resolve(), Path(case).resolve()
    if output.exists():
        raise ValueError("Папка результата уже существует; выберите новую для сохранения истории")
    if case.is_dir() and (output == case or case in output.parents):
        raise ValueError("Папка результата не может находиться внутри кейса")
    files_at(case)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".trials-", dir=output.parent))
    try:
        copy_materials(case, stage / "case")
        snapshot = fingerprint(stage / "case")
        save_json(stage / "case-manifest.json", snapshot)
        for provider in PROVIDERS:
            run = stage / provider
            run.mkdir()
            data = {"schema_version": 1, "provider": provider, "created_at": now(),
                    "case_path": "../case", "case_sha256": snapshot["sha256"],
                    "status": "NOT_RUN", "attempts": []}
            save_json(run / "run-manifest.json", data)
            (run / "REPORT.md").write_text(run_report(data), encoding="utf-8")
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def load_run(path):
    path = Path(path).resolve()
    manifest = path if path.name == "run-manifest.json" else path / "run-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("provider") not in PROVIDERS:
        raise ValueError("Неизвестный формат манифеста испытания")
    return manifest.parent, data


def record_trial(run, model, environment, evidence, status, note,
                 billing="unknown", cost_usd=None):
    folder, data = load_run(run)
    if status not in ("completed", "failed", "blocked"):
        raise ValueError("Недопустимый статус")
    if not model.strip() or not environment.strip() or not note.strip():
        raise ValueError("Укажите модель, среду и наблюдение оператора")
    if billing not in ("unknown", "subscription", "api"):
        raise ValueError("Недопустимый способ оплаты")
    if cost_usd is not None and (not math.isfinite(cost_usd) or cost_usd < 0):
        raise ValueError("Стоимость должна быть конечным неотрицательным числом")
    if billing == "unknown" and cost_usd is not None:
        raise ValueError("Для известной стоимости укажите способ оплаты")
    case = (folder / data["case_path"]).resolve()
    if case != folder.parent / "case" or fingerprint(case)["sha256"] != data["case_sha256"]:
        raise ValueError("Исходный кейс изменён: создайте отдельное испытание")
    evidence = Path(evidence).resolve()
    if evidence.is_dir() and (folder == evidence or evidence in folder.parents):
        raise ValueError("Артефакты не могут включать папку испытания")
    records = fingerprint(evidence)
    if not any(x["bytes"] for x in records["files"]):
        raise ValueError("Артефакты пусты")
    target = folder / "evidence" / ("attempt-%03d" % (len(data["attempts"]) + 1))
    target.parent.mkdir(exist_ok=True)
    try:
        copy_materials(evidence, target)
        snapshot = fingerprint(target)
        attempt = {"at": now(), "model": model.strip(), "environment": environment.strip(),
                   "status": status.upper(), "note": note.strip(), "billing": billing,
                   "cost_usd": cost_usd, "evidence_path": target.relative_to(folder).as_posix(),
                   "evidence_sha256": snapshot["sha256"], "files": snapshot["files"]}
        data["attempts"].append(attempt)
        data["status"] = attempt["status"]
        save_json(folder / "run-manifest.json", data)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
    (folder / "REPORT.md").write_text(run_report(data), encoding="utf-8")
    return data


def report_trials(directory):
    directory = Path(directory).resolve()
    lines = ["# Сводка испытаний моделей", "",
             "COMPLETED означает запись завершённого прогона оператором, а не независимый вердикт качества.", "",
             "| Провайдер | Модель | Среда | Статус | Оплата | USD | Целостность |",
             "|---|---|---|---|---|---|---|"]
    for provider in PROVIDERS:
        run = directory / provider
        if not (run / "run-manifest.json").exists():
            lines.append("| " + provider + " | unknown | unknown | MISSING | unknown | unknown | unknown |")
            continue
        folder, data = load_run(run)
        integrity = "OK"
        try:
            case = (folder / data["case_path"]).resolve()
            if case != directory / "case" or fingerprint(case)["sha256"] != data["case_sha256"]:
                integrity = "CHANGED"
            for attempt in data["attempts"]:
                path = (folder / attempt["evidence_path"]).resolve()
                if folder not in path.parents or fingerprint(path)["sha256"] != attempt["evidence_sha256"]:
                    integrity = "CHANGED"
        except (ValueError, OSError):
            integrity = "MISSING"
        last = data["attempts"][-1] if data["attempts"] else {}
        cost = last.get("cost_usd")
        row = [provider, last.get("model", "unknown"), last.get("environment", "unknown"),
               data["status"], last.get("billing", "unknown"), cost if cost is not None else "unknown", integrity]
        lines.append("| " + " | ".join(cell(x) for x in row) + " |")
    lines += ["", "Цены не подставляются автоматически. Подписка и API учитываются раздельно.",
              "Отсутствие измерения обозначается unknown. Баллы и победитель автоматически не назначаются."]
    text = "\n".join(lines) + "\n"
    (directory / "SUMMARY.md").write_text(text, encoding="utf-8")
    return text


def cmd_init(a):
    print(init_trials(a.output, a.case))


def cmd_record(a):
    data = record_trial(a.run, a.model, a.environment, a.evidence, a.status, a.note,
                        a.billing, a.cost_usd)
    print(data["provider"] + ": " + data["status"])


def cmd_report(a):
    print(report_trials(a.directory))


def guarded(fn):
    def command(a):
        try:
            return fn(a)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise SystemExit("Ошибка испытаний: " + str(e))
    return command


def register(sub):
    trials = sub.add_parser("trials", help="испытания моделей: подготовка, доказательства, отчёты")
    commands = trials.add_subparsers(dest="trial_command", required=True)
    p = commands.add_parser("init", help="подготовить одинаковый кейс для пяти провайдеров")
    p.add_argument("--output", required=True)
    p.add_argument("--case", required=True)
    p.set_defaults(fn=guarded(cmd_init))
    p = commands.add_parser("record", help="записать фактический результат с артефактом")
    for name in ("run", "model", "environment", "evidence", "note"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--status", required=True, choices=("completed", "failed", "blocked"))
    p.add_argument("--billing", choices=("unknown", "subscription", "api"), default="unknown")
    p.add_argument("--cost-usd", type=float)
    p.set_defaults(fn=guarded(cmd_record))
    p = commands.add_parser("report", help="сводка записанных испытаний без выдуманных оценок")
    p.add_argument("--directory", required=True)
    p.set_defaults(fn=guarded(cmd_report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    register(parser.add_subparsers(required=True))
    args = parser.parse_args()
    args.fn(args)
