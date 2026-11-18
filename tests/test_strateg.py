"""Тесты команд Стратега. Запуск из корня репозитория:

    python3 -m unittest discover -s tests -v

Каждый тест работает в своей временной копии репозитория и ничего не меняет в настоящих проектах.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="strateg-test-")).resolve()
        for d in ("tools", "templates", "routing"):
            shutil.copytree(REPO / d, self.tmp / d, ignore=shutil.ignore_patterns("__pycache__"))
        (self.tmp / "projects").mkdir()
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                        CODEX_HOME=str(self.tmp / "no-codex"))
        self.run_ok("new", "demo")
        self.proj = self.tmp / "projects" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, script="strateg.py", stdin=None):
        return subprocess.run([sys.executable, str(self.tmp / "tools" / script), *args],
                              cwd=self.tmp, env=self.env, input=stdin, capture_output=True,
                              text=True, encoding="utf-8")

    def run_ok(self, *args):
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def source(self, kind="документ", url="materials/a.md"):
        return self.run_ok("source", "add", "--title", "Источник", "--url", url, "--kind", kind).strip()

    def fact(self, text="Удержание 31%", where="строка 2", source=None):
        return self.run_ok("claim", "add", "--type", "факт", "--text", text,
                           "--source", source or self.source(), "--where", where).strip()

    def confirm_all_gates(self):
        for step in ("1", "4", "7"):
            self.run_ok("gate", "confirm", step, "--by", "да")


class Registry(Base):
    def test_new_project_is_active_and_clean(self):
        self.assertEqual((self.tmp / "projects" / ".active").read_text(encoding="utf-8").strip(), "demo")
        self.assertIn("Ошибок: 0", self.run_ok("check"))

    def test_fact_without_source_is_rejected(self):
        r = self.run_cli("claim", "add", "--type", "факт", "--text", "Рынок растёт на 20%")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("факт без источника", r.stderr)

    def test_fact_needs_place_in_source(self):
        r = self.run_cli("claim", "add", "--type", "факт", "--text", "x", "--source", self.source())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("место в источнике", r.stderr)

    def test_synthetic_interview_cannot_prove_a_fact(self):
        s = self.source("модельное интервью", "materials/interviews/synthetic-a.md")
        r = self.run_cli("claim", "add", "--type", "факт", "--text", "Людям нужна функция",
                         "--source", s, "--where", "реплика 2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("не доказательство", r.stderr)
        self.run_ok("claim", "add", "--type", "синтетика", "--text", "Роль сказала, что не поняла цену",
                    "--source", s, "--where", "реплика 2")

    def test_agent_answer_cannot_become_a_fact(self):
        s = self.source("ответ агента", "outputs/0-svodka.md")
        r = self.run_cli("claim", "add", "--type", "факт", "--text", "x", "--source", s, "--where", "абзац 1")
        self.assertNotEqual(r.returncode, 0)

    def test_inference_needs_grounds_and_fact_has_none(self):
        r = self.run_cli("claim", "add", "--type", "вывод", "--text", "Причина в цене")
        self.assertIn("без оснований", r.stderr)
        f = self.fact()
        r = self.run_cli("claim", "add", "--type", "факт", "--text", "y", "--source", "S-001",
                         "--where", "z", "--depends", f)
        self.assertIn("не бывает зависимостей", r.stderr)

    def test_gap_needs_reason(self):
        r = self.run_cli("claim", "add", "--type", "пробел", "--text", "Не знаем долю ушедших")
        self.assertIn("почему", r.stderr)

    def test_inference_without_any_fact_gets_warning(self):
        h = self.run_ok("claim", "add", "--type", "гипотеза", "--text", "Отток из-за цены").strip()
        self.run_ok("claim", "add", "--type", "вывод", "--text", "Надо снижать цену", "--depends", h)
        self.confirm_all_gates()
        self.assertIn("не опирается ни на один факт", self.run_ok("check"))

    def test_text_cannot_cite_missing_or_revoked_claim(self):
        f = self.fact()
        self.confirm_all_gates()
        out = self.proj / "outputs" / "1-kartina-situacii.md"
        out.write_text(f"Тезис [{f}] и ещё [C-777].", encoding="utf-8")
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("C-777", r.stdout)
        out.write_text(f"Тезис [{f}].", encoding="utf-8")
        self.run_ok("check")
        self.run_ok("revoke", f, "--reason", "устарело")
        self.assertIn("отозванное", self.run_cli("check").stdout)

    def test_html_comment_is_not_a_reference(self):
        self.confirm_all_gates()
        (self.proj / "outputs" / "x.md").write_text("Текст <!-- образец [C-000] -->", encoding="utf-8")
        self.assertNotIn("C-000", self.run_cli("check").stdout)


class Revision(Base):
    def test_revoke_cascades_to_dependents_and_lists_texts(self):
        f1, f2 = self.fact("Удержание 31%"), self.fact("Конкурент даёт месяц бесплатно", "раздел 1")
        w = self.run_ok("claim", "add", "--type", "вывод", "--text", "Уходят к конкуренту",
                        "--depends", f"{f1};{f2}").strip()
        w2 = self.run_ok("claim", "add", "--type", "прогноз", "--text", "Отток вырастет",
                         "--depends", w).strip()
        (self.proj / "outputs" / "2-varianty.md").write_text(f"Вариант Б стоит на [{w2}].", encoding="utf-8")
        out = self.run_ok("revoke", f2, "--reason", "акция закончилась")
        self.assertIn(w, out)
        self.assertIn("2-varianty.md", out)
        rows = (self.proj / "claims.csv").read_text(encoding="utf-8")
        self.assertIn("отозвано", rows)
        self.assertEqual(rows.count("на пересмотре"), 2)

    def test_impact_by_source(self):
        s = self.source()
        f = self.fact(source=s)
        w = self.run_ok("claim", "add", "--type", "вывод", "--text", "w", "--depends", f).strip()
        out = self.run_ok("impact", s)
        self.assertIn(f, out)
        self.assertIn(w, out)

    def test_decision_on_changed_grounds_is_flagged(self):
        f = self.fact()
        self.confirm_all_gates()
        (self.proj / "decisions.md").write_text(f"# Журнал\n\n## D-001. Решение\n- Основания: [{f}]\n",
                                                encoding="utf-8")
        self.run_ok("revoke", f, "--reason", "новые данные")
        self.assertIn("пора пересмотреть", self.run_cli("check").stdout)

    def test_why_shows_chain_to_source(self):
        f = self.fact("Удержание 31%")
        w = self.run_ok("claim", "add", "--type", "вывод", "--text", "Падает", "--depends", f).strip()
        out = self.run_ok("why", w)
        self.assertIn(f, out)
        self.assertIn("источник S-001", out)


class Gates(Base):
    def test_work_without_confirmed_task_is_an_error(self):
        self.fact()
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("развилка 1", r.stdout)
        self.run_ok("gate", "confirm", "1", "--by", "Подтверждаю формулировку")
        self.run_ok("check")

    def test_strategy_without_chosen_option_is_an_error(self):
        f = self.fact()
        self.run_ok("gate", "confirm", "1", "--by", "да")
        (self.proj / "outputs" / "3-produktovaya-strategiya.md").write_text(f"Стратегия [{f}]", encoding="utf-8")
        self.assertIn("развилка 4", self.run_cli("check").stdout)
        self.run_ok("gate", "confirm", "4", "--by", "Берём вариант Б")
        self.run_ok("check")
        self.assertIn("Берём вариант Б", self.run_ok("gate", "list"))


class Verify(Base):
    def test_numbers_and_quotes_are_checked_against_source(self):
        (self.proj / "materials" / "t.csv").write_text("месяц,новые,d30\n2026-10,11200,31\n", encoding="utf-8")
        s = self.source("таблица", "materials/t.csv")
        good = self.fact("В октябре 11 200 новых, удержание 31%", "строка 2026-10", s)
        bad = self.fact("В октябре удержание 35%", "строка 2026-10", s)
        out = self.run_ok("verify")
        self.assertRegex(out, rf"OK\s+{good}")
        self.assertRegex(out, rf"ПРОВЕРЬ\s+{bad}.*35")
        self.assertEqual(self.run_cli("verify", "--strict").returncode, 1)

    def test_calculation_is_rerun(self):
        (self.proj / "analysis" / "calc.py").write_text("print('среднее', 43.5)\n", encoding="utf-8")
        s = self.source("расчёт", "analysis/calc.py")
        f = self.fact("Среднее удержание 43,5%", "вывод скрипта", s)
        self.assertNotRegex(self.run_ok("verify"), rf"OK\s+{f}")
        self.assertRegex(self.run_ok("verify", "--run-calculations"), rf"OK\s+{f}.*повторный запуск")


class CostAndHooks(Base):
    def usage(self, data):
        (self.proj / "usage.json").write_text(json.dumps(data), encoding="utf-8")

    def test_cost_uses_prices_and_shows_routing_saving(self):
        self.usage({"s1": {"claude-opus-5-5": {"input": 1000000, "output": 0, "cache_read": 0, "cache_write": 0},
                           "claude-haiku-5-5": {"input": 1000000, "output": 0, "cache_read": 0, "cache_write": 0}}})
        out = self.run_ok("cost")
        self.assertIn("4.1000 USD", out)   # 4 + 0.1
        self.assertIn("Экономия маршрутизации: 3.9000 USD", out)

    def test_cost_without_price_does_not_crash(self):
        self.usage({"s1": {"some-new-model": {"input": 10, "output": 5, "cache_read": 0, "cache_write": 0}}})
        self.assertIn("нет цены", self.run_ok("cost"))

    def test_codex_log_is_imported_once_and_only_for_this_folder(self):
        d = self.tmp / "no-codex" / "sessions" / "2026" / "11" / "15"
        d.mkdir(parents=True)
        ts = "2099-01-01T10:00:0%d.000Z"

        def tok(n, i, c, o):
            return json.dumps({"timestamp": ts % n, "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o}}}})
        mine = [json.dumps({"timestamp": ts % 1, "type": "session_meta", "payload": {"id": "A", "cwd": str(self.tmp)}}),
                json.dumps({"timestamp": ts % 2, "type": "turn_context", "payload": {"model": "gpt-test"}}),
                tok(3, 10000, 4000, 500), tok(4, 10000, 4000, 500), tok(5, 25000, 15000, 1500)]
        (d / "rollout-a.jsonl").write_text("\n".join(mine), encoding="utf-8")
        other = [json.dumps({"timestamp": ts % 1, "type": "session_meta", "payload": {"id": "B", "cwd": "/elsewhere"}}),
                 tok(2, 999999, 0, 9)]
        (d / "rollout-b.jsonl").write_text("\n".join(other), encoding="utf-8")
        for _ in range(2):
            out = self.run_ok("cost")
        self.assertIn("| gpt-test | 10000 | 1500 | 15000 | 0 |", out)
        self.assertNotIn("999999", out)

    def hook(self, payload):
        return self.run_cli(script="hook_log.py", stdin=json.dumps(payload))

    def test_hook_logs_action_and_masks_secrets(self):
        r = self.hook({"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "curl -H API_KEY=abc123 https://x"}, "tool_response": {}})
        self.assertEqual(r.returncode, 0)
        log = (self.proj / "log.jsonl").read_text(encoding="utf-8")
        self.assertIn("API_KEY=***", log)
        self.assertNotIn("abc123", log)

    def test_hook_blocks_text_with_unknown_claim(self):
        f = self.proj / "outputs" / "2-varianty.md"
        f.write_text("Тезис [C-777].", encoding="utf-8")
        r = self.hook({"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": str(f)}, "tool_response": {}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("C-777", r.stderr)

    def test_hook_survives_garbage_input(self):
        self.assertEqual(self.run_cli(script="hook_log.py", stdin="not json").returncode, 0)

    def test_session_start_hook_restores_state(self):
        r = self.hook({"session_id": "s", "hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("demo", r.stdout)
        self.assertIn("Шаг 1 из 7", r.stdout)


class Report(Base):
    def test_report_links_claims_to_registry(self):
        f = self.fact("Удержание 31%")
        self.confirm_all_gates()
        (self.proj / "outputs" / "0-svodka.md").write_text(
            f"# Сводка\n\nУдержание упало [{f}, факт].\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        self.run_ok("report")
        page = (self.proj / "outputs" / "REPORT.html").read_text(encoding="utf-8")
        self.assertIn(f'href="#{f}"', page)
        self.assertIn(f'<tr id="{f}"', page)
        self.assertIn("<table>", page)


class NewCommands(Base):
    def test_assumption_needs_reason(self):
        r = self.run_cli("claim", "add", "--type", "допущение", "--text", "Срок — конец года")
        self.assertIn("почему оно принято", r.stderr)
        self.run_ok("claim", "add", "--type", "допущение", "--text", "Срок — конец года",
                    "--note", "руководитель не назвал срок; подтвердить у него")

    def test_budget_warns_and_stops(self):
        (self.proj / "usage.json").write_text(json.dumps(
            {"s": {"claude-opus-5-5": {"input": 1000000, "output": 0, "cache_read": 0, "cache_write": 0}}}),
            encoding="utf-8")
        self.run_ok("budget", "--set", "4.5")
        self.assertIn("больше 80%", self.run_ok("cost"))
        self.run_ok("budget", "--set", "3")
        self.assertIn("БЮДЖЕТ ИСЧЕРПАН", self.run_ok("cost"))

    def test_due_flags_decision_with_changed_grounds_or_past_date(self):
        f = self.fact()
        (self.proj / "decisions.md").write_text(
            f"# Журнал\n\n## D-001. Чиним списания\n- Срок наблюдения: до 2020-01-31\n"
            f"- Основания: [{f}]\n- Статус: действует\n\n## D-002. Позже\n- Срок наблюдения: до 2999-01-01\n"
            f"- Статус: действует\n", encoding="utf-8")
        out = self.run_ok("due")
        self.assertIn("D-001", out)
        self.assertIn("наступил срок", out)
        self.assertNotIn("D-002", out)
        self.run_ok("revoke", f, "--reason", "новые данные")
        self.assertIn("основания изменились", self.run_ok("due"))

    def test_doctor_passes_on_complete_copy(self):
        shutil.copy(REPO / "AGENTS.md", self.tmp / "AGENTS.md")
        for d in ("skills", "knowledge", ".claude"):
            shutil.copytree(REPO / d, self.tmp / d)
        self.assertIn("Всё готово", self.run_ok("doctor"))


class Batch(Base):
    def test_batch_is_all_or_nothing_and_links_inside(self):
        f = self.tmp / "batch.json"
        s = self.source()
        good = [{"key": "a", "type": "факт", "text": "Удержание 31%", "source": s, "where": "строка 2"},
                {"key": "b", "type": "вывод", "text": "Падает", "depends": "a"}]
        f.write_text(json.dumps(good + [{"type": "факт", "text": "Без источника"}], ensure_ascii=False), encoding="utf-8")
        r = self.run_cli("claims-add-many", str(f))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("запись 3", r.stderr)
        self.assertNotIn("C-001", (self.proj / "claims.csv").read_text(encoding="utf-8"))
        f.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        out = self.run_ok("claims-add-many", str(f))
        self.assertIn("a: C-001", out)
        self.assertIn("C-001", self.run_ok("why", "C-002"))

    def test_batch_sources(self):
        f = self.tmp / "src.json"
        f.write_text('{"title": "А", "url": "materials/a.md", "kind": "документ"}\n'
                     '{"title": "Б", "url": "materials/b.csv", "kind": "таблица"}\n', encoding="utf-8")
        self.assertIn("2: S-002", self.run_ok("sources-add-many", str(f)))


class Mcp(Base):
    def call(self, *msgs):
        data = "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n"
        r = self.run_cli(script="mcp_server.py", stdin=data)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [json.loads(x) for x in r.stdout.splitlines()]

    def test_lists_tools_and_enforces_registry_rules(self):
        out = self.call(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "add_claim", "arguments": {"type": "факт", "text": "Рынок растёт"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "add_source", "arguments": {"title": "Т", "url": "materials/t.csv", "kind": "таблица"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "check", "arguments": {}}})
        self.assertEqual(len(out), 5)                      # уведомление без ответа
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-03-26")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertTrue({"check", "verify", "why", "impact", "add_claim", "revoke"} <= names)
        self.assertNotIn("gate_confirm", names)            # развилку закрывает только человек
        self.assertTrue(out[2]["result"]["isError"])
        self.assertIn("факт без источника", out[2]["result"]["content"][0]["text"])
        self.assertIn("S-001", out[3]["result"]["content"][0]["text"])
        self.assertIn("Ошибок: 0", out[4]["result"]["content"][0]["text"])


class HelpersRouting(Base):
    """Условия вызова помощников измеримы, пропуск нужно объяснить."""

    def line(self, out, name):
        for ln in out.splitlines():
            if ln[2:].startswith(name + " ") or ln[2:].startswith(name + "  "):
                return ln
        self.fail(f"в таблице нет строки про {name}:\n{out}")

    def source(self, url, kind, text="коротко\n", title="Источник"):
        p = self.proj / url
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.run_ok("source", "add", "--title", title, "--url", url, "--kind", kind)

    def test_fresh_project_has_nothing_to_explain(self):
        out = self.run_ok("helpers")
        self.assertIn("Необъяснённых пропусков: 0", out)

    def test_table_requires_analyst_until_the_call_is_recorded(self):
        self.source("materials/sales.csv", "таблица", "неделя,продажи\n1,10\n")
        r = self.run_cli("helpers")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("НЕ ОБЪЯСНЁН", self.line(r.stdout, "analyst"))
        self.assertIn("помощник analyst", self.run_ok("check"))
        self.run_ok("helper", "analyst", "--step", "2", "--used", "--note", "скрипт в analysis/")
        self.assertIn("вызван", self.line(self.run_ok("helpers", "--soft"), "analyst"))
        self.assertNotIn("помощник analyst", self.run_ok("check"))

    def test_skip_needs_a_reason(self):
        self.source("materials/brief.md", "документ")
        r = self.run_cli("helper", "respondent", "--step", "3", "--skipped")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("причина", r.stderr)
        self.run_ok("helper", "respondent", "--step", "3", "--skipped",
                    "--reason", "руководитель запретил модельные интервью")
        self.assertIn("пропуск объяснён", self.line(self.run_ok("helpers", "--soft"), "respondent"))

    def test_extractor_waits_for_a_long_document_or_a_saved_page(self):
        self.source("materials/brief.md", "документ")
        self.assertIn("не нужен", self.line(self.run_ok("helpers", "--soft"), "extractor"))
        self.source("materials/web/market.md", "сайт", "обзор рынка\n", "Страница рынка")
        self.assertIn("НЕ ОБЪЯСНЁН", self.line(self.run_ok("helpers", "--soft"), "extractor"))

    def test_real_interview_removes_the_respondent_condition(self):
        self.source("materials/brief.md", "документ")
        self.assertIn("НЕ ОБЪЯСНЁН", self.line(self.run_ok("helpers", "--soft"), "respondent"))
        self.source("materials/interviews.md", "интервью", "шесть бесед\n", "Интервью")
        self.assertIn("не нужен", self.line(self.run_ok("helpers", "--soft"), "respondent"))

    def test_screenshots_are_not_counted_as_long_documents(self):
        p = self.proj / "materials" / "screen.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n" + b"\x00" * 20000)
        self.run_ok("source", "add", "--title", "Экран", "--url", "materials/screen.png",
                    "--kind", "скриншот")
        self.assertIn("не нужен", self.line(self.run_ok("helpers", "--soft"), "extractor"))


if __name__ == "__main__":
    unittest.main()
