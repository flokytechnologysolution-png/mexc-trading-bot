import MetaTrader5 as mt5

if not mt5.initialize():
    print("ERROR: Failed to initialize MT5")
    exit(1)

symbol = "XAUUSD"
symbol_info = mt5.symbol_info(symbol)

print("\n" + "="*60)
print(f"FILLING MODES FOR {symbol}")
print("="*60)

filling_mode = symbol_info.filling_mode
print(f"\nRaw filling_mode value: {filling_mode} (binary: {bin(filling_mode)})")
print(f"\nSupported modes:")

modes = {
    1: ("FOK (Fill or Kill)", mt5.ORDER_FILLING_FOK),
    2: ("IOC (Immediate or Cancel)", mt5.ORDER_FILLING_IOC),
    4: ("RETURN (Partial Fill)", mt5.ORDER_FILLING_RETURN),
}

for bit, (name, constant) in modes.items():
    if filling_mode & bit:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}")

for bit, (name, filling_const) in modes.items():
    if filling_mode & bit:
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
            "comment": f"Test {name}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_const,
        }
        
        check = mt5.order_check(test_request)
        status = "✅" if check.retcode == 0 else f"❌ {check.retcode}"
        print(f"\n{status} {name}")
        print(f"   Comment: {check.comment}")

print("\n" + "="*60)
mt5.shutdown()
