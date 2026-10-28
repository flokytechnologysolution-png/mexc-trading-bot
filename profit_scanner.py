import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime

# ==============================
# USER SETTINGS
# ==============================
NGN_PER_USD = 1600

ACCOUNT_NGN = 10000
RISK_NGN = 500

account_usd = ACCOUNT_NGN / NGN_PER_USD
risk_usd = RISK_NGN / NGN_PER_USD

TIMEFRAME = mt5.TIMEFRAME_M15
BARS = 300
ATR_PERIOD = 14

# Strategy multipliers
SL_ATR_MULT = 1.0
TP_ATR_MULT = 2.0

# Safety filters
MAX_SPREAD_PCT_OF_RISK = 0.20
MAX_MARGIN_PCT_OF_ACCOUNT = 0.35
MIN_NET_RR = 1.5
MIN_SCORE = 70

COMMODITY_KEYWORDS = [
    "XAU", "XAG", "XPT", "XPD",
    "GOLD", "SILVER", "PLATINUM", "PALLADIUM",
    "OIL", "WTI", "BRENT", "UKOIL", "USOIL",
    "COPPER", "COCOA", "COFFEE", "COTTON", "SUGAR",
    "NATGAS", "GAS"
]

EXCLUDE_PATH_KEYWORDS = [
    "CRYPTO",
    "TOKEN",
    "COIN",
    "BLOCKCHAIN",
    "DIGITAL",
    # Non-commodity market groups - these are equities, indexes, forex,
    # not the physical commodity CFDs the bot trades.
    "STOCKS",
    "INDEXES",
    "INDEX",
    "FOREX",
    "FX"
]

EXCLUDE_SYMBOL_KEYWORDS = [
    "BTC",
    "ETH",
    "USDT",
    "USDC",
    "XAUT_",
    "CRYPTO"
]


def is_commodity_symbol(symbol_info):
    name = str(symbol_info.name).upper()
    path = str(symbol_info.path).upper()
    description = str(symbol_info.description).upper()

    # A symbol is only a genuine commodity if its path sits under a
    # commodity category (Metals / Energies / agriculture / softs).
    if not any(gp in path for gp in ("METALS", "ENERGIES", "ENERGY",
                                     "COMMODIT", "AGRICULT", "SOFT")):
        return False

    # Exclude crypto tokens / digital assets explicitly even if they end
    # up under a commodity-looking path.
    if any(k in path for k in EXCLUDE_PATH_KEYWORDS):
        return False
    if any(k in name for k in EXCLUDE_SYMBOL_KEYWORDS):
        return False

    text = " ".join([name, description, path])

    return any(k in text for k in COMMODITY_KEYWORDS)


def safe_float(x):
    try:
        x = float(x)
        if np.isnan(x) or np.isinf(x):
            return None
        return x
    except Exception:
        return None


def calculate_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    return atr.iloc[-1]


def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean().iloc[-1]


