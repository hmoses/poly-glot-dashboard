#!/usr/bin/env python3
"""
Fetch Poly-Glot AI analytics from App Store Connect API.
Outputs data/analytics.json for the GitHub Pages dashboard.
Uses TWO report requests: historical (one-time) + ongoing (rolling current).
"""

import jwt, time, requests, gzip, io, csv, json, os, sys
from datetime import datetime, timezone
from collections import defaultdict

APP_ID = os.environ.get("ASC_APP_ID", "6804499285")
KEY_ID = os.environ.get("ASC_KEY_ID", "3M53HUUZF3")
ISSUER_ID = os.environ.get("ASC_ISSUER_ID", "27273279-3df5-4fd7-b3f9-b6e882c1fc38")
PRIVATE_KEY = os.environ.get("ASC_PRIVATE_KEY", "")
# Two report request IDs:
REQ_HISTORICAL = "f46b6fd5-272c-4b46-9a88-55b399ea11f0"  # one-time snapshot (older data)
REQ_ONGOING = os.environ.get("ASC_REPORT_REQUEST_ID", "7d3c05d9-4ec7-46f3-a37d-0665ab7b9896")  # ongoing (current data)

if not PRIVATE_KEY:
    key_path = os.path.expanduser(f"~/private_keys/AuthKey_{KEY_ID}.p8")
    if os.path.exists(key_path):
        with open(key_path) as f:
            PRIVATE_KEY = f.read()
    else:
        print("ERROR: No private key found.")
        sys.exit(1)


