# -*- coding: utf-8 -*-
"""
Travel Price Tracker
--------------------
Διαβάζει ταξίδια από το trips.json, τραβάει καθημερινά τιμές πτήσεων
(Google Flights) και διαμονής (Booking.com μέσω Playwright),
κρατάει ιστορικό στο history.csv και παράγει report.html.

Κανόνες διαμονής (Booking):
  - έως 5 χλμ από το κέντρο
  - βαθμολογία τουλάχιστον 8/10
  - μόνο ολόκληρα διαμερίσματα Ή ξενοδοχεία με πρωινό
  - έως 800 μ από μετρό ή στάση λεωφορείου

Κανόνες πτήσεων:
  - προτίμηση: αναχώρηση όσο πιο νωρίς, επιστροφή όσο πιο αργά
  - μικρό μπόνους σε Aegean/Olympic (όχι δεσμευτικό)

Εκτέλεση:  python travel_tracker.py
"""
import csv
import html
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import date, datetime
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
TRIPS_FILE = os.path.join(BASE, "trips.json")
HISTORY_FILE = os.path.join(BASE, "history.csv")
GEOCACHE_FILE = os.path.join(BASE, "geocache.json")
STOPS_DIR = os.path.join(BASE, "stops_cache")
SNAPSHOT_DIR = os.path.join(BASE, "snapshots")
REPORT_FILE = os.path.join(BASE, "report.html")

TODAY = date.today().isoformat()

# ------------------------------------------------------------------ κανόνες
RULES = {
    "max_center_m": 5000,        # απόσταση από κέντρο
    "min_rating": 8.0,           # ελάχιστη βαθμολογία Booking
    "max_transit_m": 800,        # απόσταση από μετρό/στάση
    # καταλύματα των οποίων το όνομα περιέχει κάποια από αυτές τις λέξεις αποκλείονται
    "name_blacklist": ["student", "hostel", "dorm", "capsule"],
    # πτήσεις: score = τιμή + ποινές - μπόνους (σε "ευρώ")
    "eur_per_hour_late_departure": 3,   # ποινή ανά ώρα μετά τις 06:00 (αναχώρηση)
    "eur_per_hour_early_return": 3,     # ποινή ανά ώρα πριν τις 22:00 (επιστροφή)
    "eur_per_stop": 20,                 # ποινή ανά στάση
    "aegean_bonus_eur": 15,             # μπόνους Aegean/Olympic
    "max_flight_pp_eur": 125,           # στόχος: μέγιστο κόστος εισιτηρίων ανά άτομο (σύνολο 2 σκελών)
}


# ---------------------------------------------------------------- flights ---

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SOCS_COOKIE = "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVsIAEaBgiA_LyaBg"


def _flight_query_url(dep_date, frm, to, adults):
    from fast_flights import FlightQuery, Passengers, create_query
    q = create_query(
        flights=[FlightQuery(date=dep_date, from_airport=frm, to_airport=to)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=adults),
        currency="EUR",
    )
    params = q.params()
    params["hl"] = "en"  # αγγλικά για σταθερό parsing των aria-labels
    return q, "https://www.google.com/travel/flights?" + urlencode(params)


def _parse_live_label(label, frm, to):
    """Parse του aria-label μιας πτήσης από τη live σελίδα Google Flights."""
    m = re.search(r"From (\d[\d,]*) euros", label)
    if not m:
        return None
    price = int(m.group(1).replace(",", ""))
    stops = 0 if "Nonstop" in label else (
        int(re.search(r"(\d+) stops?", label).group(1)) if re.search(r"(\d+) stops?", label) else 1)
    ma = re.search(r"flights? with ([^.]+)\.", label)
    airlines = [a.strip() for a in re.split(r",| and ", ma.group(1))] if ma else ["?"]

    def to24(mt):
        if not mt:
            return 0, 0
        h = int(mt.group(1)) % 12 + (12 if mt.group(3) == "PM" else 0)
        return h, int(mt.group(2))

    tm = r"at (\d{1,2}):(\d{2})[\s  ]*(AM|PM)"
    dh, dm = to24(re.search(r"Leaves .*? " + tm, label))
    ah, am = to24(re.search(r"arrives at .*? " + tm, label))
    return {
        "price": price,
        "airlines": airlines,
        "stops": stops,
        "dep_hour": round(dh + dm / 60, 2),
        "depart": f"{dh:02d}:{dm:02d}",
        "arrive": f"{ah:02d}:{am:02d}",
        "via": f"{frm} → {to}" if stops == 0 else f"{frm} → ({stops} στάση/εις) → {to}",
    }


