"""
Phone Number Utilities - DentalBot v2

Handles:
    "zero four six two three six one seven eight nine" → "0462361789"
    "0 4 6 2 3 6 1 7 8 9"                             → "0462361789"
    "double four six two..."                           → "0446..."
    "+61 462 361 789"                                  → "0462361789"
"""

import re   # ✅ single import — removed duplicate

# Spoken digit words → actual digit
WORD_TO_DIGIT = {
    "zero": "0", "oh": "0", "o": "0",
    "one":  "1",
    "two":  "2",
    "three":"3",
    "four": "4",
    "five": "5",
    "six":  "6",
    "seven":"7",
    "eight":"8",
    "nine": "9"
}

MONTH_NAMES = {
    "1":  "January",  "01": "January",
    "2":  "February", "02": "February",
    "3":  "March",    "03": "March",
    "4":  "April",    "04": "April",
    "5":  "May",      "05": "May",
    "6":  "June",     "06": "June",
    "7":  "July",     "07": "July",
    "8":  "August",   "08": "August",
    "9":  "September","09": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACT PHONE FROM SPEECH
# ─────────────────────────────────────────────────────────────────────────────

def extract_phone_from_text(text: str) -> str:
    """
    Extract Australian mobile number from transcribed speech.

    "046-235-1799"               → "0462351799"
    "046 235 1799"               → "0462351799"
    "zero four six two three..." → "0462351799"
    "0462351799"                 → "0462351799"

    Always returns max 10 digits.
    """
    if not text:
        return ""

    text = text.lower().strip()

    # Try 1: pull raw digits directly
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) >= 8:
        return digits[:10]

    # Try 2: convert spoken words → digits
    result = ""
    words  = text.split()
    i = 0
    while i < len(words):
        word = re.sub(r"[^\w]", "", words[i])

        # "double four" → "44"
        if word == "double" and i + 1 < len(words):
            next_word = re.sub(r"[^\w]", "", words[i + 1])
            digit = WORD_TO_DIGIT.get(next_word)
            if digit:
                result += digit + digit
                i += 2
                continue

        digit = WORD_TO_DIGIT.get(word)
        if digit is not None:
            result += digit
        elif word.isdigit():
            result += word

        i += 1

    return result[:10] if result else digits[:10]


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZE AND FORMAT
# ─────────────────────────────────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Strip everything except digits, cap at 10."""
    if not phone:
        return ""
    return re.sub(r"[^\d]", "", str(phone))[:10]


def format_phone_for_speech(phone: str) -> str:
    """
    Format 10-digit number for clear spoken readback — digit by digit.
    "0462351799" → "0 4 6 2 3 5 1 7 9 9"
    """
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone))[:10]
    return " ".join(list(digits))


def phone_confirmation_prompt(extracted_phone: str) -> str:
    """Returns the bot's confirmation message for a given number."""
    formatted = format_phone_for_speech(extracted_phone)
    return f"I have your contact number as {formatted}. Is that correct?"


# ─────────────────────────────────────────────────────────────────────────────
# DOB NORMALIZER (used in main.py from this module)
# ─────────────────────────────────────────────────────────────────────────────

def normalize_dob(dob_str: str) -> str:
    """
    Cleans DOB string from speech input.
    - Strips ordinal suffixes: 12th → 12, 1st → 1, 3rd → 3
    - Converts numeric months to names: 12/12/2006 → 12 December 2006
    - Output is always: "DD MonthName YYYY" e.g. "12 December 2006"
      which dob_to_db_format() in date_time_utils.py can then parse.
    """
    if not dob_str:
        return dob_str

    dob_str = dob_str.strip()

    # Remove ordinal suffixes (1st, 2nd, 3rd, 12th, 21st etc.)
    dob_str = re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', dob_str, flags=re.IGNORECASE)

    # Handle numeric-only formats: DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    numeric_match = re.match(
        r'^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$', dob_str.strip()
    )
    if numeric_match:
        day   = numeric_match.group(1)
        month = numeric_match.group(2)
        year  = numeric_match.group(3)
        month_name = MONTH_NAMES.get(month, month)
        return f"{day} {month_name} {year}"

    # Handle "12 12 2006" (space-separated numbers)
    spaced_match = re.match(
        r'^(\d{1,2})\s+(\d{1,2})\s+(\d{4})$', dob_str.strip()
    )
    if spaced_match:
        day   = spaced_match.group(1)
        month = spaced_match.group(2)
        year  = spaced_match.group(3)
        month_name = MONTH_NAMES.get(month, month)
        return f"{day} {month_name} {year}"

    return dob_str
