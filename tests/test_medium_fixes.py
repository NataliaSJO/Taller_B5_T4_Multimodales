"""Monetary input, explicitly requested fund counts, and consistent output amounts."""

import os
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

from src import ai_filter, omni
from src.catalog import load_catalog
from src.conversation import apply_turn, merge, missing, parse_turn
from src.models import Preferences, Proposal, Recommendation
from src.money import format_money, investment_allocation
from src.paths import DEMO_CATALOG
from src.preferences import parse_heuristic
from src.report import build_pdf, capital_evolution, percents, summary_text
from src.recommender import valid_allocation


class MonetaryInputTests(unittest.TestCase):
    def test_amounts_and_their_currencies(self):
        cases = (
            ("10.000 dólares", 10000, "USD"),
            ("un dólar", 1, "USD"),
            ("diez mil euros", 10000, "EUR"),
            ("10 mil euros", 10000, "EUR"),
            ("1,5 millones de euros", 1500000, "EUR"),
            ("diez coma cinco euros", 10.5, "EUR"),
            ("diez coma cero cinco euros", 10.05, "EUR"),
            ("quinientas libras", 500, "GBP"),
            ("a cinco años y diez mil euros", 10000, "EUR"),
            ("1.234,56 libras", 1234.56, "GBP"),
            ("USD 1,234.56", 1234.56, "USD"),
            ("£250.50", 250.50, "GBP"),
            ("€100", 100, "EUR"),
            ("25 000 francos suizos", 25000, "CHF"),
            ("doscientos treinta y cinco mil quinientos euros", 235500, "EUR"),
            ("un millón de dólares", 1000000, "USD"),
            ("dos millones trescientos mil veinte euros", 2300020, "EUR"),
            ("ciento veintitrés euros con cuarenta y cinco céntimos", 123.45, "EUR"),
            ("veintiún euros", 21, "EUR"),
            ("999,99 CHF", 999.99, "CHF"),
        )
        for text, amount, currency in cases:
            with self.subTest(text=text):
                profile = parse_heuristic(text)
                self.assertEqual(profile.amount, amount)
                self.assertEqual(profile.currency, currency)
                self.assertFalse(profile.amount_needs_clarification)

    def test_bad_amount_requires_clarification_instead_of_changing_sign(self):
        for text in ("-100 euros", "menos cien dólares", "−100 euros", "0 euros", "1.234,567 euros",
                     "1000000000 USD", "-0 euros con cincuenta céntimos", "dos mil 500 euros", "0,001 euros"):
            with self.subTest(text=text):
                profile = parse_heuristic(text)
                self.assertIsNone(profile.amount)
                self.assertIn("amount", missing(profile))

    def test_invalid_correction_cannot_keep_old_amount_or_model_guess(self):
        old = Preferences(5, "medio", "EUR", 10000)
        new, _, _ = apply_turn(old, Preferences(amount=100), "-100 euros")
        self.assertIsNone(new.amount)
        self.assertIn("amount", missing(new))
        parsed = parse_turn("doscientos cincuenta", missing(new))
        new, _, _ = apply_turn(new, parsed, "doscientos cincuenta", missing(new))
        self.assertEqual(new.amount, 250)
        self.assertEqual(new.currency, "EUR")
        self.assertFalse(new.amount_needs_clarification)
        self.assertFalse(missing(new))

    def test_omitted_amount_is_still_optional(self):
        profile = parse_turn("5 años, riesgo medio, euros")
        self.assertIsNone(profile.amount)
        self.assertFalse(missing(profile))

    def test_model_amounts_have_same_precision_and_range(self):
        for value in (True, -100, 0, float("nan"), float("inf"), 1.001, 1e9):
            profile = omni._preferences({"importe": value})
            self.assertIsNone(profile.amount)
            self.assertTrue(profile.amount_needs_clarification)
        self.assertEqual(omni._preferences({"importe": 123.45}).amount, 123.45)


