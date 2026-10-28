import MetaTrader5 as mt5
from datetime import datetime

if not mt5.initialize():
    print("ERROR: Failed to initialize MT5")
    exit(1)

account = mt5.account_info()
print("\n" + "="*60)
print("ACCOUNT & TRADING STATUS")
print("="*60)
print(f"Trading Allowed    : {account.trade_allowed}")
print(f"Expert Allowed     : {account.trade_expert}")
print(f"Margin Level       : {account.margin_level}%")

symbol_info = mt5.symbol_info("XAUUSD")
print(f"\nXAUUSD Trade Mode  : {symbol_info.trade_mode}")
print(f"Min Volume         : {symbol_info.volume_min}")

check = mt5.order_check({"action": mt5.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": 0.01, "type": mt5.ORDER_TYPE_SELL, "price": symbol_info.bid, "sl": symbol_info.bid + 300 * symbol_info.point, "tp": symbol_info.bid - 600 * symbol_info.point, "deviation": 20, "magic": 234000, "comment": "Test", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN})
print(f"\nOrder Check Retcode: {check.retcode}")
print(f"Check Comment      : {check.comment}")

print("\n" + "="*60)
if not account.trade_expert:
    print("❌ EXPERT/AUTOMATED TRADING IS DISABLED!")
    print("FIX: Tools > Options > Expert Advisors > Allow automated trading")
else:
    print("✅ Expert trading enabled")
print("="*60 + "\n")

mt5.shutdown()