def analyze_symbol(symbol):
    mt5.symbol_select(symbol, True)

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)

    if info is None or tick is None:
        return None

    bid = safe_float(tick.bid)
    ask = safe_float(tick.ask)

    if not bid or not ask or bid <= 0 or ask <= 0:
        return None

    point = safe_float(info.point)
    digits = info.digits
    tick_size = safe_float(info.trade_tick_size)
    tick_value = safe_float(info.trade_tick_value)
    volume_min = safe_float(info.volume_min)
    contract_size = safe_float(info.trade_contract_size)

    if not point or not tick_size or not tick_value or not volume_min:
        return None

    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, BARS)

    if rates is None or len(rates) < ATR_PERIOD + 50:
        return None

    df = pd.DataFrame(rates)

    close = df["close"]
    last_close = float(close.iloc[-1])

    atr = calculate_atr(df, ATR_PERIOD)

    ema_fast = calculate_ema(close, 50)
    ema_slow = calculate_ema(close, 200)

    if ema_fast > ema_slow and last_close > ema_fast:
        trend = "BUY"
    elif ema_fast < ema_slow and last_close < ema_fast:
        trend = "SELL"
    else:
        trend = "NEUTRAL"

    spread_price = ask - bid
    spread_points = spread_price / point

    tick_value_min_lot = tick_value * volume_min

    # Spread cost for minimum lot
    spread_cost_usd = (spread_price / tick_size) * tick_value_min_lot
    spread_cost_ngn = spread_cost_usd * NGN_PER_USD

    # Margin calculation
    margin_buy = None
    margin_sell = None

    try:
        margin_buy = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY,
            symbol,
            volume_min,
            ask
        )
    except Exception:
        margin_buy = None

    try:
        margin_sell = mt5.order_calc_margin(
            mt5.ORDER_TYPE_SELL,
            symbol,
            volume_min,
            bid
        )
    except Exception:
        margin_sell = None

    if margin_buy is not None and margin_sell is not None:
        margin_required = max(margin_buy, margin_sell)
    elif margin_buy is not None:
        margin_required = margin_buy
    elif margin_sell is not None:
        margin_required = margin_sell
    else:
        margin_required = None

    # ATR-based SL/TP price distance
    sl_distance = atr * SL_ATR_MULT
    tp_distance = atr * TP_ATR_MULT

    # Approximate net profit/loss after spread
    if trend == "BUY":
        entry = ask
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance

        # For buy, spread is included because exit is at bid
        profit_distance = tp_price - entry - spread_price
        loss_distance = entry - sl_price + spread_price

    elif trend == "SELL":
        entry = bid
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance

        # For sell, entry is bid, exit buy adds spread cost
        profit_distance = entry - tp_price - spread_price
        loss_distance = sl_price - entry + spread_price

    else:
        entry = last_close
        sl_price = None
        tp_price = None
        profit_distance = 0
        loss_distance = 0

    net_profit_usd = (profit_distance / tick_size) * tick_value_min_lot
    net_loss_usd = (loss_distance / tick_size) * tick_value_min_lot

    net_profit_ngn = net_profit_usd * NGN_PER_USD
    net_loss_ngn = net_loss_usd * NGN_PER_USD

    if net_loss_usd <= 0:
        net_rr = 0
    else:
        net_rr = net_profit_usd / net_loss_usd

    # Safety checks
    pass_spread = spread_cost_usd <= (risk_usd * MAX_SPREAD_PCT_OF_RISK)
    pass_margin = margin_required is not None and margin_required <= (account_usd * MAX_MARGIN_PCT_OF_ACCOUNT)
    pass_rr = net_rr >= MIN_NET_RR
    pass_profit = net_profit_ngn >= (RISK_NGN * 1.5)
    pass_trend = trend in ["BUY", "SELL"]

    passed = pass_spread and pass_margin and pass_rr and pass_profit and pass_trend

    # Score
    score = 0

    if pass_spread:
        score += 25 * (1 - (spread_cost_usd / (risk_usd * MAX_SPREAD_PCT_OF_RISK)))

    if pass_margin and margin_required is not None:
        score += 20 * (1 - (margin_required / (account_usd * MAX_MARGIN_PCT_OF_ACCOUNT)))

    if pass_rr:
        score += min(30, net_rr * 10)

    if pass_profit:
        score += min(25, (net_profit_ngn / RISK_NGN) * 10)

    if pass_trend:
        score += 10

    score = round(score, 2)

    return {
        "symbol": symbol,
        "description": info.description,
        "bid": bid,
        "ask": ask,
        "spread_points": round(spread_points, 1),
        "spread_cost_ngn": round(spread_cost_ngn, 2),
        "volume_min": volume_min,
        "contract_size": contract_size,
        "margin_required_usd": round(margin_required, 4) if margin_required is not None else None,
        "atr": round(atr, 5),
        "trend": trend,
        "sl_price": round(sl_price, digits) if sl_price is not None else None,
        "tp_price": round(tp_price, digits) if tp_price is not None else None,
        "expected_net_profit_ngn": round(net_profit_ngn, 2),
        "expected_net_loss_ngn": round(net_loss_ngn, 2),
        "net_risk_reward": round(net_rr, 2),
        "pass_spread": pass_spread,
        "pass_margin": pass_margin,
        "pass_rr": pass_rr,
        "pass_profit": pass_profit,
        "pass_trend": pass_trend,
        "passed": passed,
        "score": score
    }


