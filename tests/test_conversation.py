import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src import ai_filter
from src.catalog import load_catalog
from src.conversation import advise, extra_question, is_yes, merge, missing, parse_turn, question, relax
from src.models import Criteria, Preferences
from src.recommender import allocate, recommend
from src.report import build_pdf, capital_evolution, percents, summary_text
from src.money import investment_allocation

ROOT = Path(__file__).resolve().parents[1]


class DialogueTests(unittest.TestCase):
    def test_missing_fields_are_asked_not_guessed(self):
        profile = merge(Preferences(), parse_turn("Quiero invertir 10.000 euros en un fondo global"))
        self.assertEqual(missing(profile), ("horizon_years", "risk"))
        asked = question(profile)
        self.assertIn("cuántos años", asked)
        self.assertIn("riesgo", asked)
        self.assertNotIn("divisa", asked)

    def test_bare_answers_fill_what_was_asked(self):
        profile = merge(Preferences(), parse_turn("Quiero invertir 10.000 euros"))
        profile = merge(profile, parse_turn("Cinco, y medio.", missing(profile)))
        self.assertEqual((profile.horizon_years, profile.risk, profile.amount), (5, "medio", 10000))
        self.assertEqual(missing(profile), ())

    def test_bare_number_is_ignored_when_not_asked(self):
        self.assertIsNone(parse_turn("tengo 3 hijos").horizon_years)

    def test_amount_is_not_read_as_horizon(self):
        self.assertIsNone(parse_turn("10.000 euros", ("horizon_years",)).horizon_years)

    def test_unsupported_horizon_is_asked_again(self):
        profile = merge(Preferences(), parse_turn("euros, riesgo bajo, a 10 años"))
        self.assertEqual(missing(profile), ("horizon_years",))
        self.assertIn("uno, tres o cinco", question(profile))

    def test_later_turn_overrides_and_relax_drops_filters(self):
        profile = merge(Preferences(5, "medio", "EUR", region="asia"), parse_turn("mejor riesgo bajo"))
        self.assertEqual(profile.risk, "bajo")
        self.assertTrue(is_yes("Sí, quítalo"))
        self.assertFalse(is_yes("no, déjalo"))
        self.assertIsNone(relax(profile, ("region",)).region)


class AdviserTests(unittest.TestCase):
    def test_follow_up_asks_only_what_is_unknown(self):
        profile = merge(Preferences(5, "alto", "EUR"), parse_turn("quiero hacer crecer el dinero"))
        self.assertEqual(profile.objective, "crecimiento")
        asked = extra_question(profile)
        self.assertNotIn("crecer el dinero", asked)
        self.assertIn("invertido antes", asked)

    def test_risk_is_lowered_when_answers_do_not_support_it(self):
        profile = merge(Preferences(5, "alto", "EUR"), parse_turn("Nunca he invertido y si cae vendería todo"))
        self.assertEqual((profile.experience, profile.loss_reaction), ("baja", "vende"))
        advised, notes = advise(profile)
        self.assertEqual(advised.risk, "medio")
        self.assertEqual(len(notes), 1)
        self.assertEqual(advise(Preferences(5, "alto", "EUR", loss_reaction="espera"))[1], [])

    def test_objective_changes_the_ranking(self):
        funds = load_catalog(ROOT / "data/demo_funds.csv")
        growth, _ = recommend(funds, Preferences(5, "alto", "EUR", objective="crecimiento"), limit=40)
        safe, _ = recommend(funds, Preferences(5, "alto", "EUR", objective="preservación"), limit=40)
        best = max(growth, key=lambda item: item.fund.return_5y).fund.isin
        score = lambda items: next(item.score for item in items if item.fund.isin == best)
        self.assertGreater(score(growth), score(safe))


