from zoneinfo import ZoneInfo
from datetime import datetime

TIMEZONE_BRT = ZoneInfo("America/Sao_Paulo")

def _days_waiting(reviewed_at):
    # Waiting time counted from APPROVAL (reviewed_at), not creation — a photo shouldn't be
    # penalized for how long manual approval took. reviewed_at is text in SQLite; parse it
    # and treat a naive timestamp as BRT so the subtraction against an aware "now" is safe.
    if not reviewed_at:
        return 0

    try:
        moment = reviewed_at if isinstance(reviewed_at, datetime) else datetime.fromisoformat(reviewed_at)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=TIMEZONE_BRT)

        return (datetime.now(TIMEZONE_BRT) - moment).days

    except Exception as e:
        print(f"Error computing wait time from {reviewed_at}: {e}.")
        return 0

def priority_sort(item):
    # Priority: quality (ai_score) leads most of the time, but a photo waiting >= 7 days since
    # approval is promoted to the top tier alongside `urgent` so nothing is forgotten in the queue.
    urgent = item.get('urgent') is not None
    days_waiting = _days_waiting(item.get('reviewed_at'))
    expiring = days_waiting >= 7

    ai_score = item.get('ai_score') or 0
    copies = int(item.get('copies') or 0)

    return (urgent or expiring, ai_score, days_waiting, -copies)


# Prior code (Phase 1 — R2 last_modified queue-age proxy, before the DB carried reviewed_at/ai_score)
# def priority_sort(item):
#     urgent = item.get('urgent') is not None
#     date_raw = item.get('date') or ""
#     last_modified_raw = item.get('last_modified') or datetime.now(TIMEZONE_BRT)
#     date = date_raw if date_raw else last_modified_raw.strftime('%y%m%d')
#     copies = int(item.get('copies') or 0)
#     days_waiting = (datetime.now(TIMEZONE_BRT) - last_modified_raw).days
#     expiring = days_waiting >= 7
#     return (urgent or expiring, date, days_waiting, -copies)

# Prior code (original — no queue-age factor, old photos only decayed)
# def priority_sort(item):
#     urgent = item.get('urgent') is not None
#     date_raw = item.get('date') or ""
#     last_modified_raw = item.get('last_modified') or datetime.now(TIMEZONE_BRT)
#     date = date_raw if date_raw else last_modified_raw.strftime('%y%m%d')
#     # Convert to timestamp and negate for propely sorting (as i'm using reverse=True)
#     last_modified = -last_modified_raw.timestamp()
#     copies = int(item.get('copies') or 0)
#     # Change this priority order logic later
#     return (urgent, date, last_modified, -copies)