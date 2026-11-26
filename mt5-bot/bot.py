"""Bot de scalping XAUUSD pour MetaTrader 5 (Windows).

Lancement :  python bot.py            (lit config.json à côté de ce fichier)
             python bot.py --config autre.json

Prérequis : le terminal MetaTrader 5 de ton broker ouvert ET connecté à ton
compte, puis  pip install MetaTrader5

Sécurités :
  - dry_run = true (par défaut) : le bot affiche les signaux mais ne passe AUCUN ordre.
  - allow_live = false (par défaut) : le bot refuse de démarrer sur un compte réel.
  - chaque ordre part avec un stop et un objectif ; une seule position à la fois.
"""

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy as st  # noqa: E402

try:
    import MetaTrader5 as mt5
except ImportError:
    sys.exit("Le module MetaTrader5 manque. Installe-le (Windows uniquement) :  pip install MetaTrader5")

log = logging.getLogger("xau-bot")


def setup_logging():
    here = os.path.dirname(os.path.abspath(__file__))
    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(), logging.FileHandler(os.path.join(here, "bot.log"), encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def rates(symbol, timeframe, count):
    """Bougies CLÔTURÉES (on saute la bougie en cours, position 0)."""
    r = mt5.copy_rates_from_pos(symbol, timeframe, 1, count)
    if r is None or len(r) == 0:
        return []
    return [(int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])) for x in r]


def my_positions(cfg):
    return [p for p in (mt5.positions_get(symbol=cfg["symbol"]) or ()) if p.magic == cfg["magic"]]


def today_pnls(cfg, server_now):
    """Résultats des trades du bot fermés depuis minuit (heure du serveur)."""
    day_start = server_now - server_now % 86400
    now = dt.datetime.now()
    deals = mt5.history_deals_get(now - dt.timedelta(days=2), now + dt.timedelta(days=1)) or ()
    out = [d for d in deals
           if d.magic == cfg["magic"] and d.entry == mt5.DEAL_ENTRY_OUT and d.time >= day_start]
    out.sort(key=lambda d: d.time)
    return [d.profit + d.commission + d.swap for d in out]


def filling_mode(info):
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def manage_breakeven(cfg):
    tick = mt5.symbol_info_tick(cfg["symbol"])
    for p in my_positions(cfg):
        side = "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell"
        price = tick.bid if side == "buy" else tick.ask
        new_sl = st.breakeven_sl(side, p.price_open, p.sl, price, cfg)
        if new_sl is None:
            continue
        if cfg["dry_run"]:
            log.info("[SIMULATION] stop de #%d à remonter au point mort : %.2f", p.ticket, new_sl)
            continue
        res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": cfg["symbol"],
                              "position": p.ticket, "sl": new_sl, "tp": p.tp})
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("Stop de #%d déplacé au point mort : %.2f", p.ticket, new_sl)
        else:
            log.warning("Échec du déplacement du stop #%d : %s", p.ticket, res)


def place(cfg, sig, info):
    tick = mt5.symbol_info_tick(cfg["symbol"])
    price = tick.ask if sig.side == "buy" else tick.bid
    # le stop reste sous/au-dessus de la bougie ; on recalcule le risque au prix réel
    risk = (price - sig.sl) if sig.side == "buy" else (sig.sl - price)
    if risk <= 0 or risk > cfg["max_sl_usd"]:
        log.info("Prix parti (%.2f) : risque réel %.2f $ hors limites, trade ignoré", price, risk)
        return
    tp = price + cfg["rr"] * risk if sig.side == "buy" else price - cfg["rr"] * risk
    min_dist = info.trade_stops_level * info.point
    if risk < min_dist:
        log.info("Stop trop proche pour le broker (%.2f < %.2f), trade ignoré", risk, min_dist)
        return
    lot = max(info.volume_min, cfg["lot"])
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": cfg["symbol"], "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if sig.side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price, "sl": round(sig.sl, info.digits), "tp": round(tp, info.digits),
        "deviation": 20, "magic": cfg["magic"], "comment": "xau-scalper",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_mode(info),
    }
    if cfg["dry_run"]:
        log.info("[SIMULATION] %s %.2f lot à %.2f  SL %.2f  TP %.2f  (risque %.2f $)",
                 sig.side.upper(), lot, price, req["sl"], req["tp"], risk)
        return
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("ORDRE EXÉCUTÉ #%d %s %.2f lot à %.2f  SL %.2f  TP %.2f",
                 res.order, sig.side.upper(), lot, res.price, req["sl"], req["tp"])
    else:
        log.error("Ordre refusé : %s", res)


def step(cfg, info, last_bar):
    """Un passage de la boucle. Renvoie l'heure de la dernière bougie M15 traitée."""
    manage_breakeven(cfg)
    m15 = rates(cfg["symbol"], mt5.TIMEFRAME_M15, 300)
    if not m15 or m15[-1][0] == last_bar:
        return last_bar
    bar_time = m15[-1][0]
    h1 = [b[4] for b in rates(cfg["symbol"], mt5.TIMEFRAME_H1, 300)]
    tick = mt5.symbol_info_tick(cfg["symbol"])
    log.info("Nouvelle bougie M15 clôturée à %.2f", m15[-1][4])

    if my_positions(cfg):
        log.info("Une position est déjà ouverte : pas de nouveau trade")
        return bar_time
    if not st.in_session(dt.datetime.now(dt.timezone.utc).hour, cfg):
        log.info("Hors session de trading")
        return bar_time
    spread = tick.ask - tick.bid
    if spread > cfg["max_spread_usd"]:
        log.info("Spread trop large (%.2f $)", spread)
        return bar_time
    ok, why = st.day_allows(today_pnls(cfg, tick.time), cfg)
    if not ok:
        log.info("Journée terminée : %s", why)
        return bar_time
    sig, why = st.find_signal(h1, m15, cfg)
    if sig is None:
        log.info("Pas de signal : %s", why)
        return bar_time
    log.info("SIGNAL %s : %s", sig.side.upper(), sig.reason)
    place(cfg, sig, info)
    return bar_time


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    args = ap.parse_args()
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    setup_logging()

    if not mt5.initialize():
        sys.exit("Impossible de se connecter à MetaTrader 5 (terminal ouvert et connecté ?) : %s" % (mt5.last_error(),))
    try:
        acc = mt5.account_info()
        demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        log.info("Compte %d sur %s (%s), solde %.2f %s", acc.login, acc.server,
                 "DÉMO" if demo else "RÉEL", acc.balance, acc.currency)
        if not demo and not cfg["allow_live"]:
            sys.exit("Compte RÉEL détecté et allow_live = false : arrêt. Teste d'abord sur un compte démo.")
        if not mt5.symbol_select(cfg["symbol"], True):
            sys.exit("Symbole %s introuvable chez ton broker (essaie XAUUSD+, XAUUSD.r, GOLD...)" % cfg["symbol"])
        info = mt5.symbol_info(cfg["symbol"])
        log.info("Démarrage sur %s, %.2f lot, mode %s. Ctrl+C pour arrêter.",
                 cfg["symbol"], cfg["lot"], "SIMULATION (aucun ordre)" if cfg["dry_run"] else "ORDRES RÉELS")
        last_bar = None
        while True:
            try:
                last_bar = step(cfg, info, last_bar)
            except Exception:  # une erreur réseau ne doit pas tuer le bot
                log.exception("Erreur dans la boucle, on continue")
            time.sleep(cfg["poll_seconds"])
    except KeyboardInterrupt:
        log.info("Arrêt demandé.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
