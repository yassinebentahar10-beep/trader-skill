"""Backtest de la stratégie sur l'historique de l'or (Yahoo Finance, contrat à terme GC=F).

  python backtest.py                    télécharge 60 jours de M15 et 2 ans de H1
  python backtest.py --m15 a.json --h1 b.json   fichiers JSON Yahoo déjà téléchargés

Simulation prudente : entrée à l'ouverture de la bougie suivante, spread payé à
chaque trade, et si une bougie touche le stop et l'objectif, on compte le stop.
Résultats en $ pour 0,01 lot (1 $ de mouvement = 1 $). Le passé ne garantit rien.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy as st  # noqa: E402

URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?interval={}&range={}"


def load(path=None, interval=None, rng=None):
    if path:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        req = urllib.request.Request(URL.format(interval, rng), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    res = data["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return [(t, o, h, l, c) for t, o, h, l, c in
            zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]) if None not in (o, h, l, c)]


def run(m15, h1, cfg, spread):
    trades, pos, h1_i = [], None, 0
    day, day_pnls = None, []
    for i in range(1, len(m15)):
        t, o, h, l, c = m15[i]
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
        if d.date() != day:
            day, day_pnls = d.date(), []
        closed_at = m15[i - 1][0] + 900  # fin de la bougie i-1 (clôturée)
        while h1_i < len(h1) and h1[h1_i][0] + 3600 <= closed_at:
            h1_i += 1
        if not pos and st.in_session(d.hour, cfg) and st.day_allows(day_pnls, cfg)[0]:
            h1_closes = [b[4] for b in h1[max(0, h1_i - 300):h1_i]]
            sig, _ = st.find_signal(h1_closes, m15[max(0, i - 300):i], cfg)
            if sig:
                entry = o  # entrée à l'ouverture de la bougie suivante
                risk = (entry - sig.sl) if sig.side == "buy" else (sig.sl - entry)
                if 0 < risk <= cfg["max_sl_usd"]:
                    tp = entry + cfg["rr"] * risk if sig.side == "buy" else entry - cfg["rr"] * risk
                    pos = (sig.side, entry, sig.sl, tp, risk)
        if pos:  # gestion de la position sur cette bougie (y compris celle d'entrée)
            side, entry, sl, tp, risk = pos
            hit_sl = l <= sl if side == "buy" else h >= sl
            hit_tp = h >= tp if side == "buy" else l <= tp
            if hit_sl or hit_tp:
                exit_ = sl if hit_sl else tp  # les deux touchés : on compte le stop
                pnl = (exit_ - entry if side == "buy" else entry - exit_) - spread
                trades.append((t, side, round(pnl, 2)))
                day_pnls.append(pnl)
                pos = None
            else:
                new = st.breakeven_sl(side, entry, sl, c, cfg)
                if new is not None:
                    pos = (side, entry, new, tp, risk)
    return trades


def report(trades):
    if not trades:
        print("Aucun trade.")
        return
    pnls = [p for _, _, p in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    pf = sum(wins) / -sum(losses) if losses and sum(losses) else float("inf")
    print("Trades        : %d  (%d gagnants, %d perdants ou nuls)" % (len(pnls), len(wins), len(losses)))
    print("Taux de réussite : %.1f %%" % (100.0 * len(wins) / len(pnls)))
    print("Résultat total : %+.2f $ pour 0,01 lot" % sum(pnls))
    print("Gain moyen / perte moyenne : %+.2f $ / %+.2f $" % (
        sum(wins) / len(wins) if wins else 0, sum(losses) / len(losses) if losses else 0))
    print("Profit factor : %.2f" % pf)
    print("Pire creux (drawdown) : %.2f $" % dd)
    print("Derniers trades :")
    for t, side, p in trades[-8:]:
        print("  %s  %-4s  %+.2f $" % (dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d/%m %H:%M"), side, p))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--config", default=os.path.join(here, "config.json"))
    ap.add_argument("--m15")
    ap.add_argument("--h1")
    ap.add_argument("--spread", type=float, default=0.45, help="coût par trade en $ (spread Vantage ~0,44)")
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    m15 = load(a.m15, "15m", "60d")
    h1 = load(a.h1, "60m", "730d")
    print("Données : %d bougies M15, %d bougies H1" % (len(m15), len(h1)))
    report(run(m15, h1, cfg, a.spread))


if __name__ == "__main__":
    main()
