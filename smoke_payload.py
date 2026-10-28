"""Smoke-test steps 1+2: verify live account state, then print the EXACT
order payload the bot's mt5_bridge.execute_trade() would send.

READ-ONLY. No order_send, no order_check. Exits:
  0 = payload printed (no order sent), 1 = not connected,
  2 = trading disabled / zero balance, 3 = no current MA-cross signal.

Usage:
    python smoke_payload.py
"""

import json
import sys
import threading

import pandas as pd

import MetaTrader5 as mt5

import mt5_bridge

INIT_TIMEOUT_S = 20
SYMBOL = "XAUUSD"
LOT_SIZE = 0.01


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
        print(f"[X] MT5 not connected: {reason}")
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        print(f"[X] account_info() -> None: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 1: trade_allowed + balance
    # ------------------------------------------------------------------
    print("=" * 62)
    print(" STEP 1 - ACCOUNT STATE")
    print("=" * 62)
    print(f" login         : {acc.login}")
    print(f" server        : {acc.server}")
    print(f" balance       : {acc.balance} {acc.currency}")
    print(f" equity        : {acc.equity} {acc.currency}")
    print(f" leverage      : 1:{acc.leverage}")
    print(f" trade_allowed : {bool(acc.trade_allowed)}")
    print(f" trade_expert  : {bool(acc.trade_expert)}")

    if not acc.trade_allowed:
        print("\n[STOP] trade_allowed is FALSE - not proceeding to payload.")
        mt5.shutdown()
        sys.exit(2)
    if acc.balance <= 0:
        print("\n[STOP] balance is <= 0 - not proceeding to payload.")
        mt5.shutdown()
        sys.exit(2)
    if not mt5.symbol_select(SYMBOL, True):
        print(f"[X] symbol_select({SYMBOL}) failed: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    if info is None or tick is None or tick.bid <= 0 or tick.ask <= 0:
        print(f"[X] symbol/tick info unavailable: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2a: current MA-cross direction from live M15 closes
    # (same indicator math + same trigger rule as the bot/backtest)
    # ------------------------------------------------------------------
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 50)
    if rates is None or len(rates) < 22:
        print(f"[X] insufficient M15 history: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    df = pd.DataFrame(rates)
    sma_fast = mt5_bridge.calculate_sma(df["close"], 9).to_numpy()
    sma_slow = mt5_bridge.calculate_sma(df["close"], 21).to_numpy()
    rsi = mt5_bridge.calculate_rsi(df["close"], 14).to_numpy()

    f2, s2 = sma_fast[-2], sma_slow[-2]
    f1, s1 = sma_fast[-1], sma_slow[-1]
    r1 = rsi[-1]

    cross_up = f2 <= s2 and f1 > s1 and r1 < 70
    cross_down = f2 >= s2 and f1 < s1 and r1 > 30
    if cross_up:
        direction = "BUY"
    elif cross_down:
        direction = "SELL"
    else:
        direction = "WAIT"

    point = info.point
    digits = info.digits

    print("\n" + "=" * 62)
    print(" STEP 2 - CURRENT MA-CROSS SIGNAL (M15 closes)")
    print("=" * 62)
    print(f" SMA9  prev={f2:.2f} last={f1:.2f}")
    print(f" SMA21 prev={s2:.2f} last={s1:.2f}")
    print(f" RSI14 last={r1:.2f}")
    print(f" signal : {direction}")

    if direction == "WAIT":
        print("\n[STOP] No fresh MA cross on the last completed M15 candle "
              "- no payload to fire by the strategy's own rule.")
        mt5.shutdown()
        sys.exit(3)

    # ------------------------------------------------------------------
    # Step 2b: exact payload execute_trade() builds (sl/tp = 0 triggers
    # the bot's own 300/600-point fallback logic exactly like the AI path)
    # ------------------------------------------------------------------
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    sl, tp = mt5_bridge._fallback_stops(order_type, price, point)
    price, sl, tp = round(price, digits), round(sl, digits), round(tp, digits)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": mt5_bridge.MAGIC_NUMBER,
        "comment": "AI Bot v2",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5_bridge.get_filling_mode(SYMBOL),
    }

    margin = mt5.order_calc_margin(order_type, SYMBOL, LOT_SIZE, price)
    margin_str = f"{margin:.2f}" if margin is not None else "calculate failed"

    print("\n" + "=" * 62)
    print(" STEP 2 - EXACT ORDER PAYLOAD THE BOT WOULD SEND")
    print("=" * 62)
    print(json.dumps(request, indent=2, default=str))
    print("-" * 62)
    print(f" SL distance : {mt5_bridge.FALLBACK_SL_POINTS} points "
          f"({mt5_bridge.FALLBACK_SL_POINTS * point:.2f} price units) -> "
          f"SL price {sl}")
    print(f" TP distance : {mt5_bridge.FALLBACK_TP_POINTS} points "
          f"({mt5_bridge.FALLBACK_TP_POINTS * point:.2f} price units) -> "
          f"TP price {tp}")
    print(f" Live margin required for 0.01 lot @ {price}: "
          f"${margin_str}")
    print(f" bid/ask     : {tick.bid} / {tick.ask}   spread "
          f"{(tick.ask - tick.bid) / point:.1f} points")
    print("=" * 62)
    print("\nNo order has been sent. Awaiting explicit approval.")

    mt5.shutdown()


if __name__ == "__main__":
    main()