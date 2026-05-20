import re
import os
import json
import smtplib
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- CONFIGURATION ---
WIKI_URL    = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
DATA_FILE   = "sp500_pulse_data.json"
HTML_FILE   = "SP500_Pulse_Dashboard.html"

EMAIL_SENDER   = os.environ.get("GMAIL_SENDER_EMAIL", "")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECEIVER = "avin.khurana18@gmail.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# Google News RSS — catches articles published on S&P's announcement day (1-13 days before effective date)
GNEWS_ADDITION_URL = (
    "https://news.google.com/rss/search?q=%22S%26P+500%22+"
    "%22will+join%22+OR+%22will+be+added%22+OR+%22joining+S%26P+500%22+"
    "OR+%22to+join+the+S%26P+500%22+OR+%22S%26P+500+addition%22+"
    "OR+%22added+to+S%26P+500%22+OR+%22added+to+the+S%26P+500%22"
    "&hl=en-US&gl=US&ceid=US:en"
)
GNEWS_REMOVAL_URL = (
    "https://news.google.com/rss/search?q=%22S%26P+500%22+"
    "%22will+be+removed%22+OR+%22leaving+the+S%26P+500%22+"
    "OR+%22dropped+from+S%26P%22+OR+%22removed+from+S%26P+500%22+"
    "OR+%22S%26P+500+removal%22"
    "&hl=en-US&gl=US&ceid=US:en"
)

DATE_FORMATS = ["%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"]

