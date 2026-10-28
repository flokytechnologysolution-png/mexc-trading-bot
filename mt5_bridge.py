import MetaTrader5 as mt5
import pandas as pd

# Bot identity tag attached to every order this bot places
MAGIC_NUMBER = 234000

# Fixed fallback SL/TP distances in points (same as v1: 300 SL / 600 TP)
FALLBACK_SL_POINTS = 300
FALLBACK_TP_POINTS = 600


# ------------------------------------------------------------------
# Connection management
# ------------------------------------------------------------------

def connect_mt5():
    print("[*] Initializing MetaTrader 5 connection...")
    if not mt5.initialize():
        print(f"ERROR: initialize() failed, error code = {mt5.last_error()}")
        return False
    print("[+] Initialization successful!")
    return True


def shutdown_mt5():
    mt5.shutdown()
    print("[*] MT5 connection closed.")


# ------------------------------------------------------------------
# Indicator calculations (same math as legacy/strategy_v1.py)
# ------------------------------------------------------------------

def calculate_sma(series, period):
    return series.rolling(window=period).mean()


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


# ------------------------------------------------------------------
# Market data
# ------------------------------------------------------------------

def get_market_data(symbol="XAUUSD"):
    """Fetch live tick + M15 indicator snapshot for the AI brain.

    Returns a dict with exactly the fields ai_brain.get_ai_decision()
    expects (symbol, price, sma_9, sma_21, rsi), or None on failure."""
    if not mt5.symbol_select(symbol, True):
        print(f"[X] Failed to select symbol {symbol}")
        return None

    tick = mt5.symbol_info_tick(symbol)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 50)

    if tick is None or tick.bid <= 0 or tick.ask <= 0:
        print(f"[X] Failed to get valid tick data for {symbol}")
        return None
    if rates is None or len(rates) < 22:
        print(f"[X] Failed to fetch sufficient historical rates for {symbol}")
        return None

    df = pd.DataFrame(rates)
    closes = df['close']

    sma_9 = calculate_sma(closes, 9).iloc[-1]
    sma_21 = calculate_sma(closes, 21).iloc[-1]
    rsi = calculate_rsi(closes, 14).iloc[-1]

    if pd.isna(sma_9) or pd.isna(sma_21) or pd.isna(rsi):
        print("[X] Indicator calculation produced NaN values")
        return None

    return {
        "symbol": symbol,
        "price": round(float(closes.iloc[-1]), 2),
        "bid": tick.bid,
        "ask": tick.ask,
        "sma_9": round(float(sma_9), 2),
        "sma_21": round(float(sma_21), 2),
        "rsi": round(float(rsi), 2),
    }


# ------------------------------------------------------------------
# Order execution
# ------------------------------------------------------------------

def get_filling_mode(symbol):
    """Pick an order filling mode supported by the symbol.

    Diagnostics from Aug 15 confirmed FOK works on this Headway account."""
    info = mt5.symbol_info(symbol)
    filling = info.filling_mode if info is not None else 0

    if filling & 1:   # SYMBOL_FILLING_FOK (Fill or Kill)
        return mt5.ORDER_FILLING_FOK
    if filling & 2:   # SYMBOL_FILLING_IOC (Immediate or Cancel)
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def _fallback_stops(order_type, price, point):
    """Fixed SL/TP levels used when the AI returns none or invalid ones."""
    if order_type == mt5.ORDER_TYPE_BUY:
        return price - FALLBACK_SL_POINTS * point, price + FALLBACK_TP_POINTS * point
    return price + FALLBACK_SL_POINTS * point, price - FALLBACK_TP_POINTS * point


def execute_trade(symbol, lot, order_type, sl=0.0, tp=0.0,
                  deviation=20, comment="AI Bot v2"):
    """Send a market order with stop-loss / take-profit.

    AI-provided SL/TP are validated against the order side; missing or
    invalid levels fall back to fixed 300/600 point distances (v1 logic).
    Returns the order_send result object, or None on failure."""
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        print(f"[X] Cannot execute trade: missing symbol/tick info for {symbol}")
        return None

    point = info.point
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    # Validate AI-provided stops; fall back to fixed distances if invalid
    if order_type == mt5.ORDER_TYPE_BUY:
        stops_valid = 0 < sl < price < tp
    else:
        stops_valid = 0 < tp < price < sl
    if not stops_valid:
        if sl or tp:
            print(f"[!] AI SL/TP invalid for this order side (SL={sl}, TP={tp})")
        else:
            print("[!] AI returned no stop levels")
        print(f"    -> using fixed fallbacks: {FALLBACK_SL_POINTS}/"
              f"{FALLBACK_TP_POINTS} points")
        sl, tp = _fallback_stops(order_type, price, point)

    # Round to the symbol's supported precision
    digits = info.digits
    price, sl, tp = round(price, digits), round(sl, digits), round(tp, digits)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": MAGIC_NUMBER,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_mode(symbol),
    }

    # Step 1: pre-flight validation (lesson from the Aug 15 debugging)
    check = mt5.order_check(request)
    if check is None:
        print(f"[X] Order check returned None! Error: {mt5.last_error()}")
        return None
    if check.retcode != 0:
        print(f"[X] Order check failed! Retcode: {check.retcode} - {check.comment}")
        return None

    # Step 2: send the real order
    result = mt5.order_send(request)
    if result is None:
        print(f"[X] order_send() returned None! Error: {mt5.last_error()}")
        return None
    if result.retcode in (mt5.TRADE_RETCODE_DONE, 0) or result.order > 0:
        print(f"[+] Trade executed: ticket {result.order} @ {price}")
        print(f"    Volume={lot} SL={sl} TP={tp} Retcode={result.retcode}")
        return result

    print(f"[X] Order failed, retcode={result.retcode} - {result.comment}")
    print(f"    Error: {mt5.last_error()}")
    return None