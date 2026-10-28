"""Diagnostic: enumerate the real commodity (Metals/Energies/Local) symbols
on this Headway account and subscribe each to see which produce live quotes.
READ-ONLY - no orders."""
import time
import threading

import MetaTrader5 as mt5

TARGET_GROUPS = ("Metals", "Energies", "Local")


def main():
    def _w():
        try:
            return bool(mt5.initialize())
        except Exception:
            return False

    t = threading.Thread(target=_w, daemon=True)
    t.start()
    t.join(20)
    if not mt5.initialize():
        print("init failed:", mt5.last_error())
        return

    sym = mt5.symbols_get()
    for grp in TARGET_GROUPS:
        print("===", grp, "===")
        for s in sym:
            path = s.path or ""
            if not path.startswith(grp):
                continue
            try:
                mt5.symbol_select(s.name, True)
                time.sleep(0.5)
            except Exception:
                pass
            tk = mt5.symbol_info_tick(s.name)
            si = mt5.symbol_info(s.name)
            b = tk.bid if tk else None
            a = tk.ask if tk else None
            vmin = getattr(si, "volume_min", None)
            print("  %-12s path=%-20s bid=%r ask=%r vmin=%r"
                  % (s.name, path, b, a, vmin))

    mt5.shutdown()


if __name__ == "__main__":
    main()