def get_token():
    now = int(time.time())
    payload = {"iss": ISSUER_ID, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    return jwt.encode(payload, PRIVATE_KEY, algorithm="ES256", headers={"kid": KEY_ID})


def api_get(url, params=None):
    r = requests.get(url, headers={"Authorization": f"Bearer {get_token()}"}, params=params or {})
    r.raise_for_status()
    return r.json()


def download_report(url):
    r = requests.get(url)
    try:
        content = gzip.decompress(r.content).decode('utf-8')
    except Exception:
        content = r.text
    return list(csv.DictReader(io.StringIO(content), delimiter='\t'))


def get_report_rows(report_id):
    all_rows = []
    instances = api_get(
        f"https://api.appstoreconnect.apple.com/v1/analyticsReports/{report_id}/instances",
        {"limit": 50}
    )
    for inst in instances.get('data', []):
        proc_date = inst['attributes'].get('processingDate', '')
        seg_url = inst['relationships']['segments']['links']['related']
        segs = api_get(seg_url)
        for seg in segs.get('data', []):
            dl_url = seg['attributes'].get('url')
            if dl_url:
                rows = download_report(dl_url)
                for row in rows:
                    row['_date'] = proc_date
                all_rows.extend(rows)
    return all_rows


def find_report_id(req_id, name_contains):
    reports = api_get(
        f"https://api.appstoreconnect.apple.com/v1/analyticsReportRequests/{req_id}/reports",
        {"limit": 200}
    )
    for rpt in reports.get('data', []):
        if name_contains.lower() in rpt['attributes'].get('name', '').lower():
            return rpt['id']
    return None


def fetch_app_versions():
    versions = []
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/appStoreVersions"
    params = {"limit": 10, "fields[appStoreVersions]": "versionString,appStoreState,platform,createdDate,releaseType"}
    data = api_get(url, params)
    for v in data.get('data', []):
        a = v['attributes']
        versions.append({
            "id": v['id'],
            "versionString": a.get('versionString'),
            "platform": a.get('platform'),
            "appStoreState": a.get('appStoreState'),
            "createdDate": a.get('createdDate'),
            "releaseType": a.get('releaseType'),
        })
    return versions


def merge_report_rows(req_ids, report_name):
    """Fetch rows from multiple report requests, merge and deduplicate."""
    all_rows = []
    for req_id in req_ids:
        rid = find_report_id(req_id, report_name)
        if rid:
            print(f"    Fetching from {req_id[:12]}... ({report_name})")
            rows = get_report_rows(rid)
            print(f"    Got {len(rows)} rows")
            all_rows.extend(rows)
        else:
            print(f"    Not found in {req_id[:12]}...")
    return all_rows


def main():
    os.makedirs("data", exist_ok=True)
    req_ids = [REQ_HISTORICAL, REQ_ONGOING]

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "app_name": "Poly-Glot AI: Prompt Studio",
        "summary": {},
        "impressions_by_date": {},
        "impressions_by_country": {},
        "web_preview_by_date": {},
        "page_views_by_date": {},
        "taps_by_date": {},
        "downloads_by_date": {},
        "downloads_by_type": {},
        "downloads_by_country": {},
        "downloads_by_version": {},
        "raw_engagement": [],
        "raw_downloads": [],
        "raw_subscriptions": [],
        "raw_purchases": [],
    }

    # --- Engagement (merge historical + ongoing) ---
    print("Fetching engagement reports (historical + ongoing)...")
    eng_rows = merge_report_rows(req_ids, "App Store Discovery and Engagement Standard")
    if not eng_rows:
        eng_rows = merge_report_rows(req_ids, "App Store Discovery and Engagement Detailed")

    if eng_rows:
        # Deduplicate by (Date, Territory, Event, Source Type, Counts)
        seen = set()
        unique = []
        for row in eng_rows:
            key = (row.get('Date',''), row.get('Territory',''), row.get('Event',''), row.get('Source Type',''), row.get('Counts',''))
            if key not in seen:
                seen.add(key)
                unique.append(row)
        eng_rows = unique
        print(f"  Total unique engagement rows: {len(eng_rows)}")

        impressions_by_date = defaultdict(int)
        impressions_by_country = defaultdict(int)
        web_by_date = defaultdict(int)
        page_views_by_date = defaultdict(int)
        taps_by_date = defaultdict(int)
        total_impressions = 0
        total_web = 0
        total_page_views = 0
        total_taps = 0

        for row in eng_rows:
            date = row.get('Date', row.get('_date', ''))
            territory = row.get('Territory', row.get('Storefront', ''))
            event = row.get('Event', '')
            counts = int(row.get('Counts', '0') or '0')

            if 'impression' in event.lower():
                impressions_by_date[date] += counts
                impressions_by_country[territory] += counts
                total_impressions += counts
            elif 'page view' in event.lower():
                page_views_by_date[date] += counts
                total_page_views += counts
            elif 'tap' in event.lower():
                taps_by_date[date] += counts
                total_taps += counts
            elif 'web' in event.lower() or 'preview' in event.lower():
                web_by_date[date] += counts
                total_web += counts

            output["raw_engagement"].append(row)

        output["impressions_by_date"] = dict(sorted(impressions_by_date.items()))
        output["impressions_by_country"] = dict(sorted(impressions_by_country.items(), key=lambda x: -x[1]))
        output["web_preview_by_date"] = dict(sorted(web_by_date.items()))
        output["page_views_by_date"] = dict(sorted(page_views_by_date.items()))
        output["taps_by_date"] = dict(sorted(taps_by_date.items()))

        dates = sorted(impressions_by_date.keys())
        output["summary"] = {
            "total_impressions": total_impressions,
            "total_page_views": total_page_views,
            "total_taps": total_taps,
            "total_web_preview_views": total_web,
            "days_tracked": len(dates),
            "date_range_start": dates[0] if dates else "",
            "date_range_end": dates[-1] if dates else "",
            "total_countries": len(impressions_by_country),
        }
        print(f"  Range: {dates[0] if dates else '?'} → {dates[-1] if dates else '?'} ({len(dates)} days)")
        print(f"  Impressions: {total_impressions}, Page Views: {total_page_views}, Taps: {total_taps}")

    # --- Web preview (merge) ---
    print("Fetching web preview reports...")
    web_rows = merge_report_rows(req_ids, "Web Preview Engagement")
    if web_rows:
        total_web_extra = sum(int(r.get('Counts', '0') or '0') for r in web_rows)
        if total_web_extra > output["summary"].get("total_web_preview_views", 0):
            output["summary"]["total_web_preview_views"] = total_web_extra
        print(f"  Web preview total: {total_web_extra}")

    # --- Downloads (merge) ---
    print("Fetching download reports...")
    dl_rows = merge_report_rows(req_ids, "App Downloads Standard")
    if not dl_rows:
        dl_rows = merge_report_rows(req_ids, "App Downloads Detailed")

    if dl_rows:
        seen = set()
        unique_rows = []
        for row in dl_rows:
            key = (row.get('Date',''), row.get('Territory',''), row.get('Download Type',''), row.get('App Version',''), row.get('Counts',''))
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)

        downloads_by_date = defaultdict(int)
        downloads_by_type = defaultdict(int)
        downloads_by_country = defaultdict(int)
        downloads_by_version = defaultdict(int)
        total_downloads = 0
        for row in unique_rows:
            counts = int(row.get('Counts', '0') or '0')
            total_downloads += counts
            downloads_by_date[row.get('Date', '')] += counts
            downloads_by_type[row.get('Download Type', '')] += counts
            downloads_by_country[row.get('Territory', '')] += counts
            downloads_by_version[row.get('App Version', '')] += counts

        output["downloads_by_date"] = dict(sorted(downloads_by_date.items()))
        output["downloads_by_type"] = dict(sorted(downloads_by_type.items(), key=lambda x: -x[1]))
        output["downloads_by_country"] = dict(sorted(downloads_by_country.items(), key=lambda x: -x[1]))
        output["downloads_by_version"] = dict(sorted(downloads_by_version.items(), key=lambda x: -x[1]))
        output["raw_downloads"] = unique_rows
        output["summary"]["total_downloads"] = total_downloads
        print(f"  Downloads: {total_downloads} | By type: {dict(downloads_by_type)}")
    else:
        output["summary"]["total_downloads"] = 0

    # --- Subscriptions ---
    print("Fetching subscription reports...")
    sub_rows = merge_report_rows(req_ids, "App Store Subscription Event Report Standard")
    if sub_rows:
        output["raw_subscriptions"] = sub_rows
        total_subs = sum(int(r.get('Counts', '0') or '0') for r in sub_rows)
        output["summary"]["total_subscriptions"] = total_subs
        print(f"  Subscription events: {total_subs}")
    else:
        output["summary"]["total_subscriptions"] = 0

    # --- Purchases ---
    print("Fetching purchase reports...")
    purch_rows = merge_report_rows(req_ids, "App Store Purchases Standard")
    if purch_rows:
        output["raw_purchases"] = purch_rows
        total_purchases = sum(int(r.get('Counts', '0') or '0') for r in purch_rows)
        output["summary"]["total_purchases"] = total_purchases
        print(f"  Purchases: {total_purchases}")
    else:
        output["summary"]["total_purchases"] = 0

    # --- App Store Versions ---
    print("Fetching app store versions...")
    output["app_versions"] = fetch_app_versions()

    # --- Pre-aggregate funnel ---
    web_ref = 0
    app_ref = 0
    web_ref_countries = defaultdict(int)
    src_data = defaultdict(int)
    for r in output.get("raw_engagement", []):
        c = int(r.get("Counts", "0") or "0")
        st = r.get("Source Type", "Unavailable")
        src_data[st] += c
        if st == "Web referrer":
            web_ref += c
            web_ref_countries[r.get("Territory", "??")] += c
        elif st == "App referrer":
            app_ref += c
    real_dl = 0
    for r in output.get("raw_downloads", []):
        if r.get("Download Type") != "Auto-update":
            real_dl += int(r.get("Counts", "0") or "0")
    output["funnel"] = {
        "web_referrer": web_ref,
        "app_referrer": app_ref,
        "real_downloads": real_dl,
        "web_ref_countries": dict(sorted(web_ref_countries.items(), key=lambda x: -x[1])),
        "source_breakdown": dict(sorted(src_data.items(), key=lambda x: -x[1])),
    }

    # Trim raw_engagement
    raw_eng = output.get("raw_engagement", [])
    raw_eng.sort(key=lambda x: x.get("Date", ""), reverse=True)
    output["raw_engagement"] = raw_eng[:200]

    with open("data/analytics.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nData written to data/analytics.json")
    s = output["summary"]
    print(f"Summary: {s.get('total_downloads',0)} downloads | {s.get('total_impressions',0)} impressions | {s.get('total_countries',0)} countries")
    print(f"Range: {s.get('date_range_start','')} → {s.get('date_range_end','')}")


if __name__ == "__main__":
    main()
