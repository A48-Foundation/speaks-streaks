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
and Embed Links permissions. **Manage Messages** is optional, but required
to remove existing user reactions from old reminders.

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
- Both 9 AM and 9 PM reminders use Spoke and Freeze buttons. Emoji reactions
  no longer modify streaks; the bot no longer adds reaction controls.
- Today's reminder cards are edited after actions. Existing reactions are
  cleared when permissions allow; otherwise only the bot's own are removed.
- Congratulations are sent only when an action reaches exactly 10, 20, 30, etc.
- Zero-streak debaters are hidden, not deleted: their schedules still exist.

## Live cards and milestones

Reminders now show a ranked Discord embed with one colored flame badge, progress
to the next major milestone, and today's speaking/freeze status. Zero streaks
stay hidden. Cards update after speaking, freezing, and schedule changes.

Flames intensify by streak: **red 1-49**, **orange 50-99**, and **blue 100+**.
Each uses a vibrant outer flame and contrasting inner flame. Rank is a plain
number, not another medal. The bot generates and reuses its own application
emojis at startup; no server emoji uploads are needed. If the emoji API is
unavailable, a standard flame plus the color's name is shown instead.

Persistent **Spoke**, **Freeze**, **My schedule**, and **My week** buttons
work after restarts. My schedule opens a form; My week shows a private
seven-day completion grid. Old reminder action buttons cannot backdate credit.
Mention commands still work; reaction controls have been retired.

Milestones at **50, 100, 200, 300**, and each later hundred get an original,
locally generated confetti GIF card. Other ten-day milestones retain a simple
congratulation. Duplicate actions and leaderboard refreshes do not replay
celebrations. GIF playback depends on the viewer's Discord motion settings.

The bot needs **Embed Links** permission in addition to the permissions above.
Use `@Squolingo test reminders` to preview both cards without granting speaking
credit or replaying milestone celebrations.

Flame silhouette: [Flaticon flame icon 8545117](https://www.flaticon.com/free-icon/flame_8545117).
The original creator is credited through this source link and in bot help;
the artwork is recolored for use inside this application, not offered as a
standalone icon resource. See `assets/flame-credit.txt` for source information.

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

### Repairing a verified total

Members with **Manage Server** permission can use
`@Squolingo repair @debater 232` (mention the actual debater).
This sets their current total, saves an audit record, and refreshes today's
reminders without issuing a milestone congratulation. Existing schedules and
today's speaking/freeze records are retained, so already-recorded speaking is
not counted twice. Unregistered debaters are created with commitments paused
and must set their own schedule afterward.

Use a total verified for the time you run the command. For example, the supplied
October transcript supports aanya at 232 through October 31; add any confirmed
speaking since then and account for any missed scheduled days before applying
that historical number.

The November 1 recovery runs once on startup and records its assumptions in
Discord state: aanya 232, Ethan 15, and Julia Ye 61 through October 31. Ethan
and Julia are assumed to have spoken daily October 26-31 at the user's request.
Already-recorded November 1 speaking adds one; existing schedules and today's
freezes are retained. Unregistered debaters keep repaired legacy values until
they choose a schedule. This automatic recovery is limited to November 1 to
avoid overriding later legitimate missed days. Subsequent restarts do not
reapply it.

## Tests

```text
python -m unittest discover -v
```
