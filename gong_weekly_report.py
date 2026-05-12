import os
import requests
import json
from datetime import datetime, timedelta, timezone
from base64 import b64encode

# ── Config from environment variables ────────────────────────────────────────
GONG_ACCESS_KEY    = os.environ["GONG_ACCESS_KEY"]
GONG_SECRET        = os.environ["GONG_SECRET"]
SLACK_WEBHOOK_URL  = os.environ["SLACK_WEBHOOK_URL"]
MANAGER_ID         = os.environ["GONG_MANAGER_ID"]       # top-level manager ID
WORKSPACE_ID       = os.environ.get("GONG_WORKSPACE_ID", "")  # optional

CALLS_TARGET = 10  # minimum calls scored per week

# ── Date range: last 7 days (Mon–Sun) ────────────────────────────────────────
def get_last_week_range():
    today = datetime.now(timezone.utc)
    # Last Monday 00:00 UTC → last Sunday 23:59 UTC
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return (
        last_monday.strftime("%Y-%m-%dT00:00:00Z"),
        last_sunday.strftime("%Y-%m-%dT23:59:59Z"),
    )

# ── Gong API helpers ──────────────────────────────────────────────────────────
def gong_auth_header():
    token = b64encode(f"{GONG_ACCESS_KEY}:{GONG_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def fetch_coaching_metrics(from_dt: str, to_dt: str) -> list[dict]:
    params = {
        "manager-id": MANAGER_ID,
        "from": from_dt,
        "to": to_dt,
    }
    if WORKSPACE_ID:
        params["workspace-id"] = WORKSPACE_ID

    url = "https://api.gong.io/v2/coaching"
    resp = requests.get(url, headers=gong_auth_header(), params=params, timeout=30)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Gong API error {resp.status_code}: {resp.text}"
        )

    data = resp.json()
    print(f"Raw API response keys: {list(data.keys())}")
    print(f"Full response: {json.dumps(data, indent=2)[:2000]}")  # first 2000 chars for debugging

    # Try common response keys
    return (
        data.get("teamActivity")
        or data.get("coachingData")
        or data.get("managers")
        or data.get("data")
        or []
    )

# ── Slack formatting ──────────────────────────────────────────────────────────
def build_slack_message(metrics: list[dict], from_dt: str, to_dt: str) -> dict:
    from_label = from_dt[:10]
    to_label   = to_dt[:10]

    rows = []
    missed = []

    for m in metrics:
        name       = m.get("userName", "Unknown")
        listened   = m.get("callsListened", 0)
        attended   = m.get("callsAttended", 0)
        feedback   = m.get("callsWithFeedback", 0)
        comments   = m.get("callsWithComments", 0)
        scored     = m.get("callsWithScorecards", 0)

        hit_target = scored >= CALLS_TARGET
        status     = "✅" if hit_target else "❌"

        if not hit_target:
            missed.append(name)

        rows.append(
            f"{status} *{name}*\n"
            f"   Listened: {listened} | Attended: {attended} | "
            f"Feedback: {feedback} | Comments: {comments} | Scored: *{scored}*"
        )

    summary_line = (
        f"*{len(metrics) - len(missed)}/{len(metrics)}* managers hit the >{CALLS_TARGET} calls scored target."
        if metrics else "No coaching data found for this period."
    )

    missed_line = (
        f"\n⚠️ *Missed target:* {', '.join(missed)}" if missed else "\n🎉 All managers hit the target!"
    )

    body = "\n\n".join(rows) if rows else "_No data returned from Gong._"

    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📊 Weekly Gong Coaching Report",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Period:* {from_label} → {to_label}\n{summary_line}{missed_line}",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Target: ≥{CALLS_TARGET} calls scored per manager per week",
                    }
                ],
            },
        ]
    }

def post_to_slack(payload: dict):
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Slack error {resp.status_code}: {resp.text}")
    print("✅ Slack message posted successfully.")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    from_dt, to_dt = get_last_week_range()
    print(f"Fetching Gong coaching metrics: {from_dt} → {to_dt}")

    metrics = fetch_coaching_metrics(from_dt, to_dt)
    print(f"Got {len(metrics)} manager records.")

    payload = build_slack_message(metrics, from_dt, to_dt)
    post_to_slack(payload)

if __name__ == "__main__":
    main()
