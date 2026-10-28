"""One-off probe: is the MT5 terminal reachable, and how much history can we pull?

Used to decide the backtest data source:
  - MT5 reachable  -> backtest on REAL broker XAUUSD history
  - MT5 offline    -> fall back to clearly-labelled synthetic data
"""
import json
import subprocess
import sys

import MetaTrader5 as mt5


def mt5_terminal_running():
    """True when an MT5 terminal64.exe process is present.

    mt5.initialize() blocks for a very long time when no terminal is
    running, so we check the process list first and exit cleanly otherwise.
    """
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             timeout=15).stdout or ""
        return "terminal64" in out.lower()
    except Exception:
        return False


def main():
    out = {"init": False}

    if not mt5_terminal_running():
        out["error"] = "No MT5 terminal64.exe process found - terminal is offline"
        print(json.dumps(out, indent=2))
        sys.exit(1)

    if not mt5.initialize():
        out["error"] = str(mt5.last_error())
        print(json.dumps(out, indent=2))
        sys.exit(1)

    out["init"] = True
    acc = mt5.account_info()
    sym = mt5.symbol_info("XAUUSD")
    mt5.symbol_select("XAUUSD", True)

    out["account"] = {
        "login": getattr(acc, "login", None),
        "server": getattr(acc, "server", None),
        "balance": getattr(acc, "balance", None),
        "currency": getattr(acc, "currency", None),
        "leverage": getattr(acc, "leverage", None),
    }
    out["xauusd"] = {
        "point": getattr(sym, "point", None),
        "digits": getattr(sym, "digits", None),
        "volume_min": getattr(sym, "volume_min", None),
        "volume_step": getattr(sym, "volume_step", None),
        "contract_size": getattr(sym, "trade_contract_size", None),
        "tick_value": getattr(sym, "trade_tick_value", None),
        "tick_size": getattr(sym, "trade_tick_size", None),
        "filling_mode": getattr(sym, "filling_mode", None),
    }

    # How deep does M15 history go?
    for tf_name, tf in (("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4)):
        for bars in (5000, 20000, 50000):
            rates = mt5.copy_rates_from_pos("XAUUSD", tf, 0, bars)
            if rates is not None and len(rates) > 0:
                import datetime as dt
                first = dt.datetime.fromtimestamp(int(rates[0]["time"]))
                last = dt.datetime.fromtimestamp(int(rates[-1]["time"]))
                out[f"history_{tf}"] = {"bars": len(rates), "first": str(first), "last": str(last)}
                break
        else:
            out[f"history_{tf}"] = None

    mt5.shutdown()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
