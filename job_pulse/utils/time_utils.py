from datetime import datetime, timezone, timedelta
from typing import Optional, Union

# Indian Standard Time (IST) is UTC + 05:30
IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET, name="IST")


def get_ist_now() -> datetime:
    """Return the current datetime in Indian Standard Time (IST, UTC+05:30)."""
    return datetime.now(IST_TZ)


def get_ist_iso() -> str:
    """Return current IST timestamp in ISO 8601 format (e.g. '2026-08-25T11:30:00+05:30')."""
    return get_ist_now().isoformat()


def get_ist_sheet_timestamp() -> str:
    """Return current IST timestamp formatted for Google Sheets (e.g. '2026-08-25 11:30:00 IST')."""
    return get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")


def get_ist_display(dt_or_str: Optional[Union[datetime, str]] = None) -> str:
    """
    Format a datetime object or ISO string into a clean Indian display format:
    e.g. '25 Aug 2026, 11:30 AM IST'.
    """
    if not dt_or_str:
        dt = get_ist_now()
    elif isinstance(dt_or_str, datetime):
        if dt_or_str.tzinfo is None:
            dt = dt_or_str.replace(tzinfo=timezone.utc).astimezone(IST_TZ)
        else:
            dt = dt_or_str.astimezone(IST_TZ)
    elif isinstance(dt_or_str, str):
        s = dt_or_str.strip()
        if not s or s.lower() in ["never", "none", "null", ""]:
            return "Never"
        try:
            # Handle ISO string (e.g. '2026-08-25T05:30:00Z' or '2026-08-25T05:30:00')
            cleaned = s.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None:
                # If no tzinfo, assume it was stored as UTC
                dt = parsed.replace(tzinfo=timezone.utc).astimezone(IST_TZ)
            else:
                dt = parsed.astimezone(IST_TZ)
        except Exception:
            return s
    else:
        return str(dt_or_str)

    return dt.strftime("%d %b %Y, %I:%M %p IST")
