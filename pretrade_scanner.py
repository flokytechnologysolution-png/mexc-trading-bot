"""Read-only Pre-Trade Profit Scanner for the AI Trading Bot (XAUUSD MA bot).

ANALYSIS ONLY - sends NO orders, NO order_check, NO order_send.

Scans available commodity/metals/energy symbols on the connected MT5 account
and selects the single one with the best SAFE profit margin, using:

    account (deposit target) : 10,000 NGN  = 10000/1600 USD
    max stop loss / trade    :   500 NGN   =   500/1600 USD
    position size            : minimum lot only
    NGN_PER_USD              : 1600

For every commodity it computes: bid/ask, spread (points + cost in USD/NGN),
margin for min lot, M15 ATR volatility, ATR-based SL/TP distances, net profit
& loss after spread, net risk/reward, profit margin %, EMA50/EMA200 trend,
and a 0-100 score.

Pass rules (ALL must hold for a symbol to be tradeable):
  1. Spread cost (NGN)  <= 20% of the 500 NGN risk budget
  2. Margin required    <= 35% of the 10,000 NGN account estimate (USD)
  3. Net expected profit after spread >= 1.5x the risk
  4. Net risk/reward    >= 1.5
  5. Valid live bid/ask present
  6. account trade_allowed is reported (never acted on)

The bot must only trade when trade_allowed == true AND score >= 70; otherwise
it must WAIT.

Outputs a ranked table and a JSON decision dict (also saved to
pretrade_decision.json).

Usage:
    python pretrade_scanner.py
"""

import json
import math
import sys
import threading
import time

import pandas as pd

import MetaTrader5 as mt5

INIT_TIMEOUT_S = 25
M15_PERIOD = 14                  # ATR/RSI period (M15)
EMA_FAST, EMA_SLOW = 50, 200     # trend EMAs
ATR_SL_MULT, ATR_TP_MULT = 1.5, 2.5

NGN_PER_USD = 1600
ACCOUNT_NGN = 10000.0
RISK_NGN = 500.0
ACCOUNT_USD = ACCOUNT_NGN / NGN_PER_USD
RISK_USD = RISK_NGN / NGN_PER_USD

SPREAD_BUDGET_RATIO = 0.20       # pass 1: spread <= 20% of risk budget
MARGIN_BUDGET_RATIO = 0.35       # pass 2: margin <= 35% of account
PROFIT_MIN_MULT = 1.5            # pass 3: net profit >= 1.5x risk
RR_MIN = 1.5                     # pass 4: net R/R >= 1.5
MIN_SCORE = 70                   # bot only trades at score >= 70


def is_commodity_like(info):
    """Identify genuine commodity/metals/energy CFDs.

    Excludes crypto-tokenized 'metals' (e.g. Crypto\\Coins\\XAUT_) and sector
    indexes (e.g. Indexes\\IDX\\IDXENERGY), which are NOT the physical commodity
    CFDs this bot trades. Path-based matching first, then name tokens.
    """
    path = (info.path or "").upper()
    if "CRYPTO" in path or "INDEX" in path:
        return False
    if path and any(gp in path for gp in
                    ("METAL", "ENERG", "COMMODIT", "AGRICULT", "SOFT")):
        return True
    name = (info.name or "").upper()
    return any(tok in name for tok in
               ("XAU", "XAG", "XTI", "XBR", "XNG", "GOLD", "SILVER",
                "USOIL", "UKOIL", "WTI", "BRENT", "NGAS", "NATURALGAS",
                "COPPER", "PALLADIUM", "PLATINUM", "COCOA", "COFFEE",
                "SUGAR", "WHEAT", "CORN", "SOY", "RICE"))


def get_info(info, field):
    try:
        val = getattr(info, field, None)
        return None if val is None else float(val)
    except Exception:
        return None