class RequestedCountTests(unittest.TestCase):
    def setUp(self):
        self.funds = load_catalog(DEMO_CATALOG)
        self.items = [Recommendation(fund, 1, "test") for fund in self.funds[:7]]
        self.profile = Preferences(5, "medio", "EUR", 10000)

    def test_exact_count_is_separate_from_diversification(self):
        for text, count in (("un solo fondo", 1), ("un único fondo", 1), ("solo un fondo", 1),
                            ("tres fondos", 3), ("7 fondos", 7)):
            with self.subTest(text=text):
                profile = parse_turn(text)
                self.assertEqual(profile.fund_count, count)
                self.assertEqual(ai_filter.requested_count(profile), count)
        self.assertEqual(ai_filter.requested_count(parse_turn("pocos fondos")), 2)
        self.assertEqual(ai_filter.requested_count(parse_turn("muy diversificado")), 7)
        self.assertIsNone(parse_turn("no quiero un solo fondo").fund_count)

    def test_single_fund_in_both_selectors_and_truthful_summary(self):
        profile = merge(self.profile, parse_turn("un solo fondo"))
        answer = {"seleccion": [{"id": 2, "peso": 100}], "comentario": ""}
        with patch.object(ai_filter, "backend", return_value="local"), \
             patch.dict(ai_filter.ASK, {"local": lambda *args: answer}), \
             patch.object(omni, "generate", return_value='{"seleccion":[{"id":2,"peso":100}]}'):
            proposals = [ai_filter.select(self.items, profile, "un solo fondo"),
                         omni.select(self.items, profile, "un solo fondo")]
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposals.append(ai_filter.select(self.items, profile, "un solo fondo"))
        for proposal in proposals:
            self.assertEqual(len(proposal.items), 1)
            self.assertEqual(proposal.weights, (1.0,))
            self.assertNotIn("Solo un fondo cumple", summary_text(proposal, profile))
            self.assertTrue(build_pdf(proposal, profile, [], "test").startswith(b"%PDF"))

    def test_count_survives_unrelated_turn_and_changes_with_new_request(self):
        profile = merge(self.profile, parse_turn("un solo fondo"))
        self.assertEqual(merge(profile, parse_turn("riesgo bajo")).fund_count, 1)
        self.assertEqual(merge(profile, parse_turn("mejor tres fondos")).fund_count, 3)
        profile = merge(profile, parse_turn("mejor muy diversificado"))
        self.assertIsNone(profile.fund_count)
        self.assertEqual(ai_filter.requested_count(profile), 7)

    def test_model_count_is_strict_and_explicit_text_prevails(self):
        self.assertEqual(omni._preferences({"numero_fondos": 1}).fund_count, 1)
        for value in (True, 0, 8, 1.5, "1"):
            self.assertIsNone(omni._preferences({"numero_fondos": value}).fund_count)
        updated, _, _ = apply_turn(self.profile, Preferences(fund_count=2), "un solo fondo")
        self.assertEqual(updated.fund_count, 1)

    def test_insufficient_candidates_are_explained(self):
        profile = replace(self.profile, fund_count=3)
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposal = ai_filter.select(self.items[:1], profile, "tres fondos")
        self.assertIn("Has pedido 3 fondos, pero solo hay 1", summary_text(proposal, profile))


