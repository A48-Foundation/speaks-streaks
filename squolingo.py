import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Retrieves data for JSON file 
def get_pages(num_pages=None):
    """
    If num_pages is None, get all pages, otherwise just the defined number.
    """
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"

    get_all = num_pages is None
    page_size = 100 if get_all else num_pages

    payload = {"page_size": page_size}
    response = requests.post(url, json=payload, headers=headers)

    data = response.json()

    if not response.ok:
        print(f"Notion API error {response.status_code}: {data}")
        return []

    #Comment this out to dump all data to a file
    import json
    with open('db.json', 'w', encoding='utf8') as f:
       json.dump(data, f, ensure_ascii=False, indent=4)

    results = data["results"]
    while data["has_more"] and get_all:
        payload = {"page_size": page_size, "start_cursor": data["next_cursor"]}
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        if not response.ok:
            print(f"Notion API error {response.status_code}: {data}")
            break
        results.extend(data["results"])

    return results

pages = get_pages()

unique_assignees = sorted(
    {
        person["name"]
        for page in pages
        for person in page.get("properties", {}).get("Assignee", {}).get("people", [])
        if person.get("name")
    }
)

print(unique_assignees)


def get_due_date(page):
    due_date = page.get("properties", {}).get("Due date", {}).get("date", {})
    start = due_date.get("start")
    if start:
        try:
            return datetime.fromisoformat(start)
        except ValueError:
            pass

    created_time = page.get("created_time")
    if created_time:
        return datetime.fromisoformat(created_time.replace("Z", "+00:00"))

    return datetime.min


def get_status_name(page):
    return (
        page.get("properties", {})
        .get("Status", {})
        .get("status", {})
        .get("name", "")
    )


assignee_pages = {name: [] for name in unique_assignees}

for page in pages:
    people = page.get("properties", {}).get("Assignee", {}).get("people", [])
    for person in people:
        name = person.get("name")
        if name:
            assignee_pages.setdefault(name, []).append(page)

streaks = {}
for assignee, assignee_page_list in assignee_pages.items():
    sorted_pages = sorted(assignee_page_list, key=get_due_date, reverse=True)

    streak = 0
    for page in sorted_pages:
        status_name = get_status_name(page).strip().lower()
        if status_name == "yes":
            streak += 1
        else:
            break

    streaks[assignee] = streak

print(streaks)