def main():
    print("=" * 100)
    print("PRE-TRADE PROFIT SCANNER")
    print("READ-ONLY — NO ORDERS")
    print("=" * 100)

    if not mt5.initialize():
        print("MT5 initialize failed:", mt5.last_error())
        return

    account = mt5.account_info()

    if account:
        print("\nACCOUNT")
        print(f"login         : {account.login}")
        print(f"server        : {account.server}")
        print(f"balance       : {account.balance}")
        print(f"equity        : {account.equity}")
        print(f"trade_allowed : {account.trade_allowed}")
        print(f"trade_expert  : {account.trade_expert}")
    else:
        print("Could not read account info")

    print("\nBUDGET")
    print(f"ACCOUNT_NGN   : ₦{ACCOUNT_NGN}")
    print(f"RISK_NGN      : ₦{RISK_NGN}")
    print(f"account_usd   : ${account_usd:.4f}")
    print(f"risk_usd      : ${risk_usd:.4f}")

    symbols = mt5.symbols_get()

    if symbols is None:
        print("symbols_get failed:", mt5.last_error())
        return

    results = []

    for symbol_info in symbols:
        if not is_commodity_symbol(symbol_info):
            continue

        result = analyze_symbol(symbol_info.name)

        if result is not None:
            results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)

    print("\nSCAN RESULTS")
    print("=" * 160)
    print(
        f"{'PASS':<6} {'SCORE':<7} {'SYMBOL':<15} {'TREND':<7} "
        f"{'SPREAD₦':<10} {'MARGIN$':<10} {'NET PROFIT₦':<14} "
        f"{'NET LOSS₦':<12} {'RR':<6} {'SL':<12} {'TP':<12}"
    )
    print("-" * 160)

    for r in results:
        print(
            f"{str(r['passed']):<6} "
            f"{r['score']:<7} "
            f"{r['symbol']:<15} "
            f"{r['trend']:<7} "
            f"{r['spread_cost_ngn']:<10} "
            f"{str(r['margin_required_usd']):<10} "
            f"{r['expected_net_profit_ngn']:<14} "
            f"{r['expected_net_loss_ngn']:<12} "
            f"{r['net_risk_reward']:<6} "
            f"{str(r['sl_price']):<12} "
            f"{str(r['tp_price']):<12}"
        )

    print("=" * 160)

    valid = [r for r in results if r["passed"] and r["score"] >= MIN_SCORE]

    print("\nFINAL DECISION")

    if not valid:
        decision = {
            "trade_allowed": False,
            "best_symbol": None,
            "direction": None,
            "score": 0,
            "expected_net_profit_ngn": 0,
            "expected_max_loss_ngn": RISK_NGN,
            "net_risk_reward": 0,
            "spread_cost_ngn": 0,
            "margin_required_usd": 0,
            "reason": "No commodity currently meets the profit-margin safety rules"
        }
    else:
        best = valid[0]

        decision = {
            "trade_allowed": True,
            "best_symbol": best["symbol"],
            "direction": best["trend"],
            "score": best["score"],
            "expected_net_profit_ngn": best["expected_net_profit_ngn"],
            "expected_max_loss_ngn": RISK_NGN,
            "net_risk_reward": best["net_risk_reward"],
            "spread_cost_ngn": best["spread_cost_ngn"],
            "margin_required_usd": best["margin_required_usd"],
            "sl_price": best["sl_price"],
            "tp_price": best["tp_price"],
            "reason": "Low spread, enough volatility, positive trend, acceptable margin"
        }

    print(decision)

    mt5.shutdown()


if __name__ == "__main__":
    main()