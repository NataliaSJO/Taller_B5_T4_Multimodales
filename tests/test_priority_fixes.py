"""Regressions for the high-priority findings, without loading real models."""

import json
import math
import os
import random
import unittest
from dataclasses import replace
from unittest.mock import patch

from src import ai_filter, omni
from src.catalog import load_catalog
from src.conversation import apply_turn, is_yes, missing, parse_turn, relaxation_answer
from src.models import Preferences, Recommendation
from src.paths import DEMO_CATALOG
from src.preferences import parse_heuristic
from src.recommender import allocate, allocation_limits, recommend, valid_allocation, _family_name
from src.report import build_pdf


class NegationTests(unittest.TestCase):
    def test_risk_negations_and_corrections(self):
        cases = {
            "No quiero riesgo alto, prefiero riesgo medio": "medio",
            "No quiero riesgo alto, prefiero medio": "medio",
            "Riesgo bajo, mejor riesgo alto": "alto",
            "No quiero riesgo bajo ni riesgo alto, sino riesgo medio": "medio",
            "No quiero riesgo alto": None,
            "No quiero riesgo bajo y riesgo alto": None,
            "Riesgo alto o riesgo medio": None,
            "No soy conservador, soy moderado": "medio",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_heuristic(text).risk, expected)

    def test_bare_risk_answers_respect_negation(self):
        self.assertEqual(parse_turn("No alto, medio", ("risk",)).risk, "medio")
        self.assertIsNone(parse_turn("No alto", ("risk",)).risk)

    def test_reaction_negation_and_negative_phrases(self):
        for text, expected in (
            ("No vendería si cae, esperaría", "espera"),
            ("Nunca vendería", None),
            ("No haría nada", "espera"),
            ("Vendería o compraría", None),
            ("No compraría más, vendería", "vende"),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_turn(text).loss_reaction, expected)
        self.assertEqual(parse_turn("Nunca he invertido").experience, "baja")
        self.assertEqual(parse_turn("No tengo experiencia").experience, "baja")
        self.assertEqual(parse_turn("Quiero no perder dinero").objective, "preservación")

    def test_rejected_or_ambiguous_risk_does_not_reuse_previous_value(self):
        for text in ("No quiero riesgo alto", "Riesgo medio o riesgo alto"):
            with self.subTest(text=text):
                # Even a model returning the old risk cannot override the explicit text.
                profile, _, _ = apply_turn(Preferences(5, "alto", "EUR"),
                                           Preferences(risk="alto"), text)
                self.assertIsNone(profile.risk)
                self.assertIn("risk", missing(profile))
                profile, _, _ = apply_turn(profile, parse_turn("medio", ("risk",)),
                                           "medio", ("risk",))
                self.assertEqual(profile.risk, "medio")


class RelaxationTests(unittest.TestCase):
    def setUp(self):
        self.profile = Preferences(5, "medio", "EUR", excluded_sectors=("tecnología",))
        self.fields = ("excluded_sectors",)

    def test_negative_or_conditional_reply_never_counts_as_yes(self):
        for text in (
            "No quiero quitarlo, continúa con la exclusión", "No, vale, mantenla",
            "Sí, pero no quites la exclusión", "Si cae el mercado, esperaría",
            "Continúa con las restricciones", "Tal vez", "No vendería si cae",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_yes(text))
                profile, _, reply = apply_turn(self.profile, Preferences(), text,
                                               pending_relax=self.fields)
                self.assertEqual(profile.excluded_sectors, self.profile.excluded_sectors)
                self.assertTrue(reply)

    def test_explicit_assent_removes_only_pending_fields(self):
        for text in ("Sí, quítalo", "Sí, quítalas", "Vale", "sigue sin ellas", "Sí, por favor"):
            with self.subTest(text=text):
                profile, pending, reply = apply_turn(self.profile, Preferences(), text,
                                                     pending_relax=self.fields)
                self.assertEqual(profile.excluded_sectors, ())
                self.assertEqual(profile.risk, "medio")
                self.assertEqual(pending, ())
                self.assertFalse(reply)

    def test_ambiguous_reply_preserves_pending_question_until_answer(self):
        profile, pending, reply = apply_turn(self.profile, Preferences(), "Quizá",
                                             pending_relax=self.fields)
        self.assertIsNone(relaxation_answer("Quizá"))
        self.assertEqual(pending, self.fields)
        self.assertTrue(reply)
        profile, pending, reply = apply_turn(profile, Preferences(), "sí", pending_relax=pending)
        self.assertEqual(profile.excluded_sectors, ())
        self.assertFalse(pending or reply)

    def test_refusal_stops_selection_and_closes_question(self):
        profile, pending, reply = apply_turn(self.profile, Preferences(), "No, mantenlas",
                                             pending_relax=self.fields)
        self.assertEqual(profile, self.profile)
        self.assertFalse(pending)
        self.assertTrue(reply)


