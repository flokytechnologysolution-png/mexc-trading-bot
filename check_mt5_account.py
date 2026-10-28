import MetaTrader5 as mt5
import json
import sys

def main():
    result = {"read_only": True}

    if not mt5.initialize():
        result["init"] = False
        result["error"] = f"MT5 initialize failed: {mt5.last_error()}"
        print(json.dumps(result, indent=2, default=str))
        sys.exit(1)

    result["init"] = True
    account = mt5.account_info()

    if account is None:
        result["account"] = None
        result["error"] = f"account_info failed: {mt5.last_error()}"
    else:
        a = account._asdict()
        result["account"] = {
            "login": a.get("login"),
            "server": a.get("server"),
            "currency": a.get("currency"),
            "balance": a.get("balance"),
            "equity": a.get("equity"),
            "leverage": a.get("leverage"),
            "trade_allowed": bool(a.get("trade_allowed")),
            "trade_expert": bool(a.get("trade_expert"))
        }

    # Check Gold
    symbols = mt5.symbols_get()
    if symbols:
        for s in symbols:
            if s.name.upper() in ["XAUUSD", "GOLD"] and "BTC" not in s.name.upper():
                mt5.symbol_select(s.name, True)
                tick = mt5.symbol_info_tick(s.name)
                if tick:
                    result["gold"] = {
                        "symbol": s.name,
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "spread": round(tick.ask - tick.bid, 5)
                    }
                break

    mt5.shutdown()
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()