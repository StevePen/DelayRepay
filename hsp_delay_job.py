#!/usr/bin/env python3
"""
Northfleet Delay Repay backstop job.

Runs each MORNING and processes the PREVIOUS day, so one pass covers both the
morning trip in and the evening trip home.

For each commute leg it asks the National Rail Historic Service Performance
(HSP) API for every service in your time window, reads the actual arrival
versus the timetable at your destination, and keeps the service with the
LARGEST delay. Without your smartcard tap data the job cannot know which train
you were on, so it surfaces the worst delayed candidate and YOU confirm before
claiming. Only ever claim for journeys you really made.

It records which OPERATOR ran the flagged train (Southeastern vs Thameslink),
because the claim must go to whichever operator caused the delay.

Cancelled services in your window are flagged separately for manual review.

Environment variables:
  HSP_EMAIL              Rail Data Marketplace account email
  HSP_PASSWORD           Rail Data Marketplace account password
  TELEGRAM_BOT_TOKEN     bot token from BotFather              (optional)
  TELEGRAM_CHAT_ID       your chat id from getUpdates          (optional)
  SUPABASE_URL           e.g. https://xxxx.supabase.co         (optional)
  SUPABASE_SERVICE_KEY   service role key for the ledger       (optional)
  TEST_MODE              set to 1 to fake data, no HSP needed  (optional)
"""

import os
import sys
import json
import base64
from datetime import date, timedelta
import urllib.request
import urllib.error
import urllib.parse

HSP_BASE = "https://hsp-prod.rockshore.net/api/v1"
CLAIM_THRESHOLD_MIN = 15  # both SE and TL run Delay Repay 15

HSP_EMAIL = os.environ.get("HSP_EMAIL")
HSP_PASSWORD = os.environ.get("HSP_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TEST_MODE = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")

OPERATORS = {
    "SE": {"name": "Southeastern",
           "claim": "https://www.southeasternrailway.co.uk/help-and-contact/delay-repay"},
    "TL": {"name": "Thameslink",
           "claim": "https://www.thameslinkrailway.com/help-and-support/delay-repay"},
}
FALLBACK_OPERATOR = {"name": "Unknown operator",
                     "claim": "https://www.nationalrail.co.uk/travel-information/delay-repay/"}

# Your monitored legs. Departure window from origin, HHMM.
# NFL = Northfleet, LBG = London Bridge.
JOURNEYS = [
    {"label": "Morning into work", "origin": "NFL", "destination": "LBG",
     "from_time": "0600", "to_time": "0800"},
    {"label": "Evening home", "origin": "LBG", "destination": "NFL",
     "from_time": "1630", "to_time": "1930"},
]


# ---------- HSP ----------

def _hsp_post(path, payload):
    if not (HSP_EMAIL and HSP_PASSWORD):
        sys.exit("Set HSP_EMAIL and HSP_PASSWORD (Rail Data Marketplace login).")
    token = base64.b64encode(f"{HSP_EMAIL}:{HSP_PASSWORD}".encode()).decode()
    req = urllib.request.Request(
        f"{HSP_BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _delay_minutes(planned_hhmm, actual_hhmm):
    p = int(planned_hhmm[:2]) * 60 + int(planned_hhmm[2:])
    a = int(actual_hhmm[:2]) * 60 + int(actual_hhmm[2:])
    diff = a - p
    if diff < -720:        # arrival rolled past midnight
        diff += 1440
    return diff


def get_service_rids(leg, day_str):
    result = _hsp_post("serviceMetrics", {
        "from_loc": leg["origin"], "to_loc": leg["destination"],
        "from_time": leg["from_time"], "to_time": leg["to_time"],
        "from_date": day_str, "to_date": day_str, "days": "WEEKDAY",
    })
    rids = []
    for svc in result.get("Services", []):
        rids.extend(svc.get("serviceAttributesMetrics", {}).get("rids", []))
    return rids


def get_service_outcome(rid, origin, destination):
    """Delay at destination, or a cancellation marker, plus the operator."""
    details = _hsp_post("serviceDetails", {"rid": rid}).get(
        "serviceAttributesDetails", {})
    toc = details.get("toc_code", "")
    sched_dep = None
    for loc in details.get("locations", []):
        if loc.get("location") == origin and loc.get("gbtt_ptd"):
            sched_dep = loc.get("gbtt_ptd")
        if loc.get("location") == destination:
            planned, actual = loc.get("gbtt_pta"), loc.get("actual_ta")
            if planned and not actual:
                return {"cancelled": True, "toc": toc,
                        "scheduled_dep": sched_dep, "scheduled_arr": planned}
            if planned and actual:
                return {"cancelled": False, "toc": toc,
                        "scheduled_dep": sched_dep, "scheduled_arr": planned,
                        "actual_arr": actual,
                        "delay": _delay_minutes(planned, actual)}
    return None


# ---------- Outputs ----------

def operator_info(toc):
    if toc in OPERATORS:
        return OPERATORS[toc]
    name = f"Operator {toc}" if toc else FALLBACK_OPERATOR["name"]
    return {**FALLBACK_OPERATOR, "name": name}


def send_telegram(text):
    if not (TG_TOKEN and TG_CHAT):
        return
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data)
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        print(f"  ! telegram send failed: {e.read().decode()}")


def save(record):
    if not (SUPABASE_URL and SUPABASE_KEY):
        return
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/delay_log?on_conflict=leg_label,travel_date",
        data=json.dumps(record).encode(),
        headers={"Content-Type": "application/json", "apikey": SUPABASE_KEY,
                 "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Prefer": "resolution=merge-duplicates"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        print(f"  ! could not save: {e.read().decode()}")


# ---------- Main ----------

def run(target_day=None):
    target_day = target_day or (date.today() - timedelta(days=1))
    if target_day.weekday() >= 5:
        print(f"{target_day} was a weekend, nothing to check.")
        return
    day_str = target_day.isoformat()
    if TEST_MODE:
        return run_test(day_str)
    print(f"Checking commute for {day_str}\n")
    summary = [f"Delay Repay check, {day_str}"]
    anything_to_flag = False

    for leg in JOURNEYS:
        best, cancellations = None, []
        for rid in get_service_rids(leg, day_str):
            out = get_service_outcome(rid, leg["origin"], leg["destination"])
            if out is None:
                continue
            if out["cancelled"]:
                cancellations.append(out)
            elif best is None or out["delay"] > best["delay"
