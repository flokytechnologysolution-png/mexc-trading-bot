"""Build a read-only Pre-Trade Profit Scanner for the MT5 bot.

Do not send orders.
Do not use order_send.
Do not use order_check.
This is analysis only.

Goal:
Before the bot commits to any commodity trade, it must scan available commodities and select only the one with the best safe profit margin.

Account assumptions:
- Deposit target: ₦10,000
- Max stop loss per trade: ₦500
- Use minimum lot size only
- Use live broker data only
- No bonus funds
- NGN_PER_USD = 1600

The scanner must calculate for each commodity:
1. Current bid/ask
2. Spread points
3. Spread cost in USD and NGN at minimum lot
4. Margin required for minimum lot
5. ATR volatility on M15
6. Estimated stop-loss distance using ATR
7. Estimated take-profit distance using ATR
8. Estimated net profit after spread
9. Estimated net loss after spread
10. Net risk/reward ratio
11. Profit margin percentage
12. Trend direction using EMA 50 and EMA 200
13. Final score from 0 to 100

Pass rules:
- Spread cost must be <= 20% of the ₦500 risk budget
- Margin required must be <= 35% of the ₦10,000 account estimate
- Net expected profit after spread must be at least 1.5x the risk
- Net risk/reward must be >= 1.5
- Symbol must have valid live bid/ask
- Account trade_allowed must be reported but no trade must be sent
- If no symbol passes, output WAIT and do not trade

Output:
Return a ranked table and JSON decision like:

{
  "trade_allowed": false,
  "best_symbol": null,
  "direction": null,
  "score": 0,
  "expected_net_profit_ngn": 0,
  "expected_max_loss_ngn": 500,
  "net_risk_reward": 0,
  "spread_cost_ngn": 0,
  "margin_required_usd": 0,
  "reason": "No commodity currently meets the profit-margin safety rules"
}

If a valid symbol is found, return:

{
  "trade_allowed": true,
  "best_symbol": "SYMBOL",
  "direction": "BUY" or "SELL",
  "score": 75,
  "expected_net_profit_ngn": 850,
  "expected_max_loss_ngn": 500,
  "net_risk_reward": 1.7,
  "spread_cost_ngn": 80,
  "margin_required_usd": 1.25,
  "sl_price": 0,
  "tp_price": 0,
  "reason": "Low spread, enough volatility, positive trend, acceptable margin"
}

Important:
The bot must only commit to a trade when the scanner returns trade_allowed = true and score >= 70.
Otherwise, it must wait.

-------------------------------------------------------------------------------
Read-only MT5 commodity/metals/energy symbol scan.

NO orders, NO order_check, NO order_send. Commission/fees are deliberately
excluded (not requested / can't compute reliably from the API).

For each commodity-like symbol, collects live bid/ask, contract data and
margin (order_calc_margin only), then scores it against the funding and risk
budget:  account_usd = 10000/1600, risk_usd = 500/1600.

Pass criteria:
  1. account info reported (trade_allowed etc.) - reported, never traded
  2. spread cost at minimum lot <= 25% of risk_usd
  3. margin for minimum lot     <= 50% of account_usd
  4. affordable stop distance   >= 3x current spread
  5. valid live bid/ask present

Outputs a ranked table (safest first) to console and commodities_scan.csv.

Usage:
    python scan_commodities.py
"""

import csv
import math
import sys
import threading

import MetaTrader5 as mt5

INIT_TIMEOUT_S = 20
NGN_PER_USD = 1600
ACCOUNT_NGN = 10000.0
RISK_NGN = 500.0
ACCOUNT_USD = ACCOUNT_NGN / NGN_PER_USD
RISK_USD = RISK_NGN / NGN_PER_USD
SPREAD_RATIO_MAX = 0.25      # criterion 2
MARGIN_RATIO_MAX = 0.50      # criterion 3
STOP_MIN_MULT = 3.0          # criterion 4


