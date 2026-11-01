"""Schedule-aware streak rules, independent of Discord and external services."""

from datetime import date, timedelta

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FULL_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def parse_schedule(text):
    words = text.lower().replace(",", " ").split()
    if words == ["daily"]:
        return list(range(7))
    if words in (["off"], ["none"]):
        return []
    if not words:
        raise ValueError("Use daily, off, or weekdays such as mon wed fri.")
    days = []
    for word in words:
        if word not in DAYS + FULL_DAYS:
            raise ValueError(f"Unknown weekday: {word}")
        days.append(DAYS.index(word[:3]))
    return sorted(set(days))


def reconcile(person, today):
    """Expire only scheduled days, leaving today's incomplete commitment alone."""
    previous = date.fromisoformat(person["processed_through"])
    day = previous + timedelta(days=1)
    while day < today:
        if day.weekday() in person["schedule"]:
            if person["results"].get(day.isoformat()) not in ("yes", "frozen"):
                person["streak"] = 0
        day += timedelta(days=1)
    person["processed_through"] = max(previous, today - timedelta(days=1)).isoformat()
    cutoff = (today - timedelta(days=30)).isoformat()
    person["results"] = {k: v for k, v in person["results"].items() if k >= cutoff}


def record(person, today, action):
    reconcile(person, today)
    if today.weekday() not in person["schedule"]:
        return "Today isn't on your schedule; your streak is unchanged.", False
    key = today.isoformat()
    previous = person["results"].get(key)
    if previous == "yes":
        return "You've already recorded speaking today.", False
    if action == "frozen":
        if previous == "frozen":
            return "You've already frozen today's streak.", False
        person["results"][key] = "frozen"
        person["freeze_count"] += 1
        return f"Streak frozen at **{person['streak']}**.", False
    if action != "yes":
        raise ValueError("Unknown streak action.")
    person["results"][key] = "yes"
    person["streak"] += 1
    milestone = person["streak"] > 0 and person["streak"] % 10 == 0
    return f"Spoke today! Streak updated to **{person['streak']}**.", milestone


def new_person(name, schedule, today, streak=0, freeze_count=0):
    return {
        "name": name,
        "schedule": schedule,
        "streak": streak,
        "freeze_count": freeze_count,
        "results": {},
        "processed_through": (today - timedelta(days=1)).isoformat(),
    }
