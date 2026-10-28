"""AI Trading Bot v2 - MT5 bridge + Gemini AI decision engine.

Pipeline per cycle:
    1. Pull live market data + M15 indicators  (mt5_bridge)
    2. Ask the AI brain for a trade decision   (ai_brain)
    3. Validate confidence + open-position guard
    4. Execute the trade with SL/TP            (mt5_bridge)

Usage:
    python main_v2.py            # DRY RUN - decisions logged, no orders sent
    python main_v2.py --live     # LIVE trading - real orders are sent!
    python main_v2.py --once     # run a single cycle then exit
"""

import json
import sys
import time
from datetime import datetime

import MetaTrader5 as mt5

import mt5_bridge
from ai_brain import get_ai_decision

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
SYMBOL = "XAUUSD"
LOT_SIZE = 0.01                # minimum volume for this account
MIN_CONFIDENCE = 60            # skip AI decisions below this confidence
POLL_INTERVAL_SECONDS = 900    # one cycle per M15 candle
LOG_FILE = "bot_activity.log"

DRY_RUN = True                 # flipped to False by the --live flag


def log(message):
    """Print a timestamped message and append it to the activity log."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


def to_float(value):
    """Safely convert AI-returned numbers to float (0.0 on failure)."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def has_open_position(symbol):
    """True if this bot already holds an open position on the symbol."""
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return False
    return any(p.magic == mt5_bridge.MAGIC_NUMBER for p in positions)


def run_cycle():
    """One full analyze -> decide -> (maybe) trade cycle."""
    market_data = mt5_bridge.get_market_data(SYMBOL)
    if market_data is None:
        log("[!] No market data this cycle - skipping")
        return

    log(f"[*] Market: price={market_data['price']} bid={market_data['bid']} "
        f"ask={market_data['ask']} SMA9={market_data['sma_9']} "
        f"SMA21={market_data['sma_21']} RSI={market_data['rsi']}")

    decision = get_ai_decision(market_data)
    log(f"[*] AI decision: {json.dumps(decision)}")

    action = str(decision.get("decision", "")).strip().upper()
    if action not in ("BUY", "SELL"):
        log("[*] AI says WAIT - no trade this cycle")
        return

    confidence = to_float(decision.get("confidence"))
    if confidence < MIN_CONFIDENCE:
        log(f"[*] Confidence {confidence:g} below threshold "
            f"{MIN_CONFIDENCE} - skipping trade")
        return

    if has_open_position(SYMBOL):
        log("[*] Bot already holds an open position - no new entry")
        return

    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    sl = to_float(decision.get("stop_loss"))
    tp = to_float(decision.get("take_profit"))

    if DRY_RUN:
        log(f"[DRY RUN] Would {action} {LOT_SIZE} {SYMBOL} | SL={sl} TP={tp} "
            f"| Reason: {decision.get('reason', '')}")
        return

    result = mt5_bridge.execute_trade(
        SYMBOL, LOT_SIZE, order_type, sl=sl, tp=tp, comment="AI Bot v2"
    )
    if result is not None:
        log(f"[+] Entry target {decision.get('entry')} "
            f"| {decision.get('reason', '')}")
    else:
        log("[X] Trade execution failed - see messages above")


def main():
    global DRY_RUN

    if "--live" in sys.argv:
        DRY_RUN = False

    if not mt5_bridge.connect_mt5():
        sys.exit(1)

    mode = "DRY RUN (add --live to send real orders)" if DRY_RUN else "LIVE TRADING"
    log("=" * 60)
    log(f" AI TRADING BOT v2 STARTED - {mode}")
    log(f" Symbol={SYMBOL} | Lot={LOT_SIZE} | MinConfidence={MIN_CONFIDENCE} "
        f"| Interval={POLL_INTERVAL_SECONDS}s")
    log("=" * 60)

    try:
        if "--once" in sys.argv:
            run_cycle()
        else:
            while True:
                run_cycle()
                time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log("[*] Stopped by user")
    finally:
        mt5_bridge.shutdown_mt5()


if __name__ == "__main__":
    main()