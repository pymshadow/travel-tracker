# AI Handover Document

This document is intended for future AI assistants to quickly understand the architecture, state, and rules of the **Travel Price Tracker** project.

## 1. Project Architecture

The project consists of two main parts:
1. **The Scraper (Backend):** `travel_tracker.py`
   - Uses Playwright to scrape live flight data and booking.com listings.
   - Reads configuration from `trips.json`.
   - Iterates over defined destinations and `date_pairs`.
   - For trips with a `surprise_pool`, it randomly selects one destination from the pool before processing.
   - Saves the cheapest result per destination as a JSON object into the `snapshots/` directory.

2. **The Dashboard (Frontend):** `/dashboard/`
   - A React (Vite) application styled with TailwindCSS.
   - Fetches `/trips.json` and `/snapshot.json` dynamically from the `public/` directory upon load.
   - Matches the data and renders the destination cards.
   - Contains a hardcoded `COST_OF_LIVING` dictionary in `App.jsx` which provides daily cost estimates (Low/Mid/High) for the supported cities.

## 2. Key Mechanisms

### Dynamic Date Scanning
Instead of scanning a single fixed date per trip, `travel_tracker.py` checks all `date_pairs` defined in `trips.json` for a specific trip. It calculates `total = flight_min + booking_min` for each date pair and only retains the date pair with the absolute lowest `total` cost.

### Surprise City Logic
In `trips.json`, there is a trip entry with ID `surprise-europe`. It contains a `surprise_pool` array. When `travel_tracker.py` runs, it randomly picks one dictionary from this pool and assigns its `to`, `city`, and `name` attributes to the trip before execution.

### Scoring Penalties
In `travel_tracker.py`, the `_score_leg` function calculates the quality of a flight based on price and hours.
- There is a `+40` EUR penalty for bad flight hours.
- For trips lasting **6 or more nights**, the hour restrictions are heavily relaxed (e.g., departure can be as late as 17:00, return as early as 08:00) before applying the penalty, because an extra night makes up for lost time.

## 3. Automation and Deployment
- **Hosting: GitHub Pages** at https://pymshadow.github.io/travel-tracker/ (migrated from Netlify on 2026-07-17 after the Netlify team ran out of credits). The repo was made public for this (GitHub Free requires public repos for Pages). Deployment method: push `dashboard/dist/` to the `gh-pages` branch via `peaceiris/actions-gh-pages@v4` with the default `GITHUB_TOKEN` — do NOT use `actions/configure-pages` with `enablement: true`, it fails (GITHUB_TOKEN cannot enable Pages).
- **GitHub Actions (`.github/workflows/scrape.yml`):** Runs daily at 08:00 UTC (10:00/11:00 AM Greece time).
  - Runs the Python scraper.
  - Builds the React app (Node 20, `npm ci`; Vite `base: '/travel-tracker/'`).
  - Commits the new JSON data, does `git pull --rebase` and pushes to GitHub.
  - Deploys `dashboard/dist/` to the `gh-pages` branch.
- **`.github/workflows/deploy-pages.yml`:** Builds + deploys on pushes touching `dashboard/**` (needed because pushes made with `GITHUB_TOKEN` by scrape.yml don't trigger other workflows) and via manual dispatch.
- **Netlify is no longer used.** The old Netlify token that was hardcoded in workflow history is revoked. A `NETLIFY_AUTH_TOKEN` repo secret may still exist — unused, safe to delete.
- **Security:** Never commit tokens; `.gitignore` blocks `.env` and `cookies.txt`. The repo is public — treat everything committed as world-readable.
- **Local Windows scheduled task** "Travel Price Tracker" is **Disabled** (was double-scraping alongside the Action). Re-enable with `Enable-ScheduledTask -TaskName "Travel Price Tracker"` only if the Action is turned off.

## 3b. History semantics
- `history.csv` rows are keyed by `hist_id`: equal to the trip id, except for surprise trips where it is `<trip_id>-<airport code>` (e.g. `surprise-europe-prg`) so price history is per-city. Snapshots carry `hist_id` for the report's sparklines. Rows written before 2026-07-17 under plain `surprise-europe` are legacy/mixed and ignored.
- Snapshot writes merge with the existing same-day file, so `--single <trip_id>` no longer wipes other trips' data.
- The report shows the dates of the *cheapest* date pair (stored in `depart_str`/`return_str`), not the last one scanned.

## 3c. Rollback
- Git: branch `backup-pre-fixes` / tag `backup-2026-07-17` (pushed to origin).
- Full folder zip (incl. untracked files): `D:\Travel_backup_20260717_0246.zip`.

## 4. Where to find things
- **Scraper Engine:** `travel_tracker.py`
- **Current Trip Config:** `trips.json`
- **UI Rendering:** `dashboard/src/App.jsx`
- **History Data:** `history.csv`
- **Deployment Config:** `.github/workflows/scrape.yml`
