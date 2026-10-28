import MetaTrader5 as mt5

if not mt5.initialize():
    print("ERROR: Failed to initialize MT5")
    exit(1)

account = mt5.account_info()

print("\n" + "="*60)
print("ACCOUNT TRADING RESTRICTIONS CHECK")
print("="*60)

print(f"\nTrade Allowed           : {account.trade_allowed}")
print(f"Trade Expert            : {account.trade_expert}")
print(f"Leverage                : {account.leverage}")
print(f"Margin Mode             : {account.margin_mode}")

print(f"\nBalance                 : {account.balance}")
print(f"Equity                  : {account.equity}")
print(f"Margin                  : {account.margin}")
print(f"Margin Free             : {account.margin_free}")
print(f"Margin Level            : {account.margin_level}%")

print("\n" + "="*60)
print("PROBLEM ANALYSIS")
print("="*60)

issues = []

if not account.trade_allowed:
    print("❌ CRITICAL: trade_allowed = False")
    issues.append("Trading disabled")

if not account.trade_expert:
    print("❌ CRITICAL: trade_expert = False")
    issues.append("Expert trading disabled")

if account.margin_level == 0:
    print("❌ CRITICAL: margin_level = 0.0%")
    print("   This is VERY abnormal - account is restricted")
    issues.append("Margin level is 0%")

if account.margin_level > 0 and account.margin_level < 100:
    print(f"❌ CRITICAL: margin_level < 100% ({account.margin_level}%)")
    print("   Cannot open new positions (margin call)")
    issues.append("Margin call active")

if account.margin_free <= 0:
    print("❌ CRITICAL: No free margin")
    issues.append("No free margin")

symbol_info = mt5.symbol_info("XAUUSD")
required_margin = 43.76

print(f"\nRequired Margin: {required_margin}")
print(f"Available Margin: {account.margin_free}")

if account.margin_free < required_margin:
    print(f"❌ NOT ENOUGH MARGIN to trade")
    issues.append("Insufficient margin")
else:
    print(f"✅ Sufficient margin")

print("\n" + "="*60)
if issues:
    print(f"❌ {len(issues)} ISSUE(S) FOUND")
else:
    print("✅ Account appears OK")
print("="*60 + "\n")

mt5.shutdown()
