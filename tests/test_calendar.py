import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from strateg import calendar_problems


class CalendarTest(unittest.TestCase):
    def test_schedule_for_library_pilot(self):
        plan = 'Календарь проверки: набор 1–14 мая, наблюдение до 21 мая, решение 22 мая.'
        self.assertFalse(calendar_problems(plan, 'Итог\n' + plan))
        self.assertTrue(calendar_problems(plan, plan.replace('22 мая', '16 мая')))
        self.assertTrue(calendar_problems(plan, 'Итог'))
        self.assertTrue(calendar_problems(plan, plan + '\n' + plan))
        self.assertTrue(calendar_problems('Календарь проверки:', 'Календарь проверки:'))
        self.assertFalse(calendar_problems('Старый план', 'Старая сводка'))
