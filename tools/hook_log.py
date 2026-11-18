#!/usr/bin/env python3
"""Хук Claude Code. Вызывается после каждого действия агента и в конце ответа.

Делает три вещи:
1. Пишет действие в projects/<активный>/log.jsonl.
2. В конце ответа считает токены по моделям и пишет в usage.json.
3. После правки результатов или реестра запускает проверку. Если есть ошибки,
   возвращает их агенту (код выхода 2), чтобы он исправил их до продолжения.

Собственные сбои хука работу агента не останавливают.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

SECRET = re.compile(r"(?i)(key|token|secret|password|passwd|authorization)(\s*[=:]\s*)\S+")
GATED = re.compile(r"^(outputs/.+\.md|claims\.csv|decisions\.md|materials/sources\.csv)$")


def active_project():
    f = ROOT / "projects" / ".active"
    if not f.exists():
        return None
    p = ROOT / "projects" / f.read_text(encoding="utf-8").strip()
    return p if p.is_dir() else None


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return str(path)


def target_of(ti):
    for k in ("file_path", "path", "notebook_path"):
        if ti.get(k):
            return rel(ti[k])
    for k in ("url", "query", "command", "subagent_type", "pattern", "description"):
        if ti.get(k):
            return SECRET.sub(r"\1\2***", str(ti[k]))[:160]
    return ""


def usage_from_transcript(path):
    """Токены по моделям: основной журнал сеанса плюс журналы помощников."""
    path = Path(path)
    files = [path] + sorted((path.parent / path.stem / "subagents").glob("*.jsonl"))
    seen = {}
    for fp in files:
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines):
            try:
                m = json.loads(line).get("message")
            except (ValueError, AttributeError):
                continue
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            u = m.get("usage")
            if isinstance(u, dict):
                seen[m.get("id") or f"{fp.name}:{n}"] = (m.get("model") or "unknown", u)
    total = {}
    for model, u in seen.values():
        t = total.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
        t["input"] += u.get("input_tokens") or 0
        t["output"] += u.get("output_tokens") or 0
        t["cache_read"] += u.get("cache_read_input_tokens") or 0
        t["cache_write"] += u.get("cache_creation_input_tokens") or 0
    return total


def session_brief(proj):
    """Короткая справка о проекте: попадает в начало нового сеанса."""
    import strateg
    import extra
    text = (proj / "state.md").read_text(encoding="utf-8") if (proj / "state.md").exists() else ""
    lines = [f"[Стратег] Активный проект: {proj.name}. Состояние восстановлено из projects/{proj.name}/state.md."]
    for title in ("Текущий шаг", "Следующее действие", "Открытые вопросы к руководителю"):
        body = strateg.section(text, title)
        if body:
            lines.append(f"{title}: {body}")
    gates = extra.load_gates(proj)
    lines.append("Развилки, закрытые руководителем: " + (", ".join(f"шаг {k}" for k in sorted(gates)) or "нет"))
    from workflow import step_state
    current = step_state(proj)
    lines.append(f"Шаг по файлам: {current['step']} из 7 · {current['label']} ({current['status']}).")
    lines.append("Не повторяй сделанное. Сначала скажи пользователю, где остановились, затем продолжай.")
    return "\n".join(lines)


def main():
    data = json.load(sys.stdin)
    proj = active_project()
    if not proj:
        if data.get("hook_event_name") == "SessionStart":
            print("[Стратег] Активного проекта нет. Попроси пользователя описать задачу "
                  "и создай проект: python3 tools/strateg.py new <имя>.")
        return 0
    event = data.get("hook_event_name", "")
    if event == "SessionStart":
        print(session_brief(proj))
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    resp = data.get("tool_response")
    ok = not (isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")))

    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
             "session": data.get("session_id", ""), "event": event}
    if tool:
        entry.update(tool=tool, target=target_of(ti), ok=ok)
    with open(proj / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if event in ("Stop", "SubagentStop") and data.get("transcript_path"):
        tp = Path(data["transcript_path"])
        if tp.exists():
            up = proj / "usage.json"
            usage = json.loads(up.read_text(encoding="utf-8")) if up.exists() else {}
            usage[data.get("session_id") or tp.stem] = usage_from_transcript(tp)
            up.write_text(json.dumps(usage, ensure_ascii=False, indent=1), encoding="utf-8")

    if event == "PostToolUse" and tool in ("Write", "Edit", "MultiEdit") and ti.get("file_path"):
        try:
            inside = str(Path(ti["file_path"]).resolve().relative_to(proj.resolve()))
        except ValueError:
            inside = ""
        if GATED.match(inside.replace("\\", "/")):
            import strateg
            errs, _ = strateg.run_check(proj)
            if errs:
                lines = [f"- {i}: {m}" for i, m in errs[:12]]
                more = f"\n…и ещё {len(errs) - 12}" if len(errs) > 12 else ""
                sys.stderr.write(
                    "Проверка реестра не пройдена. Исправь до того, как продолжать:\n"
                    + "\n".join(lines) + more
                    + "\nПравило: сначала строка реестра (claim add), потом тезис в тексте.\n")
                return 2
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # хук не должен ломать работу агента
        sys.stderr.write(f"hook_log: {e}\n")
        code = 0
    sys.exit(code)
