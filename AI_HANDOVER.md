# AI Handover Document

This document is intended for future AI assistants to quickly understand the architecture, state, rules, and **user preferences** of the **Travel Price Tracker** project. Last full update: **2026-07-17**.

## 0. The user, in brief

- Greek speaker (writes in Greeklish). Answer in Greek.
- Wants: 2 fixed cities + 1 daily "surprise" city, tracked daily, with strict quality rules (below).
- Budget target: **≤ 125€/person** for flights (round trip total). Shown as a target, not a hard filter.
- **Does NOT want:** promo videos or social-media uploads (pipeline was deleted 2026-07-17 — don't rebuild it or suggest it), the 6-nights hour relaxation (removed — don't reintroduce), morning returns ("προτιμώ να χάσω το ταξίδι παρά να γυρίσω πρωί").

## 1. Project Architecture

1. **The Scraper (Backend):** `travel_tracker.py`
   - **Flights:** live Google Flights page via Playwright headless Chromium (SOCS consent cookie on `.google.com` bypasses the EU consent wall; results parsed from `[aria-label*='euros']` elements). Fallback: static-HTML fetch via `primp` + `fast_flights.parser`. Two one-way searches per trip; prices are **totals for all passengers**, EUR.
   - **Hotels:** Booking.com via Playwright (`--disable-blink-features=AutomationControlled` + webdriver-undefined init script — plain HTTP gets bot-challenged with a tiny 202 page). Results parsed from the `script[data-capla-store-data="apollo"]` JSON blob; two searches merged: entire apartments (`privacy_type=3`) OR hotels with breakfast (`ht_id=204;mealplan=1`). Prices are **stay totals incl. taxes**.
   - Transit-distance fallback: Overpass API (2 mirrors) → stops cached in `stops_cache/`. City bounding boxes via Nominatim → `geocache.json`.
   - Outputs: `snapshots/<date>.json` (merged with same-day file), `history.csv`, `top_deals.json`, `report.html` (legacy standalone report), and copies of snapshot/trips/cost_of_living/top_deals into `dashboard/public/`.

2. **The Dashboard (Frontend):** `/dashboard/` — React (Vite, `base: '/travel-tracker/'`) + TailwindCSS.
   - Fetches `trips.json`, `snapshot.json`, `cost_of_living.json`, `top_deals.json` from `public/` (via `import.meta.env.BASE_URL`).
   - Per-trip cards: dates + 🌙 nights, cheapest/best flights, cheapest rule-compliant stay, total, daily cost of living (per-person values × adults, source-linked to Numbeo), top-3 tables with booking links.
   - **Red warning banner** when a trip has no rule-compliant flights in any date pair (tells the user "το ταξίδι δεν βγαίνει"; flight tables hidden).
   - **🏆 Top Προσφορές** section at the bottom (see 2d).

## 2. Key Mechanisms

### 2a. Dynamic Date Scanning
Each trip has `date_pairs` in `trips.json`. All pairs are scanned; only the pair with the lowest `flight_min + booking_min` is kept (its dates go to `depart_str`/`return_str`). Pairs missing either component score `inf` and can't win.

### 2b. Surprise City (`surprise-europe` trip)
- Pool in `trips.json` (`surprise_pool`). Each run draws a city that is **guaranteed different from the previous run's** (previous read from the latest `snapshots/*.json`).
- **Redraw on failure:** if the drawn city has no rule-compliant flights in ANY date pair, the next pool city is tried (shuffled order), until one works. While probing, Booking is skipped for flightless pairs to save time.
- History note: Budapest effectively never passes (direct ATH-BUD is Wizz Air only → excluded by the low-cost rule). User was offered a relaxation and hasn't asked for it.

