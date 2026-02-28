import os
import json
import requests
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

# -----------------------------
# Code by Zapier — displays streaks from Notion DB
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


# ---- Read streaks from most recent page per assignee ----

def _read_streaks(results):
    assignee_pages = defaultdict(list)
    for page in results:
        people = (
            page.get("properties", {})
            .get("Assignee", {})
            .get("people", [])
        )
        for person in people:
            name = person.get("name")
            if name:
                assignee_pages[name].append(page)

    streaks = {}
    for assignee, pages in assignee_pages.items():
        most_recent = max(pages, key=_get_due_or_created)
        streaks[assignee] = most_recent.get("properties", {}).get("Streak", {}).get("number") or 0

    return streaks


# ---- Run ----

results = get_all_pages()
streaks = _read_streaks(results)

names = sorted(streaks.keys(), key=lambda n: streaks[n], reverse=True)

# Build a Discord-friendly table
max_display = 0
for name in names:
    entry = name + " !!" if streaks[name] > 0 else name
    max_display = max(max_display, len(entry))

col_total = max_display + 2 + 6

lines = []
lines.append("```")
lines.append("Debater" + " " * (col_total - len("Debater") - len("Streak")) + "Streak")
lines.append("━" * col_total)
for name in names:
    s = streaks[name]
    num_str = str(s)
    if s > 0:
        prefix = name + " 🔥"
        prefix_visual = len(name) + 1 + 2
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
