import MetaTrader5 as mt5
import json
import sys

NGN_PER_USD = 1600
ACCOUNT_NGN = 10000
RISK_NGN = 500

account_usd = ACCOUNT_NGN / NGN_PER_USD
risk_usd = RISK_NGN / NGN_PER_USD

def main():
    print("=" * 90)
    print("SEARCHING ALL SYMBOLS FOR BEST TRADE WITH NGN 10,000 / NGN 500 RISK")
    print("READ-ONLY - NO ORDERS - NO TRADES")
    print("=" * 90)

    if not mt5.initialize():
        print(f"ERROR: MT5 init failed: {mt5.last_error()}")
        sys.exit(1)

    account = mt5.account_info()
    if account:
        print(f"\nAccount: {account.login} | Server: {account.server}")
        print(f"Balance: {account.balance} | trade_allowed: {account.trade_allowed}")

    symbols = mt5.symbols_get()
    if not symbols:
        print("No symbols found")
        mt5.shutdown()
        sys.exit(1)

    print(f"\nScanning {len(symbols)} symbols...")
    print()

    results = []

    for s in symbols:
        try:
            mt5.symbol_select(s.name, True)
            tick = mt5.symbol_info_tick(s.name)
            info = mt5.symbol_info(s.name)

            if not tick or not info:
                continue
            if tick.bid <= 0 or tick.ask <= 0:
                continue

            spread_price = tick.ask - tick.bid
            tick_value = info.trade_tick_value
            tick_size = info.trade_tick_size
            min_lot = info.volume_min
            point = info.point

            if tick_value <= 0 or tick_size <= 0 or min_lot <= 0 or point <= 0:
                continue

            tick_val_min = tick_value * min_lot
            spread_cost = (spread_price / tick_size) * tick_val_min
            spread_points = spread_price / point

            # Max stop loss points we can afford
            max_sl_points = risk_usd / tick_val_min if tick_val_min > 0 else 0
            usable_sl_points = max_sl_points - spread_points

            # Margin
            margin = (tick.bid * info.trade_contract_size * min_lot) / 1000
            margin_pct = (margin / account_usd) * 100

            # Spread as % of risk
            spread_pct = (spread_cost / risk_usd) * 100 if risk_usd > 0 else 999

            # Expected net profit (1.5R target minus spread)
            win_payout = risk_usd * 1.5
            net_win = win_payout - spread_cost
            net_win_ngn = net_win * NGN_PER_USD

            # Score: lower spread% = better, more usable SL = better, lower margin = better
            score = 0
            if spread_cost < risk_usd:
                score += 40 * (1 - spread_pct / 100)
            if usable_sl_points > 0:
                score += 30 * min(1, usable_sl_points / 10)
            if margin_pct < 50:
                score += 20 * (1 - margin_pct / 50)
            if net_win > 0:
                score += 10

            score = round(min(100, max(0, score)), 1)

            # Filter: must not instantly lose
            if spread_cost < risk_usd and usable_sl_points > 0 and margin_pct < 80:
                results.append({
                    "symbol": s.name,
                    "path": s.path,
                    "spread_cost_usd": round(spread_cost, 4),
                    "spread_cost_ngn": round(spread_cost * NGN_PER_USD, 0),
                    "spread_pct_risk": round(spread_pct, 1),
                    "max_sl_points": round(max_sl_points, 1),
                    "usable_sl_points": round(usable_sl_points, 1),
                    "margin_usd": round(margin, 2),
                    "margin_pct": round(margin_pct, 0),
                    "net_win_ngn": round(net_win_ngn, 0),
                    "min_lot": min_lot,
                    "score": score
                })

        except Exception:
            continue

    # Sort by score (highest = best)
    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"Found {len(results)} symbols that don't instantly lose.")
    print()

    if not results:
        print("NO SYMBOL WORKS FOR NGN 10,000. Do not fund this account.")
        mt5.shutdown()
        return

    # Print top 10
    print(f"{'#':<3} {'SYMBOL':<18} {'SCORE':<7} {'SPREAD NGN':<12} {'SPR%RISK':<10} {'USABLE SL':<11} {'MARGIN$':<10} {'MARG%':<7} {'NET WIN NGN':<12} {'PATH'}")
    print("-" * 130)

    for i, r in enumerate(results[:10], 1):
        print(
            f"{i:<3} "
            f"{r['symbol']:<18} "
            f"{r['score']:<7} "
            f"{r['spread_cost_ngn']:<12} "
            f"{r['spread_pct_risk']:<10}% "
            f"{r['usable_sl_points']:<11} "
            f"${r['margin_usd']:<9} "
            f"{r['margin_pct']:<7}% "
            f"{r['net_win_ngn']:<12} "
            f"{r['path']}"
        )

    # Best symbol
    best = results[0]
    print()
    print("=" * 90)
    print(f"BEST SYMBOL FOR NGN 10,000: {best['symbol']}")
    print("=" * 90)
    print(f"Score: {best['score']}/100")
    print(f"Spread cost: NGN {best['spread_cost_ngn']} ({best['spread_pct_risk']}% of risk)")
    print(f"Usable stop loss: {best['usable_sl_points']} points")
    print(f"Margin: ${best['margin_usd']} ({best['margin_pct']}% of account)")
    print(f"Net win per trade (1.5R target): NGN {best['net_win_ngn']}")
    print()

    # Save decision
    decision = {
        "trade_allowed": best["score"] >= 50,
        "best_symbol": best["symbol"],
        "score": best["score"],
        "spread_cost_ngn": best["spread_cost_ngn"],
        "usable_sl_points": best["usable_sl_points"],
        "margin_usd": best["margin_usd"],
        "net_win_ngn": best["net_win_ngn"],
        "min_lot": best["min_lot"],
        "reason": "Best symbol for NGN 10000 with NGN 500 risk" if best["score"] >= 50 else "Score too low - do not trade"
    }

    with open("C:\\TradingBot\\best_symbol_decision.json", "w") as f:
        json.dump(decision, f, indent=2)

    print(f"Decision saved to C:\\TradingBot\\best_symbol_decision.json")
    print()

    if decision["trade_allowed"]:
        print("VERDICT: This symbol CAN be traded with NGN 10,000.")
        print("But use DEMO first. Only go live after 2 weeks of demo profit.")
    else:
        print("VERDICT: Even the best symbol scores too low. DO NOT TRADE.")

    mt5.shutdown()

if __name__ == "__main__":
    main()