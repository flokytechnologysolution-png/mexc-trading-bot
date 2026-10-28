import MetaTrader5 as mt5

if not mt5.initialize():
    print("ERROR: Failed to initialize MT5")
    exit(1)

symbol = "XAUUSD"
symbol_info = mt5.symbol_info(symbol)

print("\n" + "="*60)
print("DETAILED ORDER SEND DEBUG")
print("="*60)

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
    "comment": "Debug Order",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_FOK,
}

print("\nRequest:")
print(f"  Symbol: {symbol}, Volume: 0.01, Type: SELL")
print(f"  Price: {symbol_info.bid}, SL: {symbol_info.bid + 300 * symbol_info.point}")

check = mt5.order_check(test_request)
print(f"\nOrder Check: Retcode {check.retcode} - {check.comment}")

result = mt5.order_send(test_request)

print("\nOrder Send Result:")
if result is None:
    print("  ❌ Result is None")
else:
    print(f"  retcode    : {result.retcode}")
    print(f"  order      : {result.order}")
    print(f"  comment    : {result.comment}")
    print(f"  bid        : {result.bid}")
    print(f"  ask        : {result.ask}")
    
    # Check for other attributes
    if hasattr(result, 'deal'):
        print(f"  deal       : {result.deal}")
    if hasattr(result, 'volume'):
        print(f"  volume     : {result.volume}")

print("\n" + "="*60)
mt5.shutdown()
