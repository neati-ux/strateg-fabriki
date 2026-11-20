import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from strateg import run_check


class DecisionThresholdTest(unittest.TestCase):
    def test_summary_preserves_approval_status(self):
        pending = "Бизнес-порог: ожидает согласования"
        cases = [
            (pending, pending, True),
            (pending, "Бизнес-порог: 4%", False),
            ("", pending, False),
            (pending, "", False),
            (pending, pending + "\n" + pending, False),
            ("Бизнес-порог:", "Бизнес-порог:", False),
            ("Старый план", "Старая сводка", True),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            shutil.copytree(ROOT / "templates" / "project", project)
            out = project / "outputs"
            out.mkdir(exist_ok=True)
            for plan, summary, expected in cases:
                with self.subTest(plan=plan, summary=summary):
                    (out / "5-plan-proverki.md").write_text(plan, encoding="utf-8")
                    (out / "0-svodka.md").write_text(summary, encoding="utf-8")
                    errors, _ = run_check(project)
                    self.assertEqual(not any(key == "порог" for key, _ in errors), expected)
