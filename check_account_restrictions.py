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
print(f"Trade Practice          : {account.trade_practice}")
print(f"Trade Fifo              : {account.trade_fifo}")

print(f"\nMargin Mode             : {account.margin_mode}")
print(f"Margin SO Mode          : {account.margin_so_mode}")
print(f"Margin SO Call          : {account.margin_so_call}")
print(f"Margin SO Level         : {account.margin_so_level}")

print(f"\nBalance                 : {account.balance}")
print(f"Equity                  : {account.equity}")
print(f"Margin                  : {account.margin}")
print(f"Margin Free             : {account.margin_free}")
print(f"Margin Level            : {account.margin_level}%")

# Check for problems
print("\n" + "="*60)
print("PROBLEM CHECKS")
print("="*60)

if not account.trade_allowed:
    print("❌ CRITICAL: trade_allowed = False")
    print("   Trading is globally disabled on this account")

if not account.trade_expert:
    print("❌ CRITICAL: trade_expert = False")
    print("   Automated trading is disabled")

if account.margin_level == 0:
    print("❌ CRITICAL: margin_level = 0.0%")
    print("   This is VERY abnormal - account may be restricted")
    print("   Try depositing funds or check with your broker")

if account.margin_level < 100:
    print("❌ CRITICAL: margin_level < 100%")
    print(f"   Current: {account.margin_level}%")
    print("   You have a margin call - cannot trade")

if account.margin_free <= 0:
    print("❌ CRITICAL: margin_free <= 0")
    print("   No free margin available")

# Check if this is a micro account
if "micro" in account.company.lower() or account.leverage < 50:
    print(f"⚠️  Micro/Restricted Account Detected")
    print(f"   Leverage: {account.leverage}")
    print(f"   Company: {account.company}")

print("\n" + "="*60)
mt5.shutdown()
