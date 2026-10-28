import MetaTrader5 as mt5
from datetime import datetime, timedelta

MAGICS = {17460779: "EURUSD", 17460780: "XAUUSD"}
DAYS = 30
START_BALANCE = 15500.0

print("=" * 70)
print("SUN TZU BOT - BATTLE REPORT (READ-ONLY, NO ORDERS)")
print("=" * 70)

if not mt5.initialize():
    print("ERROR: cannot connect to MT5")
    raise SystemExit

acc = mt5.account_info()
if acc:
    print(f"Account : {acc.login} | {acc.server}")
    print(f"Balance : ${acc.balance:.2f}")
    print(f"Equity  : ${acc.equity:.2f}")
    print(f"Change  : ${acc.balance - START_BALANCE:+.2f} since start")
print()

now = datetime.now()
deals = mt5.history_deals_get(now - timedelta(days=DAYS), now) or []

rows = []
for d in deals:
    if d.entry != mt5.DEAL_ENTRY_OUT:
        continue
    if d.magic not in MAGICS:
        continue
    net = d.profit + d.swap + d.commission
    side = "BUY" if d.type == mt5.DEAL_TYPE_SELL else "SELL"
    rows.append((d.time, MAGICS[d.magic], side, d.volume, net, d.comment))

rows.sort(key=lambda r: r[0])

wins = [r for r in rows if r[4] > 0]
losses = [r for r in rows if r[4] <= 0]
net_pl = sum(r[4] for r in rows)
gross_win = sum(r[4] for r in wins)
gross_loss = -sum(r[4] for r in losses)
pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

print(f"Closed trades (last {DAYS} days): {len(rows)}")
print(f"Wins    : {len(wins)}")
print(f"Losses  : {len(losses)}")
if rows:
    print(f"Win rate: {100.0 * len(wins) / len(rows):.1f}%")
    print(f"Net P/L : ${net_pl:+.2f}")
    print(f"Profit factor: {pf:.2f}")
    if wins: print(f"Avg win : ${gross_win / len(wins):+.2f}")
    if losses: print(f"Avg loss: ${-gross_loss / len(losses):+.2f}")
print()

print("PER-SYMBOL SCORECARD")
print("-" * 70)
for sym in ("EURUSD", "XAUUSD"):
    srows = [r for r in rows if r[1] == sym]
    if not srows:
        print(f"{sym}: no trades")
        continue
    sw = [r for r in srows if r[4] > 0]
    snet = sum(r[4] for r in srows)
    print(f"{sym}: {len(srows)} trades | {len(sw)}W/{len(srows) - len(sw)}L | net ${snet:+.2f}")
print()

print("TRADE LOG")
print("-" * 70)
if not rows:
    print("No closed trades in window. The bot is waiting for signals.")
for t, sym, side, vol, net, comment in rows:
    ts = datetime.fromtimestamp(t).strftime("%m-%d %H:%M")
    print(f"{ts} | {sym:8s} | closed {side:4s} | {vol:.2f} lot | ${net:+.2f} | {comment}")
print()

poss = mt5.positions_get() or []
openp = [p for p in poss if p.magic in MAGICS]
print(f"Open positions: {len(openp)}")
for p in openp:
    side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
    print(f"{side:4s} {p.symbol:8s} {p.volume:.2f} lot | entry {p.price_open} | P/L ${p.profit:+.2f}")

mt5.shutdown()
print()
print("Report complete. Paste this output for analysis.")