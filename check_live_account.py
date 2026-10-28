"""Read-only MT5 connection check: confirms the account the bot is on.

Step 1 of the live smoke test - prints account number, server name, balance
and equity from the MT5 API WITHOUT placing any order or fetching history.
Exits 1 if the terminal/API is unreachable.

Usage:
    python check_live_account.py
"""

import json
import sys
import threading

import MetaTrader5 as mt5

INIT_TIMEOUT_S = 20


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
        if "err" in state:
            reason = state["err"]
        elif state["ok"] is False:
            reason = str(mt5.last_error())
        else:
            reason = f"initialize() did not return within {INIT_TIMEOUT_S}s"
        print(json.dumps({"connected": False, "error": reason}, indent=2))
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        print(json.dumps(
            {"connected": True, "error": "account_info() returned None: "
             + str(mt5.last_error())}, indent=2))
        mt5.shutdown()
        sys.exit(1)

    print(json.dumps({
        "connected": True,
        "login": acc.login,
        "server": acc.server,
        "company": acc.company,
        "name": acc.name,
        "currency": acc.currency,
        "balance": acc.balance,
        "equity": acc.equity,
        "leverage": acc.leverage,
        "trade_allowed": acc.trade_allowed,
        "trade_expert": acc.trade_expert,
    }, indent=2))

    mt5.shutdown()


if __name__ == "__main__":
    main()