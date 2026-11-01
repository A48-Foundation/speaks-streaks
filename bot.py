"""Discord-only speaking streaks with self-service schedules."""

import asyncio
import io
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from streaks import DAYS, new_person, parse_schedule, reconcile, record

load_dotenv()
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
ROLE_ID = int(os.environ["LOCKED_IN_ROLE_ID"])
PT = ZoneInfo("America/Los_Angeles")
STATE_MARKER = "Squolingo persistent state v1 - do not delete."
_state = None
_state_message = None
_state_revision = 0
_saved_revision = -1
_state_lock = asyncio.Lock()
_action_lock = asyncio.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("squolingo")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)


def today_pt():
    return datetime.now(PT).date()


def _default_data():
    return {
        "version": 2, "participants": {}, "legacy_scores": {},
        "frozen_dates": {}, "name_cache": {},
        "morning_messages": [], "evening_messages": [],
    }


def load_data():
    return json.loads(json.dumps(_state if _state is not None else _default_data()))


def save_data(data):
    global _state, _state_revision
    _state = json.loads(json.dumps(data))
    _state_revision += 1


def load_frozen_dates():
    return {k: set(v) for k, v in load_data().get("frozen_dates", {}).items()}


def save_frozen_dates(frozen_map):
    data = load_data()
    data["frozen_dates"] = {k: sorted(v) for k, v in frozen_map.items()}
    save_data(data)


def _read_legacy_table(content):
    if "Current Streaks:" not in content:
        return {}
    scores = {}
    for line in content.splitlines():
        match = re.fullmatch(r"\s*(.+?)\s+(\d+)\s*", line)
        if match:
            name = match[1].replace("🔥", "").strip()
            if name and name != "Debater":
                scores[name] = int(match[2])
    return scores


def _validate_state(data):
    if not isinstance(data, dict) or not isinstance(data.get("frozen_dates"), dict):
        raise ValueError("Invalid Discord state; refusing to reset it.")
    if data.get("version") not in (None, 1, 2):
        raise ValueError("Unsupported Discord state version.")
    if data.get("version") == 2:
        if not isinstance(data.get("participants"), dict):
            raise ValueError("Invalid participants.")
        for person in data["participants"].values():
            if not isinstance(person["streak"], int) or person["streak"] < 0:
                raise ValueError("Invalid streak.")
            if any(day not in range(7) for day in person["schedule"]):
                raise ValueError("Invalid schedule.")
            datetime.fromisoformat(person["processed_through"])
            if not isinstance(person["results"], dict):
                raise ValueError("Invalid speaking history.")


async def restore_discord_state(channel):
    global _state_message, _state, _state_revision, _saved_revision
    legacy = None
    scores = None
    score_day = None
    today = today_pt()
    async for message in channel.history(limit=None):
        if message.author.id != bot.user.id:
            continue
        if message.content == STATE_MARKER:
            if len(message.attachments) != 1:
                raise ValueError("Discord state attachment is missing.")
            data = json.loads(await message.attachments[0].read())
            _validate_state(data)
            _state_message = message
            if data.get("version") == 2:
                _state = data
                _state_revision = _saved_revision = 0
                return
            legacy = data
        # Use a completed day's leaderboard as the migration baseline.
        day = message.created_at.astimezone(PT).date()
        if scores is None and day < today:
            table = _read_legacy_table(message.content)
            if table:
                scores, score_day = table, day
        if legacy is not None and scores is not None:
            break
    data = _default_data()
    if legacy:
        for key in ("frozen_dates", "name_cache", "morning_messages", "evening_messages"):
            data[key] = legacy.get(key, data[key])
        data["legacy_freeze_counts"] = legacy.get("freeze_counts", {})
    data["legacy_scores"] = {
        name: {"streak": value, "date": score_day.isoformat()}
        for name, value in (scores or {}).items()
    }
    save_data(data)
    await persist_discord_state(channel)


async def persist_discord_state(channel=None):
    global _state_message, _saved_revision
    async with _state_lock:
        if _state is None or _saved_revision == _state_revision:
            return
        channel = channel or bot.get_channel(CHANNEL_ID)
        if channel is None:
            raise RuntimeError("Discord state channel unavailable.")
        revision = _state_revision
        payload = json.dumps(_state, ensure_ascii=True).encode("utf-8")
        attachment = discord.File(io.BytesIO(payload), filename="squolingo-state.json")
        try:
            if _state_message is None:
                _state_message = await channel.send(STATE_MARKER, file=attachment)
            else:
                await _state_message.edit(content=STATE_MARKER, attachments=[attachment])
        finally:
            attachment.close()
        _saved_revision = revision