### 2c. Flight rules (STRICT with an auto-relax fallback)
Hard filters at fetch time, ALL trips, regardless of duration:
- Direct flights only (`stops > 0` dropped).
- Outbound departure **≤ 13:00** (`RULES["out_max"]`); return departure **≥ 16:30** (`RULES["ret_min"]`). The old "6+ nights relaxation" was removed — don't reintroduce that specific one.
- **Auto-relax fallback (user request 2026-07-23):** if a leg finds NO flights under the strict times, that leg is re-fetched with relaxed limits `RULES["out_max_relaxed"]`="15:00" / `RULES["ret_min_relaxed"]`="14:00" (still cuts dawn/very-late flights). Relaxation is **per-leg** (only the empty leg loosens; the other stays strict). Flagged in the snapshot as `out_relaxed`/`ret_relaxed` and shown in the UI with an amber "εκτός κανόνα ωρών" badge + note in the leg header. Example: Budapest weekends have only 06:10 (dropped) and 16:05 (kept via relax) direct returns.
- Low-cost carriers (Ryanair/Wizz/easyJet/Volotea/Vueling/Pegasus/Transavia/Air Malta) excluded for trips of **4+ nights** only — so 2-night weekends (e.g. Budapest) DO allow Wizz/Ryanair.
`_score_leg` ranks survivors: price + 3€/h after 06:00 (outbound) or before 22:00 (return) + 20€/stop − 15€ Aegean/Olympic bonus. ⭐ = best score; the absolute cheapest is also tracked. `RULES` dict at the top of `travel_tracker.py` holds all weights incl. `max_flight_pp_eur: 125` (per-person target, display-only).

