"""Stratégie de scalping XAUUSD, en fonctions pures (testables sans MetaTrader).

Règles :
  1. Tendance en H1 : EMA rapide au-dessus de l'EMA lente -> achats seulement,
     en dessous -> ventes seulement.
  2. Entrée en M15, sur une bougie CLÔTURÉE qui touche l'EMA d'entrée (retour
     dans la tendance) et la rejette : bougie dans le sens de la tendance,
     clôture du bon côté de l'EMA, mèche de rejet suffisante.
  3. Stop sous (ou au-dessus de) la bougie de rejet, entre min_sl_usd et
     max_sl_usd ; au-delà de max_sl_usd le trade est ignoré.
  4. Objectif = rr x le risque. Stop ramené au prix d'entrée à breakeven_at_r.
  5. Garde-fous journaliers : nombre de trades, pertes d'affilée, objectif de
     gain et perte maximale du jour.

Une bougie est un tuple (time, open, high, low, close).
"""

from dataclasses import dataclass


def ema(values, n):
    """Moyenne mobile exponentielle, amorcée sur la moyenne simple des n premières valeurs."""
    if len(values) < n:
        return []
    k = 2.0 / (n + 1)
    out = [None] * (n - 1)
    e = sum(values[:n]) / n
    out.append(e)
    for v in values[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def trend(h1_closes, fast=20, slow=50):
    """'up', 'down' ou None (pas assez d'historique ou EMA égales)."""
    if len(h1_closes) < slow + 1:
        return None
    f, s = ema(h1_closes, fast)[-1], ema(h1_closes, slow)[-1]
    if f > s:
        return "up"
    if f < s:
        return "down"
    return None


@dataclass
class Signal:
    side: str        # "buy" ou "sell"
    entry: float     # prix de référence (clôture de la bougie de rejet)
    sl: float
    tp: float
    risk: float      # distance entrée -> stop, en $
    reason: str


def find_signal(h1_closes, m15_bars, cfg):
    """Renvoie (Signal, None) ou (None, raison du refus).

    m15_bars : bougies M15 clôturées, la dernière est celle qu'on évalue.
    """
    t = trend(h1_closes, cfg["ema_trend_fast"], cfg["ema_trend_slow"])
    if t is None:
        return None, "pas de tendance H1"
    closes = [b[4] for b in m15_bars]
    e = ema(closes, cfg["ema_entry"])
    if not e:
        return None, "pas assez de bougies M15"
    e20 = e[-1]
    _, o, h, l, c = m15_bars[-1]
    rng = h - l
    if rng <= 0:
        return None, "bougie sans amplitude"
    tol = cfg["touch_usd"]

    if t == "up":
        if l > e20 + tol:
            return None, "tendance haussière, prix loin de l'EMA (pas de repli)"
        wick = min(o, c) - l
        if not (c > o and c > e20 and wick >= cfg["min_wick_ratio"] * rng):
            return None, "tendance haussière, pas de rejet de l'EMA"
        sl = l - cfg["sl_buffer_usd"]
        risk = c - sl
        if risk < cfg["min_sl_usd"]:
            risk = cfg["min_sl_usd"]
            sl = c - risk
        if risk > cfg["max_sl_usd"]:
            return None, "stop trop large (%.2f $ > %.2f $)" % (risk, cfg["max_sl_usd"])
        return Signal("buy", c, round(sl, 2), round(c + cfg["rr"] * risk, 2), round(risk, 2),
                      "H1 haussier, rejet de l'EMA%d M15 à %.2f" % (cfg["ema_entry"], e20)), None

    if h < e20 - tol:
        return None, "tendance baissière, prix loin de l'EMA (pas de repli)"
    wick = h - max(o, c)
    if not (c < o and c < e20 and wick >= cfg["min_wick_ratio"] * rng):
        return None, "tendance baissière, pas de rejet de l'EMA"
    sl = h + cfg["sl_buffer_usd"]
    risk = sl - c
    if risk < cfg["min_sl_usd"]:
        risk = cfg["min_sl_usd"]
        sl = c + risk
    if risk > cfg["max_sl_usd"]:
        return None, "stop trop large (%.2f $ > %.2f $)" % (risk, cfg["max_sl_usd"])
    return Signal("sell", c, round(sl, 2), round(c - cfg["rr"] * risk, 2), round(risk, 2),
                  "H1 baissier, rejet de l'EMA%d M15 à %.2f" % (cfg["ema_entry"], e20)), None


def day_allows(pnls, cfg):
    """pnls : résultats ($) des trades fermés aujourd'hui, dans l'ordre. Renvoie (ok, raison)."""
    if len(pnls) >= cfg["max_trades_per_day"]:
        return False, "nombre maximum de trades du jour atteint"
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break
    if streak >= cfg["max_consecutive_losses"]:
        return False, "%d pertes d'affilée : stop pour aujourd'hui" % streak
    total = sum(pnls)
    if total >= cfg["daily_profit_target_usd"]:
        return False, "objectif du jour atteint (+%.2f $)" % total
    if total <= -cfg["daily_loss_limit_usd"]:
        return False, "perte maximale du jour atteinte (%.2f $)" % total
    return True, ""


def in_session(hour_utc, cfg):
    start, end = cfg["session_utc"]
    return start <= hour_utc < end


def breakeven_sl(side, open_price, sl, price, cfg):
    """Nouveau stop si le trade a atteint breakeven_at_r fois le risque, sinon None."""
    if side == "buy":
        risk = open_price - sl
        if risk > 0 and price - open_price >= cfg["breakeven_at_r"] * risk:
            return round(open_price + cfg["breakeven_offset_usd"], 2)
    else:
        risk = sl - open_price
        if risk > 0 and open_price - price >= cfg["breakeven_at_r"] * risk:
            return round(open_price - cfg["breakeven_offset_usd"], 2)
    return None