class CriteriaTests(unittest.TestCase):
    profile = Preferences(5, "medio", "EUR")

    def test_model_criteria_are_validated(self):
        criteria = ai_filter.criteria_from({
            "peso_riesgo": 0, "peso_sharpe": 20, "peso_rentabilidad": 80, "volatilidad_objetivo": 90,
            "rentabilidad_minima_anual": 400, "palabras_clave": ["Tecnología", "tech", "a", "x;y", "tech"],
            "explicacion": "crecer"}, self.profile)
        self.assertAlmostEqual(sum(criteria.weights), 1.0)
        self.assertGreaterEqual(criteria.weights[0], 0.25)       # risk always counts
        self.assertEqual(criteria.target_vol, 0.20)              # never above the profile ceiling
        self.assertIsNone(criteria.min_annual_return)            # absurd floor is ignored
        self.assertEqual(criteria.keywords, ("tecnologia", "tech"))

    def test_criteria_are_applied_to_the_catalog(self):
        funds = load_catalog(ROOT / "data/demo_funds.csv")
        alto = Preferences(5, "alto", "EUR")
        everything, _ = recommend(funds, alto, limit=40)
        themed, _ = recommend(funds, alto, limit=40, criteria=Criteria((0.4, 0.3, 0.3), 0.30, keywords=("tecnologia",)))
        self.assertGreater(len(everything), len(themed))
        self.assertIn("DEMO000004", [item.fund.isin for item in themed])  # Fondo Demo Tecnología Mundial
        floor, _ = recommend(funds, alto, limit=40, criteria=Criteria((0.4, 0.3, 0.3), 0.30, min_annual_return=0.10))
        self.assertTrue(all((1 + item.fund.return_5y) ** 0.2 - 1 >= 0.10 for item in floor))

    def test_no_criteria_without_a_capable_model(self):
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            self.assertIsNone(ai_filter.decide(self.profile, "texto"))


class ProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = Preferences(5, "medio", "EUR", amount=10000)
        cls.candidates, _ = recommend(load_catalog(ROOT / "data/demo_funds.csv"), cls.profile, limit=40)

    def test_allocation_favours_lower_volatility(self):
        weights = allocate(self.candidates, 5)
        self.assertAlmostEqual(sum(weights), 1.0)
        calmest = min(range(len(weights)), key=lambda i: self.candidates[i].fund.vol_5y)
        self.assertEqual(weights.index(max(weights)), calmest)
        self.assertEqual(sum(percents(weights)), 100)

    def test_rules_are_used_when_ai_is_off(self):
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposal = ai_filter.select(self.candidates, self.profile, "texto")
        self.assertEqual(proposal.method, "Reglas deterministas")
        self.assertEqual(len(proposal.items), min(5, len(self.candidates)))

    def test_diversification_sets_number_of_funds(self):
        self.assertEqual(parse_turn("quiero algo muy diversificado").diversification, "alta")
        self.assertEqual(parse_turn("prefiero pocos fondos").diversification, "baja")
        narrow = Preferences(5, "alto", "EUR", diversification="baja")
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            self.assertEqual(len(ai_filter.select(self.candidates, narrow, "texto").items), 2)

    def test_model_answer_is_validated(self):
        answer = {"comentario": "ok", "seleccion": [
            {"id": 2, "peso": 50}, {"id": 99, "peso": 30},
            {"id": 2, "peso": 10}, {"id": 1, "peso": 50}]}
        chosen, shares, _ = ai_filter._validated(answer, self.candidates, self.profile, 2)
        self.assertEqual([item.fund.isin for item in chosen],
                         [self.candidates[1].fund.isin, self.candidates[0].fund.isin])
        self.assertEqual(shares, [0.5, 0.5])

    def test_concentrated_weights_are_replaced(self):
        answer = {"comentario": "", "seleccion": [{"id": 1, "peso": 95}, {"id": 2, "peso": 5}]}
        chosen, shares, _ = ai_filter._validated(answer, self.candidates, self.profile, 5)
        self.assertEqual(shares, allocate(chosen, 5))

    def test_model_failure_falls_back_to_rules(self):
        with patch.object(ai_filter, "backend", return_value="local"), \
             patch.object(ai_filter, "_ask_local", side_effect=RuntimeError("sin modelo")):
            proposal = ai_filter.select(self.candidates, self.profile, "texto")
        self.assertIn("Reglas deterministas", proposal.method)
        self.assertTrue(proposal.items)

    def test_pdf_and_summary(self):
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposal = ai_filter.select(self.candidates, self.profile, "texto")
        summary = summary_text(proposal, self.profile)
        self.assertIn(proposal.items[0].fund.name, summary)
        self.assertIn("10000 euros", summary)
        pdf = build_pdf(proposal, self.profile, ["Quiero invertir 10.000 € a 5 años"], "demo")
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_capital_evolution_uses_cumulative_returns_and_requested_horizon(self):
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposal = ai_filter.select(self.candidates, self.profile, "texto")
        for years in (1, 3, 5):
            points = capital_evolution(proposal, 10000, years)
            self.assertEqual(len(points), years * 12 + 1)
            self.assertAlmostEqual(points[0][1], 10000)
            self.assertEqual(points[-1][0], years)
            expected = sum(
                float(amount) * (1 + item.fund.metrics(years)[0])
                for item, amount in zip(proposal.items, investment_allocation(proposal.weights, 10000).amounts)
            )
            self.assertAlmostEqual(points[-1][1], expected)


if __name__ == "__main__":
    unittest.main()
