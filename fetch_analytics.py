#!/usr/bin/env python3
"""
Fetch Poly-Glot AI analytics from App Store Connect API.
Outputs data/analytics.json for the GitHub Pages dashboard.
"""

import jwt, time, requests, gzip, io, csv, json, os, sys
from datetime import datetime
from collections import defaultdict

KEY_ID = os.environ.get("ASC_KEY_ID", "3M53HUUZF3")
ISSUER_ID = os.environ.get("ASC_ISSUER_ID", "27273279-3df5-4fd7-b3f9-b6e882c1fc38")
PRIVATE_KEY = os.environ.get("ASC_PRIVATE_KEY", "")
REQ_ID = os.environ.get("ASC_REPORT_REQUEST_ID", "f46b6fd5-272c-4b46-9a88-55b399ea11f0")

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
    except:
        content = r.text
    return list(csv.DictReader(io.StringIO(content), delimiter='\t'))


def get_report_rows(report_id):
    """Get all data rows across all instances/segments for a report."""
    all_rows = []
    instances = api_get(
        f"https://api.appstoreconnect.apple.com/v1/analyticsReports/{report_id}/instances",
        {"limit": 30}
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
    """Find a report ID by name."""
    reports = api_get(
        f"https://api.appstoreconnect.apple.com/v1/analyticsReportRequests/{req_id}/reports",
        {"limit": 200}
    )
    for rpt in reports.get('data', []):
        if name_contains.lower() in rpt['attributes'].get('name', '').lower():
            return rpt['id']
    return None


def main():
    os.makedirs("data", exist_ok=True)

    output = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "app_name": "Poly-Glot AI: Prompt Studio",
        "summary": {},
        "impressions_by_date": {},
        "impressions_by_country": {},
        "web_preview_by_date": {},
        "raw_engagement": [],
    }

    # --- Engagement report (impressions, product page views, web previews) ---
    print("Finding engagement report...")
    eng_id = find_report_id(REQ_ID, "App Store Discovery and Engagement Standard")
    if not eng_id:
        eng_id = find_report_id(REQ_ID, "App Store Discovery and Engagement Detailed")

    if eng_id:
        print(f"  Found: {eng_id}")
        print("  Downloading engagement data...")
        rows = get_report_rows(eng_id)
        print(f"  Got {len(rows)} rows")

        impressions_by_date = defaultdict(int)
        impressions_by_country = defaultdict(int)
        web_by_date = defaultdict(int)
        total_impressions = 0
        total_web = 0

        page_views_by_date = defaultdict(int)
        taps_by_date = defaultdict(int)
        total_page_views = 0
        total_taps = 0

        for row in rows:
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
        print(f"  Impressions: {total_impressions}")
        print(f"  Web previews: {total_web}")
        print(f"  Countries: {len(impressions_by_country)}")
        print(f"  Days: {len(dates)}")
    else:
        print("  No engagement report found")

    # --- Web preview report ---
    print("Finding web preview report...")
    web_id = find_report_id(REQ_ID, "App Store Web Preview Engagement")
    if web_id:
        print(f"  Found: {web_id}")
        web_rows = get_report_rows(web_id)
        print(f"  Got {len(web_rows)} web preview rows")
        total_web_extra = 0
        for row in web_rows:
            counts = int(row.get('Counts', '0') or '0')
            total_web_extra += counts
        if total_web_extra > output["summary"].get("total_web_preview_views", 0):
            output["summary"]["total_web_preview_views"] = total_web_extra
        print(f"  Web preview total: {total_web_extra}")

    # --- Install report ---
    print("Finding install report...")
    install_id = find_report_id(REQ_ID, "Platform App Installs")
    if install_id:
        print(f"  Found: {install_id}")
        install_rows = get_report_rows(install_id)
        print(f"  Got {len(install_rows)} install rows")
        total_installs = 0
        for row in install_rows:
            counts = int(row.get('Counts', '0') or '0')
            total_installs += counts
        output["summary"]["total_installs"] = total_installs
        print(f"  Total installs: {total_installs}")

    # Write JSON
    with open("data/analytics.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nData written to data/analytics.json")
    print(f"Total rows: {len(output['raw_engagement'])}")


if __name__ == "__main__":
    main()