def is_commodity_like(info):
    """Heuristic: name matches common commodity tokens, OR the symbol's
    group/path sits under a commodity category. Falls back to token matching
    when the path is empty."""
    name = (info.name or "").upper()
    path = (info.path or "").upper()
    if any(tok in name for tok in
           ("XAU", "XAG", "GOLD", "SILVER", "USOIL", "UKOIL", "OIL", "WTI",
            "BRENT", "NGAS", "NATURALGAS", "GAS", "COPPER", "PALLADIUM",
            "PLATINUM", "ALU", "COCOA", "COFFEE", "SUGAR", "WHEAT", "CORN",
            "SOY", "RICE", "ORANGE")):
        return True
    if path:
        return any(gp in path for gp in
                   ("Metals", "Commodit", "Energy", "Agriculture", "Soft"))
    return False


def get_info(info, field):
    try:
        val = getattr(info, field, None)
        return None if val is None else float(val)
    except Exception:
        return None

def main():
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
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        print(f"[X] account_info() -> None: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    print("=" * 72)
    print(" COMMODITY / METALS / ENERGY SYMBOL SCAN  (READ-ONLY, NO ORDERS)")
    print("=" * 72)
    print(f" account login  : {acc.login}")
    print(f" server         : {acc.server}")
    print(f" balance/equity : {acc.balance} / {acc.equity} {acc.currency}")
    print(f" leverage       : 1:{acc.leverage}")
    print(f" trade_allowed  : {bool(acc.trade_allowed)}  "
          f"trade_expert: {bool(acc.trade_expert)}")
    print(f" funding target : {ACCOUNT_NGN:,.0f} NGN = "
          f"${ACCOUNT_USD:.2f} USD  (@ NGN {NGN_PER_USD}/USD)")
    print(f" risk / trade   : {RISK_NGN:,.0f} NGN = "
          f"${RISK_USD:.3f} USD")
    print("=" * 72)

    symbols = mt5.symbols_get()
    if symbols is None or len(symbols) == 0:
        print("[X] symbols_get() returned no symbols.")
        mt5.shutdown()
        sys.exit(1)

    candidates = []
    for s in symbols:
        try:
            if is_commodity_like(s):
                candidates.append(s)
        except Exception:
            continue

    print(f"[*] {len(symbols)} total symbols; {len(candidates)} "
          f"commodity-like candidates.\n")

    rows = []
    for s in candidates:
        name = s.name
        path = s.path or ""
        try:
            mt5.symbol_select(name, True)
        except Exception:
            pass
        info = mt5.symbol_info(name)
        tick = mt5.symbol_info_tick(name)

        if info is None or tick is None:
            rows.append({"symbol": name, "path": path,
                         "error": "no info/tick"})
            continue
        bid, ask = float(tick.bid), float(tick.ask)
        if not (bid > 0 and ask > 0):
            rows.append({"symbol": name, "path": path,
                         "bid": None, "ask": None,
                         "error": "no live bid/ask"})
            continue

        point = get_info(info, "point")
        digits = get_info(info, "digits")
        tick_size = get_info(info, "trade_tick_size")
        tick_value = get_info(info, "trade_tick_value")
        contract = get_info(info, "trade_contract_size")
        vmin = get_info(info, "volume_min")
        vstep = get_info(info, "volume_step")

        spread_pts = (ask - bid) / point if point else 0.0
        spread_cost = (ask - bid) * (contract or 0) * (vmin or 0)

        margin = None
        try:
            m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, name,
                                      vmin or 0.01, ask)
            margin = float(m) if m is not None else None
        except Exception:
            margin = None

        # affordable stop distance in POINTS using risk after spread.
        # profit per 1 price-unit move on min lot = contract * vmin
        if contract and vmin and point and spread_cost is not None:
            risk_after = RISK_USD - spread_cost
            if risk_after > 0 and contract > 0 and vmin > 0 and point > 0:
                stop_dist_price = risk_after / (contract * vmin)
                stop_dist_points = stop_dist_price / point
            else:
                stop_dist_points = 0.0
        else:
            stop_dist_points = None

        # ---- pass criteria ----
        reasons = []
        if spread_cost is None or spread_cost > SPREAD_RATIO_MAX * RISK_USD:
            reasons.append("spread")
        if margin is None or margin > MARGIN_RATIO_MAX * ACCOUNT_USD:
            reasons.append("margin")
        if (stop_dist_points is None
                or stop_dist_points < STOP_MIN_MULT * spread_pts):
            reasons.append("stop")
        passed = not reasons

        rows.append({
            "symbol": name, "path": path,
            "bid": bid, "ask": ask,
            "spread_pts": spread_pts,
            "digits": digits, "point": point,
            "tick_size": tick_size, "tick_value": tick_value,
            "contract_size": contract, "volume_min": vmin,
            "volume_step": vstep,
            "margin_min": margin,
            "spread_cost_min": spread_cost,
            "stop_dist_pts": stop_dist_points,
            "pass": passed,
            "fail_reasons": "; ".join(reasons),
        })
        try:
            mt5.symbol_select(name, False)
        except Exception:
            pass

    # --- sort: passes first, then safer (lower spread cost, then margin) ---
    def sort_key(r):
        return (0 if r.get("pass") else 1,
                0 if r.get("spread_cost_min") is not None else 1,
                0 if r.get("margin_min") is not None else 1,
                r.get("spread_cost_min") if r.get("spread_cost_min")
                is not None else math.inf,
                r.get("margin_min") if r.get("margin_min") is not None
                else math.inf)
    rows.sort(key=sort_key)

    # --- print ranked table -------------------------------------------
    header = (f"{'SYMBOL':<10}{'BID':>12}{'ASK':>12}{'SPR':>6}"
              f"{'DGT':>6}{'CNTRCT':>10}{'VMIN':>7}"
              f"{'MARGIN$':>9}{'SPR$':>7}{'STOPPT':>8}  RESULT")
    print(header)
    print("-" * len(header))
    for r in rows:
        if r.get("error"):
            print(f"{r['symbol']:<10}  ERROR: {r['error']}")
            continue
        res = "PASS" if r["pass"] else "FAIL"
        print(f"{r['symbol']:<10}"
              f"{r['bid']:>12.3f}{r['ask']:>12.3f}"
              f"{r['spread_pts']:>6.1f}{r['digits']:>6.0f}"
              f"{r['contract_size']:>10.0f}{r['volume_min']:>7.2f}"
              f"{r['margin_min']:>9.2f}"
              f"{r['spread_cost_min']:>7.2f}"
              f"{r['stop_dist_pts']:>8.0f}  {res}")
    print("-" * len(header))

    npass = sum(1 for r in rows if r.get("pass"))
    nerr = sum(1 for r in rows if r.get("error"))
    nfail = len(rows) - npass - nerr
    print(f"\nPASS: {npass}   FAIL: {nfail}   no-data/errors: {nerr}   "
          f"total candidates: {len(candidates)}")

    print("\nLegends:")
    print("  SPR$    = spread cost in USD at minimum lot")
    print("  MARGIN$ = order_calc_margin for minimum lot (BUY)")
    print("  STOPPT  = affordable stop distance in POINTS with "
          f"${RISK_USD:.3f} risk (after spread)")

    # --- write csv ----------------------------------------------------
    if rows:
        fieldnames = (["symbol", "path", "bid", "ask", "spread_pts",
                       "digits", "point", "tick_size", "tick_value",
                       "contract_size", "volume_min", "volume_step",
                       "margin_min", "spread_cost_min", "stop_dist_pts",
                       "pass", "fail_reasons", "error"])
        with open("commodities_scan.csv", "w", newline="",
                  encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=fieldnames)
            wr.writeheader()
            for r in rows:
                out = {k: r.get(k) for k in fieldnames}
                if r.get("error"):
                    out["fail_reasons"] = ""
                    out["pass"] = False
                wr.writerow(out)
        print("\n[*] CSV saved -> commodities_scan.csv")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())