import MetaTrader5 as mt5

if not mt5.initialize():
    exit(1)

print("\nTesting if orders can be created...")

symbol_info = mt5.symbol_info("XAUUSD")
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": "XAUUSD",
    "volume": 0.01,
    "type": mt5.ORDER_TYPE_BUY,
    "price": symbol_info.ask,
    "sl": symbol_info.ask - 300 * symbol_info.point,
    "tp": symbol_info.ask + 600 * symbol_info.point,
    "deviation": 20,
    "magic": 234000,
    "comment": "API Test",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_FOK,
}

result = mt5.order_send(request)

print(f"Order ID: {result.order}")
print(f"Deal ID: {result.deal}")
print(f"Retcode: {result.retcode}")
print(f"Comment: {result.comment}")

if result.order > 0 or result.deal > 0:
    print("\n✅ SUCCESS! API trading is now enabled!")
else:
    print("\n❌ Still being rejected. Broker likely has API trading disabled on demo.")
    print("   Contact your broker or switch to a live account.")

mt5.shutdown()