# Phrases that indicate speculation rather than an actual announcement
SPECULATION_MARKERS = [
    "prediction:", "predict", "before year-end", "could join", "might join",
    "may join", "could be added", "might be added", "will it join",
    "expected to join", "candidates", "next stock to join",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_date(text):
    text = re.sub(r"\s+", " ", text.strip())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_tickers(text):
    tickers = []
    # "(NYSE: VEEV)" or "(NasdaqGS: CASY)" — from marketscreener headlines
    tickers += re.findall(r"(?:NYSE|NasdaqGS|Nasdaq|AMEX|BATS)[:\s]+([A-Z]{1,5})\)", text)
    # bare "(VEEV)" parenthetical
    tickers += re.findall(r"\(([A-Z]{2,5})\)", text)
    # "LITE Surges", "COHR Joins", "VEEV added", etc.
    tickers += re.findall(
        r"\b([A-Z]{2,5})\b\s+(?:Surges|Jumps|Drops|Climbs|Rises|Falls|"
        r"joins|Joins|added|Added|removed|Removed|Stock|Shares)", text
    )
    noise = {"SP", "CEO", "IPO", "ETF", "AND", "THE", "FOR", "ARE",
             "NOT", "NEW", "TOP", "KEY", "ALL", "NOW", "OUT", "INC", "AI"}
    return list({t for t in tickers if t not in noise and len(t) >= 2})


def _is_speculation(title):
    tl = title.lower()
    return any(m in tl for m in SPECULATION_MARKERS)


def _action_from_title(title, fallback):
    tl = title.lower()
    if any(w in tl for w in ["removed", "dropping", "dropped", "leaving", "exits", "removal"]):
        return "REMOVAL"
    if any(w in tl for w in ["added", "joins", "joining", "addition", "will join", "added to"]):
        return "ADDITION"
    return fallback


# ── data sources ─────────────────────────────────────────────────────────────

def fetch_google_news(days_back=30):
    """
    Tier-1: Announcement-day detection via Google News RSS.
    Articles appear 1–13 days before the S&P effective date — the tradeable window.
    Status = ANNOUNCED (pre-effective signal).
    """
    print("[*] Scanning Google News for S&P 500 pre-announcement articles...")
    cutoff = datetime.now() - timedelta(days=days_back)
    entries = []
    seen = set()

    for url, default_action in [(GNEWS_ADDITION_URL, "ADDITION"), (GNEWS_REMOVAL_URL, "REMOVAL")]:
        feed = feedparser.parse(url)
        for e in feed.entries:
            pub = e.get("published_parsed")
            if not pub:
                continue
            pub_dt = datetime(*pub[:6])
            if pub_dt < cutoff or e.link in seen:
                continue
            if _is_speculation(e.title):
                continue
            seen.add(e.link)

            tickers = _extract_tickers(e.title + " " + e.get("summary", ""))
            action  = _action_from_title(e.title, default_action)

            entries.append({
                "title":          e.title,
                "action":         action,
                "status":         "ANNOUNCED",
                "tickers":        tickers,
                "date_announced": pub_dt.strftime("%Y-%m-%d %H:%M"),
                "effective_date": "TBC — see article",
                "link":           e.link,
                "summary":        e.get("summary", "")[:250],
                "source":         "google_news",
            })

    print(f"[+] Google News: {len(entries)} pre-announcement articles found.")
    return entries


def fetch_wikipedia_confirmed(days_back=90):
    """
    Tier-2: Confirmed changes from Wikipedia (post-effective, structured).
    Status = CONFIRMED.
    """
    print("[*] Fetching confirmed S&P 500 changes from Wikipedia...")
    r = requests.get(WIKI_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    changes_table = soup.find("table", {"id": "changes"})
    if not changes_table:
        print("[!] Wikipedia changes table not found.")
        return []

    cutoff  = datetime.now() - timedelta(days=days_back)
    entries = []

    for row in changes_table.find_all("tr")[2:]:   # skip two header rows
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        effective_text = cells[0].get_text(strip=True)
        effective_dt   = _parse_date(effective_text)
        if not effective_dt or effective_dt < cutoff:
            continue

        added_ticker   = cells[1].get_text(strip=True)
        added_name     = cells[2].get_text(strip=True)
        removed_ticker = cells[3].get_text(strip=True)
        removed_name   = cells[4].get_text(strip=True)
        reason         = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        date_str       = effective_dt.strftime("%Y-%m-%d %H:%M")
        link           = WIKI_URL + "#changes"

        if added_ticker:
            entries.append({
                "title":          f"{added_ticker} ({added_name}) added to S&P 500",
                "action":         "ADDITION",
                "status":         "CONFIRMED",
                "tickers":        [added_ticker],
                "date_announced": date_str,
                "effective_date": effective_text,
                "link":           link,
                "summary":        reason[:250],
                "source":         "wikipedia",
            })
        if removed_ticker:
            entries.append({
                "title":          f"{removed_ticker} ({removed_name}) removed from S&P 500",
                "action":         "REMOVAL",
                "status":         "CONFIRMED",
                "tickers":        [removed_ticker],
                "date_announced": date_str,
                "effective_date": effective_text,
                "link":           link,
                "summary":        reason[:250],
                "source":         "wikipedia",
            })

    print(f"[+] Wikipedia: {len(entries)} confirmed changes found.")
    return entries


# ── persistence ───────────────────────────────────────────────────────────────

def save_data(new_entries):
    existing = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            existing = json.load(f)

    existing_links = {e["link"] for e in existing}
    added = 0
    for entry in new_entries:
        if entry["link"] not in existing_links:
            existing.insert(0, entry)
            existing_links.add(entry["link"])
            added += 1

    with open(DATA_FILE, "w") as f:
        json.dump(existing, f, indent=4)

    print(f"[+] {added} new records saved to {DATA_FILE}.")
    return existing


# ── dashboard ─────────────────────────────────────────────────────────────────

def generate_html(data, news_window=30, confirmed_window=90):
    now    = datetime.now()
    cutoff = now - timedelta(days=confirmed_window)

    recent = [
        e for e in data
        if datetime.strptime(e["date_announced"], "%Y-%m-%d %H:%M") >= cutoff
    ]
    # ANNOUNCED cards at top, then CONFIRMED
    recent.sort(key=lambda e: (0 if e.get("status") == "ANNOUNCED" else 1,
                               e["date_announced"]), reverse=False)
    recent.sort(key=lambda e: e["date_announced"], reverse=True)
    # Re-sort: ANNOUNCED first within same day
    recent.sort(key=lambda e: (e["date_announced"], e.get("status") != "ANNOUNCED"), reverse=True)

    announced_count = sum(1 for e in recent if e.get("status") == "ANNOUNCED")
    confirmed_count = sum(1 for e in recent if e.get("status") == "CONFIRMED")

    html_template = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>S&P 500 Pulse Monitor</title>
    <style>
        body { font-family: 'Inter', -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 40px; }
        .container { max-width: 960px; margin: 0 auto; }
        header { border-bottom: 1px solid #30363d; padding-bottom: 20px; margin-bottom: 32px; }
        h1 { margin: 0; font-size: 1.8rem; color: #58a6ff; font-weight: 700; letter-spacing: -0.5px; }
        .stats { margin-top: 10px; font-size: 0.85rem; color: #8b949e; display: flex; gap: 24px; flex-wrap: wrap; }
        .stat-pill { background: #161b22; border: 1px solid #30363d; border-radius: 20px; padding: 3px 12px; }

        .section-label { font-size: 0.7rem; font-weight: 800; text-transform: uppercase;
                         letter-spacing: 1.5px; color: #8b949e; margin: 28px 0 12px; }

        .alert-card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
                      padding: 22px 24px; margin-bottom: 16px; transition: all 0.2s; }
        .alert-card:hover { border-color: #58a6ff; transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
        .alert-card.announced { border-left: 3px solid #d29922; }

        .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
        .badge { padding: 4px 12px; border-radius: 20px; font-size: 0.68rem; font-weight: 800; text-transform: uppercase; }
        .badge-ADDITION { background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); }
        .badge-REMOVAL  { background: rgba(248,81,73,0.15);  color: #f85149; border: 1px solid rgba(248,81,73,0.3); }
        .status-badge { padding: 3px 10px; border-radius: 20px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; }
        .status-ANNOUNCED { background: rgba(210,153,34,0.15); color: #d29922; border: 1px solid rgba(210,153,34,0.3); }
        .status-CONFIRMED { background: rgba(88,166,255,0.12); color: #58a6ff; border: 1px solid rgba(88,166,255,0.25); }

        .ticker-group { display: flex; gap: 6px; margin-left: auto; flex-wrap: wrap; }
        .ticker { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #fff;
                  background: #21262d; padding: 3px 10px; border-radius: 6px; border: 1px solid #30363d; font-size: 0.85rem; }

        .title { font-size: 1.05rem; font-weight: 600; display: block; text-decoration: none;
                 color: #adbac7; margin: 12px 0; line-height: 1.45; }
        .title:hover { color: #58a6ff; }

        .effective-box { background: rgba(35,134,54,0.07); border: 1px solid rgba(35,134,54,0.2);
                         border-radius: 8px; padding: 10px 14px; margin: 12px 0; }
        .effective-box.pending { background: rgba(210,153,34,0.07); border-color: rgba(210,153,34,0.2); }
        .effective-label { font-size: 0.72rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
        .effective-date  { font-size: 0.95rem; color: #3fb950; font-weight: 600; margin-top: 3px; }
        .effective-date.pending { color: #d29922; }

        .summary { font-size: 0.82rem; color: #8b949e; margin: 10px 0; line-height: 1.5; }
        .footer-info { display: flex; justify-content: space-between; font-size: 0.78rem;
                       color: #8b949e; border-top: 1px solid #30363d; padding-top: 12px; margin-top: 12px; flex-wrap: wrap; gap: 8px; }
        .source-tag { font-size: 0.68rem; background: #21262d; border-radius: 10px; padding: 2px 8px; color: #8b949e; }

        .empty { text-align: center; padding: 80px; border: 2px dashed #30363d; border-radius: 12px; color: #8b949e; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>S&amp;P 500 PULSE MONITOR</h1>
        <div class="stats">
            <span class="stat-pill">&#x26A1; {announced} pre-announcement</span>
            <span class="stat-pill">&#x2713; {confirmed} confirmed (90d)</span>
            <span>Updated: {updated}</span>
        </div>
    </header>
    <div id="alerts">
        {alerts}
    </div>
</div>
</body>
</html>
"""

    if not recent:
        alerts_html = '<div class="empty">No S&P 500 alerts in the last 90 days.</div>'
    else:
        alerts_html = ""
        prev_status = None
        for entry in recent:
            status = entry.get("status", "CONFIRMED")
            if status != prev_status:
                label = "Early Warning — Announced, Not Yet Effective" if status == "ANNOUNCED" else "Confirmed Changes"
                alerts_html += f'<div class="section-label">{label}</div>\n'
                prev_status = status

            action_class = f"badge-{entry['action']}"
            status_class  = f"status-{status}"
            tickers_html  = "".join(f'<span class="ticker">{t}</span>' for t in entry["tickers"]) \
                            if entry["tickers"] else '<span style="color:#8b949e;font-size:0.8rem">ticker TBC</span>'
            is_pending   = "TBC" in entry["effective_date"]
            eff_class    = "pending" if is_pending else ""
            eff_dt_class = "pending" if is_pending else ""
            source_label = "Google News" if entry.get("source") == "google_news" else "Wikipedia"
            card_class   = "alert-card announced" if status == "ANNOUNCED" else "alert-card"
            summary_html = f'<div class="summary">{entry["summary"]}</div>' if entry.get("summary") else ""

            alerts_html += f"""
<div class="{card_class}">
    <div class="card-header">
        <span class="badge {action_class}">{entry['action']}</span>
        <span class="status-badge {status_class}">{status}</span>
        <div class="ticker-group">{tickers_html}</div>
    </div>
    <a href="{entry['link']}" class="title" target="_blank">{entry['title']}</a>
    {summary_html}
    <div class="effective-box {eff_class}">
        <div class="effective-label">Effective Date</div>
        <div class="effective-date {eff_dt_class}">{entry['effective_date']}</div>
    </div>
    <div class="footer-info">
        <span>Detected: {entry['date_announced']}</span>
        <span class="source-tag">{source_label}</span>
        <a href="{entry['link']}" style="color:#58a6ff;text-decoration:none;">Read Article →</a>
    </div>
</div>
"""

    final = (html_template
             .replace("{announced}", str(announced_count))
             .replace("{confirmed}", str(confirmed_count))
             .replace("{updated}",   now.strftime("%Y-%m-%d %H:%M"))
             .replace("{alerts}",    alerts_html))
    with open(HTML_FILE, "w") as f:
        f.write(final)
    print(f"[+] Dashboard written to {HTML_FILE}.")


# ── email ─────────────────────────────────────────────────────────────────────

def send_email_report():
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("[!] Email skipped: GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD not set.")
        return

    with open(HTML_FILE, "r") as f:
        html_body = f.read()

    now = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"S&P 500 Pulse Dashboard — {now}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html"))

    print(f"[*] Sending dashboard email to {EMAIL_RECEIVER}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print("[+] Email sent successfully.")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    news_entries      = fetch_google_news(days_back=30)
    confirmed_entries = fetch_wikipedia_confirmed(days_back=90)
    all_new           = news_entries + confirmed_entries
    all_data          = save_data(all_new)
    generate_html(all_data)
    send_email_report()
    print("[!] Pulse Check Complete.")