class OmniExclusionTests(unittest.TestCase):
    def test_exclusions_are_validated_deduplicated_and_not_included(self):
        profile = omni._preferences({"sectores_excluidos": ["Tecnología", "salud", "tecnología"],
                                     "sector": "tecnología"})
        self.assertEqual(profile.excluded_sectors, ("tecnología", "salud"))
        self.assertIsNone(profile.sector)
        for value in ("tecnología", {}, False, ["unknown"], [42]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                omni._preferences({"sectores_excluidos": value})

    def test_exclusion_reaches_common_filter_and_survives_later_turn(self):
        new = omni._preferences({"sectores_excluidos": ["tecnología"]})
        profile, _, _ = apply_turn(Preferences(5, "medio", "EUR"), new, "Sin tecnología")
        profile, _, _ = apply_turn(profile, omni._preferences({}), "continúa")
        selected, diagnostics = recommend(load_catalog(DEMO_CATALOG), profile)
        self.assertFalse(selected)
        self.assertIn("reason", diagnostics)

    def test_model_omission_is_recovered_from_text_and_audio_transcript(self):
        answer = json.dumps({"sector": "tecnología", "sectores_excluidos": []})
        with patch.object(omni, "generate", return_value=answer):
            profile, _, _ = omni.understand([], Preferences(), text="Fondos sin tecnología")
        self.assertEqual(profile.excluded_sectors, ("tecnología",))
        self.assertIsNone(profile.sector)
        with patch.object(omni, "listen", return_value="Sin tecnología"), \
             patch.object(omni, "generate", return_value=answer):
            profile, _, _ = omni.understand([], Preferences(), audio=["mock.wav"])
        self.assertEqual(profile.excluded_sectors, ("tecnología",))

    def test_invalid_horizon_is_not_truncated(self):
        for value in (3.9, True, float("nan"), float("inf")):
            self.assertIsNone(omni._preferences({"plazo_anios": value}).horizon_years)
        self.assertEqual(omni._preferences({"plazo_anios": 3.0}).horizon_years, 3)


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.base = load_catalog(DEMO_CATALOG)[0]
        self.profile = Preferences(5, "medio", "EUR", amount=10000)

    def items(self, vols):
        return [Recommendation(replace(self.base, isin=str(i), vol_5y=vol), 1.0, "test")
                for i, vol in enumerate(vols)]

    def assert_valid(self, weights):
        lower, upper = allocation_limits(len(weights))
        self.assertTrue(all(math.isfinite(w) and lower - 1e-9 <= w <= upper + 1e-9 for w in weights))
        self.assertAlmostEqual(sum(weights), 1)

    def test_extreme_volatilities_respect_bounds_for_every_supported_size(self):
        rng = random.Random(42)
        for size in range(1, 8):
            for _ in range(30):
                weights = allocate(self.items([10 ** rng.uniform(-5, 0) for _ in range(size)]), 5)
                self.assert_valid(weights)
        self.assertEqual(allocate(self.items([0]), 5), [1])
        for vols, expected in (([0.001, 0.2], [0.8, 0.2]),
                               ([0.001, 0.2, 0.2], [0.6, 0.2, 0.2])):
            for actual, target in zip(allocate(self.items(vols), 5), expected):
                self.assertAlmostEqual(actual, target)

    def test_invalid_metrics_cannot_generate_weights(self):
        for vol in (None, -0.1, float("nan"), float("inf"), True):
            with self.subTest(vol=vol), self.assertRaises(ValueError):
                allocate(self.items([vol]), 5)
        with self.assertRaises(ValueError):
            allocate([], 5)

    def test_bad_model_weights_use_bounded_fallback(self):
        candidates = self.items([0.001, 0.2, 0.2])
        for bad in (float("inf"), float("nan"), -1, 0, True, "50", None, 1e308):
            answer = {"seleccion": [{"id": 1, "peso": bad}, {"id": 2, "peso": 50},
                                    {"id": 3, "peso": 50}], "comentario": ""}
            with self.subTest(bad=bad):
                chosen, weights, _ = ai_filter._validated(answer, candidates, self.profile, 3)
                self.assertEqual(len(chosen), 3)
                self.assert_valid(weights)
        overflow = {"seleccion": [{"id": i, "peso": 1e308} for i in (1, 2, 3)]}
        self.assert_valid(ai_filter._validated(overflow, candidates, self.profile, 3)[1])

    def test_invalid_identifiers_never_index_candidates(self):
        candidates = self.items([0.001, 0.2, 0.2])
        for bad in (True, 1.0, "1", None, -1, 999):
            answer = {"seleccion": [{"id": bad, "peso": 50}, {"id": 2, "peso": 50}]}
            chosen, weights, _ = ai_filter._validated(answer, candidates, self.profile, 3)
            self.assertEqual(chosen[0], candidates[1])
            self.assertEqual(len({item.fund.isin for item in chosen}), 3)
            self.assert_valid(weights)

    def test_valid_model_allocation_is_preserved(self):
        answer = {"seleccion": [{"id": 1, "peso": 50}, {"id": 2, "peso": 30}, {"id": 3, "peso": 20}]}
        _, weights, _ = ai_filter._validated(answer, self.items([0.1, 0.2, 0.2]), self.profile, 3)
        self.assertEqual(weights, [0.5, 0.3, 0.2])
        self.assertFalse(valid_allocation([float("nan"), 0], 2))

    def test_rules_and_both_model_failure_paths_produce_valid_pdf(self):
        candidates = self.items([0.001] + [0.2] * 7)
        with patch.dict(os.environ, {"AI_FILTER": "off"}):
            proposals = [ai_filter.select(candidates, self.profile, "texto")]
        with patch.object(ai_filter, "backend", return_value="local"), \
             patch.dict(ai_filter.ASK, {"local": lambda *args: (_ for _ in ()).throw(RuntimeError("test"))}):
            proposals.append(ai_filter.select(candidates, self.profile, "texto"))
        with patch.object(omni, "generate", side_effect=RuntimeError("test")):
            proposals.append(omni.select(candidates, self.profile, "texto"))
        for proposal in proposals:
            self.assert_valid(proposal.weights)
            self.assertTrue(build_pdf(proposal, self.profile, ["texto"], "test").startswith(b"%PDF"))


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.base = replace(load_catalog(DEMO_CATALOG)[0], name="Global Technology Bond Fund",
                            source_url="https://example.org/fund")

    def test_verified_contradiction_cannot_be_overridden_by_name(self):
        for field, value, facts in (
            ("asset_class", "renta fija", {"assets": "Renta variable: acciones"}),
            ("sector", "tecnología", {"sectors": "Salud"}),
            ("region", "global", {"regions": "Europa", "strategy": "Estrategia global"}),
        ):
            with self.subTest(field=field):
                selected, _ = recommend([replace(self.base, **facts)],
                                         replace(Preferences(5, "medio", "EUR"), **{field: value}))
                self.assertFalse(selected)

    def test_unknown_facts_can_use_name_with_disclosure(self):
        for value in ("", "Pendiente de consulta", "Sin dato verificado", "No disponible", "—"):
            selected, _ = recommend([replace(self.base, assets=value)],
                                     Preferences(5, "medio", "EUR", asset_class="renta fija"))
            self.assertEqual(len(selected), 1)
            self.assertIn("exposición no verificada", selected[0].rationale)

    def test_verified_match_does_not_require_matching_name(self):
        selected, _ = recommend([replace(self.base, name="ABC", assets="Renta fija")],
                                 Preferences(5, "medio", "EUR", asset_class="renta fija"))
        self.assertEqual(len(selected), 1)
        self.assertNotIn("por el nombre", selected[0].rationale)

    def test_missing_source_is_not_verified(self):
        selected, _ = recommend([replace(self.base, assets="Renta variable", source_url="")],
                                 Preferences(5, "medio", "EUR", asset_class="renta fija"))
        self.assertEqual(len(selected), 1)
        self.assertIn("exposición no verificada", selected[0].rationale)

    def test_distinct_products_are_not_collapsed(self):
        names = ["Example S&P 500 A", "Example S&P 400 A", "Example Global Hedged EUR A",
                 "Example Global Unhedged EUR A", "Example US Equity A", "Example UK Equity A",
                 "Example Equity JP A", "Example Equity HK A"]
        self.assertEqual(len({_family_name(name) for name in names}), len(names))
        funds = [replace(self.base, name=name, isin=str(i)) for i, name in enumerate(names)]
        selected, _ = recommend(funds, Preferences(5, "medio", "EUR"), limit=10)
        self.assertEqual(len(selected), len(names))


class PageFlowTests(unittest.TestCase):
    def test_both_pages_preserve_exclusion_after_refusal(self):
        from streamlit.testing.v1 import AppTest
        from src import tts, ui
        from src.paths import ROOT

        funds = load_catalog(DEMO_CATALOG)
        profile = Preferences(5, "medio", "EUR", 10000, excluded_sectors=("tecnología",),
                              objective="crecimiento", experience="alta", loss_reaction="espera")
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
                 patch.object(omni, "select", side_effect=ai_filter.select) as select:
                app = AppTest.from_file(str(ROOT / "paginas" / f"{page}.py")).run()
                self.assertFalse(app.exception)
                app.radio[0].set_value(ui.CHAT).run()
                app.session_state["profile"] = profile
                app.session_state["extra_asked"] = True
                app.chat_input[0].set_value("continúa").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["relax"], ("excluded_sectors",))
                app.chat_input[0].set_value("No quiero quitarlo, continúa con la exclusión").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["profile"].excluded_sectors, ("tecnología",))
                self.assertNotIn("relax", app.session_state)
                self.assertIn("Mantengo", app.session_state["messages"][-1]["text"])
                self.assertNotIn("result", app.session_state["messages"][-1])
                select.assert_not_called()
                app.chat_input[0].set_value("continúa").run()
                app.chat_input[0].set_value("quizá").run()
                self.assertEqual(app.session_state["relax"], ("excluded_sectors",))
                self.assertNotIn("result", app.session_state["messages"][-1])
                app.chat_input[0].set_value("Sí, quítalas").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["profile"].excluded_sectors, ())
                result = app.session_state["messages"][-1]["result"]
                self.assertTrue(result["pdf"].startswith(b"%PDF"))
                app.chat_input[0].set_value("Riesgo alto o riesgo medio").run()
                self.assertFalse(app.exception)
                self.assertIn("risk", app.session_state["pending"])
                self.assertIsNone(app.session_state["profile"].risk)
                self.assertNotIn("result", app.session_state["messages"][-1])
                app.chat_input[0].set_value("No alto, medio").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["profile"].risk, "medio")
                self.assertIn("result", app.session_state["messages"][-1])


if __name__ == "__main__":
    unittest.main()
