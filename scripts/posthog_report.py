"""PostHog opt-in Poly-Glot iOS/macOS events, via documented HogQL API.

Uses a private personal read API key ONLY in GitHub Actions. Never publish this key.
Missing credentials and query errors mean unavailable data, not zero events.
"""
import json
import os
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
import requests

EVENTS = ("trial_started", "first_send", "provider_opened", "app_returned",
          "compare_used", "daily_free_send_used")
PROVIDERS = ("chatgpt", "claude", "gemini", "grok", "copilot", "perplexity",
             "mistral", "huggingchat", "duckduckgo")
OUT = Path("data/posthog.json")

def refresh(start_date, end_date, pacific_tz):
    key = os.getenv("POSTHOG_API_KEY", "").strip()
    project = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    host = os.getenv("POSTHOG_API_HOST", "https://us.posthog.com").rstrip("/")
    now = datetime.now(timezone.utc).isoformat()
    base = {"updated": now, "date_range_start": start_date, "date_range_end": end_date}
    if not key or not project:
        OUT.write_text(json.dumps({**base, "status": "not_configured", "events": {},
                                   "providers": {}, "platform_split": {}}, indent=2), encoding="utf8")
        print("PostHog personal read API key or project missing; opt-in metrics marked unavailable.")
        return
    if host not in ("https://us.posthog.com", "https://eu.posthog.com"):
        raise ValueError("Unrecognized PostHog query API host")
    try:
        from datetime import date as calendar_date
        start = datetime.combine(calendar_date.fromisoformat(start_date), time.min, tzinfo=pacific_tz).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        stop = datetime.combine(calendar_date.fromisoformat(end_date) + timedelta(days=1), time.min, tzinfo=pacific_tz).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        names = ", ".join("'" + name + "'" for name in EVENTS)
        where = ("timestamp >= toDateTime('" + start + "', 'UTC') AND "
                 "timestamp < toDateTime('" + stop + "', 'UTC') AND "
                 "event IN (" + names + ") AND properties.platform IN ('ios', 'macos')")
        def hogql(sql):
            r = requests.post(
                f"{host}/api/projects/{project}/query/",
                headers={"Authorization": "Bearer " + key},
                json={"query": {"kind": "HogQLQuery", "query": sql}}, timeout=45)
            r.raise_for_status()
            payload = r.json()
            if payload.get("error") or not isinstance(payload.get("results"), list):
                raise RuntimeError("PostHog returned no verified query results")
            return payload["results"]
        counts = {}
        unique = {}
        for row in hogql("SELECT event, count(), uniqExact(distinct_id) FROM events WHERE " + where + " GROUP BY event"):
            if len(row) >= 3 and row[0] in EVENTS:
                counts[row[0]] = int(row[1])
                unique[row[0]] = int(row[2])
        providers = {}
        for row in hogql("SELECT properties.provider, count() FROM events WHERE " + where +
                         " AND event = 'provider_opened' GROUP BY properties.provider"):
            if len(row) >= 2 and str(row[0]).lower() in PROVIDERS:
                providers[str(row[0]).lower()] = int(row[1])
        platform_split = {"ios": 0, "macos": 0}
        for row in hogql("SELECT properties.platform, count() FROM events WHERE " + where +
                         " GROUP BY properties.platform"):
            if len(row) >= 2 and row[0] in platform_split:
                platform_split[row[0]] = int(row[1])
        output = {**base, "status": "connected",
                  "events": {name: counts.get(name, 0) for name in EVENTS},
                  "unique_installs": unique, "providers": providers,
                  "platform_split": platform_split}
    except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as err:
        print("PostHog event query not verified: " + type(err).__name__)
        output = {**base, "status": "unavailable", "events": {}, "providers": {},
                  "platform_split": {}}
    OUT.write_text(json.dumps(output, indent=2), encoding="utf8")
    print("PostHog availability status: " + output["status"])
