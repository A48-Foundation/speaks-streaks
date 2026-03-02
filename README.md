# sQuolingo Speaks Streaks 🔥

Track consecutive speaking streaks for debate team members using a Notion database, and announce them automatically to Discord via Zapier.

## Overview

Each debater has a daily Notion page with a **"Did you speak today?"** task. The system:

1. **Calculates** each person's consecutive "Yes" streak and writes it back to Notion
2. **Displays** a formatted leaderboard table in Discord

---

## Files

| File | Purpose |
|---|---|
| `update_streaks.py` | Calculates streaks and updates each assignee's `Streak` property in Notion |
| `display_streaks.py` | Reads the `Streak` property from Notion and builds a Discord-formatted table |
| `zapier_streaks.py` | All-in-one: calculates streaks, updates Notion, **and** outputs the Discord table |
| `squolingo.py` | Local development/testing script — dumps Notion data to `db.json` |
| `.env` | Stores `NOTION_TOKEN` and `DATABASE_ID` (not committed to git) |

---

## Zapier Flow — sQuolingo Announcer

The Zap runs on a daily schedule and sends streak leaderboards to Discord twice (morning + evening check-in).

```
┌─────────────────────────────────────────┐
│  1. Schedule by Zapier                  │
│     Reminder at 9 AM                    │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  2. Code by Zapier — Calculate Streaks  │
│     Paste: update_streaks.py            │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  3. Code by Zapier — Display Streaks    │
│     Paste: display_streaks.py           │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  4. Discord — Send Channel Message      │
│     Message Body: Step 3's table output │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  5. Delay by Zapier — Delay For         │
│     Wait until evening check-in         │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  6. Code by Zapier — Display Streaks    │
│     Paste: display_streaks.py           │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  7. Discord — Send Channel Message      │
│     Message Body: Step 6's table output │
└─────────────────────────────────────────┘
```

### Step-by-Step Setup

#### 1. Schedule by Zapier
- **Trigger:** Every Day
- **Time:** 9:00 AM (or your preferred morning time)

#### 2. Code by Zapier — Calculate Streaks
- **Action:** Run Python
- **Code:** Paste the contents of `update_streaks.py`
- **Input Data:** None required (token and database ID are hardcoded in the script)
- **What it does:** Fetches all pages from Notion, computes each debater's current streak, and PATCHes the `Streak` number property on their most recent page. Skips updates where the streak hasn't changed.

> ⚠️ **For Zapier:** Since Zapier's Code step can't read `.env` files, you must **hardcode** `NOTION_TOKEN` and `DATABASE_ID` directly in the script. Replace the `load_dotenv()` / `os.environ` lines with:
> ```python
> NOTION_TOKEN = "your_token_here"
> DATABASE_ID = "your_database_id_here"
> ```

#### 3. Code by Zapier — Display Streaks
- **Action:** Run Python
- **Code:** Paste the contents of `display_streaks.py`
- **Input Data:** None required
- **What it does:** Reads each assignee's `Streak` number from their most recent Notion page and formats a Discord-friendly leaderboard table.
- **Output:** `table` (the formatted code block) and `streaks_json`

#### 4. Discord — Send Channel Message
- **Channel:** Your announcements/streaks channel
- **Message Body:** Map to **Step 3 → Table** output
- The message will look like:
  ```
  Debater              Streak
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Neo Cai 🔥               12
  Jerry Song 🔥              7
  Oliver Chen                0
  ```

#### 5. Delay by Zapier
- **Delay For:** Set to however long you want between the morning and evening announcements (e.g., 10 hours)

#### 6. Code by Zapier — Display Streaks (again)
- Same as Step 3 — paste `display_streaks.py` again
- This re-reads streaks from Notion so it picks up any changes made during the day

#### 7. Discord — Send Channel Message
- Same as Step 4 — map to **Step 6 → Table** output

---

## Notion Database Setup

The Notion database is a **calendar-style recurring task board**. A new page is automatically created every day for each debater who has opted in, asking "Did you speak today?" Debaters mark their page `Yes` or `No`, and the scripts read those responses to calculate streaks.

