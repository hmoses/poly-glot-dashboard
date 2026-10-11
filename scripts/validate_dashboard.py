#!/usr/bin/env python3
"""Validate Poly-Glot dashboard semantics and existing Apple report aggregates."""
import json
import py_compile
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "data/analytics.json").read_text(encoding="utf-8"))
html = (ROOT / "index.html").read_text(encoding="utf-8")
py_compile.compile(str(ROOT / "fetch_analytics.py"), doraise=True)
summary = data["summary"]
taps = data.get("taps_by_engagement_type", {})
downloads = data.get("downloads_by_type", {})
installs = data.get("installs", {})
install_types = installs.get("installs_by_type", {})

def tally(d):
    return sum(int(v) for v in d.values())

assert tally(taps) == summary["total_taps"], "Apple engagement-action subtotal mismatch"
assert tally(downloads) == summary["total_downloads"], "Apple download subtotal mismatch"
# Download attribution must count only first-time and redownload rows, not updates.
expected_download_sources = {}
for row in data.get("raw_downloads", []):
    if row.get("Download Type") not in ("First-time download", "Redownload"):
        continue
    source = row.get("Source Type") or "Unavailable"
    expected_download_sources[source] = expected_download_sources.get(source, 0) + int(row.get("Counts", "0") or 0)
assert sum(expected_download_sources.values()) == summary["total_downloads"], "Raw download attribution must reconcile with App Downloads totals"
if data.get("downloads_by_source"):
    assert data["downloads_by_source"] == expected_download_sources, "Download source aggregation differs from Apple raw download events"

assert tally(install_types) == installs["total_installs"], "Opt-in install subtotal mismatch"
assert tally(data.get("taps_by_source", {})) == summary["total_taps"], "Tap source totals mismatch"
for event, count in taps.items():
    assert tally(data.get("taps_by_engagement_source", {}).get(event, {})) == count, "Tap event/source subtotal mismatch: " + event
assert all(str(row.get("App Apple Identifier", "6804499285")) in ("", "6804499285")
           for row in data.get("raw_downloads", [])), "Other app identifiers in download data"

for name in ["reconcile-get", "reconcile-downloads", "reconcile-installs",
             "reconcile-report-dates", "reconcile-report-health"]:
    assert 'id="' + name + '"' in html, "Missing reconciliation field: " + name
assert "reportedInstalls=(data.installs||{}).total_installs;" in html
assert "Number.isFinite(inst.total_installs)?inst.total_installs.toLocaleString()" in html
assert "var realDl=funnel.user_installs" not in html, "Legacy downloads erroneously presented as installs"
assert "var appRefDownloads=reportedDownloadsBySource?.['App referrer'];" in html, "App Referrer Downloads card must use Apple Downloads report"
assert "var appRefOptInInstalls=" in html, "Opt-in install attribution should be a separate metric"
assert "App-referrer tap attribution will populate after the next analytics refresh" not in html, "Do not promise nonexistent source attribution"
assert 'id="inst-event-timeline"' in html and "fullDates.forEach" in html, "Install chart must render through report cutoff"
assert "No reported event row" in html and "this does not establish later daily coverage" in html, "Missing install rows must not be depicted as confirmed zeros"

assert 'download_events = first_time_dl + redownloads' in (ROOT / "fetch_analytics.py").read_text()
fetcher = (ROOT / "fetch_analytics.py").read_text()
assert '"filter[granularity]": "DAILY"' in fetcher, "Do not mix weekly/monthly and daily report instances"
assert "ASC_REPORT_END_DATE" in fetcher and "timedelta(days=1)" in fetcher, "Use last complete Pacific day"
assert "date as calendar_date" in fetcher and "calendar_date.fromisoformat" in fetcher, "Avoid collision with local date variable in report loops"
assert 'dedupe_latest(filter_app_rows(merge_report_rows(req_ids, "Web Preview Engagement")))' in fetcher, "Filter all Web Preview rows"
assert 'dedupe_latest(filter_app_rows(merge_report_rows(req_ids, "App Store Purchases Standard")))' in fetcher, "Filter all Purchase rows"
assert 'period_after' in fetcher and '"before": period_before' in fetcher, "PostHog must use the reporting range"
assert 'start_date = REPORT_START' in fetcher and 'end_date = REPORT_END' in fetcher, "TikTok API must match the range"
assert "hero-reporting-period" in html and "hero-data-coverage" in html, "Display as-of reporting range and coverage caveat"
assert summary["date_range_start"] == "2026-09-18", "Unexpected reporting start"
assert summary["date_range_end"] >= summary["date_range_start"], "Invalid as-of reporting range"
assert '"limit": 200' in fetcher and 'next_url = instances.get' in fetcher, "Apple report pagination must be followed"
assert 'Unexpected Apple analytics granularity' in fetcher, "Reject non-daily aggregates"


scripts = re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", html, re.IGNORECASE)
assert len(scripts) == 1, "Expected one inline application script"
with tempfile.NamedTemporaryFile(mode="w", suffix=".js", encoding="utf-8") as source:
    source.write(scripts[0])
    source.flush()
    subprocess.run(["node", "--check", source.name], check=True)

print(f"Dashboard checks passed: {taps.get('Get',0)} Get taps; "
      f"{summary['total_downloads']} downloads; {installs['total_installs']} reported installs; "
      f"{summary['total_updates']} updates.")
