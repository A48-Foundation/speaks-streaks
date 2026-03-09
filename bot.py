"""sQuolingo Speaks Streaks — Discord Bot.

Sends morning/evening reminders, handles 🔥 (spoke) and 🧊 (freeze) reactions,
and keeps Notion streak data in sync.
"""

import os
import json
import logging
from datetime import datetime, time, date, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import notion_client as notion

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
ROLE_ID = int(os.environ["LOCKED_IN_ROLE_ID"])
NOTION_LINK = os.environ["NOTION_LINK"]

PT = ZoneInfo("America/Los_Angeles")
BOT_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("squolingo")

# ─── Discord setup ────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Persistent data ─────────────────────────────────────────────────────────

def load_data() -> dict:
    try:
        with open(BOT_DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_data()


def _default_data() -> dict:
    return {
        "freeze_counts": {},
        "frozen_dates": {},
        "last_milestones": {},
        "morning_messages": [],
        "evening_messages": [],
        "last_page_statuses": {},
    }


def save_data(data: dict):
    with open(BOT_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── Streak computation ──────────────────────────────────────────────────────

def _group_by_assignee(pages: list) -> dict[str, list]:
    """Group pages by assignee name."""
    groups: dict[str, list] = {}
    for page in pages:
        for name in notion.get_assignee_names(page):
            groups.setdefault(name, []).append(page)
    return groups


def compute_streaks(frozen_dates_map: dict | None = None):
    """Efficient streak computation — reads stored Streak values from recent pages.

    Fetches only the last 14 days of pages so cost does not grow with DB size.
    Relies on process_previous_day() and the 🔥 handler keeping stored values
    accurate.
    """
    if frozen_dates_map is None:
        frozen_dates_map = {}

    today = datetime.now(PT).date()
    since = today - timedelta(days=14)
    recent_pages = notion.get_recent_pages(since)

    assignee_pages = _group_by_assignee(recent_pages)

    streaks = {}
    most_recent_pages = {}

    for assignee, page_list in assignee_pages.items():
        sorted_pages = sorted(page_list, key=notion.get_due_date, reverse=True)
        most_recent = sorted_pages[0]
        most_recent_date = notion.get_due_date(most_recent).date()
        most_recent_pages[assignee] = most_recent
        frozen = frozen_dates_map.get(assignee, set())

        if most_recent_date == today:
            if notion.get_status(most_recent) == "yes":
                # Today marked Yes — stored streak should already be correct
                streaks[assignee] = notion.get_streak(most_recent)
            else:
                # Today not done yet — carry previous page's streak
                if len(sorted_pages) > 1:
                    prev = sorted_pages[1]
                    prev_status = notion.get_status(prev)
                    prev_date = notion.get_due_date(prev).date()
                    if prev_status == "yes":
                        streaks[assignee] = notion.get_streak(prev)
                    elif prev_date.isoformat() in frozen:
                        streaks[assignee] = notion.get_streak(prev)
                    else:
                        streaks[assignee] = 0
                else:
                    streaks[assignee] = 0
        else:
            # Most recent page is a past day
            if notion.get_status(most_recent) == "yes":
                streaks[assignee] = notion.get_streak(most_recent)
            elif most_recent_date.isoformat() in frozen:
                streaks[assignee] = notion.get_streak(most_recent)
            else:
                streaks[assignee] = 0

    return streaks, most_recent_pages


def audit_streaks(frozen_dates_map: dict | None = None):
    """Full streak audit — walks every page from scratch.

    Fetches ALL pages. Use only for manual verification via the check command.
    """
    if frozen_dates_map is None:
        frozen_dates_map = {}

    pages = notion.get_all_pages()
    today = datetime.now(PT).date()

    assignee_pages = _group_by_assignee(pages)

    streaks = {}
    most_recent_pages = {}

    for assignee, page_list in assignee_pages.items():
        sorted_pages = sorted(page_list, key=notion.get_due_date, reverse=True)
        frozen = frozen_dates_map.get(assignee, set())

        streak = 0
        for page in sorted_pages:
            page_date = notion.get_due_date(page).date()
            status = notion.get_status(page)

            if page_date == today:
                if status == "yes":
                    streak += 1
                else:
                    continue  # Grace period for current day
            else:
                if status == "yes":
                    streak += 1
                elif page_date.isoformat() in frozen:
                    streak += 1
                else:
                    break

        streaks[assignee] = streak
        most_recent_pages[assignee] = sorted_pages[0] if sorted_pages else None

    return streaks, most_recent_pages


def process_previous_day(frozen_dates_map: dict | None = None):
    """Sync yesterday's Streak values on Notion pages.

    Called at the start of each morning reminder (and on startup) to ensure
    stored Streak properties are correct before the leaderboard is displayed.
    """
    if frozen_dates_map is None:
        frozen_dates_map = {}

    today = datetime.now(PT).date()
    yesterday = today - timedelta(days=1)
    since = today - timedelta(days=14)
    recent_pages = notion.get_recent_pages(since)

    assignee_pages = _group_by_assignee(recent_pages)

    for assignee, page_list in assignee_pages.items():
        sorted_pages = sorted(page_list, key=notion.get_due_date, reverse=True)
        frozen = frozen_dates_map.get(assignee, set())

        # Find yesterday's page and the page before it
        yesterday_page = None
        prev_page = None
        for i, page in enumerate(sorted_pages):
            page_date = notion.get_due_date(page).date()
            if page_date >= today:
                continue
            if page_date == yesterday:
                yesterday_page = page
                for j in range(i + 1, len(sorted_pages)):
                    prev_page = sorted_pages[j]
                    break
                break
            else:
                break  # No yesterday page for this debater

        if not yesterday_page:
            continue

        prev_streak = notion.get_streak(prev_page) if prev_page else 0
        status = notion.get_status(yesterday_page)

        if status == "yes":
            expected = prev_streak + 1
        elif yesterday.isoformat() in frozen:
            expected = prev_streak
        else:
            expected = 0

        current = notion.get_streak(yesterday_page)
        if current != expected:
            try:
                notion.update_page_streak(yesterday_page["id"], expected)
                log.info("Synced %s streak: %d → %d", assignee, current, expected)
            except Exception as e:
                log.error("Failed to sync streak for %s: %s", assignee, e)


def sync_all_streaks(frozen_dates_map: dict | None = None) -> int:
    """Full sync — walks ALL pages chronologically and fixes stored Streak values.

    Used for initial setup and manual audit corrections.  Returns the number
    of pages that were corrected.
    """
    if frozen_dates_map is None:
        frozen_dates_map = {}

    pages = notion.get_all_pages()
    today = datetime.now(PT).date()

    assignee_pages = _group_by_assignee(pages)
    fixed = 0

    for assignee, page_list in assignee_pages.items():
        sorted_pages = sorted(page_list, key=notion.get_due_date)  # oldest first
        frozen = frozen_dates_map.get(assignee, set())

        prev_streak = 0
        for page in sorted_pages:
            page_date = notion.get_due_date(page).date()
            status = notion.get_status(page)

            if page_date == today:
                if status == "yes":
                    expected = prev_streak + 1
                else:
                    continue  # Skip today's incomplete pages
            else:
                if status == "yes":
                    expected = prev_streak + 1
                elif page_date.isoformat() in frozen:
                    expected = prev_streak
                else:
                    expected = 0

            current = notion.get_streak(page)
            if current != expected:
                try:
                    notion.update_page_streak(page["id"], expected)
                    fixed += 1
                except Exception as e:
                    log.error("Sync fix failed for %s on %s: %s", assignee, page_date, e)

            prev_streak = expected

    return fixed


# ─── Display helpers ──────────────────────────────────────────────────────────

def fire_emojis(streak: int) -> str:
    """Return fire emoji string scaled by 10-day milestones.

    0       → ""
    1–9     → " 🔥"
    10–19   → " 🔥🔥"
    20–29   → " 🔥🔥🔥"   etc.
    """
    if streak <= 0:
        return ""
    count = (streak // 10) + 1
    return " " + "🔥" * count


def format_leaderboard(streaks: dict) -> str:
    """Build a Discord-friendly monospace leaderboard."""
    names = sorted(streaks.keys(), key=lambda n: streaks[n], reverse=True)

    # Calculate column width based on longest display entry
    max_visual = 0
    for name in names:
        emoji_count = (streaks[name] // 10) + 1 if streaks[name] > 0 else 0
        visual = len(name) + (1 + 2 * emoji_count if emoji_count > 0 else 0)
        max_visual = max(max_visual, visual)

    col_total = max(max_visual + 2 + 6, 32)  # min width 32

    lines = ["```"]
    header_pad = col_total - len("Debater") - len("Streak")
    lines.append("Debater" + " " * header_pad + "Streak")
    lines.append("━" * col_total)

    for name in names:
        s = streaks[name]
        emojis = fire_emojis(s)
        prefix = name + emojis
        num_str = str(s)
        emoji_count = (s // 10) + 1 if s > 0 else 0
        prefix_visual = len(name) + (1 + 2 * emoji_count if emoji_count > 0 else 0)
        pad = col_total - prefix_visual - len(num_str)
        lines.append(prefix + " " * max(pad, 1) + num_str)

    lines.append("```")
    return "\n".join(lines)


def get_milestone_shoutouts(streaks: dict) -> list[str]:
    """Return shoutout strings for debaters who just crossed a 10-day milestone."""
    data = load_data()
    last_milestones = data.get("last_milestones", {})
    shoutouts = []

    for name, streak in streaks.items():
        if streak == 0:
            last_milestones.pop(name, None)
            continue

        current_milestone = (streak // 10) * 10
        last = last_milestones.get(name, 0)

        if current_milestone >= 10 and current_milestone > last:
            shoutouts.append(
                f"🎉 Congrats to **{name}** for hitting a "
                f"**{current_milestone}-day** streak!"
            )
            last_milestones[name] = current_milestone

    data["last_milestones"] = last_milestones
    save_data(data)
    return shoutouts


# ─── Name matching ────────────────────────────────────────────────────────────

def match_display_name(display_name: str, assignee_names) -> str | None:
    """Case-insensitive match of a Discord display name to a Notion assignee."""
    lower = display_name.lower()
    for name in assignee_names:
        if name.lower() == lower:
            return name
    return None


def _all_notion_names(all_pages: list) -> set[str]:
    """Collect every unique assignee name across all pages."""
    names = set()
    for page in all_pages:
        names.update(notion.get_assignee_names(page))
    return names


# ─── Core reminder logic (called by tasks + startup catch-up) ─────────────────

async def send_morning_reminder():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.error("Could not find channel %s", CHANNEL_ID)
        return

    data = load_data()
    frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}

    # Sync yesterday's stored streak values before displaying
    process_previous_day(frozen_map)

    streaks, _ = compute_streaks(frozen_map)

    shoutouts = get_milestone_shoutouts(streaks)
    leaderboard = format_leaderboard(streaks)

    parts = [
        f"<@&{ROLE_ID}> Did you speak today? "
        f"Update your streak [here]({NOTION_LINK})!",
    ]
    if shoutouts:
        parts.append("")
        parts.extend(shoutouts)
    parts.append("Current Streaks:")
    parts.append(leaderboard)
    parts.append("")
    parts.append("React with 🧊 to freeze your streak.")

    sent = await channel.send("\n".join(parts))
    await sent.add_reaction("🧊")

    today_str = datetime.now(PT).date().isoformat()
    data = load_data()  # reload in case of concurrent writes
    data["morning_messages"].append({"id": sent.id, "date": today_str})
    data["morning_messages"] = data["morning_messages"][-14:]
    save_data(data)
    log.info("Morning reminder sent for %s", today_str)


async def send_evening_reminder():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.error("Could not find channel %s", CHANNEL_ID)
        return

    data = load_data()
    frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}

    streaks, _ = compute_streaks(frozen_map)
    leaderboard = format_leaderboard(streaks)

    parts = [
        f"<@&{ROLE_ID}> Did you speak today?",
        "Current Streaks:",
        leaderboard,
        "",
        "React with 🔥 if you did!",
    ]

    sent = await channel.send("\n".join(parts))
    await sent.add_reaction("🔥")

    today_str = datetime.now(PT).date().isoformat()
    data = load_data()
    data["evening_messages"].append({"id": sent.id, "date": today_str})
    data["evening_messages"] = data["evening_messages"][-14:]
    save_data(data)
    log.info("Evening reminder sent for %s", today_str)


# ─── Scheduled tasks ─────────────────────────────────────────────────────────

MORNING_TIME = time(hour=9, minute=0, tzinfo=PT)
EVENING_TIME = time(hour=21, minute=0, tzinfo=PT)
MIDNIGHT_TIME = time(hour=0, minute=30, tzinfo=PT)


@tasks.loop(time=MORNING_TIME)
async def morning_task():
    try:
        await send_morning_reminder()
    except Exception as e:
        log.exception("Error in morning reminder: %s", e)


@tasks.loop(time=EVENING_TIME)
async def evening_task():
    try:
        await send_evening_reminder()
    except Exception as e:
        log.exception("Error in evening reminder: %s", e)


@tasks.loop(time=MIDNIGHT_TIME)
async def midnight_task():
    """12:30 AM PT — process the day that just ended and reset poll cache."""
    try:
        data = load_data()
        frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}
        process_previous_day(frozen_map)

        # Clear cached statuses for the new day
        data = load_data()
        data["last_page_statuses"] = {}
        save_data(data)

        log.info("Midnight recalculation complete")
    except Exception as e:
        log.exception("Error in midnight task: %s", e)


@tasks.loop(minutes=2)
async def poll_notion_changes():
    """Poll Notion every 2 min for status changes on today's pages."""
    try:
        today = datetime.now(PT).date()
        today_pages = notion.get_pages_for_date(today)

        data = load_data()
        last_statuses = data.get("last_page_statuses", {})
        changed = False

        for page in today_pages:
            page_id = page["id"]
            current_status = notion.get_status(page)
            prev_status = last_statuses.get(page_id)

            if prev_status is None:
                # First time seeing this page — record without triggering
                last_statuses[page_id] = current_status
                changed = True
                continue

            if current_status == prev_status:
                continue

            last_statuses[page_id] = current_status
            changed = True

            names = notion.get_assignee_names(page)
            if not names:
                continue
            assignee = names[0]

            if current_status == "yes":
                # Debater marked Yes in Notion — compute and update streak
                since = today - timedelta(days=14)
                recent_pages = notion.get_recent_pages(since)
                debater_pages = sorted(
                    [p for p in recent_pages
                     if assignee in notion.get_assignee_names(p)],
                    key=notion.get_due_date,
                    reverse=True,
                )

                prev_streak = 0
                found_today = False
                for p in debater_pages:
                    if notion.get_due_date(p).date() == today:
                        found_today = True
                    elif found_today:
                        prev_streak = notion.get_streak(p)
                        break

                new_streak = prev_streak + 1
                notion.update_page_streak(page_id, new_streak)

                channel = bot.get_channel(CHANNEL_ID)
                if channel:
                    emojis = fire_emojis(new_streak)
                    await channel.send(
                        f"✅ **{assignee}** spoke today! "
                        f"Streak updated to **{new_streak}**!{emojis}"
                    )
                log.info("Poll: %s marked Yes — streak → %d", assignee, new_streak)

            elif prev_status == "yes":
                # Reverted from Yes — reset stored streak on this page
                notion.update_page_streak(page_id, 0)
                log.info("Poll: %s reverted from Yes — streak reset", assignee)

        if changed:
            data["last_page_statuses"] = last_statuses
            save_data(data)

    except Exception as e:
        log.exception("Error polling Notion: %s", e)


# ─── Reaction handlers ───────────────────────────────────────────────────────

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    if not payload.guild_id:
        return

    data = load_data()
    emoji = str(payload.emoji)

    evening_ids = {m["id"]: m["date"] for m in data.get("evening_messages", [])}
    morning_ids = {m["id"]: m["date"] for m in data.get("morning_messages", [])}

    if emoji == "🔥" and payload.message_id in evening_ids:
        await _handle_fire(payload, evening_ids[payload.message_id])
    elif emoji == "🧊" and payload.message_id in morning_ids:
        await _handle_freeze(payload, morning_ids[payload.message_id])


async def _handle_fire(payload: discord.RawReactionActionEvent, date_str: str):
    """🔥 reaction: mark page as Yes and update streak."""
    member = payload.member
    if not member:
        return

    channel = bot.get_channel(payload.channel_id)
    display_name = member.display_name
    target_date = date.fromisoformat(date_str)

    try:
        since = target_date - timedelta(days=14)
        recent_pages = notion.get_recent_pages(since)
        all_names = _all_notion_names(recent_pages)
        matched_name = match_display_name(display_name, all_names)

        if not matched_name:
            log.warning("No Notion match for Discord user '%s'", display_name)
            if channel:
                await channel.send(
                    f"⚠️ Couldn't find a Notion match for **{display_name}**. "
                    "Make sure your Discord display name matches your Notion name."
                )
            return

        # Find this debater's pages, sorted newest first
        debater_pages = sorted(
            [p for p in recent_pages if matched_name in notion.get_assignee_names(p)],
            key=notion.get_due_date,
            reverse=True,
        )

        # Locate target date page and previous page's streak
        debater_page = None
        prev_streak = 0
        found_target = False
        for p in debater_pages:
            p_date = notion.get_due_date(p).date()
            if p_date == target_date:
                debater_page = p
                found_target = True
            elif found_target:
                prev_streak = notion.get_streak(p)
                break

        if not debater_page:
            log.warning("No page found for %s on %s", matched_name, date_str)
            return

        if notion.get_status(debater_page) == "yes":
            return  # Already marked

        # Single API call: set status + streak together
        new_streak = prev_streak + 1
        notion.update_page_status_and_streak(debater_page["id"], "Yes", new_streak)

        if channel:
            emojis = fire_emojis(new_streak)
            await channel.send(
                f"✅ **{matched_name}**'s streak updated to **{new_streak}**!{emojis}"
            )

        log.info("🔥 %s marked Yes for %s — streak=%d", matched_name, date_str, new_streak)

    except Exception as e:
        log.exception("Error handling 🔥 for %s: %s", display_name, e)


async def _handle_freeze(payload: discord.RawReactionActionEvent, date_str: str):
    """🧊 reaction: record a streak freeze for the day."""
    member = payload.member
    if not member:
        return

    channel = bot.get_channel(payload.channel_id)
    display_name = member.display_name

    try:
        since = datetime.now(PT).date() - timedelta(days=14)
        recent_pages = notion.get_recent_pages(since)
        all_names = _all_notion_names(recent_pages)
        matched_name = match_display_name(display_name, all_names)

        if not matched_name:
            log.warning("No Notion match for Discord user '%s' (freeze)", display_name)
            if channel:
                await channel.send(
                    f"⚠️ Couldn't find a Notion match for **{display_name}**. "
                    "Make sure your Discord display name matches your Notion name."
                )
            return

        data = load_data()

        # Ensure structures exist
        if matched_name not in data.get("frozen_dates", {}):
            data.setdefault("frozen_dates", {})[matched_name] = []
        if matched_name not in data.get("freeze_counts", {}):
            data.setdefault("freeze_counts", {})[matched_name] = 0

        # Prevent double-freeze on the same day
        if date_str in data["frozen_dates"][matched_name]:
            total = data["freeze_counts"][matched_name]
            if channel:
                await channel.send(
                    f"❄️ **{matched_name}**, you already froze today! "
                    f"You have used **{total}** freeze{'s' if total != 1 else ''} in total."
                )
            return

        data["frozen_dates"][matched_name].append(date_str)
        data["freeze_counts"][matched_name] += 1
        save_data(data)

        total = data["freeze_counts"][matched_name]
        if channel:
            s = "s" if total != 1 else ""
            await channel.send(
                f"❄️ Streak frozen! **{matched_name}** has used "
                f"**{total}** freeze{s} in total."
            )

        log.info("🧊 %s froze streak for %s (total=%d)", matched_name, date_str, total)

    except Exception as e:
        log.exception("Error handling 🧊 for %s: %s", display_name, e)


# ─── Commands & mention handlers ─────────────────────────────────────────────

@bot.command(name="streaks")
async def streaks_cmd(ctx):
    """Display the current streak leaderboard."""
    try:
        data = load_data()
        frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}
        streaks, _ = compute_streaks(frozen_map)
        leaderboard = format_leaderboard(streaks)
        await ctx.send("Current Streaks:\n" + leaderboard)
    except Exception as e:
        log.exception("Error in !streaks command: %s", e)
        await ctx.send("⚠️ Error fetching streaks. Check the logs.")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Handle @mention commands (e.g. "@squolingo report scores")
    if bot.user and bot.user.mentioned_in(message) and not message.mention_everyone:
        content = message.content.lower()
        for mention in [f"<@{bot.user.id}>", f"<@!{bot.user.id}>"]:
            content = content.replace(mention, "").strip()

        if "report score" in content or "report streak" in content:
            await _cmd_report_scores(message)
        elif "check streak" in content:
            await _cmd_audit_streaks(message)
        elif "test reminder" in content:
            await _cmd_test_reminders(message)

    await bot.process_commands(message)


async def _cmd_report_scores(message):
    """@squolingo report scores — send the current leaderboard."""
    try:
        data = load_data()
        frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}
        streaks, _ = compute_streaks(frozen_map)
        leaderboard = format_leaderboard(streaks)
        await message.channel.send("Current Streaks:\n" + leaderboard)
    except Exception as e:
        log.exception("Error in report scores: %s", e)
        await message.channel.send("⚠️ Error fetching streaks.")


async def _cmd_audit_streaks(message):
    """@squolingo check streak calculations — full audit against all pages."""
    try:
        await message.channel.send(
            "🔍 Running full streak audit and syncing all pages..."
        )
        data = load_data()
        frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}

        # Full sync: walk ALL pages chronologically and fix stored Streak values
        fixed = sync_all_streaks(frozen_map)

        # Now compute streaks from the corrected data
        audited_streaks, _ = audit_streaks(frozen_map)

        all_names = sorted(
            audited_streaks.keys(),
            key=lambda n: audited_streaks.get(n, 0),
            reverse=True,
        )

        lines = ["**Streak Audit Results:**\n```"]
        lines.append(f"{'Debater':<28} {'Streak':>6}")
        lines.append("─" * 36)

        for name in all_names:
            audited = audited_streaks.get(name, 0)
            lines.append(f"{name:<28} {audited:>6}")

        lines.append("```")

        if fixed:
            lines.append(f"\n🔧 Fixed **{fixed}** page(s) with incorrect streak values.")
        else:
            lines.append("\n✅ All stored streaks were already correct!")

        leaderboard = format_leaderboard(audited_streaks)
        lines.append("\nCurrent Streaks:")
        lines.append(leaderboard)

        await message.channel.send("\n".join(lines))
    except Exception as e:
        log.exception("Error in audit: %s", e)
        await message.channel.send("⚠️ Error running streak audit.")


