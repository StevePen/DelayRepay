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
  HSP_EMAIL              RDM API key (x-apikey) from raildata.org.uk HSP page
  TELEGRAM_BOT_TOKEN     bot token from BotFather              (optional)
  TELEGRAM_CHAT_ID       your chat id from getUpdates          (optional)
  SUPABASE_URL           e.g. https://xxxx.supabase.co         (optional)
  SUPABASE_SERVICE_KEY   service role key for the ledger       (optional)
  TEST_MODE              set to 1 to fake data, no HSP needed  (optional)
"""

import os
import sys
import json
from datetime import date, timedelta
import urllib.request
import urllib.error
import urllib.parse

HSP_BASE = "https://api1.raildata.org.uk/1010-historical-service-performance-_hsp_v1/api/v1"
CLAIM_THRESHOLD_MIN = 15  # both SE and TL run Delay Repay 15
RDM_EXPIRY = "2027-06-10"  # HSP agreement renewal date, update after each renewal

RDM_KEY    = os.environ.get("HSP_EMAIL")       # paste Consumer key / API key here
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT    = os.environ.get("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TEST_MODE  = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")

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
    if not RDM_KEY:
        sys.exit("Set HSP_EMAIL to your RDM API key from raildata.org.uk.")
    req = urllib.request.Request(
        f"{HSP_BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "x-apikey": RDM_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            send_telegram(
                "Delay Repay Bot: RDM credentials have expired or been rejected.\n\n"
                "Go to raildata.org.uk, open the HSP product page,\n"
                "copy the new API key, then update HSP_EMAIL in:\n"
                "github.com/StevePen/DelayRepay/settings/secrets/actions"
            )
            sys.exit("RDM credentials expired, Telegram notified.")
        raise


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


# ---------- Expiry check ----------

def check_credential_expiry():
    """Warn via Telegram 30, 14, and 7 days before the RDM agreement expires."""
    try:
        expiry = date.fromisoformat(RDM_EXPIRY)
    except ValueError:
        return
    days_left = (expiry - date.today()).days
    if days_left in (30, 14, 7):
        send_telegram(
            f"Delay Repay Bot: your Rail Data Marketplace agreement "
            f"expires in {days_left} days ({RDM_EXPIRY}).\n\n"
            f"Go to raildata.org.uk and renew your HSP subscription, "
            f"then update HSP_EMAIL in:\n"
            f"github.com/StevePen/DelayRepay/settings/secrets/actions"
        )
        print(f"Expiry warning sent: {days_left} days remaining.")


# ---------- Main ----------

def run(target_day=None):
    target_day = target_day or (date.today() - timedelta(days=1))
    if target_day.weekday() >= 5:
        print(f"{target_day} was a weekend, nothing to check.")
        return
    check_credential_expiry()
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
            elif best is None or out["delay"] > best["delay"]:
                best = {**out, "rid": rid}

        lines = [f"\n{leg['label']} ({leg['origin']} to {leg['destination']}):"]

        if best is None and not cancellations:
            lines.append("  no usable data")
        if best is not None:
            claimable = best["delay"] >= CLAIM_THRESHOLD_MIN
            op = operator_info(best["toc"])
            if claimable:
                anything_to_flag = True
                lines.append(f"  CLAIMABLE: {best['delay']} min late "
                             f"(due {best['scheduled_arr']}, "
                             f"arrived {best['actual_arr']})")
                lines.append(f"  Operator: {op['name']}, claim here "
                             f"if this was your train:")
                lines.append(f"  {op['claim']}")
            else:
                lines.append(f"  ok, worst delay {best['delay']} min "
                             f"({op['name']})")
            save({"leg_label": leg["label"], "travel_date": day_str,
                  "rid": best["rid"], "operator": op["name"],
                  "toc_code": best["toc"], "claim_url": op["claim"],
                  "scheduled_dep": best["scheduled_dep"],
                  "scheduled_arr": best["scheduled_arr"],
                  "actual_arr": best["actual_arr"],
                  "delay_minutes": best["delay"], "claimable": claimable,
                  "cancelled_in_window": len(cancellations),
                  "status": "candidate" if claimable else "no_claim"})
        if cancellations:
            anything_to_flag = True
            ops = ", ".join(sorted({operator_info(c["toc"])["name"]
                                    for c in cancellations}))
            times = ", ".join(c.get("scheduled_dep") or "?"
                              for c in cancellations)
            lines.append(f"  {len(cancellations)} CANCELLED in window "
                         f"(dep {times}, {ops}).")
            lines.append("  If one was your train, your delay is measured to")
            lines.append("  when the train you actually caught arrived.")

        for ln in lines:
            print(ln)
        summary.extend(lines)

    if anything_to_flag:
        send_telegram("\n".join(summary))
    else:
        print("\nNothing claimable, no notification sent.")


def run_test(day_str):
    """End to end test without HSP: fakes one claimable delay and one
    cancellation, sends the Telegram message, and writes a TEST row to
    Supabase. Delete the TEST rows whenever you like."""
    print(f"TEST MODE for {day_str}: no HSP call, fake data only\n")
    op = OPERATORS["SE"]
    summary = [f"TEST RUN, Delay Repay check, {day_str}",
               "",
               "TEST Morning into work (NFL to LBG):",
               "  CLAIMABLE: 18 min late (due 0742, arrived 0800)",
               f"  Operator: {op['name']}, claim here if this was your train:",
               f"  {op['claim']}",
               "",
               "TEST Evening home (LBG to NFL):",
               "  1 CANCELLED in window (dep 1815, Thameslink).",
               "  If one was your train, check manually.",
               "",
               "If you can read this, Telegram works. Check Supabase for",
               "a TEST row in delay_log, then the pipeline is fully proven."]
    send_telegram("\n".join(summary))
    save({"leg_label": "TEST Morning into work", "travel_date": day_str,
          "rid": "TEST", "operator": op["name"], "toc_code": "SE",
          "claim_url": op["claim"], "scheduled_dep": "0712",
          "scheduled_arr": "0742", "actual_arr": "0800",
          "delay_minutes": 18, "claimable": True,
          "cancelled_in_window": 0, "status": "dismissed",
          "notes": "TEST ROW, safe to delete"})
    print("Test message sent (if Telegram vars set) and TEST row saved",
          "(if Supabase vars set).")


if __name__ == "__main__":
    run()