### 2d. Booking rules
≤ 5 km from centre · rating ≥ 8/10 · entire apartments OR hotels with breakfast · ≤ 800 m from metro/bus (Booking's own `publicTransportDistanceDescription` first, OSM stops fallback) · name blacklist: student/hostel/dorm/capsule.

### 2e. Top Deals (`update_top_deals()` in travel_tracker.py)
Keeps the best **complete** deal (flights + stay) per city in `top_deals.json` (root = master, copied to `dashboard/public/`). Replacement policy: cheaper total wins; entries older than 7 days get refreshed by newer data; entries older than 14 days are dropped. This is how good surprise-city deals survive the daily rotation. Rendered as the "🏆 Top Προσφορές" table.

### 2f. Cost of Living (`dashboard/public/cost_of_living.json`)
Per-person/day values (low/mid/high, **excluding accommodation**) derived from Numbeo prices (meal cheap/mid-range, transit ticket, coffee, beer) on 2026-07-17. UI multiplies by `adults` and links to the Numbeo city page. To add a city: add one JSON entry (key = airport code). To refresh: re-derive from Numbeo (`_meta.formula` documents the approach).

## 3. Automation and Deployment
- **Hosting: GitHub Pages** at https://pymshadow.github.io/travel-tracker/ (repo `pymshadow/travel-tracker`, **public**). Deploy = push `dashboard/dist/` to the `gh-pages` branch via `peaceiris/actions-gh-pages@v4` with the default `GITHUB_TOKEN`. Do NOT use `actions/configure-pages` with `enablement: true` — it fails (GITHUB_TOKEN cannot enable Pages).
- **`.github/workflows/scrape.yml`:** daily at 08:00 UTC (10:00/11:00 Greece). Scrapes → builds (Node 20, `npm ci`) → commits data files (`git pull --rebase` first) → deploys to `gh-pages`.
- **`.github/workflows/deploy-pages.yml`:** builds + deploys on pushes touching `dashboard/**` and via manual dispatch (needed because `GITHUB_TOKEN` pushes don't trigger other workflows).
- **Netlify is no longer used** (team ran out of credits, 2026-07-17). The leaked-then-revoked token saga is over; a stale `NETLIFY_AUTH_TOKEN` repo secret may exist — unused, safe to delete.
- **Security:** repo is public — everything committed is world-readable. `.gitignore` blocks `.env`, `cookies.txt`, `videos/`, `__pycache__/`. Never commit tokens.
- **Local Windows scheduled task** "Travel Price Tracker" is **Disabled** (the Action replaced it). Re-enable only if the Action is turned off.
- Scraping runs on GitHub datacenter IPs — if Google/Booking start bot-blocking there (empty results in Action logs but fine locally), consider a self-hosted runner on the user's PC.

## 3b. History semantics
- `history.csv` rows are keyed by `hist_id`: the trip id, except surprise trips → `<trip_id>-<airport code>` (e.g. `surprise-europe-prg`) so price history is per-city. Snapshots carry `hist_id`. Rows before 2026-07-17 under plain `surprise-europe` are legacy/mixed — ignore.
- Snapshot writes **merge** with the existing same-day file, so `--single <trip_id>` doesn't wipe other trips.
- CLI: `python travel_tracker.py [--single <trip_id>] [--file <trips.json>]`.

## 3c. Rollback
- Git: branch `backup-pre-fixes` / tag `backup-2026-07-17` (pushed to origin).
- Full folder zip (incl. files now deleted, e.g. the video pipeline): `D:\Travel_backup_20260717_0246.zip`.

## 4. Where to find things
- **Scraper Engine + all rules:** `travel_tracker.py` (`RULES` dict at top)
- **Trip Config:** `trips.json`
- **UI:** `dashboard/src/App.jsx` · **Vite config (base path):** `dashboard/vite.config.js`
- **Data:** `history.csv`, `snapshots/`, `top_deals.json`, `dashboard/public/*.json`
- **CI/CD:** `.github/workflows/scrape.yml`, `.github/workflows/deploy-pages.yml`
- **Caches (committed, speed up CI):** `geocache.json`, `stops_cache/`

## 4b. Incident log
- **2026-07-18:** Daily Action failed at the "Commit new snapshot" step (`git pull --rebase origin main` conflicted because other sessions had pushed commits touching the same auto-generated files). Scrape + build had succeeded, but the failed commit step skipped the deploy, so the site kept showing the previous day's data (surprise city stuck on Berlin — it was NOT a surprise-logic bug; the redraw/exclusion works and correctly picks a new city daily). Fix: the commit step now does `git pull --no-rebase -X ours --no-edit origin main` (fresh scrape always wins conflicts on generated files) inside a 5× retry loop. If the daily run ever fails again, recover by running `python travel_tracker.py` locally and pushing the data files.

## 4c. Current trips (2026-07-23)
Only **Madrid** (Jan 2027, 5-6 nights, 3 date_pairs) and **Budapest** (Nov 2026, 2-night Fri-Sun weekends, 4 date_pairs). Vienna + the surprise-europe pool were removed at the user's request. Budapest's cheapest weekend is Nov 6-8 (~246€ total for 2). If re-adding a surprise trip, the pool logic (2b) still exists in code.

## 4d. Deploy gotcha (learned 2026-07-23)
A **merge commit** pushed to main does NOT reliably trigger `deploy-pages.yml` (GitHub path-filter behaviour on merge commits), so the live site can lag behind main. Two reliable ways to force a deploy: (a) a normal non-merge commit touching `dashboard/**`, or (b) manual: `cd dashboard && npm run build`, copy `dist/*` to a temp dir, add a `.nojekyll`, `git init -b gh-pages`, commit, and `git push -f <repo-url> gh-pages`. Method (b) is what recovered the site on 07-23. The daily Action deploys fine on its own (non-merge commits).

## 5. Known fragilities (check here first when something breaks)
- Google Flights parsing depends on English `aria-label`s (`hl=en` is forced) and the phrase "From X euros".
- Booking parsing depends on the `data-capla-store-data="apollo"` script tag; the deprecated-but-working search hash fallback lives inside pyairbnb-era history — current code uses Playwright only.
- pyairbnb was removed from requirements (Airbnb era is over; Booking.com is the accommodation source).
- Overpass mirrors time out occasionally — harmless (Booking's own transit data covers most listings; failures only reduce the OSM fallback).
