#!/usr/bin/env python3
"""MCP-сервер Стратега: действия с реестром как встроенные инструменты агента.

Работает по стандартному вводу и выводу (JSON-RPC 2.0, одно сообщение в строке), только стандартная
библиотека. Каждый инструмент вызывает ту же команду tools/strateg.py, что и терминал, поэтому правила
реестра одинаковы при любом способе вызова. Подключение описано в .mcp.json.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ID = {"type": "string", "description": "номер утверждения C-001 или источника S-001"}
TYPES = ["факт", "гипотеза", "допущение", "прогноз", "вывод", "синтетика", "пробел"]
KINDS = ["документ", "таблица", "сайт", "интервью", "модельное интервью", "скриншот", "расчёт",
         "слова руководителя", "ответ агента"]
HELPERS = ["extractor", "researcher", "analyst", "respondent", "critic"]


def opt(p, *pairs):
    out = []
    for key, flag in pairs:
        if p.get(key):
            out += [flag, str(p[key])]
    return out


TOOLS = {
    "evidence_priority": ("Какие источники и допущения проверить первыми по охвату итоговых документов.",
                          {}, ["project"], lambda p: ["evidence-priority"]),
    "ux_capture": ("Пройти явно заданный браузерный сценарий; сохранить экраны и зарегистрировать источник.",
                   {"scenario": {"type": "string"}, "title": {"type": "string"}}, ["project", "scenario"],
                   lambda p: ["ux-capture", "--scenario=" + p["scenario"]] + opt(p, ("title", "--title"))),
    "knowledge_search": ("Найти карту методики по ключевым словам.", {"query": {"type": "string"}}, ["query"],
                         lambda p: ["research", "knowledge", "--", p["query"]]),
    "research_plan": ("Исследовательские вопросы, ответы и основания, которые требуют пересмотра.", {}, [],
                      lambda p: ["research", "list"]),
    "source_locate": ("Найти цитату по сохранённому источнику и получить точное место.",
                      {"source": {"type": "string"}, "quote": {"type": "string"}}, ["source", "quote"],
                      lambda p: ["locate", "--", p["source"], p["quote"]]),
    "route_status": ("Посмотреть утверждённый маршрут и операции, ожидающие продолжения.",
                     {"task": {"type": "string"}}, ["project", "task"],
                     lambda p: ["execution", "status", "--task=" + p["task"]]),
    "route_cost": ("Расходы утверждённого маршрута. Для всех стадий одной задачи используйте whole_work.",
                   {"task": {"type": "string"}, "whole_work": {"type": "boolean"}}, ["project", "task"],
                   lambda p: ["execution", "report", "--task=" + p["task"], "--details"]
                             + (["--whole-work"] if p.get("whole_work") else [])),
    "workflow_next": ("Найти следующий шаг по состоянию, результатам и ответам руководителя.", {}, [],
                      lambda p: ["workflow", "next"]),
    "status": ("Где остановились: текущий шаг, следующее действие, счётчики реестра.", {}, [],
               lambda p: ["status"]),
    "check": ("Проверить реестр, тексты и развилки: факты без источников, выводы без оснований, "
              "ссылки на отозванное, шаги без решения человека.", {}, [], lambda p: ["check"]),
    "verify": ("Сверить числа и цитаты фактов с сохранёнными источниками. Без модели.", {}, [],
               lambda p: ["verify"]),
    "why": ("Цепочка оснований утверждения до источников.", {"id": ID}, ["id"], lambda p: ["why", p["id"]]),
    "impact": ("Что зависит от утверждения или источника и какие тексты придётся обновить.",
               {"id": ID}, ["id"], lambda p: ["impact", p["id"]]),
    "due": ("Какие решения пора пересмотреть: наступил срок или изменились основания.", {}, [],
            lambda p: ["due"]),
    "cost": ("Время, действия, токены и расходы по моделям, доля бюджета.", {}, [], lambda p: ["cost"]),
    "gates": ("Какие развилки закрыты руководителем и какими словами.", {}, [], lambda p: ["gate", "list"]),
    "helpers": ("У кого из пяти помощников условие вызова выполнено, чем это измерено "
                "и записан ли вызов или объяснённый пропуск.", {}, [], lambda p: ["helpers", "--soft"]),
    "helper": ("Записать работу помощника: вызов или пропуск с причиной.",
               {"name": {"type": "string", "enum": HELPERS},
                "step": {"type": "string", "description": "номер шага"},
                "used": {"type": "boolean", "description": "true — вызван, false — пропущен"},
                "reason": {"type": "string", "description": "почему пропущен или что сделал"}},
               ["name", "step", "used"],
               lambda p: ["helper", p["name"], "--step", str(p["step"]),
                          "--used" if p["used"] else "--skipped"] + opt(p, ("reason", "--reason"))),
    "add_source": ("Зарегистрировать источник. Возвращает номер S-….",
                   {"title": {"type": "string"}, "url": {"type": "string", "description": "ссылка или путь в materials/"},
                    "kind": {"type": "string", "enum": KINDS}, "note": {"type": "string"}},
                   ["title", "url", "kind"],
                   lambda p: ["source", "add", "--title", p["title"], "--url", p["url"], "--kind", p["kind"]]
                   + opt(p, ("note", "--note"))),
    "add_claim": ("Добавить утверждение. Факт требует источник и место в нём, вывод и прогноз требуют оснований.",
                  {"type": {"type": "string", "enum": TYPES}, "text": {"type": "string"},
                   "source": {"type": "string"}, "where": {"type": "string", "description": "место в источнике"},
                   "depends": {"type": "string", "description": "из чего следует: C-001;C-002"},
                   "note": {"type": "string"}},
                  ["type", "text"],
                  lambda p: ["claim", "add", "--type", p["type"], "--text", p["text"]]
                  + opt(p, ("source", "--source"), ("where", "--where"), ("depends", "--depends"), ("note", "--note"))),
    "revoke": ("Отозвать утверждение или все утверждения источника; зависимое помечается на пересмотр.",
               {"id": ID, "reason": {"type": "string"}}, ["id", "reason"],
               lambda p: ["revoke", p["id"], "--reason", p["reason"]]),
}
# Закрыть развилку через сервер нельзя намеренно: это делает человек, подтверждая команду gate confirm.


def run_cli(args, project=None):
    cmd = [sys.executable, str(HERE / "strateg.py")] + (["-p", project] if project else []) + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=HERE.parent)
    text = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip() or "(пустой вывод)"
    return text, r.returncode not in (0,)


def tool_list():
    out = []
    for name, (desc, props, req, _) in TOOLS.items():
        props = dict(props, project={"type": "string", "description": "имя проекта, по умолчанию активный"})
        out.append({"name": name, "description": desc,
                    "inputSchema": {"type": "object", "properties": props, "required": req}})
    return out


def handle(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:           # уведомление, ответ не нужен
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "strateg", "version": "1.0.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        spec = TOOLS.get(params.get("name"))
        args = params.get("arguments") or {}
        if not spec:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "нет такого инструмента"}}
        missing = [k for k in spec[2] if not args.get(k)]
        if missing:
            text, bad = "Не заданы обязательные поля: " + ", ".join(missing), True
        else:
            text, bad = run_cli(spec[3](args), args.get("project"))
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": text}], "isError": bad}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"метод {method} не поддерживается"}}


def main():
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line))
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "не JSON"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