def compute_atr(highs, lows, closes, period=M15_PERIOD):
    """Average True Range (rolling mean of True Range)."""
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def analyze_symbol(s, rows):
    """Collect all metrics for one commodity symbol. Appends to rows."""
    name = s.name
    path = s.path or ""
    try:
        mt5.symbol_select(name, True)
        time.sleep(0.5)
    except Exception:
        pass
    tick = mt5.symbol_info_tick(name)
    info = mt5.symbol_info(name)
    if (tick is None or info is None
            or not (float(tick.bid) > 0 and float(tick.ask) > 0)):
        rows.append({"symbol": name, "path": path,
                     "error": "no live bid/ask"})
        return

    bid, ask = float(tick.bid), float(tick.ask)
    point = get_info(info, "point")
    contract = get_info(info, "trade_contract_size")
    vmin = get_info(info, "volume_min")

    spread_pts = (ask - bid) / point if point else 0.0
    spread_cost_usd = (ask - bid) * (contract or 0) * (vmin or 0)
    spread_cost_ngn = spread_cost_usd * NGN_PER_USD

    margin_usd = None
    try:
        m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, name, vmin or 0.01, ask)
        margin_usd = float(m) if m is not None else None
    except Exception:
        margin_usd = None

    # --- ATR + EMAs from M15 history --------------------------------
    atr_pts = None
    trend = "FLAT"
    ema50 = ema200 = None
    rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M15, 0, 400)
    if rates is not None and len(rates) >= 220:
        df = pd.DataFrame(rates)
        atr_val = compute_atr(df["high"], df["low"], df["close"]).iloc[-1]
        atr_pts = float(atr_val) / point if point else None
        e50 = compute_ema(df["close"], EMA_FAST).iloc[-1]
        e200 = compute_ema(df["close"], EMA_SLOW).iloc[-1]
        ema50, ema200 = float(e50), float(e200)
        if not (math.isnan(ema50) or math.isnan(ema200)):
            trend = "UP" if ema50 > ema200 else ("DOWN" if ema50 < ema200 else "FLAT")

    # --- ATR-based SL/TP distances (in points) ----------------------
    sl_pts = tp_pts = None
    if atr_pts is not None and atr_pts > 0:
        sl_pts = max(1, int(round(ATR_SL_MULT * atr_pts)))
        tp_pts = max(1, int(round(ATR_TP_MULT * atr_pts)))

    sl_loss_usd = tp_profit_usd = None
    net_loss_usd = net_profit_usd = None
    net_rr = None
    profit_margin_pct = None
    if (sl_pts is not None and contract and vmin and point
            and spread_cost_usd is not None):
        sl_loss_usd = sl_pts * point * contract * vmin
        tp_profit_usd = tp_pts * point * contract * vmin
        net_loss_usd = sl_loss_usd + spread_cost_usd
        net_profit_usd = tp_profit_usd - spread_cost_usd
        if net_loss_usd and net_loss_usd > 0:
            net_rr = net_profit_usd / net_loss_usd
            profit_margin_pct = (net_profit_usd / net_loss_usd - 1) * 100
        else:
            net_rr = None

    # --- pass rules ------------------------------------------------
    reasons = []
    if spread_cost_ngn > SPREAD_BUDGET_RATIO * RISK_NGN:
        reasons.append("spread")
    if margin_usd is None or margin_usd > MARGIN_BUDGET_RATIO * ACCOUNT_USD:
        reasons.append("margin")
    if net_profit_usd is None or net_profit_usd < PROFIT_MIN_MULT * net_loss_usd:
        reasons.append("profit")
    if net_rr is None or net_rr < RR_MIN:
        reasons.append("rr")
    passed = not reasons

    # --- score 0-100 ----------------------------------------------
    score = 0
    if spread_cost_ngn <= SPREAD_BUDGET_RATIO * RISK_NGN:
        score += 25
    if margin_usd is not None and margin_usd <= MARGIN_BUDGET_RATIO * ACCOUNT_USD:
        score += 25
    if (net_profit_usd is not None and net_loss_usd
            and net_profit_usd >= PROFIT_MIN_MULT * net_loss_usd):
        score += 25
    if net_rr is not None and net_rr >= RR_MIN:
        score += 15
    if trend in ("UP", "DOWN"):
        score += 10
    score = max(0, min(100, score))

    rows.append({
        "symbol": name, "path": path,
        "bid": bid, "ask": ask,
        "spread_pts": spread_pts,
        "spread_cost_usd": spread_cost_usd,
        "spread_cost_ngn": spread_cost_ngn,
        "margin_usd": margin_usd,
        "atr_pts": atr_pts,
        "sl_pts": sl_pts, "tp_pts": tp_pts,
        "sl_loss_usd": sl_loss_usd,
        "tp_profit_usd": tp_profit_usd,
        "net_loss_usd": net_loss_usd,
        "net_profit_usd": net_profit_usd,
        "net_rr": net_rr,
        "profit_margin_pct": profit_margin_pct,
        "trend": trend, "ema50": ema50, "ema200": ema200,
        "score": score,
        "pass": passed,
        "fail_reasons": "; ".join(reasons),
    })


