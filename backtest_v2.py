"""Backtest harness for the AI Trading Bot v2 MA-cross strategy.

== Data source (same contract as probe_mt5.py) ==
  * MT5 terminal reachable  -> backtest on REAL broker XAUUSD M15 history
  * MT5 offline / no data   -> backtest on clearly-labelled SYNTHETIC M15 data

== Strategy simulated ==
The live v2 bot asks the Gemini AI brain for each M15 decision, but the
historical AI calls cannot be replayed.  This backtest therefore simulates
the *deterministic core* the AI augments:
  - Signal : SMA(9) x SMA(21) crossover on M15 close
             BUY  on bullish cross  (RSI < 70)
             SELL on bearish cross  (RSI > 30)
  - Entry  : next candle open, one position at a time (v2 guard)
  - SL/TP  : fixed 300 / 600 points (same fallback as v1/v2)
  - Costs  : spread paid at entry (exec = open +/- spread)

Usage:
    python backtest_v2.py                          # 20000 bars, auto source
    python backtest_v2.py --source synthetic       # force synthetic data
    python backtest_v2.py --source mt5             # force real MT5 history
    python backtest_v2.py --bars 50000 --seed 7    # more bars / different seed
"""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

import MetaTrader5 as mt5

import mt5_bridge

# ----------------------------------------------------------------------
# Configuration defaults (match main_v2 / mt5_bridge)
# ----------------------------------------------------------------------
SYMBOL = "XAUUSD"
POINT = 0.01            # 2-digit gold quote point
CONTRACT_SIZE = 100     # oz per 1.0 lot
LOT_SIZE = 0.01
SL_POINTS = 300
TP_POINTS = 600
SPREAD_POINTS = 20      # pessimistic ~$0.20 round-trip cost on gold
START_BALANCE = 10_000.0
DEFAULT_BARS = 20_000
REPORT_FILE = "backtest_report.txt"
TRADES_FILE = "backtest_trades.csv"
EQUITY_FILE = "backtest_equity.csv"


# ----------------------------------------------------------------------
# MT5 connection helpers (never hang the bot when the terminal is offline)
# ----------------------------------------------------------------------

def mt5_terminal_running():
    """True when an MT5 terminal64.exe process is present.

    Calling mt5.initialize() with no terminal running blocks for a very
    long time, and a native call left hanging at interpreter exit hangs
    the whole process.  Checking `tasklist` for the terminal process first
    is cheap and deterministic on Windows.
    """
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             timeout=15).stdout or ""
        return "terminal64" in out.lower()
    except Exception as exc:   # tasklist unavailable -- assume no terminal
        print(f"[!] Could not check for MT5 terminal process: {exc}")
        return False


def start_mt5_if_possible():
    """Initialize MT5 only when a terminal is actually running.

    Returns True only if the live connection is usable.  Never blocks
    for long: with the terminal present, initialize() returns quickly.
    """
    if not mt5_terminal_running():
        print("[!] No MT5 terminal process running - will use fallback data")
        return False
    try:
        if not mt5.initialize():
            print(f"[!] MT5 initialize() failed: {mt5.last_error()}")
            return False
        return True
    except Exception as exc:
        print(f"[!] MT5 initialize() raised: {exc}")
        return False


def stop_mt5():
    """Best-effort clean shutdown of a live MT5 connection."""
    try:
        mt5.shutdown()
    except Exception:
        pass


def fetch_real_rates(symbol, bars):
    """Pull real M15 history from the broker. Returns DataFrame or None."""
    if not mt5.symbol_select(symbol, True):
        print(f"[X] Failed to select symbol {symbol}")
        return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, bars)
    if rates is None or len(rates) < 22:
        print(f"[X] Failed to fetch sufficient {symbol} history")
        return None
    frame = pd.DataFrame(rates)
    frame["dt"] = pd.to_datetime(frame["time"], unit="s")
    return frame


# ----------------------------------------------------------------------
# Synthetic data fallback (clearly labelled, reproducible)
# ----------------------------------------------------------------------

