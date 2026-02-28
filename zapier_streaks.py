import os
import json
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

# -----------------------------
# Code by Zapier — calls Notion API directly
# -----------------------------

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


# ---- Fetch all pages from the Notion database ----

def get_all_pages():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    results = []
    payload = {"page_size": 100}

    while True:
        resp = requests.post(url, json=payload, headers=HEADERS)
        data = resp.json()
        if not resp.ok:
            raise Exception(f"Notion API error {resp.status_code}: {data}")
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return results


# ---- Helpers ----

def _parse_datetime(value):
    if not value:
        return datetime.min
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text[:10])
    except ValueError:
        return datetime.min


def _get_due_or_created(page):
    due_start = (
        page.get("properties", {})
        .get("Due date", {})
        .get("date", {})
        .get("start")
    )
    if due_start:
        return _parse_datetime(due_start)
    return _parse_datetime(page.get("created_time"))


def _get_status_name(page):
    return (
        page.get("properties", {})
        .get("Status", {})
        .get("status", {})
        .get("name", "")
        .strip()
        .lower()
    )


def _compute_streaks(results):
    assignee_pages = {}
    for page in results:
        people = (
            page.get("properties", {})
            .get("Assignee", {})
            .get("people", [])
        )
        for person in people:
            name = person.get("name")
            if name:
                assignee_pages.setdefault(name, []).append(page)

    streaks = {}
    most_recent_page = {}
    today = datetime.now().date()
    for assignee, pages in assignee_pages.items():
        sorted_pages = sorted(pages, key=_get_due_or_created, reverse=True)
        if len(sorted_pages) == 1:
            streak = 1 if _get_status_name(sorted_pages[0]) == "yes" else 0
        else:
            prev_streak = sorted_pages[1].get("properties", {}).get("Streak", {}).get("number") or 0
            most_recent_date = _get_due_or_created(sorted_pages[0]).date()
            if most_recent_date == today:
                if _get_status_name(sorted_pages[0]) == "yes":
                    # Today is Yes: increment previous streak
                    streak = prev_streak + 1
                else:
                    # Today is not Yes yet: carry previous streak only if previous day was Yes
                    prev_status = _get_status_name(sorted_pages[1])
                    streak = prev_streak if prev_status == "yes" else 0
            else:
                # Past page: normal logic
                if _get_status_name(sorted_pages[0]) == "yes":
                    streak = prev_streak + 1
                else:
                    streak = 0
        streaks[assignee] = streak
        most_recent_page[assignee] = sorted_pages[0]
    return streaks, most_recent_page


def _update_streak_on_page(page_id, streak_value):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "Streak": {
                "number": streak_value
            }
        }
    }
    resp = requests.patch(url, json=payload, headers=HEADERS)
    if not resp.ok:
        raise Exception(f"Failed to update page {page_id}: {resp.status_code} {resp.json()}")


# ---- Run ----

results = get_all_pages()
streaks, most_recent_page = _compute_streaks(results)

# Update each assignee's most recent page — skip if streak is already correct
updates = []
for assignee, streak_val in streaks.items():
    page = most_recent_page[assignee]
    current = page.get("properties", {}).get("Streak", {}).get("number")
    if current != streak_val:
        updates.append((page["id"], streak_val))

# Run updates in parallel (up to 5 threads)
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(_update_streak_on_page, pid, val): pid for pid, val in updates}
    for f in as_completed(futures):
        f.result()  # raises if any update failed

names = sorted(streaks.keys(), key=lambda n: streaks[n], reverse=True)

# Build a Discord-friendly table
# Table width adapts to longest name; numbers are right-aligned to last '-'
max_display = 0
for name in names:
    entry = name + " !!" if streaks[name] > 0 else name  # "!!" placeholder = 2 visual chars for 🔥
    max_display = max(max_display, len(entry))

col_total = max_display + 2 + 6  # 2 gap + 6 for "Streak"

lines = []
lines.append("```")
lines.append("Debater" + " " * (col_total - len("Debater") - len("Streak")) + "Streak")
lines.append("━" * col_total)
for name in names:
    s = streaks[name]
    num_str = str(s)
    if s > 0:
        # Build line manually: name + " 🔥" + spaces + number
        # 🔥 displays as ~2 chars wide in monospace, so subtract 1 extra
        prefix = name + " 🔥"
        prefix_visual = len(name) + 1 + 2  # space + emoji(2 wide)
    else:
        prefix = name
        prefix_visual = len(name)
    pad = col_total - prefix_visual - len(num_str)
    lines.append(prefix + " " * max(pad, 1) + num_str)
lines.append("```")

table = "\n".join(lines)

output = {
    "table": table,
    "streaks_json": json.dumps(streaks),
}
