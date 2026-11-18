import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("capabilities", Path(__file__).resolve().parents[1] / "tools" / "capabilities.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def model(mid, price=None, available=True, roles=None):
    return dict(id=mid, provider="test", price=price, available=available,
                roles=roles or ["critic"], evidence="user confirmed in UI on 2026-11-17")


class RoutingTests(unittest.TestCase):
    def inventory(self, *models):
        data = C.template()
        data["models"] = list(models)
        return data

    def test_empty_inventory_refuses_to_invent_model(self):
        r = C.choose_model(self.inventory(), "critic")
        self.assertIsNone(r["selected"])
        self.assertEqual(r["status"], "unavailable")

    def test_unavailable_and_wrong_role_never_selected(self):
        d = self.inventory(model("cheap-unavailable", 0, False), model("wrong-role", 0, roles=["extractor"]))
        self.assertIsNone(C.choose_model(d, "critic")["selected"])

    def test_lowest_price_among_eligible(self):
        r = C.choose_model(self.inventory(model("large", 20), model("small", 3)), "critic")
        self.assertEqual(r["selected"]["id"], "small")
        self.assertFalse(r["switched"])

    def test_unknown_prices_are_not_zero(self):
        r = C.choose_model(self.inventory(model("unknown"), model("known", 3)), "critic")
        self.assertEqual(r["selected"]["id"], "known")
        self.assertEqual(r["unknown_prices"], ["unknown"])
        self.assertIn("невозможно", r["reason"])

    def test_all_unknown_explains_order(self):
        r = C.choose_model(self.inventory(model("first"), model("second")), "critic")
        self.assertEqual(r["selected"]["id"], "first")
        self.assertIn("Экономичность не установлена", r["reason"])

    def test_single_eligible_fallback_is_explicit(self):
        r = C.choose_model(self.inventory(model("only")), "critic")
        self.assertTrue(r["single_model_fallback"])
        self.assertIsNone(r["selected"]["price"])

    def test_rejects_unproven_or_invalid_availability(self):
        for patch in ({"available": "true"}, {"evidence": ""}, {"price": -1}, {"price": float("nan")}, {"price": True}):
            m = model("bad"); m.update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                C.choose_model(self.inventory(m), "critic")

    def test_mixed_price_basis_rejected(self):
        d = self.inventory(model("one", 2)); d["price_basis"] = "monthly subscription"
        with self.assertRaises(ValueError): C.choose_model(d, "critic")

    def test_inspect_does_not_claim_models(self):
        self.assertEqual(C.inspect_local()["models"], "unknown")


if __name__ == "__main__":
    unittest.main()