def generate_synthetic_m15(bars, seed):
    """Geometric-random-walk M15 data with alternating trend regimes.

    The regime switching keeps the SMA crossovers rare enough to resemble
    a real market while still generating enough trades to be a meaningful
    strategy test.  Synthetic data is always clearly labelled in the report.
    """
    rng = np.random.default_rng(seed)
    start_price = 4300.0
    vol = 0.0025                  # per-bar volatility ~= gold M15 scale
    closes = np.empty(bars)
    closes[0] = start_price
    regime_drift = rng.choice([-0.0005, 0.0005])
    regime_remaining = int(rng.integers(40, 200))

    for i in range(1, bars):
        if regime_remaining <= 0:
            regime_drift = rng.choice([-0.0005, 0.0005])
            regime_remaining = int(rng.integers(40, 200))
        regime_remaining -= 1
        closes[i] = closes[i - 1] * (1 + rng.normal(regime_drift, vol))

    opens = np.empty(bars)
    opens[0] = start_price
    opens[1:] = closes[:-1]       # next bar opens where the last one closed

    # Intrabar wiggle so highs/lows can reach SL/TP levels
    wiggle = rng.uniform(0.4, 1.2, bars) * SPREAD_POINTS * POINT
    highs = np.maximum(opens, closes) + wiggle
    lows = np.minimum(opens, closes) - wiggle

    times = pd.date_range("2025-01-01", periods=bars, freq="15min")
    # pandas 3.x: astype('int64') on a DatetimeIndex returns milliseconds,
    # so convert explicitly to seconds via datetime64[s] for the unix column.
    time_s = times.values.astype("datetime64[s]").astype("int64")

    frame = pd.DataFrame({
        "time": time_s,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "tick_volume": rng.integers(50, 400, bars),
    })
    frame["dt"] = times
    return frame
# ----------------------------------------------------------------------
# Simulation core
# ----------------------------------------------------------------------

@dataclass
class TradeRecord:
    entry_time: object
    side: str
    entry: float
    stop: float
    target: float
    exit_time: object
    exit_price: float
    exit_reason: str
    pnl: float
    balance_after: float
    bars_held: int = 0


def simulate(frame, point, contract_size, lot,
             sl_points, tp_points, spread_points, start_balance):
    """Run the deterministic strategy over a bar DataFrame.

    Never uses the current bar's data to decide the current bar's entry
    (signal fires on candle `i-1`, entry fills at candle `i` open).
    """
    n = len(frame)
    # Convert once to numpy so the per-bar loop never pays pandas overhead
    sma_fast = mt5_bridge.calculate_sma(frame["close"], 9).to_numpy()
    sma_slow = mt5_bridge.calculate_sma(frame["close"], 21).to_numpy()
    rsi = mt5_bridge.calculate_rsi(frame["close"], 14).to_numpy()
    opens = frame["open"].to_numpy()
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    dts = frame["dt"].to_numpy()

    balance = start_balance
    equity_curve = np.empty(n)
    trades = []
    position = None   # dict: side, entry, stop, target, entry_time, entry_idx

    for i in range(n):
        high = highs[i]
        low = lows[i]
        close = closes[i]

        # --- 1) manage an existing position against this bar
        if position is not None:
            side = position["side"]
            if side == "BUY":
                hit_stop = low <= position["stop"]
                hit_target = high >= position["target"]
            else:
                hit_stop = high >= position["stop"]
                hit_target = low <= position["target"]

            if hit_stop and hit_target:
                exit_price, reason = position["stop"], "SL"   # conservative
            elif hit_stop:
                exit_price, reason = position["stop"], "SL"
            elif hit_target:
                exit_price, reason = position["target"], "TP"
            else:
                exit_price = None

            if exit_price is not None:
                direction = 1 if side == "BUY" else -1
                pnl = direction * (exit_price - position["entry"]) \
                    * contract_size * lot
                balance += pnl
                trades.append(TradeRecord(
                    entry_time=position["entry_time"],
                    side=side,
                    entry=position["entry"],
                    stop=position["stop"],
                    target=position["target"],
                    exit_time=dts[i],
                    exit_price=exit_price,
                    exit_reason=reason,
                    pnl=pnl,
                    balance_after=balance,
                    bars_held=i - position["entry_idx"],
                ))
                position = None

        # --- 2) open a position on the signal from the previous bar
        if position is None and i >= 2:
            f2 = sma_fast[i - 2]
            s2 = sma_slow[i - 2]
            f1 = sma_fast[i - 1]
            s1 = sma_slow[i - 1]
            r1 = rsi[i - 1]

            if not (np.isnan(f1) or np.isnan(s1) or np.isnan(r1)):
                cross_up = f2 <= s2 and f1 > s1 and r1 < 70
                cross_down = f2 >= s2 and f1 < s1 and r1 > 30

                if cross_up or cross_down:
                    side = "BUY" if cross_up else "SELL"
                    spread = spread_points * point
                    exec_price = opens[i] + (spread if cross_up else -spread)
                    if side == "BUY":
                        stop = exec_price - sl_points * point
                        target = exec_price + tp_points * point
                    else:
                        stop = exec_price + sl_points * point
                        target = exec_price - tp_points * point
                    position = {
                        "side": side,
                        "entry": exec_price,
                        "stop": stop,
                        "target": target,
                        "entry_time": dts[i],
                        "entry_idx": i,
                    }

        # --- 3) mark-to-market to build the equity curve
        if position is not None:
            direction = 1 if position["side"] == "BUY" else -1
            equity_curve[i] = balance + direction * (close - position["entry"]) \
                * contract_size * lot
        else:
            equity_curve[i] = balance

    # Close any leftover position at the final close
    if position is not None:
        direction = 1 if position["side"] == "BUY" else -1
        close = closes[-1]
        pnl = direction * (close - position["entry"]) * contract_size * lot
        balance += pnl
        trades.append(TradeRecord(
            entry_time=position["entry_time"],
            side=position["side"],
            entry=position["entry"],
            stop=position["stop"],
            target=position["target"],
            exit_time=dts[-1],
            exit_price=close,
            exit_reason="MARKET (end of data)",
            pnl=pnl,
            balance_after=balance,
            bars_held=n - 1 - position["entry_idx"],
        ))
        equity_curve[-1] = balance

    return trades, equity_curve, balance


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------

