"""When a cron fires next: the one piece of calendar arithmetic the scheduler and the admin
panel both need, so that what the panel says is due is what the scheduler will run."""

from datetime import datetime

from croniter import CroniterBadCronError, croniter


def next_slot(expression: str | None, now: datetime) -> datetime | None:
    """The next slot of a cron, or nothing for no schedule or one that does not parse."""
    if not expression:
        return None
    try:
        return croniter(expression, now).get_next(datetime)
    except (CroniterBadCronError, ValueError):
        return None
