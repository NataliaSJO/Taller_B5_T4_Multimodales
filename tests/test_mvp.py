import tempfile
import unittest
from pathlib import Path

from scripts.import_catalog import convert
from src.catalog import load_catalog
from src.models import Preferences
from src.preferences import parse_heuristic
from src.recommender import recommend

ROOT = Path(__file__).resolve().parents[1]


class PreferencesTests(unittest.TestCase):
    def test_explicit_spanish_request(self):
        profile = parse_heuristic("Quiero invertir 10.000 euros a cinco años, riesgo medio, en un fondo global")
        self.assertEqual(profile.amount, 10000)
        self.assertEqual(profile.horizon_years, 5)
        self.assertEqual(profile.risk, "medio")
        self.assertEqual(profile.currency, "EUR")
        self.assertEqual(profile.region, "global")

    def test_missing_risk_is_not_guessed(self):
        profile = parse_heuristic("Quiero un fondo a tres años")
        self.assertIsNone(profile.risk)
        self.assertIsNone(profile.currency)
        self.assertEqual(profile.horizon_years, 3)

    def test_exclusion_is_not_inclusion(self):
        profile = parse_heuristic("5 años, riesgo medio, euros, sin tecnología")
        self.assertIn("tecnología", profile.excluded_sectors)
        self.assertIsNone(profile.sector)

    def test_everyday_risk_words(self):
        self.assertEqual(parse_heuristic("no quiero sustos").risk, "bajo")
        self.assertEqual(parse_heuristic("puedo aguantar bastante riesgo").risk, "alto")

    def test_plural_region(self):
        self.assertEqual(parse_heuristic("fondos globales a 5 años").region, "global")

    def test_asset_class_is_preserved(self):
        self.assertEqual(parse_heuristic("bonos en euros a cinco años").asset_class, "renta fija")
        self.assertEqual(parse_heuristic("renta fija y renta variable").asset_class, "mixto")


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.funds = load_catalog(ROOT / "data/demo_funds.csv")

    def test_risk_currency_and_horizon_filters(self):
        results, diag = recommend(self.funds, Preferences(5, "bajo", "EUR"))
        self.assertTrue(results)
        self.assertTrue(all(item.fund.currency == "EUR" and item.fund.vol_5y <= 0.10 for item in results))
        self.assertEqual(diag["catalog"], 10)

    def test_region_requires_profile(self):
        results, _ = recommend(self.funds, Preferences(5, "medio", "EUR", region="global"))
        self.assertTrue(results)
        self.assertTrue(all("global" in item.fund.strategy.lower() for item in results))

    def test_sector_exclusion_abstains(self):
        results, diag = recommend(self.funds, Preferences(5, "medio", "EUR", excluded_sectors=("tecnología",)))
        self.assertEqual(results, [])
        self.assertIn("no verifica", diag["reason"])

    def test_sharpe_missing_stays_missing(self):
        results, _ = recommend(self.funds, Preferences(5, "medio", "CHF"))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].fund.sharpe_5y)
        self.assertIn("sin Sharpe", results[0].rationale)

    def test_share_classes_of_one_fund_are_grouped(self):
        from src.recommender import _family_name
        names = ("DNB Technology IA EUR in GB**", "DNB Fund - Technology retail A (N)", "DNB Fund Technology retail A")
        self.assertEqual({_family_name(name) for name in names}, {"dnb technology"})
        self.assertNotEqual(_family_name("Amundi Global Equity A"), _family_name("Amundi Global Equity Income A"))

    def test_retail_class_is_preferred_for_small_amounts(self):
        from dataclasses import replace
        base = next(fund for fund in self.funds if fund.isin == "DEMO000002")
        inst = replace(base, isin="INST", name=base.name + " Institutional", return_5y=base.return_5y + 0.05)
        funds = [inst, replace(base, name=base.name + " Retail A")]
        small, _ = recommend(funds, Preferences(5, "medio", "EUR", amount=5000))
        large, _ = recommend(funds, Preferences(5, "medio", "EUR", amount=500000))
        self.assertEqual([item.fund.isin for item in small], ["DEMO000002"])
        self.assertEqual([item.fund.isin for item in large], ["INST"])

    def test_documents_filter_by_official_risk_and_minimum(self):
        from dataclasses import replace
        base = next(fund for fund in self.funds if fund.isin == "DEMO000002")
        risky = replace(base, isin="SRI6", name="Demo Arriesgado", sri=6, brochure="DFI")
        costly = replace(base, isin="MIN", name="Demo Minimo Alto", min_investment=50000, min_currency="EUR", brochure="ficha")
        cheap = replace(base, isin="OK", name="Demo Barato", sri=3, costs=0.2, brochure="DFI")
        dear = replace(base, isin="CARO", name="Demo Caro", sri=3, costs=2.5, brochure="DFI")
        results, diag = recommend([risky, costly, cheap, dear], Preferences(5, "medio", "EUR", amount=5000), limit=10)
        self.assertEqual([item.fund.isin for item in results], ["OK", "CARO"])   # lower costs rank first
        self.assertEqual((diag["sri"], diag["minimum"]), (1, 1))
        self.assertIn("riesgo oficial 3 de 7", results[0].rationale)
        enough, _ = recommend([costly], Preferences(5, "medio", "EUR", amount=60000))
        self.assertEqual(len(enough), 1)

    def test_brochure_extraction_rules(self):
        from scripts.procesar_folletos import classify, number, read_ficha, read_kid
        kid = read_kid("Tipo: Fondo de Inversión. RENTA VARIABLE INTERNACIONAL.\nel plazo de inversión recomendado es de 5 años.\n"
                       "Hemos clasificado este producto en la clase de riesgo 5 en una escala de 7\n"
                       "Comisiones de gestión y otros costes administrativos o de funcionamiento 1,85 % del valor\n"
                       "Objetivos: El fondo invierte al menos un 75% en renta variable de empresas radicadas en China y Asia.")
        self.assertEqual((kid["sri"], kid["periodo_anios"], kid["costes_pct"]), (5, 5, 1.85))
        self.assertEqual(number("35.000"), 35000)
        self.assertEqual(read_ficha("INVERSIÓN MÍNIMA\n35.000 USD\n5.000 USD\nDIVISA\nEUR")["inversion_minima"], 35000)
        self.assertEqual(classify(kid["objetivo"])["regiones"], "asia")
        self.assertNotIn("sectores", classify("invierte en instrumentos financieros y activos financieros"))

    def test_semantic_matches_pass_the_keyword_filter_and_rank_higher(self):
        from src.models import Criteria
        alto = Preferences(5, "alto", "EUR")
        gold = Criteria((0.4, 0.3, 0.3), 0.30, keywords=("oro",))
        self.assertEqual(recommend(self.funds, alto, limit=40, criteria=gold)[0], [])      # no fund is called «oro»
        found, _ = recommend(self.funds, alto, limit=40, criteria=gold, semantic={"DEMO000004": 0.6})
        self.assertEqual([item.fund.isin for item in found], ["DEMO000004"])
        self.assertIn("búsqueda semántica", found[0].rationale)
        plain = {item.fund.isin: item.score for item in recommend(self.funds, alto, limit=40)[0]}
        pushed = {item.fund.isin: item.score for item in recommend(self.funds, alto, limit=40, semantic={"DEMO000004": 0.6})[0]}
        self.assertAlmostEqual(pushed["DEMO000004"] - plain["DEMO000004"], 0.03)

    def test_whisper_phantom_lines_are_not_speech(self):
        from types import SimpleNamespace
        from src.audio import spoken
        segment = lambda text, silence=0.1, logprob=-0.3: SimpleNamespace(text=text, no_speech_prob=silence, avg_logprob=logprob)
        self.assertEqual(spoken([segment(" Subtítulos por la comunidad de Amara.org")]), "")
        self.assertEqual(spoken([segment("¡Gracias por ver el vídeo!"), segment("[Música]")]), "")
        self.assertEqual(spoken([segment("mmm", silence=0.9, logprob=-1.4)]), "")
        self.assertEqual(spoken([segment(" Cinco años."), segment(" Subtítulos realizados por la comunidad de Amara.org")]),
                         "Cinco años.")
        self.assertEqual(spoken([segment("Gracias, con riesgo medio")]), "Gracias, con riesgo medio")

    def test_fixed_income_does_not_return_mixed_fund(self):
        results, _ = recommend(self.funds, Preferences(5, "bajo", "EUR", asset_class="renta fija"))
        self.assertEqual([item.fund.isin for item in results], ["DEMO000001"])