def compute_stats(trades, equity_curve, start_balance):
    stats = {
        "start_balance": start_balance,
        "end_balance": float(equity_curve[-1]),
        "total_pnl": float(equity_curve[-1] - start_balance),
        "return_pct": float((equity_curve[-1] / start_balance - 1) * 100),
        "trade_count": len(trades),
        "wins": sum(1 for t in trades if t.pnl > 0),
        "losses": sum(1 for t in trades if t.pnl <= 0),
        "win_rate_pct": (sum(1 for t in trades if t.pnl > 0) / len(trades) * 100)
                        if trades else 0.0,
        "gross_profit": sum(t.pnl for t in trades if t.pnl > 0),
        "gross_loss": -sum(t.pnl for t in trades if t.pnl < 0),
        "profit_factor": 0.0,
        "avg_trade": float(np.mean([t.pnl for t in trades])) if trades else 0.0,
        "avg_win": float(np.mean([t.pnl for t in trades if t.pnl > 0])) or 0.0,
        "avg_loss": float(np.mean([t.pnl for t in trades if t.pnl < 0])) or 0.0,
        "best_trade": float(max((t.pnl for t in trades), default=0.0)),
        "worst_trade": float(min((t.pnl for t in trades), default=0.0)),
    }
    if stats["gross_loss"] > 0:
        stats["profit_factor"] = float(stats["gross_profit"] / stats["gross_loss"])

    peak = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - peak
    dd_idx = int(np.argmin(drawdown))
    stats["max_drawdown"] = float(drawdown.min())
    stats["max_drawdown_pct"] = float(
        drawdown.min() / peak[dd_idx] * 100) if peak[dd_idx] else 0.0
    return stats