def run_scan():
    """Connect, scan all commodities, rank, and return (rows, account)."""
    state = {"ok": False}

    def _worker():
        try:
            state["ok"] = bool(mt5.initialize())
        except Exception as exc:
            state["err"] = str(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(INIT_TIMEOUT_S)

    if not state.get("ok", False):
        reason = state.get("err") or (
            "init timed out" if state.get("ok") is None
            else str(mt5.last_error()))
        print(f"[X] MT5 init failed: {reason}")
        return None, None

    acc = mt5.account_info()
    if acc is None:
        print(f"[X] account_info() -> None: {mt5.last_error()}")
        mt5.shutdown()
        return None, None

    symbols = mt5.symbols_get()
    if symbols is None or len(symbols) == 0:
        print("[X] symbols_get() returned no symbols.")
        mt5.shutdown()
        return None, None

    candidates = [s for s in symbols if is_commodity_like(s)]
    rows = []
    for s in candidates:
        analyze_symbol(s, rows)

    mt5.shutdown()
    return rows, acc

def build_decision(rows, acc):
    """Pick the best passing symbol and build the JSON decision."""
    ta = bool(acc.trade_allowed) if acc is not None else False

    passing = [r for r in rows if r.get("pass") and r.get("score", 0) >= MIN_SCORE]
    passing.sort(key=lambda r: (-r["score"],
                                r.get("spread_cost_ngn") or math.inf,
                                -(r.get("net_rr") or 0.0)))
    best = passing[0] if passing else None

    if best is None:
        return {
            "trade_allowed": False,
            "best_symbol": None,
            "direction": None,
            "score": 0,
            "expected_net_profit_ngn": 0,
            "expected_max_loss_ngn": int(RISK_NGN),
            "net_risk_reward": 0,
            "spread_cost_ngn": 0,
            "margin_required_usd": 0,
            "sl_price": 0,
            "tp_price": 0,
            "reason": "No commodity currently meets the profit-margin safety rules",
        }, ta

    direction = "BUY" if best["trend"] in ("UP", "FLAT") else "SELL"
    entry = best["ask"] if direction == "BUY" else best["bid"]
    point = (best["ask"] - best["bid"]) / best["spread_pts"] if best["spread_pts"] else 0.01
    if direction == "BUY":
        sl_price = entry - best["sl_pts"] * point
        tp_price = entry + best["tp_pts"] * point
    else:
        sl_price = entry + best["sl_pts"] * point
        tp_price = entry - best["tp_pts"] * point

    return {
        "trade_allowed": True,
        "best_symbol": best["symbol"],
        "direction": direction,
        "score": best["score"],
        "expected_net_profit_ngn": round(best["net_profit_usd"] * NGN_PER_USD),
        "expected_max_loss_ngn": round(best["net_loss_usd"] * NGN_PER_USD),
        "net_risk_reward": round(best["net_rr"], 2),
        "spread_cost_ngn": round(best["spread_cost_ngn"]),
        "margin_required_usd": round(best["margin_usd"], 2),
        "sl_price": round(sl_price, 2),
        "tp_price": round(tp_price, 2),
        "reason": "Low spread, enough volatility, positive trend, acceptable margin",
    }, ta


def print_ranked(rows, acc):
    print("=" * 78)
    print(" PRE-TRADE PROFIT SCANNER  (READ-ONLY, NO ORDERS)")
    print("=" * 78)
    if acc is not None:
        print(f" account : {acc.login}  server={acc.server}  "
              f"balance={acc.balance} {acc.currency}")
        print(f" trade_allowed={bool(acc.trade_allowed)}  "
              f"trade_expert={bool(acc.trade_expert)}")
    print(f" funding : {ACCOUNT_NGN:,.0f} NGN = ${ACCOUNT_USD:.2f} USD "
          f"({NGN_PER_USD}/USD)")
    print(f" risk/trade : {RISK_NGN:,.0f} NGN = ${RISK_USD:.4f} USD")
    print("=" * 78)

    def rank_key(r):
        return (0 if r.get("pass") else 1,
                0 if r.get("spread_cost_ngn") is not None else 1,
                r.get("spread_cost_ngn") if r.get("spread_cost_ngn")
                is not None else math.inf)
    srows = sorted(rows, key=rank_key)

    header = (f"{'SYMBOL':<9}{'BID':>11}{'ASK':>11}{'SPR$':>7}"
              f"{'MARG$':>7}{'ATRpt':>7}{'SLpt':>6}{'TPpt':>6}"
              f"{'NETRF':>7}{'PROF%':>7}{'TREND':>6}  RES  SCORE")
    print(header)
    print("-" * len(header))
    for r in srows:
        if r.get("error"):
            print(f"{r['symbol']:<9}  ERROR: {r['error']}")
            continue
        net_rr = f"{r['net_rr']:.2f}" if r["net_rr"] is not None else "n/a"
        pm = f"{r['profit_margin_pct']:.0f}" if r["profit_margin_pct"] is not None else "n/a"
        res = "PASS" if r["pass"] else "FAIL"
        print(f"{r['symbol']:<9}"
              f"{r['bid']:>11.3f}{r['ask']:>11.3f}"
              f"{r['spread_cost_ngn']:>7.0f}"
              f"{r['margin_usd']:>7.2f}"
              f"{r['atr_pts'] if r['atr_pts'] is not None else 0:>7.0f}"
              f"{r['sl_pts'] if r['sl_pts'] is not None else 0:>6.0f}"
              f"{r['tp_pts'] if r['tp_pts'] is not None else 0:>6.0f}"
              f"{net_rr:>7}{pm:>7.5s}{r['trend']:>6}  {res}  {r['score']}")
    print("-" * len(header))
    npass = sum(1 for r in rows if r.get("pass"))
    nerr = sum(1 for r in rows if r.get("error"))
    print(f"\nPASS: {npass}   FAIL: {len(rows)-npass-nerr}   "
          f"no-data/errors: {nerr}   candidates: {len(rows)}")
    print("SPR$=spread(NGN) MARG$=margin(USD) ATRpt=M15 ATR(points) "
          "NETRF=net R/R PROF%=margin%")

def main():
    rows, acc = run_scan()
    if rows is None:
        sys.exit(1)

    print_ranked(rows, acc)
    decision, trade_allowed = build_decision(rows, acc)

    print("\n" + "=" * 78)
    print(" DECISION")
    print("=" * 78)
    print(json.dumps(decision, indent=2))

    with open("pretrade_decision.json", "w", encoding="utf-8") as fh:
        json.dump(decision, fh, indent=2)
    print(f"\n[*] Decision saved -> pretrade_decision.json")

    if not decision["trade_allowed"]:
        print("\n[WAIT] No commodity meets the safety rules - the bot must wait.")
    elif decision["score"] >= MIN_SCORE:
        print(f"\n[TRADE OK] {decision['best_symbol']} {decision['direction']} "
              f"score={decision['score']} - meets score >= {MIN_SCORE}.")
    else:
        print(f"\n[WAIT] {decision['best_symbol']} score={decision['score']} "
              f"below {MIN_SCORE} - do not trade.")


if __name__ == "__main__":
    main()
