import json
import os
import unittest

from _load import ROOT, load

st = load("mt5-bot", "strategy")
with open(os.path.join(ROOT, "mt5-bot", "config.json"), encoding="utf-8") as fh:
    CFG = json.load(fh)


def bars_around(level, n=60):
    """Bougies plates autour d'un niveau, pour que l'EMA M15 y soit."""
    return [(i * 900, level, level + 1, level - 1, level) for i in range(n)]


class Strategy(unittest.TestCase):
    def test_ema_matches_hand_computation(self):
        e = st.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)
        self.assertAlmostEqual(e[4], 4.0)

    def test_trend(self):
        self.assertEqual(st.trend(list(range(100))), "up")
        self.assertEqual(st.trend(list(range(100, 0, -1))), "down")
        self.assertIsNone(st.trend([1] * 10))

    def test_buy_on_rejection_of_the_ema_in_an_uptrend(self):
        m15 = bars_around(3550) + [(99999, 3549, 3556, 3546, 3555)]  # mèche basse, clôture haute
        sig, why = st.find_signal(list(range(3400, 3500)), m15, CFG)
        self.assertIsNotNone(sig, why)
        self.assertEqual(sig.side, "buy")
        self.assertEqual(sig.sl, 3545.0)            # bas 3546 - 1 $ de marge
        self.assertEqual(sig.risk, 10.0)
        self.assertEqual(sig.tp, 3575.0)            # 2 x le risque

    def test_sell_on_rejection_in_a_downtrend(self):
        m15 = bars_around(3550) + [(99999, 3551, 3554, 3544, 3545)]
        sig, why = st.find_signal(list(range(3600, 3500, -1)), m15, CFG)
        self.assertIsNotNone(sig, why)
        self.assertEqual(sig.side, "sell")
        self.assertEqual(sig.sl, 3555.0)
        self.assertEqual(sig.tp, 3525.0)

    def test_no_counter_trend_trade(self):
        m15 = bars_around(3550) + [(99999, 3549, 3556, 3546, 3555)]
        sig, why = st.find_signal(list(range(3600, 3500, -1)), m15, CFG)
        self.assertIsNone(sig)
        self.assertIn("baissière", why)

    def test_stop_too_wide_is_skipped(self):
        m15 = bars_around(3550) + [(99999, 3549, 3575, 3530, 3570)]
        sig, why = st.find_signal(list(range(3400, 3500)), m15, CFG)
        self.assertIsNone(sig)
        self.assertIn("stop trop large", why)

    def test_min_stop_is_applied(self):
        m15 = bars_around(3550) + [(99999, 3549.8, 3551.5, 3548.5, 3551)]
        sig, why = st.find_signal(list(range(3400, 3500)), m15, CFG)
        self.assertIsNotNone(sig, why)
        self.assertEqual(sig.risk, CFG["min_sl_usd"])

    def test_day_guard(self):
        self.assertTrue(st.day_allows([], CFG)[0])
        self.assertFalse(st.day_allows([-9, -9], CFG)[0])               # 2 pertes d'affilée
        self.assertTrue(st.day_allows([-9, 18, -9], CFG)[0])
        self.assertFalse(st.day_allows([18, 18], CFG)[0])                # objectif atteint
        self.assertFalse(st.day_allows([5, -9, 5, -9], CFG)[0])          # 4 trades
        self.assertFalse(st.day_allows([-21], CFG)[0])                   # perte max

    def test_breakeven(self):
        self.assertEqual(st.breakeven_sl("buy", 3550, 3540, 3560, CFG), 3550.5)
        self.assertIsNone(st.breakeven_sl("buy", 3550, 3540, 3555, CFG))
        self.assertIsNone(st.breakeven_sl("buy", 3550, 3550.5, 3570, CFG))  # déjà au point mort
        self.assertEqual(st.breakeven_sl("sell", 3550, 3560, 3540, CFG), 3549.5)

    def test_safe_defaults(self):
        self.assertTrue(CFG["dry_run"])
        self.assertFalse(CFG["allow_live"])
        self.assertEqual(CFG["lot"], 0.01)


if __name__ == "__main__":
    unittest.main()