def _reconcile_all(data, today):
    for person in data["participants"].values():
        reconcile(person, today)


def recover_october_totals(data, today):
    """Apply the supplied October baseline and explicitly assumed attendance once."""
    recovery_id = "october-2026-reset"
    if recovery_id in data.get("recoveries", {}):
        return False
    # Later dates require attendance after this verified recovery window.
    if today != date(2026, 11, 1):
        return False
    totals = {"aanya": 232, "Ethan": 15, "Julia Ye": 61}
    changes = []
    for name, total in totals.items():
        matched = False
        for user_id, person in data["participants"].items():
            identity = data.get("name_cache", {}).get(person["name"], person["name"])
            if identity.casefold() != name.casefold():
                continue
            previous = person["streak"]
            # The baseline ends yesterday; retain any credit already earned today.
            person["streak"] = total + (person["results"].get(today.isoformat()) == "yes")
            person["processed_through"] = (today - timedelta(days=1)).isoformat()
            changes.append({"user_id": user_id, "name": name, "previous": previous,
                            "total": person["streak"]})
            matched = True
        if not matched:
            key = next((key for key in data["legacy_scores"]
                        if key.casefold() == name.casefold()), name)
            previous = data["legacy_scores"].get(key, {}).get("streak", 0)
            data["legacy_scores"][key] = {"streak": total, "date": "2026-10-31"}
            changes.append({"name": name, "previous": previous, "total": total})
    data.setdefault("recoveries", {})[recovery_id] = {
        "baseline_date": "2026-10-31",
        "assumption": "Ethan and Julia spoke daily October 26-31, per user request.",
        "changes": changes,
    }
    return True


