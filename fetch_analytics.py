#!/usr/bin/env python3
"""
Fetch Poly-Glot AI analytics from App Store Connect API.
Outputs data/analytics.json for the GitHub Pages dashboard.
Uses TWO report requests: historical (one-time) + ongoing (rolling current).
Includes: Engagement, Downloads, Install+Delete, Acquisitions (Source Info + Campaign).
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
    """Fetch app versions for BOTH iOS and macOS platforms separately to avoid
    one platform's versions pushing the other off the API limit."""
    versions = []
    base_url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/appStoreVersions"
    base_fields = "versionString,appStoreState,platform,createdDate,releaseType"

    for platform in ["IOS", "MAC_OS"]:
        params = {
            "limit": 10,
            "fields[appStoreVersions]": base_fields,
            "filter[platform]": platform,
        }
        try:
            data = api_get(base_url, params)
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
            print(f"  {platform}: {len(data.get('data', []))} versions fetched")
        except Exception as e:
            print(f"  {platform}: error fetching versions: {e}")

    return versions