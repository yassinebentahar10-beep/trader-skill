# Bot de scalping XAUUSD pour MetaTrader 5

Un bot simple et lisible (environ 300 lignes de Python, sans code caché) qui
scalpe l'or sur MetaTrader 5. **Il démarre en simulation : il n'envoie aucun
ordre tant que tu ne changes pas `dry_run`.**

> ⚠️ **Le backtest est négatif.** Sur 60 jours d'or en M15 (novembre 2026,
> contrat à terme GC, spread de 0,45 $ payé), les réglages par défaut donnent
> 82 trades, 42,7 % de gagnants, **−76 $ pour 0,01 lot**, profit factor 0,78 et
> un creux de −187 $. Aucune variante testée n'est rentable de façon fiable.
> Ce bot est un **outil d'apprentissage et de test sur compte démo**, pas une
> machine à gagner. Pas un conseil financier.

## La stratégie

1. **Tendance en H1** : si l'EMA20 est au-dessus de l'EMA50, le bot ne fait que des achats ;
   si elle est en dessous, que des ventes.
2. **Entrée en M15** : une bougie clôturée revient toucher l'EMA20 et la rejette
   (bougie dans le sens de la tendance, clôture du bon côté de l'EMA, mèche d'au moins 30 % de la bougie).
3. **Stop** sous le bas (achat) ou au-dessus du haut (vente) de cette bougie, plus 1 $.
   Il fait au moins 4 $. Au-delà de 12 $, le trade est ignoré.
4. **Objectif** = 2 fois le risque. Le stop passe au point mort quand le trade gagne 1 fois le risque.
5. **Garde-fous** : une seule position à la fois, 4 trades par jour au maximum, arrêt après
   2 pertes d'affilée, après +30 $ ou après −20 $ dans la journée,
   seulement entre 7h et 20h UTC, et pas de trade si le spread dépasse 0,60 $.

## Installation (Windows)

1. Installe **MetaTrader 5** depuis le site de Vantage et connecte-toi à un **compte démo**.
2. Dans MT5 : **Outils → Options → Expert Advisors → coche « Autoriser le trading algorithmique »**.
3. Installe Python 3.9 ou plus récent depuis python.org (coche « Add to PATH »), puis :

   ```
   pip install MetaTrader5
   ```

4. Copie le dossier `mt5-bot` sur ton PC, puis lance le bot, MT5 restant ouvert :

   ```
   cd mt5-bot
   python bot.py
   ```

   Il se connecte au terminal MT5 déjà ouvert. Tu n'as pas de mot de passe à mettre dans un fichier.
5. Le journal s'affiche à l'écran et dans `bot.log`. Ctrl+C pour arrêter.

## Réglages (`config.json`)

| Clé | Défaut | Rôle |
|---|---|---|
| `symbol` | `XAUUSD` | Nom de l'or chez ton broker (chez Vantage, parfois `XAUUSD+` ou `XAUUSD.r` selon le compte) |
| `lot` | `0.01` | Taille de position (0,01 lot = 1 $ par $ de mouvement) |
| `dry_run` | `true` | `true` = simulation, aucun ordre ; `false` = ordres réels sur le compte connecté |
| `allow_live` | `false` | `false` = le bot refuse de tourner sur un compte réel |
| `max_sl_usd` / `min_sl_usd` | `12` / `4` | Stop maximum et minimum en $ |
| `rr` | `2.0` | Objectif = rr × risque |
| `breakeven_at_r` | `1.0` | Stop au point mort quand le gain atteint ce multiple du risque |
| `session_utc` | `[7, 20]` | Heures de trading (UTC) |
| `max_trades_per_day`, `max_consecutive_losses`, `daily_profit_target_usd`, `daily_loss_limit_usd` | 4, 2, 30, 20 | Garde-fous journaliers |

Ordre conseillé : **simulation** (`dry_run: true`) pendant quelques jours, puis **ordres sur compte démo**
(`dry_run: false`) pendant plusieurs semaines. Passe en réel seulement si les résultats du démo sont bons,
en changeant toi-même `allow_live`.

## Backtest

```
python backtest.py
```

Il télécharge l'historique de l'or (Yahoo Finance) et rejoue la stratégie. Change `config.json`
et relance pour comparer. Attention : en essayant des dizaines de réglages, on finit toujours par en
trouver un qui « marche » sur le passé, sans qu'il marche à l'avenir.

## Fichiers

- `strategy.py` : les règles, en fonctions pures, testées dans `tests/test_mt5_bot.py`
- `bot.py` : la connexion à MetaTrader 5, les ordres et les garde-fous
- `backtest.py` : le test sur l'historique
- `config.json` : les réglages
