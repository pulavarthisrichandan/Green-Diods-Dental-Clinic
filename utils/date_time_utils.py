"""
Date and Time Utilities - DentalBot v2
Handles all natural language date/time parsing.
"""

from datetime import datetime, date, time as dt_time, timedelta
import re

CLINIC_START = dt_time(9, 0)    # 9:00 AM
CLINIC_END   = dt_time(18, 0)   # 6:00 PM

WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
}

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12
}


def parse_date(date_str: str) -> date | None:
    """
    Parse natural language date string to date object.
    Handles: 'today', 'tomorrow', 'next Monday', '20 Feb',
             '20-02-2026', '2026-02-20', '20/02/2026', 'in 3 days'
    """
    if not date_str:
        return None

    today = date.today()
    s = date_str.lower().strip()

    if s == "today":          return today
    if s == "tomorrow":       return today + timedelta(days=1)
    if s in ("day after tomorrow", "day after tom"):
                               return today + timedelta(days=2)

    m = re.match(r"in (\d+) days?", s)
    if m:
        return today + timedelta(days=int(m.group(1)))

    m = re.match(r"(?:next|coming|this)?\s*(\w+day)", s)
    if m:
        day_name = m.group(1).lower()
        if day_name in WEEKDAY_NAMES:
            target_wd  = WEEKDAY_NAMES[day_name]
            current_wd = today.weekday()
            days_ahead = (target_wd - current_wd) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead)

    m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", date_str)
    if m:
        try:    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError: pass

    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if m:
        try:    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: pass

    m = re.match(r"(\d{1,2})\s+([a-zA-Z]+)", date_str)
    if m:
        month = MONTH_NAMES.get(m.group(2).lower()[:3])
        if month:
            try:
                year = today.year
                d = date(year, month, int(m.group(1)))
                if d < today:
                    d = date(year + 1, month, int(m.group(1)))
                return d
            except ValueError: pass

    m = re.match(r"([a-zA-Z]+)\s+(\d{1,2})", date_str)
    if m:
        month = MONTH_NAMES.get(m.group(1).lower()[:3])
        if month:
            try:
                year = today.year
                d = date(year, month, int(m.group(2)))
                if d < today:
                    d = date(year + 1, month, int(m.group(2)))
                return d
            except ValueError: pass

    return None


def parse_time(time_str: str) -> dt_time | None:
    """
    Parse natural language time string to time object.
    Handles: '3pm', '3:30 PM', '10am', '14:00', 'morning', 'afternoon'
    """
    if not time_str:
        return None

    s = time_str.lower().strip()

    period_hint = None
    if "morning"  in s: period_hint = "am"
    elif any(w in s for w in ["afternoon", "evening", "night"]): period_hint = "pm"

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if m:
        hour   = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm   = m.group(3) or period_hint

        if ampm == "pm" and hour != 12:   hour += 12
        elif ampm == "am" and hour == 12: hour = 0
        elif ampm is None and hour < 9:   hour += 12  # e.g. "6" → 6 PM

        try:    return dt_time(hour, minute)
        except ValueError: pass

    return None


def format_date_for_db(d: date) -> str:
    """Returns: '20-02-2026' — storage format."""
    return d.strftime("%d-%m-%Y")


def format_date_for_speech(d: date) -> str:
    """Returns: 'Friday, 20 February 2026' — spoken to user."""
    return d.strftime("%A, %d %B %Y")


def format_time_for_speech(t: dt_time) -> str:
    """Returns: '4:30 PM' — spoken to user."""
    return t.strftime("%I:%M %p").lstrip("0")


def is_within_clinic_hours(t: dt_time) -> bool:
    return CLINIC_START <= t <= CLINIC_END


def is_date_in_past(d: date) -> bool:
    return d < date.today()


def is_clinic_closed(d: date) -> tuple[bool, str]:
    """Returns (is_closed: bool, reason: str)."""
    wd = d.weekday()
    if wd == 5:
        return True, "We are closed on Saturdays. Our hours are Monday to Friday, 9 AM to 6 PM."
    if wd == 6:
        return True, "We are closed on Sundays. Our hours are Monday to Friday, 9 AM to 6 PM."
    return False, ""


def get_next_available_slot(
    from_date: date,
    from_time: dt_time,
    booked_slots: list
) -> tuple[date | None, dt_time | None]:
    """
    Find the nearest available 30-minute slot starting from given date/time.
    Searches up to 14 days forward.
    """
    check_date = from_date
    check_time = from_time

    for _ in range(14):
        closed, _ = is_clinic_closed(check_date)
        if not closed:
            t = check_time
            while t < CLINIC_END:
                if (check_date, t) not in booked_slots:
                    return check_date, t
                total_minutes = t.hour * 60 + t.minute + 30
                if total_minutes >= CLINIC_END.hour * 60:
                    break
                t = dt_time(total_minutes // 60, total_minutes % 60)

        check_date += timedelta(days=1)
        check_time  = CLINIC_START

    return None, None


def dob_to_db_format(dob_str: str) -> str:
    """
    Normalise DOB string to DD-MM-YYYY storage format.

    ✅ Handles ALL formats produced by normalize_dob() and speech input:
        "12 December 2006"   ← output of normalize_dob() — WAS BROKEN, NOW FIXED
        "12 Dec 2006"
        "12-12-2006"
        "12/12/2006"
        "2006-12-12"
    """
    if not dob_str:
        return ""

    # ✅ Full month name: "12 December 2006" or "12 Dec 2006"
    for fmt in ["%d %B %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(dob_str.strip(), fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue

    # Numeric formats: DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(dob_str.strip(), fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue

    # Last resort — return as-is
    return dob_str.strip()