class ConsistentAllocationTests(unittest.TestCase):
    def setUp(self):
        base = load_catalog(DEMO_CATALOG)[0]
        items = tuple(Recommendation(replace(base, isin=str(i), return_5y=ret), 1, "test")
                      for i, ret in enumerate((0.1, 0.2, -0.1)))
        self.proposal = Proposal(items, (1/3, 1/3, 1/3), "test")
        self.profile = Preferences(5, "medio", "EUR", 10000.01)

    def test_cents_are_conserved_and_simulation_uses_these_amounts(self):
        allocation = investment_allocation(self.proposal.weights, self.profile.amount)
        expected = (Decimal("3333.34"), Decimal("3333.34"), Decimal("3333.33"))
        self.assertEqual(allocation.amounts, expected)
        self.assertEqual(sum(allocation.amounts), Decimal("10000.01"))
        points = capital_evolution(self.proposal, self.profile.amount, 5)
        self.assertAlmostEqual(points[0][1], 10000.01)
        self.assertAlmostEqual(points[-1][1], 3333.34 * 1.1 + 3333.34 * 1.2 + 3333.33 * 0.9)
        self.assertEqual(sum(percents(allocation.weights, 2)), Decimal(100))
        summary = summary_text(self.proposal, self.profile)
        self.assertIn("10000,01 euros", summary)
        self.assertIn("3333,34 euros", summary)
        self.assertIn("3333,33 euros", summary)

    def test_pdf_rows_and_weighted_return_use_same_actual_allocation(self):
        with patch("src.report.SimpleDocTemplate.build") as build:
            build_pdf(self.proposal, self.profile, [], "test")
        story = build.call_args.args[0]
        from reportlab.platypus import Table
        table = next(item for item in story if isinstance(item, Table) and item._cellvalues[0][0] == "#")
        self.assertEqual([row[3] for row in table._cellvalues[1:]],
                         ["3.333,34 EUR", "3.333,34 EUR", "3.333,33 EUR"])
        self.assertTrue(any("10.666,68" in getattr(item, "text", "") for item in story))

    def test_cent_rounding_keeps_concentration_bounds(self):
        for total in (0.03, 1.01, 10000.01):
            allocation = investment_allocation((0.6, 0.2, 0.2), total)
            self.assertTrue(valid_allocation(allocation.weights, 3))
            self.assertEqual(sum(allocation.amounts), Decimal(str(total)))
        with self.assertRaisesRegex(ValueError, "demasiado pequeño"):
            investment_allocation((0.5, 0.5), 0.01)

    def test_no_amount_keeps_original_weights_and_invalid_amount_rejected(self):
        allocation = investment_allocation(self.proposal.weights, None)
        self.assertIsNone(allocation.amounts)
        self.assertEqual(allocation.weights, self.proposal.weights)
        for amount in (0, -100, float("inf"), float("nan"), 1.001):
            with self.assertRaises(ValueError):
                investment_allocation(self.proposal.weights, amount)
        self.assertEqual(format_money(1234.56), "1.234,56")


class MediumPageFlowTests(unittest.TestCase):
    def test_invalid_amount_recovery_single_fund_and_displayed_cents_in_both_pages(self):
        from streamlit.testing.v1 import AppTest
        from src import tts, ui
        from src.paths import ROOT

        funds = load_catalog(DEMO_CATALOG)
        for page in ("especialistas", "modelo_unico"):
            with self.subTest(page=page), \
                 patch.object(ui, "catalog", return_value=(funds, "test", True)), \
                 patch.object(tts, "synthesize", return_value=None), \
                 patch.object(tts, "available", return_value=False), \
                 patch.object(ai_filter, "available", side_effect=lambda name: name == "off"), \
                 patch.object(ai_filter, "backend", return_value="off"), \
                 patch.object(omni, "available", return_value=True), \
                 patch.object(omni, "decide", return_value=None), \
                 patch.object(omni, "understand", side_effect=lambda history, known, text, *args:
                              (parse_turn(text), text, "")), \
                 patch.object(omni, "select", side_effect=ai_filter.select):
                app = AppTest.from_file(str(ROOT / "paginas" / f"{page}.py")).run()
                app.radio[0].set_value(ui.CHAT).run()
                app.session_state["profile"] = Preferences(5, "medio", "EUR", 10000,
                    objective="crecimiento", experience="alta", loss_reaction="espera")
                app.session_state["extra_asked"] = True
                app.chat_input[0].set_value("-100 euros").run()
                self.assertFalse(app.exception)
                self.assertIn("amount", app.session_state["pending"])
                self.assertNotIn("result", app.session_state["messages"][-1])
                app.chat_input[0].set_value("diez mil").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["profile"].amount, 10000)
                app.chat_input[0].set_value("un solo fondo").run()
                self.assertFalse(app.exception)
                result = app.session_state["messages"][-1]["result"]
                self.assertEqual(len(result["proposal"].items), 1)
                self.assertEqual(app.dataframe[-1].value["Importe"].tolist(), [10000])
                app.chat_input[0].set_value("tres fondos, 10.000,01 euros").run()
                self.assertFalse(app.exception)
                result = app.session_state["messages"][-1]["result"]
                self.assertEqual(len(result["proposal"].items), 3)
                displayed = [Decimal(str(amount)) for amount in app.dataframe[-1].value["Importe"]]
                self.assertEqual(sum(displayed), Decimal("10000.01"))
                expected_final = sum(float(amount) * (1 + item.fund.return_5y)
                                     for amount, item in zip(displayed, result["proposal"].items))
                self.assertAlmostEqual(capital_evolution(result["proposal"], 10000.01, 5)[-1][1], expected_final)


if __name__ == "__main__":
    unittest.main()