def format_leaderboard(data):
    rows = [(p["name"], p["streak"]) for p in data["participants"].values()]
    rows.extend((name, p["streak"]) for name, p in data["legacy_scores"].items())
    rows = sorted((row for row in rows if row[1] > 0), key=lambda row: (-row[1], row[0]))
    if not rows:
        return "No active streaks yet. Set your schedule with `!schedule daily`."
    lines = ["```", f"{'Debater':<40} Streak", "━" * 48]
    for index, (name, streak) in enumerate(rows):
        label = re.sub(r"[`\r\n]", "", name)[:32]
        label += " " + "🔥" * min(streak // 10 + 1, 24)
        line = f"{label:<40} {streak}"
        if len("\n".join(lines + [line])) > 1600:
            lines.append(f"... {len(rows) - index} more active streaks")
            break
        lines.append(line)
    return "\n".join(lines + ["```"])


def reminder_content(data):
    return (
        f"<@&{ROLE_ID}> Did you speak today? Current Streaks:\n"
        f"{format_leaderboard(data)}\n"
        "React with 🔥 if you spoke today! React with 🧊 to freeze your streak.\n"
        "Set your schedule: `!schedule daily` or `!schedule mon wed fri`."
    )


async def send_reminder(kind):
    async with _action_lock:
        channel = bot.get_channel(CHANNEL_ID)
        data = load_data()
        today = today_pt()
        _reconcile_all(data, today)
        save_data(data)
        await persist_discord_state(channel)
        sent = await channel.send(reminder_content(data))
        key = f"{kind}_messages"
        data[key].append({"id": sent.id, "date": today.isoformat()})
        data[key] = data[key][-14:]
        save_data(data)
        await persist_discord_state(channel)
        await sent.add_reaction("🔥")
        await sent.add_reaction("🧊")


async def send_morning_reminder():
    await send_reminder("morning")


async def send_evening_reminder():
    await send_reminder("evening")


async def refresh_reminders(channel, data):
    today = today_pt().isoformat()
    for key in ("morning_messages", "evening_messages"):
        for item in data[key]:
            if item["date"] == today:
                try:
                    message = await channel.fetch_message(item["id"])
                    await message.edit(content=reminder_content(data))
                except discord.NotFound:
                    continue
                except discord.HTTPException:
                    log.exception("Could not refresh reminder.")


def _legacy_match(member, data):
    names = data["legacy_scores"]
    cached = data.get("name_cache", {}).get(member.display_name)
    if cached in names:
        return cached
    display = member.display_name.casefold()
    ranked = []
    for name in names:
        value = name.casefold()
        score = 1 if value == display else (
            0.9 if value in display or display in value
            else SequenceMatcher(None, display, value).ratio()
        )
        ranked.append((score, name))
    ranked.sort(reverse=True)
    if ranked and ranked[0][0] >= 0.8:
        if len(ranked) == 1 or ranked[0][0] > ranked[1][0]:
            return ranked[0][1]
    return None


async def set_schedule(member, text, channel):
    days = parse_schedule(text)
    async with _action_lock:
        data = load_data()
        today = today_pt()
        person = data["participants"].get(str(member.id))
        if person is None:
            legacy_name = _legacy_match(member, data)
            baseline = data["legacy_scores"].pop(legacy_name, {"streak": 0})
            freeze_count = data.get("legacy_freeze_counts", {}).get(legacy_name, 0)
            person = new_person(member.display_name, days, today,
                                baseline["streak"], freeze_count)
            data["participants"][str(member.id)] = person
        else:
            reconcile(person, today)
            person["schedule"] = days
            person["name"] = member.display_name
        save_data(data)
        await persist_discord_state(channel)
    label = ", ".join(DAYS[day].title() for day in days) if days else "off (paused)"
    await channel.send(f"{member.mention} Schedule: **{label}** (Pacific time). "
                       f"Streak: **{person['streak']}**.")


async def handle_action(member, action, channel, reminder_date=None):
    async with _action_lock:
        today = today_pt()
        if reminder_date is not None and reminder_date != today.isoformat():
            await channel.send(f"{member.mention} That reminder's Pacific day has ended.")
            return
        data = load_data()
        person = data["participants"].get(str(member.id))
        if person is None:
            await channel.send(f"{member.mention} Set your schedule first: "
                               "`!schedule daily` or `!schedule mon wed fri`.")
            return
        person["name"] = member.display_name
        text, milestone = record(person, today, action)
        save_data(data)
        await persist_discord_state(channel)
        await refresh_reminders(channel, data)
        await channel.send(f"{member.mention} {text}")
        if milestone:
            await channel.send(f"🎉 Congrats to {member.mention} for hitting a "
                               f"**{person['streak']}-day** streak!")


async def repair_total(actor, argument, channel):
    permissions = actor.guild_permissions
    if not (permissions.administrator or permissions.manage_guild):
        await channel.send("Only members with Manage Server permission can repair totals.")
        return
    match = re.fullmatch(r"<@!?(\d+)>\s+(\d{1,7})", argument.strip())
    if not match:
        await channel.send("Usage: `@Squolingo repair @debater total`.")
        return
    user_id, total = int(match[1]), int(match[2])
    target = actor.guild.get_member(user_id)
    if target is None:
        try:
            target = await actor.guild.fetch_member(user_id)
        except discord.NotFound:
            await channel.send("That debater isn't in this server.")
            return
    if target.bot:
        await channel.send("Bot accounts cannot have speaking streaks.")
        return
    async with _action_lock:
        data = load_data()
        today = today_pt()
        person = data["participants"].get(str(user_id))
        if person is None:
            legacy_name = _legacy_match(target, data)
            baseline = data["legacy_scores"].pop(legacy_name, {"streak": 0})
            person = new_person(target.display_name, [], today, baseline["streak"])
            data["participants"][str(user_id)] = person
        else:
            reconcile(person, today)
        previous = person["streak"]
        person["streak"] = total
        data.setdefault("repairs", []).append({
            "user_id": str(user_id), "by": str(actor.id),
            "date": today.isoformat(), "previous": previous, "total": total,
        })
        data["repairs"] = data["repairs"][-100:]
        save_data(data)
        await persist_discord_state(channel)
        await refresh_reminders(channel, data)
    await channel.send(f"{target.mention} Streak repaired: **{previous} → {total}**. "
                       "Your schedule and today's recorded actions are unchanged. "
                       "If not registered, set your schedule to resume commitments.")


@bot.event
async def on_raw_reaction_add(payload):
    if _state_message is None or payload.channel_id != CHANNEL_ID or not payload.member:
        return
    if payload.member.bot:
        return
    emoji = str(payload.emoji)
    if emoji not in ("🔥", "🧊"):
        return
    data = load_data()
    reminders = {item["id"]: item["date"]
                 for key in ("morning_messages", "evening_messages")
                 for item in data[key]}
    if payload.message_id not in reminders:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if reminders[payload.message_id] != today_pt().isoformat():
        await channel.send(f"{payload.member.mention} React to today's reminder, "
                           "or use `!speak` / `!freeze`.")
        return
    await handle_action(payload.member, "yes" if emoji == "🔥" else "frozen",
                        channel, reminders[payload.message_id])


async def dispatch(member, text, channel):
    command, _, argument = text.strip().partition(" ")
    command = command.lower()
    if command == "help":
        await channel.send(
            "**Squolingo help**\n"
            "Mention me in this channel to use these commands:\n"
            "`@Squolingo schedule daily` - speak every day.\n"
            "`@Squolingo schedule mon, wed, fri` - choose any combination of "
            "`mon, tue, wed, thu, fri, sat, sun`.\n"
            "`@Squolingo schedule` - view your schedule.\n"
            "`@Squolingo schedule off` - pause without deleting your streak.\n"
            "`@Squolingo speak` - record speaking today.\n"
            "`@Squolingo freeze` - preserve today's streak without adding a day.\n"
            "`@Squolingo report scores` - show positive streaks.\n"
            "`@Squolingo test reminders` - send both reminders.\n"
            "`@Squolingo repair @debater total` - correct a verified total "
            "(Manage Server permission required).\n"
            "Both reminders accept 🔥 for speaking and 🧊 for a freeze. "
            "Repeat reactions count only once; reactions are kept.\n"
            "All schedules use Pacific time. Only missed scheduled days reset "
            "your streak, after the day ends. Unscheduled days do not change it.\n"
            "Set your own schedule before recording speaking. "
            "Commands also work with `!`, such as `!schedule daily`."
        )
    elif command == "repair":
        await repair_total(member, argument, channel)
    elif command == "schedule":
        if not argument:
            person = load_data()["participants"].get(str(member.id))
            label = ", ".join(DAYS[d].title() for d in person["schedule"]) if person else "not set"
            await channel.send(f"{member.mention} Schedule: {label or 'off'}. "
                               "Use `!schedule daily`, `!schedule mon wed fri`, or `!schedule off`.")
        else:
            try:
                await set_schedule(member, argument, channel)
            except ValueError as error:
                await channel.send(str(error))
    elif command in ("speak", "freeze"):
        await handle_action(member, "yes" if command == "speak" else "frozen", channel)
    elif command == "streaks" or text.lower() in ("report scores", "report streaks",
                                                "check streak calculations"):
        async with _action_lock:
            data = load_data()
            _reconcile_all(data, today_pt())
            save_data(data)
            await persist_discord_state(channel)
            await channel.send("Current Streaks:\n" + format_leaderboard(data))
    elif text.lower() == "test reminders":
        await send_morning_reminder()
        await send_evening_reminder()


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild or message.channel.id != CHANNEL_ID:
        return
    if _state_message is None:
        return
    content = message.content.strip()
    if content.startswith("!"):
        await dispatch(message.author, content[1:], message.channel)
    elif bot.user and bot.user.mentioned_in(message) and not message.mention_everyone:
        content = re.sub(rf"<@!?{bot.user.id}>", "", content).strip()
        await dispatch(message.author, content, message.channel)


@tasks.loop(time=time(hour=9, tzinfo=PT))
async def morning_task():
    try:
        await send_morning_reminder()
    except Exception:
        log.exception("Morning reminder failed.")


@tasks.loop(time=time(hour=21, tzinfo=PT))
async def evening_task():
    try:
        await send_evening_reminder()
    except Exception:
        log.exception("Evening reminder failed.")


@tasks.loop(time=time(hour=0, minute=30, tzinfo=PT))
async def midnight_task():
    await reconcile_task()


@tasks.loop(minutes=2)
async def reconcile_task():
    try:
        async with _action_lock:
            data = load_data()
            _reconcile_all(data, today_pt())
            if data != load_data():
                save_data(data)
            await persist_discord_state()
    except Exception:
        log.exception("Scheduled-day reconciliation failed; will retry.")


@tasks.loop(seconds=10)
async def persist_state_task():
    try:
        await persist_discord_state()
    except Exception:
        log.exception("Failed saving state to Discord; will retry.")


@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        log.error("Discord state channel unavailable.")
        return
    try:
        async with _action_lock:
            if _state_message is None:
                await restore_discord_state(channel)
            data = load_data()
            recovered = recover_october_totals(data, today_pt())
            _reconcile_all(data, today_pt())
            save_data(data)
            await persist_discord_state(channel)
        if recovered:
            await refresh_reminders(channel, data)
            await channel.send(
                "October streak recovery applied. Totals through October 31: "
                "**aanya 232 · Ethan 15 · Julia Ye 61**. "
                "Ethan and Julia's attendance was assumed complete as requested. "
                "Any speaking already recorded on November 1 is retained. "
                "Set your schedule with `@Squolingo schedule daily` or chosen weekdays."
            )
        now = datetime.now(PT)
        for kind, hour in (("morning", 9), ("evening", 21)):
            if now.hour >= hour and not any(
                item["date"] == now.date().isoformat()
                for item in load_data()[f"{kind}_messages"]
            ):
                await send_reminder(kind)
        for task in (morning_task, evening_task, midnight_task,
                     reconcile_task, persist_state_task):
            if not task.is_running():
                task.start()
    except Exception:
        log.exception("Startup failed; refusing to discard Discord state.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