### 1. Create the Database

1. In Notion, create a new **Database — Full page**
2. Switch the view to **Calendar** (by `Due date`) so you can see daily entries at a glance
3. Copy the **database ID** from the URL — it's the 32-character hex string after your workspace name:
   ```
   https://www.notion.so/yourworkspace/30f8d3b7301c800db7a2eac33f994ea4?v=...
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   ```
   Format it with hyphens for the API: `30f8d3b7-301c-800d-b7a2-eac33f994ea4`

### 2. Required Properties

Every page in the database must have these properties. The scripts depend on the **exact property names** listed below:

| Property | Type | Required | How It's Used |
|---|---|---|---|
| `Task name` | **Title** | ✅ | The page title (e.g., "Did you speak today?"). Typically the same for every page. |
| `Assignee` | **People** | ✅ | The debater this page belongs to. The scripts group pages by assignee to calculate per-person streaks. |
| `Status` | **Status** | ✅ | Must have **`Yes`** and **`No`** as status options. Debaters set this to `Yes` when they've spoken that day. This is the core input the streak calculation reads. |
| `Due date` | **Date** | ✅ | The date this page is for. Used to sort pages chronologically and determine which page is "most recent." Set this to the current day when the page is created. |
| `Streak` | **Number** | ✅ | **Auto-updated by the scripts** — do not fill in manually. `update_streaks.py` writes the calculated streak count here. `display_streaks.py` reads from here to build the leaderboard. |


### 3. Set Up Recurring Pages

To automatically create a page every day for each debater:

1. **Use Notion's built-in recurring templates:**
   - Open the database → click **New** dropdown → **+ New template**
   - Set the template title to "Did you speak today?"
   - Set `Status` default to `No`
   - Set `Due date` to `Today`
   - Click the **⟳ Repeat** option and set it to **Daily**
   - Assign it to a specific debater via `Assignee`
   - Create one recurring template per debater

2. **Or use a Notion automation:**
   - Database → **Automations** → **New automation**
   - Trigger: "When a page property matches a condition" or use a schedule-based trigger
   - Action: Create a new page with the default properties filled in

### 4. Connect to the API

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) and create a new **internal integration**
2. Copy the **token** (starts with `ntn_`)
3. In your Notion database, click **⋯** → **Connections** → **Connect to** → select your integration
4. Store the token in your `.env` file (for local use) or hardcode it in the Zapier Code step

### 5. How the Scripts Use These Properties

```
Page created daily:
┌──────────────────────────────────────────────┐
│ Task name:  "Did you speak today?"           │
│ Assignee:   Neo Cai                          │
│ Due date:   2026-02-28                       │
│ Status:     No  ← debater changes to "Yes"   │
│ Streak:     0   ← script updates to 12       │
└──────────────────────────────────────────────┘

update_streaks.py logic:
  1. Fetches all pages, groups by Assignee
  2. Sorts each person's pages by Due date (newest first)
  3. Reads the Streak number from the 2nd most recent page
  4. If the most recent page Status = "Yes" → new streak = previous + 1
  5. If "No" and today's page → grace period (carries streak if yesterday was "Yes")
  6. If "No" and past page → streak resets to 0
  7. PATCHes the Streak property on the most recent page

display_streaks.py logic:
  1. Fetches all pages, finds each person's most recent page
  2. Reads the Streak number directly (no recalculation)
  3. Formats a sorted leaderboard table for Discord
```

---

## Local Development

To run scripts locally (not on Zapier):

1. Clone the repo
2. Create a `.env` file in the project root:
   ```
   NOTION_TOKEN=ntn_your_token_here
   DATABASE_ID=30f8d3b7-301c-800d-b7a2-eac33f994ea4
   ```
3. Install dependencies:
   ```
   pip install requests python-dotenv
   ```
4. Run:
   ```
   python update_streaks.py     # Calculate & update streaks
   python display_streaks.py    # Generate Discord table
   ```

---

