# sQuolingo Speaks Streaks

A Discord-only speaking streak bot. No Notion account, database, API token,
or Railway storage volume is required.

## Setup

Use Python 3.10+. Set these environment variables in Railway (or a local `.env`):

```text
DISCORD_TOKEN=your_bot_token
CHANNEL_ID=your_reminder_channel_id
LOCKED_IN_ROLE_ID=your_role_id
```

Enable Message Content and Server Members intents in the Discord Developer
Portal. Grant View Channel, Read Message History, Send Messages, Attach Files,
and Add Reactions permissions.

```text
pip install -r requirements.txt
python bot.py
```

Railway uses `Procfile` (`worker: python bot.py`).

## Self-service commands

Commands work only in the configured reminder channel. Each debater controls
their own schedule; registrations use Discord user IDs, not names.

| Command | Effect |
| --- | --- |
| `!schedule` | Show your schedule and setup instructions |
| `!schedule daily` | Schedule every day |
| `!schedule mon wed fri` | Schedule specific weekdays (commas/full names also accepted) |
| `!schedule off` | Pause commitments without deleting your streak |
| `!speak` | Record speaking today |
| `!freeze` | Freeze today's scheduled commitment |
| `!streaks` | Show positive streaks only |
| `!test reminders` | Send both reminders |

Mention commands also work: `@Squolingo schedule tue thu`,
`@Squolingo speak`, `@Squolingo report scores`, and
`@Squolingo test reminders`. `check streak calculations` reconciles expired
commitments without a historical rewrite.

Use **`@Squolingo help`** for in-channel instructions. The preferred schedule
syntax is `@Squolingo schedule daily` or
`@Squolingo schedule mon, tue, wed, thu, fri` (choose any listed weekdays).

## Streak rules

- All commitments use **America/Los_Angeles** dates, including daylight saving.
- A scheduled day marked spoken increments the streak once, immediately.
- Unscheduled days do not increment or reset the streak.
- An incomplete scheduled day resets the streak only after that Pacific day
  ends. Reconciliation runs at 12:30 AM, every two minutes, and before actions.
- A freeze preserves the streak without incrementing it. Speaking after a
  freeze increments once; repeating either action cannot grant extra credit.
- Changes to a schedule apply today onward, never rewriting past commitments.
- Both 9 AM and 9 PM reminders accept fire and ice-cube reactions. Reactions to
  old reminders cannot modify historical commitments.
- Today's reminder tables are edited after actions without removing reactions.
- Congratulations are sent only when an action reaches exactly 10, 20, 30, etc.
- Zero-streak debaters are hidden, not deleted: their schedules still exist.

## Discord persistence and migration

One bot message labeled `Squolingo persistent state v1 - do not delete.` holds
an attached state snapshot. The bot restores it on startup and updates it
before acknowledging schedule changes, speaking, and freezes. No runtime JSON
files are written to Railway.

Keep this message and its channel. Changing `CHANNEL_ID` requires transferring
the state message first. The snapshot contains participant IDs, names,
schedules, streaks, and recent speaking history, so it is visible to anyone
with access to the reminder channel. Corrupt state aborts startup rather than
silently discarding streaks. Failed saves are retried every 10 seconds.

The previous Discord-state format is migrated automatically. The most recent
completed day's reminder supplies legacy leaderboard values; these remain
visible until users register a schedule. Registration claims an unambiguous
name/cache match, preserving that value. No old Notion schedule is guessed.
Unmatched users start at zero.

Already-corrupted leaderboard values are **not** automatically repaired.
Migration preserves the available baseline, rather than claiming it can
reconstruct missing speaking or freeze history.

## Tests

```text
python -m unittest discover -v
```
