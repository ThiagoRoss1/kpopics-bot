from zoneinfo import ZoneInfo
from datetime import datetime

TIMEZONE_BRT = ZoneInfo("America/Sao_Paulo")

def priority_sort(item):
    urgent = item.get('urgent') is not None
    date = item.get('date') or ""
    last_modified_raw = item.get('last_modified') or datetime.now(TIMEZONE_BRT)
    # Convert to timestamp and negate for propely sorting (as i'm using reverse=True)
    last_modified = -last_modified_raw.timestamp()
    copies = int(item.get('copies') or 0)
    
    return (urgent, date, last_modified, copies)