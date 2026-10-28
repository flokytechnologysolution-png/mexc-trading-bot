"""Read-only market/margin report for XAUUSD - NO orders, NO order_check,
NO order_send. Only symbol_info, symbol_info_tick and order_calc_margin.

Reports:
  1. account leverage
  2. XAUUSD contract size + live margin requirement for 0.01 lot
  3. current spread (bid/ask)

Usage:
    python report_xauusd.py
"""

import json
import sys
import threading

import MetaTrader5 as mt5

INIT_TIMEOUT_S = 20
SYMBOL = "XAUUSD"
LOT = 0.01


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
        print(json.dumps({"connected": False, "error": reason}, indent=2))
        sys.exit(1)

    out = {"connected": True}

    acc = mt5.account_info()
    if acc is None:
        out["error"] = f"account_info() -> None: {mt5.last_error()}"
        print(json.dumps(out, indent=2))
        mt5.shutdown()
        sys.exit(1)
    out["account"] = {
        "login": acc.login,
        "server": acc.server,
        "balance": acc.balance,
        "currency": acc.currency,
        "leverage": acc.leverage,
        "trade_allowed": bool(acc.trade_allowed),
    }

    if not mt5.symbol_select(SYMBOL, True):
        out["error"] = f"symbol_select({SYMBOL}) failed: {mt5.last_error()}"
        print(json.dumps(out, indent=2))
        mt5.shutdown()
        sys.exit(1)

    info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if info is None or tick is None:
        out["error"] = f"symbol_info/tick unavailable: {mt5.last_error()}"
        print(json.dumps(out, indent=2))
        mt5.shutdown()
        sys.exit(1)

    point = info.point
    digits = info.digits
    contract_size = info.trade_contract_size
    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value

    bid, ask = tick.bid, tick.ask
    spread_points = (ask - bid) / point
    spread_usd = (ask - bid) * contract_size * LOT   # per 0.01 lot

    # Live margin requirement for 0.01 lot via the broker's calculator
    margin_buy = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, LOT, ask)
    margin_sell = mt5.order_calc_margin(mt5.ORDER_TYPE_SELL, SYMBOL, LOT, bid)

    out["xauusd"] = {
        "bid": bid,
        "ask": ask,
        "spread_points": round(spread_points, 1),
        "spread_pips": round(spread_points / 10, 1),
        "spread_usd_per_001_lot": round(spread_usd, 2),
        "point": point,
        "digits": digits,
        "contract_size_units": contract_size,
        "tick_size": tick_size,
        "tick_value": tick_value,
        "volume_min": info.volume_min,
        "volume_step": info.volume_step,
        "margin_required_buy_001": margin_buy,
        "margin_required_sell_001": margin_sell,
        "approx_margin_by_leverage_buy": round(
            (ask * contract_size * LOT) / acc.leverage, 2),
    }

    print(json.dumps(out, indent=2))
    mt5.shutdown()


if __name__ == "__main__":
    main()