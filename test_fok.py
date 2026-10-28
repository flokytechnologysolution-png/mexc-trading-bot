import MetaTrader5 as mt5

if not mt5.initialize():
    print("ERROR: Failed to initialize MT5")
    exit(1)

symbol = "XAUUSD"
symbol_info = mt5.symbol_info(symbol)

print("\n" + "="*60)
print("TESTING FOK FILLING MODE")
print("="*60)

# Test with FOK (which we know works)
test_request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": 0.01,
    "type": mt5.ORDER_TYPE_SELL,
    "price": symbol_info.bid,
    "sl": symbol_info.bid + 300 * symbol_info.point,
    "tp": symbol_info.bid - 600 * symbol_info.point,
    "deviation": 20,
    "magic": 234000,
    "comment": "FOK Test",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_FOK,
}

check = mt5.order_check(test_request)
if check and check.retcode == 0:
    print("✅ FOK Order Check: PASSED")
    print(f"   Comment: {check.comment}")
    print(f"   Required Margin: {check.margin}")
    print("\n✅ YOUR BOT SHOULD NOW WORK!")
else:
    print(f"❌ FOK Order Check: FAILED")
    if check:
        print(f"   Retcode: {check.retcode}")
        print(f"   Comment: {check.comment}")

print("="*60 + "\n")
mt5.shutdown()
