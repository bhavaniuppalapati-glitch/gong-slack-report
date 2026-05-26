import os
import requests
from datetime import datetime, timedelta, timezone
from base64 import b64encode

GONG_ACCESS_KEY   = os.environ["GONG_ACCESS_KEY"]
GONG_SECRET       = os.environ["GONG_SECRET"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
MANAGER_ID        = os.environ["GONG_MANAGER_ID"]
WORKSPACE_ID      = os.environ.get("GONG_WORKSPACE_ID", "")

CALLS_TARGET = 10

TRACKED_MANAGERS = {
    "4648634965683652994": {"name": "Piyush Taori",           "slack_id": "U097RJ7PSGY"},
    "4948022090249743366": {"name": "Vigneshwaran Rajasekar", "slack_id": "U097RHRB108"},
    "3150948745332828084": {"name": "Mithun Dharanendraiah",  "slack_id": "U097RJ7V908"},
    "4624980002410098669": {"name": "Aditya Sridharan",       "slack_id": "U0B1CFUKF2A"},
}

CC_USERS = [
    {"slack_id": "U0AFSEZ54JV"},
    {"slack_id": "U097RHTV4E4"},
    {"slack_id": "U097RJ818EL"},
]

def get_last_week_range():
    today = datetime.now(timezone.utc)
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return (
        last_monday.strftime("%Y-%m-%dT00:00:00Z"),
        last_sunday.strftime("%Y-%m-%dT23:59:59Z"),
    )

def gong_auth_header():
    token = b64encode(f"{GONG_ACCESS_KEY}:{GONG_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def fetch_coaching_metrics(from_dt, to_dt):
    params = {"manager-id": MANAGER_ID, "from": from_dt, "to": to_dt}
    if WORKSPACE_ID:
        params["workspace-id"] = WORKSPACE_ID
    resp = requests.get("https://api.gong.io/v2/coaching", headers=gong_auth_header(), params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Gong API error {resp.status_code}: {resp.text}")
    return resp.json().get("coachingData", [])

def build_slack_message(coaching_data, from_dt, to_dt):
    from_label = from_dt[:10]
    to_label   = to_dt[:10]
    data_by_id = {m["manager"]["id"]: m for m in coaching_data if "manager" in m}
    rows = []
    hit_count = 0

    for gong_id, info in TRACKED_MANAGERS.items():
        slack_id = info["slack_id"]
        m = data_by_id.get(gong_id)
        if m:
            dm       = m.get("directReportsMetrics", [])
            listened = sum(len(r.get("metrics", {}).get("callsListenedTo", []))           for r in dm)
            attended = sum(len(r.get("metrics", {}).get("callsManagerAttended", []))      for r in dm)
            feedback = sum(len(r.get("metrics", {}).get("callsWithFeedback", []))         for r in dm)
            comments = sum(len(r.get("metrics", {}).get("callsManagerCommentedOn", []))   for r in dm)
            scored   = sum(len(r.get("metrics", {}).get("callsWithScorecardFilled", []))  for r in dm)
        else:
            listened = attended = feedback = comments = scored = 0

        if scored >= CALLS_TARGET:
            hit_count += 1

        rows.append(
            f"-> <@{slack_id}>   "
            f"Scored: *{scored}/{CALLS_TARGET}*   "
            f"Listened: {listened}   Attended: {attended}   "
            f"Feedback: {feedback}   Comments: {comments}"
        )

    total   = len(TRACKED_MANAGERS)
    summary = f"*{hit_count}/{total}* managers hit the ≥{CALLS_TARGET} calls scored target this week."
    divider = "─" * 42
    body    = f"{divider}\n" + "\n".join(rows) + f"\n{divider}"
    cc_line = "  ".join(f"<@{u['slack_id']}>" for u in CC_USERS)

    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Weekly Gong Coaching Report", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Period:* {from_label} → {to_label}\n{summary}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"CC: {cc_line}"}]}
        ]
    }

def post_to_slack(payload):
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Slack error {resp.status_code}: {resp.text}")
    print("✅ Slack message posted successfully.")

def main():
    from_dt, to_dt = get_last_week_range()
    print(f"Fetching Gong coaching metrics: {from_dt} → {to_dt}")
    coaching_data = fetch_coaching_metrics(from_dt, to_dt)
    print(f"Got {len(coaching_data)} manager records from Gong.")
    payload = build_slack_message(coaching_data, from_dt, to_dt)
    post_to_slack(payload)

if __name__ == "__main__":
    main()
