import os, sys

COMMON = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal", "Common", "Files")
CFG = os.path.join(COMMON, "bot_config.txt")

DEFAULT = """enable_trading=false
max_trades_per_day=4
max_daily_loss_usd=60
use_time_filter=false
EURUSD.sl=50
EURUSD.tp=75
EURUSD.max_spread=15
EURUSD.magic=17460779
EURUSD.trail_trigger=40
EURUSD.trail_step=30
XAUUSD.sl=500
XAUUSD.tp=750
XAUUSD.max_spread=45
XAUUSD.magic=17460780
XAUUSD.trail_trigger=300
XAUUSD.trail_step=200
"""

def ensure():
    os.makedirs(COMMON, exist_ok=True)
    if not os.path.exists(CFG):
        with open(CFG, "w", encoding="utf-16") as f:
            f.write(DEFAULT)
        print("Created default config:", CFG)

def read_cfg():
    if not os.path.exists(CFG):
        return []
    with open(CFG, "r", encoding="utf-16") as f:
        return f.read().splitlines()

def write_cfg(lines):
    with open(CFG, "w", encoding="utf-16") as f:
        f.write("\n".join(lines) + "\n")

def set_enable(state):
    ensure()
    lines = read_cfg()
    out = ["enable_trading=" + ("true" if state else "false")]
    out += [l for l in lines if not l.startswith("enable_trading=")]
    write_cfg(out)
    print("enable_trading =", "true" if state else "false")
    print("Bots apply it within 60 seconds.")

def tune():
    with open(CFG, "w", encoding="utf-16") as f:
        f.write(DEFAULT.replace("enable_trading=false", "enable_trading=true"))
    print("TUNED: wider stops, bigger targets, tighter spread filter.")
    print("Bots apply it within 60 seconds.")

def status():
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            a = mt5.account_info()
            if a:
                print(f"Account {a.login} | {a.server} | balance ${a.balance:.2f} | trade_allowed={a.trade_allowed}")
            mt5.shutdown()
    except Exception as e:
        print("MT5 check failed:", e)
    print()
    for sym in ("EURUSD", "XAUUSD"):
        p = os.path.join(COMMON, f"ea_status_{sym}.txt")
        print(f"--- {sym} ---")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-16") as f:
                print(f.read().strip())
        else:
            print("NO STATUS FILE -> EA not attached to this chart")
        print()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "enable":
        set_enable(True)
    elif cmd == "disable":
        set_enable(False)
    elif cmd == "tune":
        tune()
    else:
        status()