def _fetch_flight_leg_live(page, direction, dep_date, frm, to, adults, nights=0):
    """Αναζητά τη 1η σελίδα live από Google Flights (πλήρη αποτελέσματα)."""
    _, url = _flight_query_url(dep_date, frm, to, adults)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("[aria-label*='euros']", timeout=25000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    labels = page.eval_on_selector_all(
        "[aria-label*='euros']",
        "els => els.map(e => e.getAttribute('aria-label'))"
        ".filter(l => l && l.startsWith('From '))")
    options, seen = [], set()
    for label in labels:
        o = _parse_live_label(label, frm, to)
        if not o or o["stops"] > 0:
            continue
        if nights >= 4:
            lowcost = ["ryanair", "wizz", "easyjet", "volotea", "vueling", "pegasus", "transavia", "air malta"]
            if any(any(lc in a.lower() for lc in lowcost) for a in o["airlines"]):
                continue

        if direction == "out":
            if o["depart"] > ("17:00" if nights >= 6 else "13:00"):
                continue
        if direction == "ret":
            if o["depart"] < ("08:00" if nights >= 6 else "16:30"):
                continue

        key = (o["price"], o["depart"], tuple(o["airlines"]))
        if key not in seen:
            seen.add(key)
            options.append(o)
    return options, url


def _fetch_flight_leg(direction, dep_date, frm, to, adults, nights=0):
    """Fallback scraping με fast_flights."""
    from primp import Client
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.parser import parse

    q = create_query(
        flights=[FlightQuery(date=dep_date, from_airport=frm, to_airport=to)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=adults),
        currency="EUR",
    )
    last_err = None
    for _ in range(3):
        try:
            client = Client(impersonate="chrome_145", impersonate_os="macos",
                            referer=True, cookie_store=True)
            client.set_cookies(
                "https://www.google.com",
                {"SOCS": SOCS_COOKIE, "CONSENT": "PENDING+987"},
            )
            res = client.get("https://www.google.com/travel/flights", params=q.params())
            results = parse(res.text)
            break
        except Exception as e:
            last_err = e
            time.sleep(5)
    else:
        raise RuntimeError(f"flight fetch failed after 3 attempts: {last_err}")

    def hm(t):
        vals = [x if isinstance(x, int) else 0 for x in (list(t or []) + [0, 0])[:2]]
        return vals[0], vals[1]

    options = []
    for f in results:
        if not f.price or len(f.flights) > 1:
            continue
        if nights >= 4:
            lowcost = ["ryanair", "wizz", "easyjet", "volotea", "vueling", "pegasus", "transavia", "air malta"]
            if any(any(lc in a.lower() for lc in lowcost) for a in f.airlines):
                continue
        
        dh, dm = hm(f.flights[0].departure.time)
        dep_str = f"{dh:02d}:{dm:02d}"
        if direction == "out":
            if dep_str > ("17:00" if nights >= 6 else "13:00"):
                continue
        if direction == "ret":
            if dep_str < ("08:00" if nights >= 6 else "16:30"):
                continue

        ah, am = hm(f.flights[-1].arrival.time)
        options.append({
            "price": f.price,
            "airlines": f.airlines,
            "stops": len(legs) - 1,
            "dep_hour": round(dh + dm / 60, 2),
            "depart": f"{dh:02d}:{dm:02d}",
            "arrive": f"{ah:02d}:{am:02d}",
            "via": " → ".join([legs[0].from_airport.code] + [l.to_airport.code for l in legs]),
        })
    search_url = "https://www.google.com/travel/flights?" + urlencode(q.params())
    return options, search_url


def _score_leg(opt, direction, nights=0):
    """Χαμηλότερο score = καλύτερη επιλογή σύμφωνα με τους κανόνες."""
    score = float(opt["price"])
    if direction == "out":
        score += max(0.0, opt["dep_hour"] - 6) * RULES["eur_per_hour_late_departure"]
        if nights >= 6 and opt["depart"] > "13:00":
            score += 40.0
    else:
        score += max(0.0, 22 - opt["dep_hour"]) * RULES["eur_per_hour_early_return"]
        if nights >= 6 and opt["depart"] < "16:30":
            score += 40.0
    score += opt["stops"] * RULES["eur_per_stop"]
    if any(a for a in opt["airlines"] if "aegean" in a.lower() or "olympic" in a.lower()):
        score -= RULES["aegean_bonus_eur"]
    return round(score, 1)


def fetch_flights(trip, playwright):
    """Επιστρέφει {'out': [...], 'ret': [...]} με score, ταξινομημένα (καλύτερο πρώτο).

    Πρώτα η live σελίδα Google Flights (πλήρη αποτελέσματα)· αν δεν δώσει
    τίποτα, fallback στο στατικό HTML.
    """
    adults = trip.get("adults", 1)
    nights = 0
    if trip.get("return"):
        from datetime import date as _d
        try:
            a = _d(*[int(x) for x in trip["depart"].split("-")])
            b = _d(*[int(x) for x in trip["return"].split("-")])
            nights = (b - a).days
        except:
            pass
    result = {}
    legs = [("out", trip["depart"], trip["from"], trip["to"])]
    if trip.get("return"):
        legs.append(("ret", trip["return"], trip["to"], trip["from"]))

    browser = playwright.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled", "--no-sandbox"])
    try:
        ctx = browser.new_context(locale="en-GB", user_agent=UA,
                                  viewport={"width": 1400, "height": 900})
        ctx.add_cookies([{"name": "SOCS", "value": SOCS_COOKIE,
                          "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()
        for direction, d, frm, to in legs:
            try:
                options, search_url = _fetch_flight_leg_live(page, direction, d, frm, to, adults, nights)
            except Exception:
                options = []
            if not options:  # fallback στο στατικό HTML
                options, search_url = _fetch_flight_leg(direction, d, frm, to, adults, nights)
            for o in options:
                o["score"] = _score_leg(o, direction, nights)
            options.sort(key=lambda o: o["score"])
            result[direction] = options
            result[direction + "_url"] = search_url
            time.sleep(2)
    finally:
        browser.close()
    return result


# ---------------------------------------------------------------- booking ---

def _parse_distance_m(text):
    """'350 m from centre' / '1.8 km ...' / 'within 150 metres' -> μέτρα."""
    if not text:
        return None
    m = re.search(r"([\d.,]+)\s*(km|m\b|metres|meters)", text)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    return val * 1000 if m.group(2) == "km" else val


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocode_city(city):
    """Bounding box πόλης μέσω Nominatim (OpenStreetMap), με cache στο δίσκο."""
    cache = {}
    if os.path.exists(GEOCACHE_FILE):
        with open(GEOCACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    key = city.strip().lower()
    if key in cache:
        return cache[key]
    from curl_cffi import requests
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": city, "format": "json", "limit": 1},
        headers={"User-Agent": "TravelPriceTracker/1.0 (personal use)"},
        impersonate="chrome124",
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise RuntimeError(f"City not found: {city}")
    s, n, w, e = (float(x) for x in data[0]["boundingbox"])
    clat, clon = (s + n) / 2, (w + e) / 2
    span = 0.20
    bbox = {"n": min(n, clat + span), "e": min(e, clon + span),
            "s": max(s, clat - span), "w": max(w, clon - span)}
    cache[key] = bbox
    with open(GEOCACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return bbox


def get_transit_stops(city):
    """Στάσεις μετρό/τραμ/λεωφορείου της πόλης από OpenStreetMap (Overpass), με cache."""
    os.makedirs(STOPS_DIR, exist_ok=True)
    path = os.path.join(STOPS_DIR, re.sub(r"\W+", "_", city.lower()) + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    bbox = geocode_city(city)
    from curl_cffi import requests
    query = f"""[out:json][timeout:90];
(node["highway"="bus_stop"]({bbox['s']},{bbox['w']},{bbox['n']},{bbox['e']});
 node["railway"~"^(station|tram_stop|subway_entrance)$"]({bbox['s']},{bbox['w']},{bbox['n']},{bbox['e']});
);out skel;"""
    last_err = None
    for endpoint in ("https://overpass-api.de/api/interpreter",
                     "https://overpass.kumi.systems/api/interpreter"):
        try:
            r = requests.post(endpoint, data={"data": query}, timeout=120,
                              headers={"User-Agent": "TravelPriceTracker/1.0 (personal use)"})
            r.raise_for_status()
            break
        except Exception as e:
            last_err = e
            time.sleep(3)
    else:
        raise RuntimeError(f"Overpass failed on all endpoints: {last_err}")
    stops = [(el["lat"], el["lon"]) for el in r.json().get("elements", [])]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stops, f)
    return stops


def _booking_search_url(trip, extra_nflt):
    from datetime import datetime as _dt
    checkin = trip.get("checkin") or trip["depart"]
    checkout = trip.get("checkout") or trip.get("return")
    
    try:
        checkin_date = _dt.strptime(checkin, "%Y-%m-%d")
        days_away = (checkin_date - _dt.now()).days
        if days_away > 60:
            extra_nflt.append("fc=2")
    except Exception:
        pass

    nflt = [f"review_score={int(RULES['min_rating'] * 10)}",
            f"distance={RULES['max_center_m']}",
            "roomfacility=38"] + extra_nflt
    params = {
        "ss": trip.get("city") or trip["to"],
        "checkin": checkin,
        "checkout": checkout,
        "group_adults": str(trip.get("adults", 1)),
        "no_rooms": "1",
        "group_children": "0",
        "selected_currency": "EUR",
        "order": "price",
        "nflt": ";".join(nflt),
    }
    return "https://www.booking.com/searchresults.en-gb.html?" + urlencode(params)


def _extract_booking_results(page):
    """Διαβάζει το apollo JSON blob της σελίδας αποτελεσμάτων."""
    blob = page.query_selector('script[data-capla-store-data="apollo"]')
    if not blob:
        return []
    data = json.loads(blob.inner_text())
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "basicPropertyData" in o and o.get("priceDisplayInfoIrene"):
                found.append(o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return found


def _parse_booking_property(r, trip, kind):
    bp = r.get("basicPropertyData") or {}
    loc = r.get("location") or {}
    reviews = bp.get("reviews") or {}
    price_info = ((r.get("priceDisplayInfoIrene") or {}).get("displayPrice") or {})
    amount = (price_info.get("amountPerStay") or {}).get("amountUnformatted")
    if not amount:
        return None
    checkin = trip.get("checkin") or trip["depart"]
    checkout = trip.get("checkout") or trip.get("return")
    cc = (bp.get("location") or {}).get("countryCode", "")
    page_name = bp.get("pageName", "")
    url = (f"https://www.booking.com/hotel/{cc}/{page_name}.en-gb.html?"
           + urlencode({"checkin": checkin, "checkout": checkout,
                        "group_adults": trip.get("adults", 1), "selected_currency": "EUR"}))
    return {
        "name": ((r.get("displayName") or {}).get("text")) or page_name,
        "kind": kind,  # apartment | hotel_breakfast
        "total": round(float(amount), 0),
        "rating": reviews.get("totalScore") or 0,
        "reviews": reviews.get("reviewsCount") or 0,
        "center_m": _parse_distance_m(loc.get("mainDistance")),
        "transit_m": _parse_distance_m(loc.get("publicTransportDistanceDescription")),
        "transit_desc": loc.get("publicTransportDistanceDescription") or "",
        "lat": (bp.get("location") or {}).get("latitude"),
        "lon": (bp.get("location") or {}).get("longitude"),
        "url": url,
    }


def _passes_rules(p, stops):
    name = str(p["name"]).lower()
    if any(word in name for word in RULES["name_blacklist"]):
        return False
    if p["rating"] < RULES["min_rating"]:
        return False
    if p["center_m"] is not None and p["center_m"] > RULES["max_center_m"]:
        return False
    # μετρό/στάση: πρώτα ό,τι δηλώνει το Booking, αλλιώς έλεγχος σε στάσεις OSM
    if p["transit_m"] is not None:
        return p["transit_m"] <= RULES["max_transit_m"]
    if p["lat"] and p["lon"] and stops:
        d = min(haversine_m(p["lat"], p["lon"], s[0], s[1]) for s in stops)
        p["transit_m"] = round(d)
        p["transit_desc"] = f"~{d:.0f} μ από στάση (OSM)"
        return d <= RULES["max_transit_m"]
    return False  # άγνωστη απόσταση από συγκοινωνία -> εκτός κανόνων


def fetch_booking(trip, playwright):
    """Δύο αναζητήσεις (διαμερίσματα / ξενοδοχεία με πρωινό), φίλτρο κανόνων, merge."""
    checkout = trip.get("checkout") or trip.get("return")
    if not checkout:
        return []

    searches = [
        ("apartment", ["privacy_type=3"]),                # ολόκληρα σπίτια/διαμερίσματα
        ("hotel_breakfast", ["ht_id=204", "mealplan=1"]),  # ξενοδοχεία με πρωινό
    ]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    browser = playwright.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled", "--no-sandbox"])
    results = {}
    try:
        ctx = browser.new_context(locale="en-GB", user_agent=UA,
                                  viewport={"width": 1400, "height": 900})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        page.goto("https://www.booking.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        for kind, nflt in searches:
            page.goto(_booking_search_url(trip, nflt),
                      wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector('[data-testid="property-card"]', timeout=30000)
            except Exception:
                continue  # πιθανόν 0 αποτελέσματα με αυτά τα φίλτρα
            page.wait_for_timeout(1500)
            for raw in _extract_booking_results(page):
                p = _parse_booking_property(raw, trip, kind)
                if p:
                    # ίδιο κατάλυμα από δύο αναζητήσεις -> κράτα τη φθηνότερη εκδοχή
                    key = p["url"].split("?")[0]
                    if key not in results or p["total"] < results[key]["total"]:
                        results[key] = p
            time.sleep(2)
    finally:
        browser.close()

    try:
        stops = get_transit_stops(trip.get("city") or trip["to"])
    except Exception as e:
        print(f"  (προειδοποίηση: αποτυχία λήψης στάσεων OSM: {e})")
        stops = []

    passing = [p for p in results.values() if _passes_rules(p, stops)]
    passing.sort(key=lambda x: x["total"])
    return passing


# ---------------------------------------------------------------- history ---

def append_history(rows):
    new_file = not os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "trip_id", "metric", "value"])
        w.writerows(rows)


def load_history():
    hist = {}
    if not os.path.exists(HISTORY_FILE):
        return hist
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hist.setdefault(row["trip_id"], {}).setdefault(row["metric"], []).append(
                (row["date"], float(row["value"])))
    return hist


def stats_for(hist, trip_id, metric, today_value):
    series = [x for x in hist.get(trip_id, {}).get(metric, []) if x[0] < TODAY]
    prev = series[-1][1] if series else None
    alltime = min((v for _, v in series), default=None)
    return prev, alltime


# ----------------------------------------------------------------- report ---

def sparkline(points, width=260, height=48):
    if len(points) < 2:
        return ""
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    step = width / (len(vals) - 1)
    coords = [(i * step, height - 6 - (v - lo) / rng * (height - 12)) for i, v in enumerate(vals)]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    lx, ly = coords[-1]
    return (f'<svg width="{width}" height="{height}" style="overflow:visible">'
            f'<polyline points="{pts}" fill="none" stroke="#2b7de9" stroke-width="2"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="#e94b2b"/></svg>')


def delta_badge(current, prev):
    if prev is None:
        return ""
    d = current - prev
    if abs(d) < 0.5:
        return '<span class="flat">= ίδια</span>'
    cls, arrow = ("down", "▼") if d < 0 else ("up", "▲")
    return f'<span class="{cls}">{arrow} {abs(d):.0f}€ από χθες</span>'


def _flight_table(options, title, url=""):
    if not options:
        return ""
    link = f" <a href='{html.escape(url)}' target='_blank' class='text-blue-400 hover:text-blue-300 ml-2 text-sm font-normal'>— άνοιγμα στο Google Flights ↗</a>" if url else ""
    rows = [f"<h3 class='text-lg font-bold text-white mt-8 mb-4 flex items-center'>{title}{link}</h3>",
            "<div class='overflow-x-auto'><table class='w-full text-left border-collapse text-sm'>",
            "<thead><tr class='border-b border-slate-700 text-slate-400'>",
            "<th class='pb-3 font-medium'></th><th class='pb-3 font-medium'>Τιμή</th>",
            "<th class='pb-3 font-medium'>Εταιρεία</th><th class='pb-3 font-medium'>Διαδρομή</th>",
            "<th class='pb-3 font-medium'>Στάσεις</th><th class='pb-3 font-medium'>Αναχ.</th>",
            "<th class='pb-3 font-medium'>Άφιξη</th></tr></thead><tbody class='text-slate-300'>"]
    for i, o in enumerate(options[:5]):
        star = "⭐" if i == 0 else ""
        rows.append(f"<tr class='border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors'>"
                    f"<td class='py-3'>{star}</td><td class='py-3 font-bold text-white'>{o['price']}€</td>"
                    f"<td class='py-3'>{html.escape(', '.join(o['airlines']))}</td><td class='py-3 text-slate-400'>{o['via']}</td>"
                    f"<td class='py-3'>{o['stops']}</td><td class='py-3 font-medium'>{o['depart']}</td><td class='py-3 font-medium'>{o['arrive']}</td></tr>")
    rows.append("</tbody></table></div>")
    return "".join(rows)

def build_report(trips, snapshot, hist):
    parts = ["""<!DOCTYPE html>
<html lang="el" class="dark">
<head>
    <meta charset="utf-8">
    <title>Travel Price Tracker Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Inter', sans-serif; }
        .glass-card {
            background: linear-gradient(145deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9));
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(148, 163, 184, 0.1);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }
        .text-gradient {
            background: linear-gradient(to right, #60a5fa, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
    </style>
</head>
<body class="min-h-screen p-4 md:p-8 antialiased">
    <div class="max-w-6xl mx-auto">
        <header class="mb-12 text-center">
            <h1 class="text-4xl md:text-5xl font-extrabold mb-4 text-gradient tracking-tight">✈️ Travel Price Tracker</h1>
            <p class="text-slate-400 font-medium">Τελευταίος έλεγχος: """ + f"{datetime.now():%d/%m/%Y %H:%M}" + """</p>
        </header>

        <div class="glass-card p-5 rounded-2xl mb-10 text-sm text-slate-300 leading-relaxed">
            <strong class="text-blue-400 block mb-2 text-base">📋 Κανόνες Συστήματος:</strong>
            <span class="opacity-90"><b>Διαμονή:</b> &le;5 χλμ κέντρο &bull; rating &ge;8 &bull; μόνο ιδιωτικό μπάνιο &bull; &le;800μ από μετρό.<br>
            <b>Πτήσεις:</b> ⭐ ιδανικός συνδυασμός (νωρίς αναχώρηση / αργά επιστροφή). Για &ge;4 νύχτες απορρίπτονται οι low-cost εταιρείες χωρίς δωρεάν καμπίνα.</span>
        </div>
        
        <div class="space-y-10">"""]

    for trip in trips:
        tid = trip["id"]
        snap = snapshot.get(tid, {})
        ret_text = f" &mdash; επιστροφή {trip['return']}" if trip.get("return") else ""
        adults = trip.get("adults", 1)
        
        parts.append(f"""
            <section class="glass-card rounded-3xl p-6 md:p-10 overflow-hidden relative">
                <div class="absolute -top-6 -right-6 p-4 opacity-5 text-9xl pointer-events-none">✈️</div>
                <h2 class="text-3xl md:text-4xl font-extrabold text-white mb-3">{html.escape(trip.get('name', tid))}</h2>
                <div class="text-slate-400 mb-8 font-medium flex flex-wrap items-center gap-3">
                    <span class="bg-slate-800 text-blue-300 px-3 py-1 rounded-full text-xs uppercase tracking-widest border border-slate-700/50">{trip['from']} &rarr; {trip['to']}</span>
                    <span>Αναχώρηση {trip['depart']}{ret_text}</span>
                    <span class="text-slate-500">&bull;</span>
                    <span>{adults} άτομα</span>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">""")
        
        for metric, label in [("flight_min", "Φθηνότερες Πτήσεις"),
                              ("flight_best", "Ιδανικές Πτήσεις ⭐"),
                              ("booking_min", "Φθηνότερη Διαμονή")]:
            if metric not in snap:
                continue
            val = snap[metric]
            prev, alltime = stats_for(hist, tid, metric, val)
            
            badge_trend = ""
            if prev is not None:
                d = val - prev
                if abs(d) < 0.5:
                    badge_trend = f'<span class="text-slate-500 text-[11px] font-medium ml-3">= ίδια από χθες</span>'
                elif d < 0:
                    badge_trend = f'<span class="text-emerald-400 text-[11px] font-bold ml-3">&darr; {abs(d):.0f}&euro; από χθες</span>'
                else:
                    badge_trend = f'<span class="text-rose-400 text-[11px] font-bold ml-3">&uarr; {abs(d):.0f}&euro; από χθες</span>'
            
            badge_low = '<span class="ml-auto bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded text-[10px] uppercase font-bold border border-amber-500/30">🔥 Low</span>' if (alltime is None or val <= alltime) else ""
            
            budget_html = ""
            if metric.startswith("flight"):
                pp = val / adults
                target = RULES["max_flight_pp_eur"]
                if pp <= target:
                    budget_html = f'<div class="mt-3 text-xs text-emerald-400 font-medium">&check; {pp:.0f}&euro;/άτομο (εντός στόχου &le;{target}&euro;)</div>'
                else:
                    budget_html = f'<div class="mt-3 text-xs text-rose-400 font-medium">&uarr; {pp:.0f}&euro;/άτομο (+{pp - target:.0f}&euro; εκτός στόχου)</div>'

            parts.append(f"""
                    <div class="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/50 hover:border-slate-600/60 transition-colors shadow-inner">
                        <div class="flex items-center mb-2">
                            <div class="text-slate-400 text-xs uppercase tracking-wider font-semibold">{label}</div>
                            {badge_low}
                        </div>
                        <div class="flex items-baseline">
                            <div class="text-4xl font-extrabold text-white">{val:.0f}&euro;</div>
                            {badge_trend}
                        </div>
                        {budget_html}
                        <div class="mt-4 opacity-70 filter brightness-110">{sparkline(hist.get(tid, {}).get(metric, []), width=220, height=36)}</div>
                    </div>""")
        
        parts.append("</div>")
        
        if snap.get("error"):
            parts.append(f'<div class="bg-rose-900/20 border border-rose-500/30 text-rose-300 p-4 rounded-xl mb-8 text-sm">{html.escape(snap["error"])}</div>')

        parts.append(_flight_table(snap.get("flights_out", []), f"Πτήσεις αναχώρησης ({trip['depart']})", snap.get("flights_out_url", "")))
        if trip.get("return"):
            parts.append(_flight_table(snap.get("flights_ret", []), f"Πτήσεις επιστροφής ({trip['return']})", snap.get("flights_ret_url", "")))

        if snap.get("booking"):
            parts.append("""
                <h3 class='text-lg font-bold text-white mt-10 mb-4 flex items-center'>Διαμονή — Booking.com <span class="text-slate-500 font-normal text-sm ml-2">(Σύνολο, εντός κανόνων)</span></h3>
                <div class='overflow-x-auto'><table class='w-full text-left border-collapse text-sm'>
                <thead><tr class='border-b border-slate-700 text-slate-400'>
                <th class='pb-3 font-medium'>Τιμή</th><th class='pb-3 font-medium'>Κατάλυμα</th>
                <th class='pb-3 font-medium'>Τύπος</th><th class='pb-3 font-medium'>Βαθμ.</th>
                <th class='pb-3 font-medium'>Κέντρο</th><th class='pb-3 font-medium'>Συγκοινωνία</th>
                <th class='pb-3'></th></tr></thead><tbody class='text-slate-300'>""")
            
            for l in snap["booking"][:8]:
                tag = "Διαμέρισμα" if l["kind"] == "apartment" else "Ξενοδοχείο"
                tag_cls = "bg-indigo-500/20 text-indigo-300 border-indigo-500/30" if l["kind"] == "apartment" else "bg-teal-500/20 text-teal-300 border-teal-500/30"
                center = f"{l['center_m']:.0f} μ" if l['center_m'] is not None else "—"
                transit = f"{l['transit_m']:.0f} μ" if l['transit_m'] is not None else "—"
                parts.append(f"""
                    <tr class='border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors'>
                        <td class='py-4 font-bold text-white text-base'>{l['total']:.0f}€</td>
                        <td class='py-4 font-medium max-w-xs truncate' title="{html.escape(str(l['name']))}">{html.escape(str(l['name']))}</td>
                        <td class='py-4'><span class='px-2 py-1 rounded text-[10px] uppercase font-bold border {tag_cls}'>{tag}</span></td>
                        <td class='py-4'><span class="text-amber-400 font-bold">{l['rating']}★</span> <span class="text-slate-500 text-xs">({l['reviews']})</span></td>
                        <td class='py-4 text-slate-400'>{center}</td><td class='py-4 text-slate-400'>{transit}</td>
                        <td class='py-4 text-right'><a href='{l['url']}' target='_blank' class='bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors'>Κράτηση &rarr;</a></td>
                    </tr>""")
            parts.append("</tbody></table></div>")
        elif "booking" in snap:
            parts.append("<p class='text-slate-500 italic mt-6'>Κανένα κατάλυμα δεν πέρασε τους κανόνες σήμερα.</p>")
            
        parts.append("</section>")

    parts.append("""
        </div>
        <footer class='text-center text-slate-500 text-sm mt-16 mb-8 font-medium'>
            Πηγές: Google Flights, Booking.com, OpenStreetMap.<br>
            Οι τιμές είναι ενδεικτικές και αλλάζουν συνεχώς — επιβεβαίωσε πριν την κράτηση.
        </footer>
    </div>
</body>
</html>""")
    
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


# ------------------------------------------------------------------- main ---

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=TRIPS_FILE, help="JSON file with trips")
    parser.add_argument("--single", help="Run only for this trip ID")
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Δεν βρέθηκε το {args.file}")
        return 1
    with open(args.file, encoding="utf-8") as f:
        trips = [t for t in json.load(f)["trips"] if t.get("enabled", True)]
        if args.single:
            trips = [t for t in trips if t["id"] == args.single]
    
    if not trips:
        print(f"Κανένα ενεργό ταξίδι προς εκτέλεση.")
        return 0

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    hist = load_history()
    snapshot, history_rows = {}, []

    from playwright.sync_api import sync_playwright
    import random
    
    # Process surprise pools before looping
    for t in trips:
        if "surprise_pool" in t:
            choice = random.choice(t["surprise_pool"])
            t["to"] = choice["to"]
            t["city"] = choice["city"]
            t["name"] = f"Έκπληξη: {choice['name']}"

    for trip in trips:
        with sync_playwright() as pw:
            tid = trip["id"]
            best_snap = None
            best_total = float('inf')
            best_hist = []
            
            pairs = trip.get("date_pairs", [{"depart": trip.get("depart"), "return": trip.get("return")}])
            
            for pair in pairs:
                trip["depart"] = pair["depart"]
                trip["return"] = pair["return"]
                snap = {}
                hist = []
                print(f"\n=== {trip.get('name', tid)} ({trip['from']}→{trip['to']}, {trip['depart']}) ===")

                try:
                    fl = fetch_flights(trip, pw)
                    snap["flights_out"] = fl.get("out", [])[:8]
                    snap["flights_ret"] = fl.get("ret", [])[:8]
                    snap["flights_out_url"] = fl.get("out_url", "")
                    snap["flights_ret_url"] = fl.get("ret_url", "")
                    out, ret = fl.get("out", []), fl.get("ret", [])
                    has_return = bool(trip.get("return"))
                    if out and (not has_return or ret):
                        cheapest = min(o["price"] for o in out) + (min(o["price"] for o in ret) if ret else 0)
                        best = out[0]["price"] + (ret[0]["price"] if ret else 0)
                        snap["flight_min"] = cheapest
                        snap["flight_best"] = best
                        hist.append([TODAY, tid, "flight_min", cheapest])
                        hist.append([TODAY, tid, "flight_best", best])
                        pp = cheapest / trip.get("adults", 1)
                        target = RULES["max_flight_pp_eur"]
                        mark = "✅ εντός στόχου" if pp <= target else f"πάνω από στόχο κατά {pp - target:.0f}€"
                        print(f"  Πτήσεις: {pp:.0f}€/άτομο ({mark} {target}€) | φθηνότερο σύνολο {cheapest}€ | καλύτερη επιλογή ⭐ {best}€ "
                              f"(αναχ. {out[0]['depart']} {','.join(out[0]['airlines'])}"
                              + (f" / επιστρ. {ret[0]['depart']} {','.join(ret[0]['airlines'])}" if ret else "") + ")")
                except Exception as e:
                    snap["error"] = f"Πτήσεις: {e}"
                    print(f"  ⚠️ Σφάλμα πτήσεων: {e}")
                    traceback.print_exc()

                try:
                    listings = fetch_booking(trip, pw)
                    snap["booking"] = listings[:12]
                    if listings:
                        snap["booking_min"] = listings[0]["total"]
                        hist.append([TODAY, tid, "booking_min", listings[0]["total"]])
                        print(f"  Booking: {len(listings)} εντός κανόνων, από {listings[0]['total']:.0f}€ "
                              f"({listings[0]['name'][:40]})")
                    else:
                        print("  Booking: κανένα αποτέλεσμα εντός κανόνων")
                except Exception as e:
                    snap["error"] = (snap.get("error", "") + f" | Booking: {e}").strip(" |")
                    print(f"  ⚠️ Σφάλμα Booking: {e}")
                    traceback.print_exc()

                fmin = snap.get("flight_min", float('inf'))
                bmin = snap.get("booking_min", float('inf'))
                total = fmin + bmin if fmin != float('inf') and bmin != float('inf') else float('inf')
                
                # Keep this snap if it's the cheapest, or if we don't have a best yet
                if total < best_total or best_snap is None:
                    if total < best_total:
                        best_total = total
                    snap["depart_str"] = pair["depart"]
                    snap["return_str"] = pair["return"]
                    snap["name"] = trip.get("name", tid)
                    snap["to"] = trip.get("to")
                    best_snap = snap
                    best_hist = hist
                
                time.sleep(2)

            if best_snap:
                snapshot[tid] = best_snap
                history_rows.extend(best_hist)

    append_history(history_rows)
    with open(os.path.join(SNAPSHOT_DIR, f"{TODAY}.json"), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
        
    import shutil
    public_dir = os.path.join(BASE, "dashboard", "public")
    os.makedirs(public_dir, exist_ok=True)
    with open(os.path.join(public_dir, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
    if os.path.exists(args.file):
        shutil.copy2(args.file, os.path.join(public_dir, "trips.json"))

    build_report(trips, snapshot, load_history())
    print(f"\n✅ Report: {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
