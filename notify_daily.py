# -*- coding: utf-8 -*-
"""
Καθημερινή ειδοποίηση Telegram με το φθηνότερο σύνολο (πτήσεις + διαμονή).

Γιατί ξεχωριστό script: το καθημερινό σκανάρισμα τρέχει στο GitHub Actions,
όπου δεν υπάρχει το τοπικό σύστημα ειδοποιήσεων (D:\\claude\\notify) ούτε το
token. Αυτό εδώ τρέχει τοπικά, διαβάζει το ήδη δημοσιευμένο snapshot από το
dashboard και στέλνει την ειδοποίηση — το token δεν φεύγει ποτέ από το PC.

Χρήση:
    python notify_daily.py            # στέλνει μία φορά τη μέρα (dedup)
    python notify_daily.py --force    # στέλνει ούτως ή άλλως
"""
import json
import os
import sys
import urllib.request
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, ".notify_state.json")
SNAPSHOT_URL = "https://pymshadow.github.io/travel-tracker/snapshot.json"


def fetch_live_snapshot():
    import random, time as _t
    url = f"{SNAPSHOT_URL}?cb={random.randint(1, 10**9)}{int(_t.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "travel-tracker-notify/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    force = "--force" in sys.argv
    sys.path.insert(0, BASE)
    import travel_tracker as tt

    try:
        snapshot = fetch_live_snapshot()
    except Exception as e:
        print(f"Αποτυχία λήψης snapshot: {e}")
        # fallback: τοπικό αρχείο
        local = os.path.join(BASE, "dashboard", "public", "snapshot.json")
        if not os.path.exists(local):
            return 1
        with open(local, encoding="utf-8") as f:
            snapshot = json.load(f)

    # Ποιες συνθέσεις να συμπεριληφθούν: όσες σαρώθηκαν σήμερα
    today = date.today().isoformat()
    parties = {pid for e in snapshot.values()
               for pid, s in (e.get("parties") or {}).items()
               if s.get("scanned") == today}
    if not parties:
        print(f"Καμία σύνθεση σαρωμένη σήμερα ({today}) — καμία ειδοποίηση.")
        return 0

    # Υπολόγισε το φθηνότερο για dedup
    best = None
    for tid, e in snapshot.items():
        for pid, s in (e.get("parties") or {}).items():
            if pid not in parties or s.get("scanned") != today:
                continue
            f_, b_ = s.get("flight_min"), s.get("booking_min")
            if not f_ or not b_:
                continue
            tot = round(f_ + b_)
            if best is None or tot < best[0]:
                best = (tot, f"{tid}|{pid}")
    if best is None:
        print("Κανένα ολοκληρωμένο deal σήμερα — καμία ειδοποίηση.")
        return 0

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    if not force and state.get("date") == today and state.get("best") == list(best):
        print(f"Ήδη στάλθηκε σήμερα ({best[0]}€) — παράλειψη.")
        return 0

    # Το travel_tracker ξέρει ήδη να φτιάχνει & να στέλνει το μήνυμα
    tt.TODAY = today
    tt.notify_best_deal(snapshot, parties)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "best": list(best)}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