def write_report(lines, trades, equity_curve, source_label, params):
    report = "\n".join(lines)
    print(report)

    with open(REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")

    pd.DataFrame(trades).to_csv(TRADES_FILE, index=False)
    pd.DataFrame({
        "bar": np.arange(len(equity_curve)),
        "equity": equity_curve,
    }).to_csv(EQUITY_FILE, index=False)

    with open("backtest_params.json", "w", encoding="utf-8") as fh:
        json.dump({
            "source": source_label,
            "symbol": SYMBOL,
            "bars": params["bars"],
            "seed": params["seed"],
            "point": POINT,
            "contract_size": CONTRACT_SIZE,
            "lot": LOT_SIZE,
            "sl_points": SL_POINTS,
            "tp_points": TP_POINTS,
            "spread_points": SPREAD_POINTS,
            "start_balance": START_BALANCE,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, fh, indent=2)
    print(f"\n[*] Report saved   -> {REPORT_FILE}")
    print(f"[*] Trades saved   -> {TRADES_FILE}")
    print(f"[*] Equity saved   -> {EQUITY_FILE}")
    print(f"[*] Params saved   -> backtest_params.json")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["auto", "mt5", "synthetic"],
                        default="auto", help="backtest data source")
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS,
                        help="number of M15 bars to test")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for synthetic data")
    args = parser.parse_args()

    if args.bars < 500:
        print(f"[X] Need at least 500 bars, got {args.bars}")
        sys.exit(1)

    print("=" * 60)
    print(f" BACKTEST - {SYMBOL} M15 | SL={SL_POINTS} TP={TP_POINTS} "
          f"Lot={LOT_SIZE}")
    print(f" Bars={args.bars} | Source={args.source} | Seed={args.seed}")
    print("=" * 60)

    # --- pick the data source ---------------------------------------
    frame = None
    source_label = None
    if args.source in ("auto", "mt5"):
        if start_mt5_if_possible():
            frame = fetch_real_rates(SYMBOL, args.bars)
            stop_mt5()
            if frame is not None:
                source_label = "REAL broker XAUUSD M15 (MT5)"
            elif args.source == "mt5":
                print("[X] --source mt5 requested but no real history "
                      "is available")
                sys.exit(1)
        elif args.source == "mt5":
            print("[X] --source mt5 requested but the MT5 terminal is "
                  "not running")
            sys.exit(1)
    if frame is None and args.source != "mt5":
        print("[*] Using SYNTHETIC M15 data (clearly marked as NOT real)")
        frame = generate_synthetic_m15(args.bars, args.seed)
        source_label = "SYNTHETIC M15 data (label: NOT a real market)"

    print(f"[*] Data source: {source_label}")

    trades, equity_curve, _ = simulate(
        frame, POINT, CONTRACT_SIZE, LOT_SIZE,
        SL_POINTS, TP_POINTS, SPREAD_POINTS, START_BALANCE,
    )
    stats = compute_stats(trades, equity_curve, START_BALANCE)

    span = (f"{frame['dt'].iloc[0]:%Y-%m-%d %H:%M} -> "
            f"{frame['dt'].iloc[-1]:%Y-%m-%d %H:%M}")
    lines = [
        "=" * 60,
        f" BACKTEST REPORT - generated {datetime.now():%Y-%m-%d %H:%M:%S}",
        "=" * 60,
        f" Data source  : {source_label}",
        f" Symbol       : {SYMBOL} M15",
        f" Bars tested  : {len(frame)}  ({span})",
        f" Params       : SL={SL_POINTS}pt TP={TP_POINTS}pt lot={LOT_SIZE} "
        f"spread={SPREAD_POINTS}pt",
        "-" * 60,
        f" Start balance      : {START_BALANCE:,.2f}",
        f" End balance        : {stats['end_balance']:,.2f}",
        f" Total P/L          : {stats['total_pnl']:+,.2f}  "
        f"({stats['return_pct']:+.2f}%)",
        f" Trades             : {stats['trade_count']}",
        f" Wins / Losses      : {stats['wins']} / {stats['losses']} "
        f"(win rate {stats['win_rate_pct']:.1f}%)",
        f" Gross profit/loss  : {stats['gross_profit']:,.2f} / "
        f"{stats['gross_loss']:,.2f}",
        f" Profit factor      : {stats['profit_factor']:.2f}",
        f" Avg trade          : {stats['avg_trade']:+,.2f}",
        f" Avg win / loss     : {stats['avg_win']:+,.2f} / "
        f"{stats['avg_loss']:+,.2f}",
        f" Best / worst trade : {stats['best_trade']:+,.2f} / "
        f"{stats['worst_trade']:+,.2f}",
        f" Max drawdown       : {stats['max_drawdown']:,.2f} "
        f"({stats['max_drawdown_pct']:.2f}%)",
        "=" * 60,
    ]

    write_report(lines, [asdict(t) for t in trades],
                 equity_curve, source_label,
                 {"bars": args.bars, "seed": args.seed})


if __name__ == "__main__":
    main()