class ImportTests(unittest.TestCase):
    def test_markdown_import_preserves_missing_sharpe(self):
        values = [
            "TEST00000001", "Fondo de prueba", "TEST.EUFUND", "EUR", "FUND",
            "Descargado (1000 obs.)", "2020-01-01–2026-10-05", "Renta fija",
            "Pendiente de consulta", "Europa", "Pendiente de consulta",
            "Rent. +3,1 %; vol. 4,0 %; Sharpe — (sin tasa)",
            "Rent. +8,0 %; vol. 5,0 %; Sharpe +0,42",
            "Histórico insuficiente", "Vol. anual 5,0 %",
            "[Fuente](https://example.org/fondo) (2026-01-01)",
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalogo.md"
            target = Path(directory) / "funds.csv"
            source.write_text("| " + " | ".join(values) + " |\n", encoding="utf-8")
            self.assertEqual(convert(source, target), 1)
            fund = load_catalog(target)[0]
            self.assertAlmostEqual(fund.return_1y, 0.031)
            self.assertIsNone(fund.sharpe_1y)
            self.assertAlmostEqual(fund.sharpe_3y, 0.42)
            self.assertIsNone(fund.return_5y)
            self.assertEqual(fund.source_url, "https://example.org/fondo")


if __name__ == "__main__":
    unittest.main()
