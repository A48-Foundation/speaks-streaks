"""Notion API client for sQuolingo Speaks Streaks bot."""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def get_all_pages():
    """Fetch all pages from the Notion database."""
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


def get_pages_for_date(target_date):
    """Fetch pages whose Due date matches the given date."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "page_size": 100,
        "filter": {
            "property": "Due date",
            "date": {"equals": target_date.isoformat()},
        },
    }
    results = []
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


def get_recent_pages(since_date):
    """Fetch pages with Due date on or after since_date, sorted newest first."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "page_size": 100,
        "filter": {
            "property": "Due date",
            "date": {"on_or_after": since_date.isoformat()},
        },
        "sorts": [{"property": "Due date", "direction": "descending"}],
    }
    results = []
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


def parse_datetime(value):
    """Parse a Notion datetime string into a datetime object."""
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


def get_due_date(page):
    """Get the due date (or created time) as a datetime."""
    due_start = (
        page.get("properties", {})
        .get("Due date", {})
        .get("date", {})
        .get("start")
    )
    if due_start:
        return parse_datetime(due_start)
    return parse_datetime(page.get("created_time"))


def get_status(page):
    """Get the status name of a page (lowercase, stripped)."""
    return (
        page.get("properties", {})
        .get("Status", {})
        .get("status", {})
        .get("name", "")
        .strip()
        .lower()
    )


def get_assignee_names(page):
    """Get list of assignee names for a page."""
    people = page.get("properties", {}).get("Assignee", {}).get("people", [])
    return [p["name"] for p in people if p.get("name")]


def get_streak(page):
    """Get the streak number from a page."""
    return page.get("properties", {}).get("Streak", {}).get("number") or 0


def update_page_status(page_id, status):
    """Update the Status property of a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": {"Status": {"status": {"name": status}}}}
    resp = requests.patch(url, json=payload, headers=HEADERS)
    if not resp.ok:
        raise Exception(
            f"Failed to update status on {page_id}: {resp.status_code} {resp.json()}"
        )


def update_page_streak(page_id, streak_value):
    """Update the Streak number property of a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": {"Streak": {"number": streak_value}}}
    resp = requests.patch(url, json=payload, headers=HEADERS)
    if not resp.ok:
        raise Exception(
            f"Failed to update streak on {page_id}: {resp.status_code} {resp.json()}"
        )


def update_page_status_and_streak(page_id, status, streak_value):
    """Update both Status and Streak on a Notion page in one call."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "Status": {"status": {"name": status}},
            "Streak": {"number": streak_value},
        }
    }
    resp = requests.patch(url, json=payload, headers=HEADERS)
    if not resp.ok:
        raise Exception(
            f"Failed to update page {page_id}: {resp.status_code} {resp.json()}"
        )
