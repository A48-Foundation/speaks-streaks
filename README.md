# sQuolingo Speaks Streaks 🔥

Track consecutive speaking streaks for debate team members using a Notion database and a Discord bot.

## Overview

Each debater has scheduled Notion pages with a **"Did you speak today?"** task. The Discord bot:

1. **Morning reminder (9 AM PT):** Posts the streak leaderboard, milestone shoutouts, and a link to update Notion. Debaters can react with 🧊 to freeze their streak.
2. **Evening reminder (9 PM PT):** Posts the leaderboard and asks debaters to react with 🔥 if they spoke. The bot updates Notion and their streak automatically.
3. **Streak freezes:** Reacting with 🧊 preserves your streak for the day even if you don't speak.
4. **Milestone shoutouts:** Every 10-day milestone (10, 20, 30…) gets a shoutout, and the leaderboard shows extra 🔥 emojis.

---

## Files

| File | Purpose |
|---|---|
| `bot.py` | Discord bot — scheduled reminders, reaction handlers, streak logic |
| `notion_client.py` | Notion API helper module — fetch/update pages, statuses, streaks |
| `bot_data.json` | Persistent runtime data — freezes, message IDs, milestones |
| `requirements.txt` | Python dependencies |
| `update_streaks.py` | *(Legacy)* Standalone streak calculator for Zapier |
| `display_streaks.py` | *(Legacy)* Standalone leaderboard formatter for Zapier |
| `zapier_streaks.py` | *(Legacy)* All-in-one Zapier script |
| `squolingo.py` | Local dev/testing — dumps Notion data to `db.json` |
| `.env` | Tokens and config (not committed to git) |

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

### 5. How the Bot Uses These Properties

```
Page created daily:
┌──────────────────────────────────────────────┐
│ Task name:  "Did you speak today?"           │
│ Assignee:   Neo Cai                          │
│ Due date:   2026-02-28                       │
│ Status:     No  ← debater changes to "Yes"   │
│ Streak:     0   ← bot updates to 12          │
└──────────────────────────────────────────────┘

bot.py streak logic:
  1. Fetches all pages, groups by Assignee
  2. Sorts each person's pages by Due date (newest first)
  3. Walks backwards counting consecutive "Yes" pages
  4. Today's "No" is skipped (grace period — hasn't done it yet)
  5. Past "No" with 🧊 freeze counts as continued
  6. Past "No" without freeze breaks the streak
  7. Updates the Streak property on the most recent page
```

---

## Setup

### 1. Prerequisites
- Python 3.10+
- A Discord bot with **Message Content**, **Server Members**, and **Reactions** intents enabled
- A Notion integration connected to your database

### 2. Environment Variables

Create a `.env` file in the project root:
```
NOTION_TOKEN=ntn_your_token_here
DATABASE_ID=30f8d3b7-301c-800d-b7a2-eac33f994ea4
DISCORD_TOKEN=your_discord_bot_token
CHANNEL_ID=your_channel_id
LOCKED_IN_ROLE_ID=your_role_id
NOTION_LINK=https://www.notion.so/your_database_link
```

### 3. Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

### 4. Discord Bot Permissions

The bot requires these **Gateway Intents** (enable in the Discord Developer Portal):
- `MESSAGE_CONTENT`
- `GUILD_MEMBERS`
- `GUILD_MESSAGE_REACTIONS`

### 5. Commands

| Command | Description |
|---|---|
| `!streaks` | Display the current streak leaderboard on demand |

### 6. Reactions

| Emoji | On Message | Effect |
|---|---|---|
| 🔥 | Evening reminder | Marks your Notion page as "Yes" and updates your streak |
| 🧊 | Morning reminder | Freezes your streak for the day (prevents reset) |

### 7. Streak Rules

- **Schedule-aware:** Only days where you have a Notion page count. No page = no change.
- **Grace period:** Today's "No" just means you haven't done it yet — your streak stays.
- **Reset:** If a past day's page is still "No" (and no freeze), your streak resets to 0.
- **Freeze:** 🧊 protects your streak for one day. Uses are tracked.
- **Milestones:** Every 10-day milestone (10, 20, 30…) gets a shoutout and an extra 🔥 in the leaderboard.
- **Fire scaling:** 1–9 days = 🔥, 10–19 = 🔥🔥, 20–29 = 🔥🔥🔥, etc.

---

