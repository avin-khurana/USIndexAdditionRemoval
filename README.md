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

Running the script produces two files and sends an email:

| File | Description |
|---|---|
| `SP500_Pulse_Dashboard.html` | Visual dashboard — open in any browser |
| `sp500_pulse_data.json` | Raw structured data (all alerts, deduped) |

After each run the dashboard is also **emailed as an inline HTML email** to `avin.khurana18@gmail.com` (requires credentials — see [Email setup](#email-setup) below).

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

## Email setup

The script emails the dashboard after every run using Gmail SMTP. No extra packages are needed — it uses Python's built-in `smtplib`.

### Credentials required

| Variable | Description |
|---|---|
| `GMAIL_SENDER_EMAIL` | Gmail address that sends the email |
| `GMAIL_APP_PASSWORD` | 16-character [App Password](https://myaccount.google.com/apppasswords) for that account (not the login password) |

> **Important:** Gmail requires an App Password, not your regular account password. Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2FA to be enabled).

### Running locally with email

```bash
export GMAIL_SENDER_EMAIL="sender@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
python sp500_pulse.py
```

If either variable is not set, the script skips the email and completes normally.

### GitHub Actions setup

The workflow already passes both secrets to the script. Add them once via the GitHub CLI:

```bash
gh secret set --repo avin-khurana/USIndexAdditionRemoval --env-file .env.secrets
```

Or set them manually: repo → **Settings → Secrets and variables → Actions → New repository secret**.

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

The repo includes `.github/workflows/sp500_pulse.yml` which runs automatically **every day at 8:00 AM US Eastern time** on GitHub's servers. Your Mac does not need to be on.

After each run:
- `sp500_pulse_data.json` and `SP500_Pulse_Dashboard.html` are committed back to the repo automatically
- A formatted job summary is written showing what changed

**Setup steps:**

1. Push this repo to GitHub
2. Go to repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save
3. Add `GMAIL_SENDER_EMAIL` and `GMAIL_APP_PASSWORD` as repository secrets (see [Email setup](#email-setup))
4. To trigger manually: repo → **Actions → S&P 500 Pulse Monitor → Run workflow**

**Mobile push notifications:**

Install the GitHub mobile app, then:
> Repo → **Watch → Custom → check Actions → Apply**

You'll receive a push notification after each run. Tapping it shows the summary table directly in the app.

### Option 2 — Mac cron job (local)

Runs on your Mac every day at 8 AM. Requires your Mac to be awake at that time.

Paste this into Terminal:

```bash
(crontab -l 2>/dev/null; \
 echo "# S&P 500 Pulse Monitor"; \
 echo "0 8 * * * cd \"/path/to/this/repo\" && /usr/bin/python3 sp500_pulse.py >> sp500_pulse.log 2>&1") \
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
├── .env.secrets                 # Local credentials file (gitignored — never committed)
├── .github/
│   └── workflows/
│       └── sp500_pulse.yml      # GitHub Actions daily schedule
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
