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


# Well-known app bundle IDs → friendly names
APP_NAMES = {
    "com.zhiliaoapp.musically": "TikTok",
    "com.ss.iphone.ugc.Ame": "TikTok (US)",
    "com.ss.iphone.ugc.tiktok.lite": "TikTok Lite",
    "com.apple.mobilesafari": "Safari",
    "com.google.chrome.ios": "Chrome",
    "com.apple.AppStore": "App Store",
    "com.facebook.Facebook": "Facebook",
    "com.facebook.Messenger": "Messenger",
    "com.burbn.instagram": "Instagram",
    "com.atebits.Tweetie2": "X (Twitter)",
    "com.twitter.twitter": "X (Twitter)",
    "com.reddit.Reddit": "Reddit",
    "com.linkedin.LinkedIn": "LinkedIn",
    "com.google.Gmail": "Gmail",
    "com.apple.mobilemail": "Apple Mail",
    "com.snapchat.snapchat": "Snapchat",
    "com.whatsapp.WhatsApp": "WhatsApp",
    "com.skype.skype": "Skype",
    "org.telegram.Telegram": "Telegram",
    "jp.naver.line": "LINE",
    "com.viber.app": "Viber",
    "com.discord": "Discord",
    "com.slack.Slack": "Slack",
    "net.whatsapp.WhatsApp": "WhatsApp",
    "com.google.GoogleMobile": "Google",
    "com.google.youtube": "YouTube",
    "com.pinterest": "Pinterest",
}


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

    # =========================================================================
    # ENGAGEMENT STANDARD (merge historical + ongoing)
    # =========================================================================
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

    # =========================================================================
    # WEB PREVIEW (merge)
    # =========================================================================
    print("Fetching web preview reports...")
    web_rows = merge_report_rows(req_ids, "Web Preview Engagement")
    if web_rows:
        total_web_extra = sum(int(r.get('Counts', '0') or '0') for r in web_rows)
        if total_web_extra > output["summary"].get("total_web_preview_views", 0):
            output["summary"]["total_web_preview_views"] = total_web_extra
        print(f"  Web preview total: {total_web_extra}")

    # =========================================================================
    # DOWNLOADS STANDARD (merge)
    # =========================================================================
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

    # =========================================================================
    # ENGAGEMENT DETAILED — ACQUISITIONS + CAMPAIGNS (Source Info, Campaign)
    # =========================================================================
    print("Fetching Engagement Detailed (acquisitions + campaigns)...")
    eng_detail_rows = merge_report_rows(req_ids, "App Store Discovery and Engagement Detailed")
    acquisitions = {
        "total_page_views_detailed": 0,
        "total_unique_views": 0,
        "source_info": {},        # bundle ID / referrer → count
        "source_info_names": {},  # bundle ID → friendly name
        "campaigns": {},          # campaign token → count
        "source_info_by_date": {},  # date → {source: count}
        "acquisitions_by_date": {},  # date → total unique page views (= "acquisitions")
        "acquisitions_by_country": {},  # territory → total unique views
        "top_referrers": [],      # [{name, bundle_id, count, pct}]
        "campaign_list": [],      # [{name, count, pct}]
    }

    if eng_detail_rows:
        # Deduplicate
        seen = set()
        unique_detail = []
        for row in eng_detail_rows:
            key = (row.get('Date',''), row.get('Territory',''), row.get('Event',''),
                   row.get('Source Type',''), row.get('Source Info',''),
                   row.get('Campaign',''), row.get('Device',''),
                   row.get('Platform Version',''), row.get('Counts',''))
            if key not in seen:
                seen.add(key)
                unique_detail.append(row)
        print(f"  Unique detailed rows: {len(unique_detail)}")

        source_info_counts = defaultdict(int)
        source_info_unique = defaultdict(int)
        campaign_counts = defaultdict(int)
        acq_by_date = defaultdict(int)
        acq_by_country = defaultdict(int)
        si_by_date = defaultdict(lambda: defaultdict(int))
        total_pv = 0
        total_unique = 0

        for row in unique_detail:
            event = row.get('Event', '')
            counts = int(row.get('Counts', '0') or '0')
            unique_c = int(row.get('Unique Counts', '0') or '0')
            si = row.get('Source Info', '') or ''
            camp = row.get('Campaign', '') or ''
            date = row.get('Date', '')
            territory = row.get('Territory', '')

            # "Acquisitions" in ASC = page views from sources (the user actually visited your page)
            if 'page view' in event.lower():
                total_pv += counts
                total_unique += unique_c
                if si:
                    source_info_counts[si] += counts
                    source_info_unique[si] += unique_c
                    si_by_date[date][si] += counts
                if camp:
                    campaign_counts[camp] += counts
                acq_by_date[date] += unique_c
                acq_by_country[territory] += unique_c

        # Build source_info with friendly names
        si_sorted = sorted(source_info_counts.items(), key=lambda x: -x[1])
        source_info_dict = {}
        source_info_names = {}
        top_referrers = []
        for bundle_id, count in si_sorted:
            friendly = APP_NAMES.get(bundle_id, bundle_id)
            source_info_dict[bundle_id] = count
            source_info_names[bundle_id] = friendly
            pct = round(count / total_pv * 100, 1) if total_pv > 0 else 0
            top_referrers.append({
                "bundle_id": bundle_id,
                "name": friendly,
                "count": count,
                "unique": source_info_unique.get(bundle_id, 0),
                "pct": pct,
            })

        # Build campaign list
        camp_sorted = sorted(campaign_counts.items(), key=lambda x: -x[1])
        campaign_list = []
        for camp_name, count in camp_sorted:
            pct = round(count / total_pv * 100, 1) if total_pv > 0 else 0
            campaign_list.append({"name": camp_name, "count": count, "pct": pct})

        acquisitions = {
            "total_page_views_detailed": total_pv,
            "total_unique_views": total_unique,
            "source_info": source_info_dict,
            "source_info_names": source_info_names,
            "campaigns": dict(campaign_counts),
            "source_info_by_date": {d: dict(v) for d, v in sorted(si_by_date.items())},
            "acquisitions_by_date": dict(sorted(acq_by_date.items())),
            "acquisitions_by_country": dict(sorted(acq_by_country.items(), key=lambda x: -x[1])),
            "top_referrers": top_referrers,
            "campaign_list": campaign_list,
        }
        print(f"  Acquisitions: {total_pv} page views, {total_unique} unique")
        print(f"  Top referrers: {[r['name'] for r in top_referrers[:5]]}")
        print(f"  Campaigns: {len(campaign_list)}")

    output["acquisitions"] = acquisitions

    # =========================================================================
    # INSTALL + DELETE (real-time installs/uninstalls)
    # =========================================================================
    print("Fetching Install+Delete reports...")
    install_rows = merge_report_rows(req_ids, "App Store Installation and Deletion Standard")

    installs_data = {
        "total_installs": 0,
        "total_first_time": 0,
        "total_redownloads": 0,
        "total_updates": 0,
        "total_deletes": 0,
        "net_installs": 0,
        "installs_by_date": {},
        "deletes_by_date": {},
        "installs_by_country": {},
        "installs_by_source": {},
        "installs_by_type": {},
        "raw_installs": [],
    }

    if install_rows:
        # Deduplicate
        seen = set()
        unique_inst = []
        for row in install_rows:
            key = (row.get('Date',''), row.get('Event',''), row.get('Download Type',''),
                   row.get('Territory',''), row.get('Source Type',''),
                   row.get('Device',''), row.get('Platform Version',''), row.get('Counts',''))
            if key not in seen:
                seen.add(key)
                unique_inst.append(row)
        print(f"  Unique install+delete rows: {len(unique_inst)}")

        inst_by_date = defaultdict(int)
        del_by_date = defaultdict(int)
        inst_by_country = defaultdict(int)
        inst_by_source = defaultdict(int)
        inst_by_type = defaultdict(int)
        total_installs = 0
        total_first = 0
        total_redl = 0
        total_upd = 0
        total_deletes = 0

        for row in unique_inst:
            evt = row.get('Event', '')
            counts = int(row.get('Counts', '0') or '0')
            date = row.get('Date', '')
            territory = row.get('Territory', '')
            dl_type = row.get('Download Type', '')
            source = row.get('Source Type', '')

            if evt == 'Install':
                inst_by_date[date] += counts
                inst_by_country[territory] += counts
                inst_by_source[source] += counts
                inst_by_type[dl_type] += counts
                total_installs += counts
                if dl_type == 'First-time download':
                    total_first += counts
                elif dl_type == 'Redownload':
                    total_redl += counts
                elif dl_type == 'Manual update':
                    total_upd += counts
            elif evt == 'Delete':
                del_by_date[date] += counts
                total_deletes += counts

        installs_data = {
            "total_installs": total_installs,
            "total_first_time": total_first,
            "total_redownloads": total_redl,
            "total_updates": total_upd,
            "total_deletes": total_deletes,
            "net_installs": total_installs - total_deletes,
            "installs_by_date": dict(sorted(inst_by_date.items())),
            "deletes_by_date": dict(sorted(del_by_date.items())),
            "installs_by_country": dict(sorted(inst_by_country.items(), key=lambda x: -x[1])),
            "installs_by_source": dict(sorted(inst_by_source.items(), key=lambda x: -x[1])),
            "installs_by_type": dict(sorted(inst_by_type.items(), key=lambda x: -x[1])),
            "raw_installs": unique_inst[:100],  # Keep last 100 for table
        }
        print(f"  Installs: {total_installs} (first: {total_first}, redl: {total_redl}, upd: {total_upd})")
        print(f"  Deletes: {total_deletes} | Net: {total_installs - total_deletes}")

    output["installs"] = installs_data

    # =========================================================================
    # SUBSCRIPTIONS (events + state from analytics reports)
    # =========================================================================
    print("Fetching subscription reports...")
    sub_event_rows = merge_report_rows(req_ids, "App Store Subscription Event Report Standard")
    sub_state_rows = merge_report_rows(req_ids, "App Store Subscription State Report Standard")

    subscription_data = {
        "plans": [],
        "total_events": 0,
        "total_active": 0,
        "total_revenue_estimate": 0.0,
        "events_by_type": {},
        "events_by_date": {},
        "events_by_country": {},
        "active_by_plan": {},
        "raw_events": [],
        "raw_state": [],
    }

    # Fetch subscription product info from ASC
    print("Fetching subscription product info...")
    try:
        sg_data = api_get(f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/subscriptionGroups")
        for sg in sg_data.get('data', []):
            sg_id = sg['id']
            sg_name = sg['attributes'].get('referenceName', 'Unknown')
            subs_data = api_get(
                f"https://api.appstoreconnect.apple.com/v1/subscriptionGroups/{sg_id}/subscriptions",
                {"fields[subscriptions]": "name,productId,state,subscriptionPeriod"}
            )
            for sub in subs_data.get('data', []):
                a = sub['attributes']
                plan = {
                    "id": sub['id'],
                    "name": a.get('name', ''),
                    "product_id": a.get('productId', ''),
                    "state": a.get('state', ''),
                    "period": a.get('subscriptionPeriod', ''),
                    "group": sg_name,
                    "price": None,
                    "proceeds": None,
                }
                # Get US price
                try:
                    price_data = api_get(
                        f"https://api.appstoreconnect.apple.com/v1/subscriptions/{sub['id']}/prices",
                        {"filter[territory]": "USA", "include": "subscriptionPricePoint", "limit": 1}
                    )
                    for inc in price_data.get('included', []):
                        if inc['type'] == 'subscriptionPricePoints':
                            plan['price'] = float(inc['attributes'].get('customerPrice', 0))
                            plan['proceeds'] = float(inc['attributes'].get('proceeds', 0))
                except Exception as e:
                    print(f"    Price fetch error: {e}")
                subscription_data["plans"].append(plan)
                print(f"    {plan['name']}: ${plan['price']} / {plan['period']} (proceeds: ${plan['proceeds']})")
    except Exception as e:
        print(f"  Subscription group fetch error: {e}")

    # Process subscription events
    if sub_event_rows:
        seen = set()
        unique = []
        for row in sub_event_rows:
            key = (row.get('Date',''), row.get('Event',''), row.get('Subscription Name',''),
                   row.get('Territory',''), row.get('Counts',''))
            if key not in seen:
                seen.add(key)
                unique.append(row)

        events_by_type = defaultdict(int)
        events_by_date = defaultdict(int)
        events_by_country = defaultdict(int)
        total_events = 0

        for row in unique:
            counts = int(row.get('Counts', '0') or '0')
            total_events += counts
            events_by_type[row.get('Event', '')] += counts
            events_by_date[row.get('Date', '')] += counts
            events_by_country[row.get('Territory', '')] += counts

        subscription_data["total_events"] = total_events
        subscription_data["events_by_type"] = dict(sorted(events_by_type.items(), key=lambda x: -x[1]))
        subscription_data["events_by_date"] = dict(sorted(events_by_date.items()))
        subscription_data["events_by_country"] = dict(sorted(events_by_country.items(), key=lambda x: -x[1]))
        subscription_data["raw_events"] = unique[:50]
        print(f"  Events: {total_events} | Types: {dict(events_by_type)}")

    # Process subscription state (active subscribers)
    if sub_state_rows:
        active_by_plan = defaultdict(int)
        total_active = 0
        for row in sub_state_rows:
            state = row.get('State', '')
            counts = int(row.get('Counts', '0') or '0')
            if state in ('Active', 'active', 'ACTIVE'):
                sub_name = row.get('Subscription Name', row.get('Product', 'Unknown'))
                active_by_plan[sub_name] += counts
                total_active += counts
        subscription_data["total_active"] = total_active
        subscription_data["active_by_plan"] = dict(active_by_plan)
        subscription_data["raw_state"] = sub_state_rows[:50]
        print(f"  Active subs: {total_active}")

    # Estimate revenue from events (Subscribe events × price)
    price_map = {}
    for plan in subscription_data["plans"]:
        if plan['price']:
            price_map[plan['name']] = plan['price']

    total_revenue = 0.0
    total_proceeds = 0.0
    for row in subscription_data.get("raw_events", []):
        evt = row.get('Event', '')
        if 'subscribe' in evt.lower() or 'renew' in evt.lower() or 'reactivat' in evt.lower():
            sub_name = row.get('Subscription Name', '')
            counts = int(row.get('Counts', '0') or '0')
            price = price_map.get(sub_name, 0)
            total_revenue += price * counts
    subscription_data["total_revenue_estimate"] = round(total_revenue, 2)

    output["subscriptions"] = subscription_data
    output["summary"]["total_subscriptions"] = subscription_data["total_events"]

    # =========================================================================
    # PURCHASES (in-app purchases)
    # =========================================================================
    print("Fetching purchase reports...")
    purch_rows = merge_report_rows(req_ids, "App Store Purchases Standard")
    if purch_rows:
        output["raw_purchases"] = purch_rows
        total_purchases = sum(int(r.get('Counts', '0') or '0') for r in purch_rows)
        output["summary"]["total_purchases"] = total_purchases
        print(f"  Purchases: {total_purchases}")
    else:
        output["summary"]["total_purchases"] = 0

    # =========================================================================
    # TIKTOK ADS DATA
    # =========================================================================
    print("Loading TikTok Ads data...")
    # TikTok Marketing API integration — if token is set, fetch live data
    tiktok_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
    tiktok_adv_id = os.environ.get("TIKTOK_ADVERTISER_ID", "7674635512447238161")

    tiktok_data = {
        "advertiser_id": tiktok_adv_id,
        "campaigns": [],
        "totals": {
            "impressions": 0,
            "clicks": 0,
            "ctr": 0.0,
            "cpc": 0.0,
            "cost": 0.0,
            "conversions": 0,
        },
        "daily": {},
        "source": "manual",  # "api" when token works
        "last_fetched": datetime.now(timezone.utc).isoformat(),
    }

    if tiktok_token:
        try:
            print("  Fetching from TikTok Marketing API...")
            tt_headers = {"Access-Token": tiktok_token}
            # Get campaign list
            tt_camp = requests.get(
                "https://business-api.tiktok.com/open_api/v1.3/campaign/get/",
                headers=tt_headers,
                params={"advertiser_id": tiktok_adv_id, "page_size": 50}
            ).json()
            # Get ad group performance (last 30 days)
            from datetime import timedelta
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
            tt_report = requests.get(
                "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/",
                headers=tt_headers,
                params={
                    "advertiser_id": tiktok_adv_id,
                    "report_type": "BASIC",
                    "data_level": "AUCTION_ADGROUP",
                    "dimensions": '["adgroup_id","stat_time_day"]',
                    "metrics": '["spend","impressions","clicks","ctr","cpc","conversion","cost_per_conversion"]',
                    "start_date": start_date,
                    "end_date": end_date,
                    "page_size": 1000,
                }
            ).json()
            if tt_report.get("code") == 0:
                daily = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0})
                tot_imp = tot_clicks = tot_conv = 0
                tot_cost = 0.0
                for row in tt_report.get("data", {}).get("list", []):
                    m = row.get("metrics", {})
                    d = row.get("dimensions", {}).get("stat_time_day", "")
                    imp = int(m.get("impressions", 0))
                    clk = int(m.get("clicks", 0))
                    cost = float(m.get("spend", 0))
                    conv = int(m.get("conversion", 0))
                    daily[d]["impressions"] += imp
                    daily[d]["clicks"] += clk
                    daily[d]["cost"] += cost
                    daily[d]["conversions"] += conv
                    tot_imp += imp
                    tot_clicks += clk
                    tot_cost += cost
                    tot_conv += conv
                tiktok_data["totals"] = {
                    "impressions": tot_imp,
                    "clicks": tot_clicks,
                    "ctr": round(tot_clicks / tot_imp * 100, 2) if tot_imp > 0 else 0,
                    "cpc": round(tot_cost / tot_clicks, 2) if tot_clicks > 0 else 0,
                    "cost": round(tot_cost, 2),
                    "conversions": tot_conv,
                }
                tiktok_data["daily"] = {k: dict(v) for k, v in sorted(daily.items())}
                tiktok_data["source"] = "api"
                print(f"  API: {tot_imp} impressions, {tot_clicks} clicks, ${tot_cost:.2f} cost")
            else:
                print(f"  API error: {tt_report.get('message','unknown')}")
        except Exception as e:
            print(f"  TikTok API error: {e}")

    # If no API data, use last known values (manual snapshot from ASC screen)
    if tiktok_data["source"] == "manual":
        # Load previous data if exists, otherwise use latest known snapshot
        prev_tiktok = {}
        try:
            with open("data/analytics.json") as f:
                prev = json.load(f)
                prev_tiktok = prev.get("tiktok_ads", {})
        except Exception:
            pass

        if prev_tiktok and prev_tiktok.get("totals", {}).get("impressions", 0) > 0:
            # Keep previous data
            tiktok_data = prev_tiktok
            tiktok_data["source"] = "cached"
            print(f"  Using cached: {tiktok_data['totals'].get('impressions',0)} impressions")
        else:
            # Hardcoded snapshot from Sep 16-23 TikTok Ads Manager
            tiktok_data["totals"] = {
                "impressions": 29795,
                "clicks": 541,
                "ctr": 1.82,
                "cpc": 0.26,
                "cost": 139.98,
                "conversions": 0,
            }
            tiktok_data["campaigns"] = [
                {
                    "name": "Poly-Glot_ios",
                    "status": "ACTIVE",
                    "budget_per_day": 20.00,
                    "start_date": "2026-09-16",
                    "end_date": "2026-09-23",
                    "impressions": 29795,
                    "clicks": 541,
                    "ctr": 1.82,
                    "cpc": 0.26,
                    "cost": 139.98,
                    "conversions": 0,
                }
            ]
            tiktok_data["source"] = "snapshot_2026-09-23"
            print(f"  Using snapshot: 29,795 impressions, $139.98 cost")

    output["tiktok_ads"] = tiktok_data

    # =========================================================================
    # APP STORE VERSIONS
    # =========================================================================
    print("Fetching app store versions...")
    output["app_versions"] = fetch_app_versions()

    # =========================================================================
    # PRE-AGGREGATE FUNNEL (existing TikTok funnel)
    # =========================================================================
    # Use UNIQUE PAGE VIEWS for source traffic. Do not mix impressions, taps,
    # media views, or repeated counts into the traffic-source funnel.
    web_ref = 0
    app_ref = 0
    web_ref_countries = defaultdict(int)
    src_data = defaultdict(int)
    for r in output.get("raw_engagement", []):
        if "page view" not in (r.get("Event", "") or "").lower():
            continue
        c = int(r.get("Unique Counts", "0") or "0")
        st = r.get("Source Type", "Unavailable") or "Unavailable"
        src_data[st] += c
        if st == "Web referrer":
            web_ref += c
            web_ref_countries[r.get("Territory", "??")] += c
        elif st == "App referrer":
            app_ref += c

    # User-initiated installs: first-time downloads + redownloads only.
    # Updates are kept separate because they are not new installs.
    first_time_dl = 0
    redownloads = 0
    manual_updates = 0
    auto_updates = 0
    for r in output.get("raw_downloads", []):
        c = int(r.get("Counts", "0") or "0")
        dl_type = r.get("Download Type", "")
        if dl_type == "First-time download":
            first_time_dl += c
        elif dl_type == "Redownload":
            redownloads += c
        elif dl_type == "Manual update":
            manual_updates += c
        elif dl_type == "Auto-update":
            auto_updates += c

    user_installs = first_time_dl + redownloads

    # Apple-attributed TikTok page views from detailed Source Info.
    # These are Apple-attributed visitors, not TikTok-reported CTA clicks.
    tiktok_page_views = 0
    tiktok_unique_views = 0
    for ref in output.get("acquisitions", {}).get("top_referrers", []):
        if (ref.get("name", "") or "").lower().startswith("tiktok"):
            tiktok_page_views += int(ref.get("count", 0) or 0)
            tiktok_unique_views += int(ref.get("unique", 0) or 0)

    output["funnel"] = {
        "web_referrer": web_ref,
        "app_referrer": app_ref,
        "first_time_downloads": first_time_dl,
        "redownloads": redownloads,
        "user_installs": user_installs,
        "manual_updates": manual_updates,
        "auto_updates": auto_updates,
        "real_downloads": user_installs,
        "tiktok_page_views": tiktok_page_views,
        "tiktok_unique_views": tiktok_unique_views,
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
    a = output.get("acquisitions", {})
    print(f"Acquisitions: {a.get('total_page_views_detailed',0)} detailed views | {len(a.get('top_referrers',[]))} referrers | {len(a.get('campaign_list',[]))} campaigns")
    i = output.get("installs", {})
    print(f"Installs: {i.get('total_installs',0)} installs | {i.get('total_deletes',0)} deletes | net {i.get('net_installs',0)}")


if __name__ == "__main__":
    main()
