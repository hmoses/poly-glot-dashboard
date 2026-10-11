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
assert 'download_events = first_time_dl + redownloads' in (ROOT / "fetch_analytics.py").read_text()

scripts = re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", html, re.IGNORECASE)
assert len(scripts) == 1, "Expected one inline application script"
with tempfile.NamedTemporaryFile(mode="w", suffix=".js", encoding="utf-8") as source:
    source.write(scripts[0])
    source.flush()
    subprocess.run(["node", "--check", source.name], check=True)

print(f"Dashboard checks passed: {taps.get('Get',0)} Get taps; "
      f"{summary['total_downloads']} downloads; {installs['total_installs']} reported installs; "
      f"{summary['total_updates']} updates.")
