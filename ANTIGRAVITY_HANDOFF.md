# Handoff — Daily Travel Tracker automation

**For:** Antigravity (or any agent picking this up)
**Written:** 2026-07-31
**Read `AI_HANDOVER.md` first** for the full project architecture. This file covers only the
**scheduled/automated pipeline**.

---

## ✅ Status: a 4-day outage was just fixed (2026-07-31)

The daily GitHub Action had **failed 4 days in a row** (27, 28, 29, 30 Jul 2026) at the
`Run Tracker` step, silently — the dashboard sat on 27 Jul prices the whole time. Root cause
and fix are below in case something similar recurs; no action needed unless you see failures
again in the Actions tab.

### Root cause

`main()`'s multi-party loop does `trip = dict(trip)` per (trip, party) — a **copy**. Every
`depart`/`return`/`adults` assignment landed on that copy, never on the original dicts inside
the outer `trips` list. The legacy `build_report(trips, ...)`, called at the very end with the
**original**, still-unmodified `trips`, then did `trip['depart']` — a flat `KeyError` on a key
those dicts never had (trips.json only carries `date_pairs`). Unhandled, it killed the whole
run *after* a full, successful scrape (~7.6 min), which is why it looked so confusing: every
city scraped fine, `🏆 Top προσφορές` even printed, then the process died before reaching
`git commit`.

### Fix applied (commit follows this file)

1. `build_report()` now derives `depart`/`return`/`adults`/`to` from `trip.get(...)` with a
   fallback to the `snap` (the actual best-pair result), instead of indexing `trip[...]` directly.
2. `update_top_deals()` and `build_report()` calls in `main()` are now wrapped in try/except —
   matching the pattern already used for `notify_best_deal()` — so a future bug in either
   (both are secondary: legacy standalone report + top-deals cache) can never again block the
   commit/deploy of the actually-important `snapshot.json`.

Verified locally: pre-fix reproduced the exact `KeyError: 'depart'` in `build_report`;
post-fix, a full run completes and prints `✅ Report: ...`. Fresh 2026-07-31 data for `couple`
was pushed along with the fix so the dashboard didn't have to wait for tomorrow's cron.

---

## 1. What runs automatically

| # | What | Where | When | Status |
|---|------|-------|------|--------|
| 1 | `Daily Travel Tracker` workflow (`.github/workflows/scrape.yml`) | GitHub Actions | 08:00 UTC ≈ 11:00 Athens | ✅ fixed 2026-07-31 |
| 2 | `Deploy Dashboard to GitHub Pages` | GitHub Actions | on push to `main` | ✅ |
| 3 | Windows task **`Travel Deal Notification`** → `D:\Travel\run_notify.bat` | this PC | 12:00 daily, `StartWhenAvailable` | ✅ Ready |
| 4 | Windows task **`Travel Price Tracker`** → `run_tracker.bat` | this PC | 09:00 | 🚫 **Disabled on purpose** — do not re-enable |

### The chain

```
11:00  GitHub Action scrapes → commits snapshot.json / history.csv / top_deals.json to main
11:05  push to main triggers the deploy workflow → gh-pages → GitHub Pages
12:00  local task runs notify_daily.py → fetches the PUBLISHED snapshot.json → Telegram
```

**Why the notifier is a separate local script:** the scrape runs in the cloud, where the
Telegram token does not and must not exist. `notify_daily.py` runs on the PC and only reads
the already-public snapshot, so the token never leaves the machine.

---

## 2. Files that matter for the automation

| File | Role |
|------|------|
| `travel_tracker.py` | the scraper. `notify_best_deal(snapshot, parties_run)` at ~line 912 sends Telegram at the end of **local** runs; `--no-notify` disables |
| `notify_daily.py` | local daily notifier. Fetches `https://pymshadow.github.io/travel-tracker/snapshot.json`, dedups via `.notify_state.json`, delegates message-building to `tt.notify_best_deal()`. `--force` bypasses dedup |
| `run_notify.bat` | what the scheduled task actually calls; appends to `notify.log` |
| `.notify_state.json` | `{"date": ..., "best": [total, "trip|party"]}` — one send per day. **gitignored** |
| `notify.log` | notifier output. **gitignored** |
| `trips.json` | trips + `party_configs`. `auto: true` → runs daily; `auto: false` → manual only |

---

## 3. Hard rules — do not break these

1. **The repo is PUBLIC.** Never commit tokens, cookies, `.env`, `.notify_state.json`, or `notify.log`.
2. **Never read, print, copy or commit the Telegram token.** It lives in
   `%USERPROFILE%\.claude\notify.config.json`. Always call the wrapper:
   ```python
   import sys; sys.path.insert(0, r"D:\claude\notify")
   from notify import notify
   notify("text", title="Title", source="travel-tracker", url=DASHBOARD_URL)
   ```
3. **Never send anything to Slack.** The user explicitly refused Slack.
4. **Only the `couple` party runs automatically.** `family` and `six` are `auto: false` and must be
   run **only when the user explicitly asks**: `python travel_tracker.py --party family`.
   A full 3-party scan = 108 Booking page loads, ~35–45 min, and reliably triggers a rate-limit.
5. **Don't re-enable the local `Travel Price Tracker` task.** The cloud Action owns the scraping.
6. **A merge commit to `main` does not reliably trigger the deploy workflow.** If the site lags
   after a merge, deploy `gh-pages` manually (procedure in `AI_HANDOVER.md` §4d).

---

## 4. If the Action fails again

`gh` is not installed on this PC. To read a failed run's log, either install `gh`, or open
https://github.com/pymshadow/travel-tracker/actions in a browser — the REST log-download
endpoint returns 403 without an admin token even on a public repo, so the API can't fetch it
headlessly.

Reproduce locally first — a local run is exactly what the Action does, same OS-independent
Python code:

```bash
python travel_tracker.py --single budapest-nov --no-notify
```

Note the step duration in the Actions UI: if it dies in a few seconds, look for a startup/import
error; if it dies after several minutes (a full scrape's worth), suspect an unhandled exception
in code that runs *after* scraping — `update_top_deals()` / `build_report()` — same shape as
the bug above. Both are now wrapped in try/except, so as of this fix a bug there prints a
warning and moves on instead of killing the run — but if a **new** unguarded call gets added
after them in `main()` later, the same failure mode can recur there instead.

After confirming a fix:

1. Confirm a green run, and that the committed `snapshot.json` has `scanned` = today.
2. Confirm the site updated: https://pymshadow.github.io/travel-tracker/
3. Test the notifier without waiting for 12:00:
   ```bash
   python notify_daily.py --force
   ```

---

## 5. Useful commands

```bash
python travel_tracker.py                      # couple only (what the Action runs)
```
```bash
python travel_tracker.py --party family        # manual — ONLY when the user asks
```
```bash
python notify_daily.py --force                 # re-send today's Telegram
```
```powershell
Get-ScheduledTask -TaskName "Travel Deal Notification" | Get-ScheduledTaskInfo
```
```powershell
Start-ScheduledTask -TaskName "Travel Deal Notification"
```

---

## 6. Notes about the user

- Greek speaker, writes in Greeklish. **Reply in Greek.**
- Wants to be told plainly when something is broken — do not paper over a failure with
  stale data. The rate-limit detection exists precisely because silent empty results had
  been recorded as if they were real.
- Runs a VPN. A Booking block hits the VPN exit IP, not the home line; switching VPN server
  clears it instantly.
- Other AI sessions also push to this repo. Always `git fetch` before assuming repo state.
