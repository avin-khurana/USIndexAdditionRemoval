# S&P 500 Pulse Monitor

Tracks S&P 500 index additions and removals — both **pre-announcement signals** (before the effective date) and **confirmed changes** — and generates a local HTML dashboard.

---

## How it works

S&P Global announces index changes 1–13 days before they take effect. That window is when institutional money moves, driving price action in the added/removed stocks. This tool catches those announcements as early as possible.

### Two-tier detection

| Tier | Source | Status badge | Lead time |
|---|---|---|---|
| **Early warning** | Google News RSS | `ANNOUNCED` (amber) | 1–13 days before effective date |
| **Confirmed** | Wikipedia changes table | `CONFIRMED` (blue) | On/after effective date |

**Why not S&P Global's own RSS feed?**  
`spglobal.com` returns `403 Forbidden` to all automated requests (Cloudflare WAF). Google News picks up the press releases within hours of publication, giving equivalent early-warning coverage.

---

## Output

Running the script produces two files:

| File | Description |
|---|---|
| `SP500_Pulse_Dashboard.html` | Visual dashboard — open in any browser |
| `sp500_pulse_data.json` | Raw structured data (all alerts, deduped) |

The dashboard shows:
- **ANNOUNCED** cards (amber left border) — changes not yet effective, the tradeable window
- **CONFIRMED** cards — changes already in effect, sourced from Wikipedia
- Ticker symbols, effective dates, and links to source articles

---

## Requirements

- Python 3.8+
- Install dependencies:

```bash
pip install -r requirements.txt
```

Dependencies: `feedparser`, `requests`, `beautifulsoup4`

---

## Running manually

```bash
python sp500_pulse.py
```

Then open `SP500_Pulse_Dashboard.html` in your browser.

The script fetches:
- Google News (last 30 days) for pre-announcement signals
- Wikipedia (last 90 days) for confirmed changes

---

## Automated scheduling

### Option 1 — GitHub Actions (recommended)

The repo includes `.github/workflows/sp500_pulse.yml` which runs automatically every **Monday at 8:00 AM US Eastern time** on GitHub's servers. Your Mac does not need to be on.

After each run:
- `sp500_pulse_data.json` and `SP500_Pulse_Dashboard.html` are committed back to the repo automatically
- A formatted job summary is written showing what changed that week

**Setup steps:**

1. Push this repo to GitHub
2. Go to repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save
3. To trigger manually: repo → **Actions → S&P 500 Pulse Monitor → Run workflow**

**Mobile push notifications:**

Install the GitHub mobile app, then:
> Repo → **Watch → Custom → check Actions → Apply**

You'll receive a push notification after each run. Tapping it shows the weekly summary table directly in the app.

### Option 2 — Mac cron job (local)

Runs on your Mac every Monday at 8 AM. Requires your Mac to be awake at that time.

Paste this into Terminal:

```bash
(crontab -l 2>/dev/null; \
 echo "# S&P 500 Pulse Monitor"; \
 echo "0 8 * * 1 cd \"/path/to/this/repo\" && /usr/bin/python3 sp500_pulse.py >> sp500_pulse.log 2>&1") \
| crontab -
```

Replace `/path/to/this/repo` with the actual folder path. Check logs with:

```bash
tail -f sp500_pulse.log
```

---

## Project structure

```
├── sp500_pulse.py               # Main script
├── sp500_pulse_data.json        # Persisted alert history
├── SP500_Pulse_Dashboard.html   # Generated dashboard (open in browser)
├── requirements.txt             # Python dependencies
├── .github/
│   └── workflows/
│       └── sp500_pulse.yml      # GitHub Actions weekly schedule
└── README.md
```

---

## Data sources

| Source | URL | Used for |
|---|---|---|
| Google News RSS | `news.google.com/rss` | Pre-announcement detection |
| Wikipedia | List of S&P 500 companies | Confirmed changes with structured dates |

---

## Limitations

- **Ticker extraction from news headlines is best-effort.** When an article only names the company in prose (e.g., "Casey's General Stores Joining S&P 500"), the ticker shows as "TBC" — click the article link to confirm.
- **Google News results vary** — occasionally a speculative article ("Prediction: this stock will join…") passes the filter. The `ANNOUNCED` status means a news source reported it, not that S&P has officially confirmed it.
- **Wikipedia lags by hours to days** after the official S&P press release.
