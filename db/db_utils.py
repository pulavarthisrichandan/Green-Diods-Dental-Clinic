from datetime import time as dt_time

CLINIC_START = dt_time(9, 0)   # 9:00 AM
CLINIC_END   = dt_time(18, 0)  # 6:00 PM

def is_within_clinic_hours(t: dt_time) -> bool:
    return CLINIC_START <= t <= CLINIC_END
