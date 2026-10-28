import sys
import MetaTrader5 as mt5
import pandas as pd

def main():
    print("[*] Initializing MetaTrader 5 connection...")
    if not mt5.initialize():
        print(f"ERROR: initialize() failed, error code = {mt5.last_error()}")
        sys.exit(1)

    print("[+] Connected successfully!\n")

    # Fetch open positions
    positions = mt5.positions_get()
    
    print("=" * 60)
    print(" ACTIVE POSITIONS ")
    print("=" * 60)
    
    if positions is None or len(positions) == 0:
        print("No active positions found.")
    else:
        # Convert to DataFrame for a clean tabular view
        df_pos = pd.DataFrame(list(positions), columns=positions[0]._asdict().keys())
        # Select key columns for readability
        display_cols = ['ticket', 'time', 'symbol', 'type', 'volume', 'price_open', 'sl', 'tp', 'profit']
        print(df_pos[display_cols].to_string(index=False))

    print("=" * 60)

    # Fetch account info
    acc = mt5.account_info()
    if acc:
        print(f"Account Balance : {acc.balance} {acc.currency}")
        print(f"Account Equity  : {acc.equity} {acc.currency}")
        print(f"Free Margin     : {acc.margin_free} {acc.currency}")
        print("=" * 60)

    mt5.shutdown()

if __name__ == "__main__":
    main()