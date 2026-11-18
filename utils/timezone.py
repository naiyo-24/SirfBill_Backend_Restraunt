from datetime import datetime, timezone, timedelta, date
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

def get_current_time() -> datetime:
    """
    Returns the authoritative local server datetime (Indian Standard Time - Asia/Kolkata)
    as a clean naive datetime object for consistent database storage and query filtering.
    """
    return datetime.now(IST).replace(tzinfo=None)

def get_current_date() -> date:
    """
    Returns the current calendar date in Indian Standard Time (IST).
    Eliminates date-boundary drift between 12:00 AM and 5:30 AM.
    """
    return datetime.now(IST).date()

def format_ist_str(dt: datetime = None, format_str: str = "%d/%m/%Y %I:%M %p", from_utc: bool = False) -> str:
    """
    Formats a datetime into a human-readable IST string.
    If dt is naive and from_utc is False (default), it is treated as already in IST.
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        if from_utc:
            dt = dt.replace(tzinfo=timezone.utc).astimezone(IST)
        else:
            dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.strftime(format_str)