async def _cmd_test_reminders(message):
    """@squolingo test reminders — send both morning and evening reminders."""
    try:
        await message.channel.send("🧪 Sending test morning reminder...")
        await send_morning_reminder()
        await message.channel.send("🧪 Sending test evening reminder...")
        await send_evening_reminder()
        await message.channel.send("✅ Both test reminders sent!")
    except Exception as e:
        log.exception("Error in test reminders: %s", e)
        await message.channel.send("⚠️ Error sending test reminders.")


# ─── Bot startup ──────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)

    # Sync streaks on startup
    data = load_data()
    frozen_map = {k: set(v) for k, v in data.get("frozen_dates", {}).items()}

    if not data.get("morning_messages"):
        # First run ever — full sync of all pages
        log.info("First run detected — running full streak sync...")
        try:
            fixed = sync_all_streaks(frozen_map)
            log.info("Initial sync complete — fixed %d page(s)", fixed)
        except Exception as e:
            log.exception("Failed initial streak sync: %s", e)
    else:
        # Regular startup — sync yesterday only
        try:
            process_previous_day(frozen_map)
        except Exception as e:
            log.exception("Failed startup streak sync: %s", e)

    # Check if we missed today's reminders (e.g. bot was down)
    today_str = datetime.now(PT).date().isoformat()
    now = datetime.now(PT)

    morning_sent = any(
        m["date"] == today_str for m in data.get("morning_messages", [])
    )
    evening_sent = any(
        m["date"] == today_str for m in data.get("evening_messages", [])
    )

    if not morning_sent and now.hour >= 9:
        log.info("Missed morning reminder for %s — sending now", today_str)
        try:
            await send_morning_reminder()
        except Exception as e:
            log.exception("Failed catch-up morning reminder: %s", e)

    if not evening_sent and now.hour >= 21:
        log.info("Missed evening reminder for %s — sending now", today_str)
        try:
            await send_evening_reminder()
        except Exception as e:
            log.exception("Failed catch-up evening reminder: %s", e)

    # Start scheduled loops
    if not morning_task.is_running():
        morning_task.start()
    if not evening_task.is_running():
        evening_task.start()
    if not midnight_task.is_running():
        midnight_task.start()
    if not poll_notion_changes.is_running():
        poll_notion_changes.start()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
