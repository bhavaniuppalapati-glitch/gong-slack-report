import os
import requests
import json
from datetime import datetime, timedelta, timezone
from base64 import b64encode

# ── Config from environment variables ────────────────────────────────────────
GONG_ACCESS_KEY    = os.environ["GONG_ACCESS_KEY"]
GONG_SECRET        = os.environ["GONG_SECRET"]
SLACK_WEBHOOK_URL  = os.environ["SLACK_WEBHOOK_URL"]
MANAGER_ID         = os.environ["GONG_MANAGER_ID"]
WORKSPACE_ID       = os.environ.get("GONG_WORKSPACE_ID", "")

CALLS_TARGET = 10  # minimum calls scored per week

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
    url = "https://api.gong.io/v2/coaching"
    resp = requests.get(url, headers=gong_auth_header(), params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Gong API error {resp.status_code}: {resp.text}")
    return resp.json().get("coachingData", [])

def build_slack_message(coaching_data, from_dt, to_dt):
    from_label = from_dt[:10]
    to_label   = to_dt[:10]
    rows = []
    missed = []

    for m in coaching_data:
        manager = m.get("manager", {})
        first   = manager.get("firstName", "")
        last    = manager.get("lastName", "")
        name    = f"{first} {last}".strip() or manager.get("emailAddress", "Unknown")

        dm = m.get("directReportsMetrics", [])
        listened = sum(len(r.get("metrics", {}).get("callsListenedTo", []))           for r in dm)
        attended = sum(len(r.get("metrics", {}).get("callsManagerAttended", []))      for r in dm)
        feedback = sum(len(r.get("metrics", {}).get("callsWithFeedback", []))         for r in dm)
        comments = sum(len(r.get("metrics", {}).get("callsManagerCommentedOn", []))   for r in dm)
        scored   = sum(len(r.get("metrics", {}).get("callsWithScorecardFilled", []))  for r in dm)

        hit_target = scored >= CALLS_TARGET
        status = "✅" if hit_target else "❌"
        if not hit_target:
            missed.append(name)

        rows.append(
            f"{status} *{name}*\n"
            f"   Listened: {listened} | Attended: {attended} | "
            f"Feedback: {feedback} | Comments: {comments} | Scored: *{scored}*"
        )

    summary_line = (
        f"*{len(coaching_data) - len(missed)}/{len(coaching_data)}* managers hit the \u2265{CALLS_TARGET} calls scored target."
        if coaching_data else "No coaching data found for this period."
    )
    missed_line = (
        f"\n\u26a0\ufe0f *Missed target:* {', '.join(missed)}" if missed else "\n\U0001f389 All managers hit the target!"
    )
    body = "\n\n".join(rows) if rows else "_No data returned from Gong._"

    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "\U0001f4ca Weekly Gong Coaching Report", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Period:* {from_label} \u2192 {to_label}\n{summary_line}{missed_line}"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Target: \u2265{CALLS_TARGET} calls scored per manager per week"}]},
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
    print(f"Got {len(coaching_data)} manager records.")
    payload = build_slack_message(coaching_data, from_dt, to_dt)
    post_to_slack(payload)

if __name__ == "__main__":
    main()
