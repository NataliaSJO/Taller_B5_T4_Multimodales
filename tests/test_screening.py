import threading
import unittest
from dataclasses import replace
from pathlib import Path

from src import screening
from src.catalog import load_catalog
from src.conversation import wants_more
from src.models import Preferences, Proposal
from src.recommender import allocate, recommend
from src.report import brief_summary, summary_text

ROOT = Path(__file__).resolve().parents[1]


class GroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = Preferences(5, "alto", "EUR", amount=10000)
        cls.items, _ = recommend(load_catalog(ROOT / "data/demo_funds.csv"), cls.profile, limit=40)

    def grouped(self):
        """Six candidates, best first: groups 1, 1, 2, none, 2, 3."""
        groups = (1, 1, 2, None, 2, 3)
        return [replace(item, group=group) for item, group in zip(self.items, groups)]

    def test_one_line_per_group_stands_for_all_its_funds(self):
        informed = self.grouped()
        leaders, sizes = screening.representatives(informed)
        self.assertEqual([item.fund.isin for item in leaders],
                         [informed[index].fund.isin for index in (0, 2, 3, 5)])
        self.assertEqual(sizes, {1: 2, 2: 2, 3: 1})
        lines, represented, in_batches = screening.final_lines(informed, limit=3)
        self.assertEqual(len(lines), 3)
        self.assertEqual((represented, in_batches), (5, 0))        # 2 + 2 + the ungrouped one

    def test_batch_picks_take_the_place_of_the_lowest_ranked(self):
        informed = self.grouped()
        outsider = informed[5].fund.isin                                # fourth leader, beyond a limit of 3
        lines, represented, in_batches = screening.final_lines(informed, winners=[outsider], screened=1, limit=3)
        chosen = [item.fund.isin for item in lines]
        self.assertIn(outsider, chosen)
        self.assertNotIn(informed[3].fund.isin, chosen)                 # the third leader gave way
        self.assertEqual(in_batches, 1)
        # a pick that was never part of a reviewed batch is ignored
        self.assertNotIn(outsider, [item.fund.isin for item in screening.final_lines(informed, [outsider], 0, 3)[0]])

    def test_background_work_is_reused_only_while_it_still_applies(self):
        job = screening.Job(key=screening.key_of(self.profile), risk="alto", objective=None)
        self.assertTrue(job.usable_for(self.profile))
        self.assertTrue(job.usable_for(replace(self.profile, risk="medio", objective="crecimiento")))  # lower risk, new trait
        self.assertFalse(job.usable_for(replace(self.profile, currency="USD")))
        self.assertFalse(screening.Job(key=job.key, risk="bajo", objective=None).usable_for(self.profile))  # risk went up

    def test_job_runs_in_the_background_and_stops_on_request(self):
        funds = load_catalog(ROOT / "data/demo_funds.csv")
        decided = threading.Event()
        job = screening.start(funds, self.profile, "texto", lambda profile, said: decided.set() or None,
                              lambda *args: [], with_documents=False)
        job.finish(timeout=30)
        self.assertTrue(decided.is_set())
        self.assertIsNone(job.error)
        self.assertFalse(job.thread.is_alive())


class SummaryTests(unittest.TestCase):
    def test_short_summary_talks_about_the_portfolio_not_the_funds(self):
        profile = Preferences(5, "medio", "EUR", amount=10000)
        items, _ = recommend(load_catalog(ROOT / "data/demo_funds.csv"), profile, limit=40)
        proposal = Proposal(tuple(items[:3]), tuple(allocate(items[:3], 5)), "Reglas deterministas")
        short, detail = brief_summary(proposal, profile, reviewed=640), summary_text(proposal, profile)
        self.assertIn("revisar 640 fondos", short)
        self.assertIn("¿Quieres que te cuente el detalle de cada fondo?", short)
        self.assertNotIn(items[0].fund.name, short)
        self.assertIn(items[0].fund.name, detail)
        self.assertLess(len(short.split()), 150)                        # about a minute of speech

    def test_answer_to_the_offer_of_detail(self):
        for text in ("Sí", "sí, por favor", "Vale, cuéntame", "Quiero el detalle", "explícamelo"):
            self.assertIs(wants_more(text), True, text)
        for text in ("No", "no hace falta", "No, gracias", "así está bien", "no quiero el detalle"):
            self.assertIs(wants_more(text), False, text)
        for text in ("Mejor riesgo bajo", "Si cae vendería todo y además quiero invertir veinte mil euros"):
            self.assertIsNone(wants_more(text), text)


if __name__ == "__main__":
    unittest.main()
