"""
Phone Number Utilities - DentalBot v2
Accurately extracts Australian mobile numbers from spoken speech.

Handles:
    "zero four six two three six one seven eight nine"
    "0 4 6 2 3 6 1 7 8 9"
    "046 236 1789"
    "double four six two..."
    "+61 462 361 789"
"""

import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

"""
phone_utils.py — DentalBot v2
Handles phone number extraction from speech transcription and formatting.
"""

import re

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


def extract_phone_from_text(text: str) -> str:
    """
    Extract Australian mobile number from transcribed speech.

    Handles:
        "046-235-1799"               → "0462351799"
        "046 235 1799"               → "0462351799"
        "zero four six two three..." → "0462351799"
        "0462351799"                 → "0462351799"

    Always returns max 10 digits.
    """
    if not text:
        return ""

    text = text.lower().strip()

    # ── Try 1: pull raw digits directly ──────────────────────────
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) >= 8:
        return digits[:10]   # ← hard cap at 10 digits

    # ── Try 2: convert spoken words → digits ─────────────────────
    result = ""
    words  = text.split()
    i = 0
    while i < len(words):
        word = re.sub(r"[^\w]", "", words[i])

        # handle "double four" → "44"
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


def normalize_phone(phone: str) -> str:
    """Strip everything except digits, cap at 10."""
    if not phone:
        return ""
    return re.sub(r"[^\d]", "", str(phone))[:10]


def format_phone_for_speech(phone: str) -> str:
    """
    Format 10-digit Australian mobile for natural speech readback.
    Splits digit by digit so bot reads each number clearly.

    "0462351799" → "0 4 6 2 3 5 1 7 9 9"

    Reading digit-by-digit is clearest on phone calls —
    no ambiguity about grouping.
    """
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone))[:10]
    # Space every digit so bot reads each one individually
    return " ".join(list(digits))


def _gpt_extract_phone(text: str) -> str:
    """GPT-4o-mini fallback — only called when pattern matching fails."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract an Australian mobile phone number from the user's spoken text. "
                        "Australian mobiles start with 04 and are exactly 10 digits long. "
                        "The user may have spoken each digit individually or used words like 'zero', 'oh', 'double four'. "
                        "Return ONLY the 10 digits with no spaces, dashes, or any other text. "
                        "If you cannot confidently extract exactly 10 digits, return exactly: UNCLEAR"
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=15
        )
        result = response.choices[0].message.content.strip()
        digits = re.sub(r"[^\d]", "", result)
        return digits if len(digits) == 10 else ""
    except Exception:
        return ""


# def normalize_phone(phone: str) -> str:
#     """Strip all non-digit characters from phone number."""
#     return re.sub(r"[^\d]", "", str(phone)) if phone else ""


# def format_phone_for_speech(phone: str) -> str:
#     """
#     Format a 10-digit number for clear spoken readback.
#     '0462361789' → '0 4 6 2, 3 6 1, 7 8 9'
#     """
#     clean = normalize_phone(phone)
#     if len(clean) == 10:
#         return (
#             f"{clean[0]} {clean[1]} {clean[2]} {clean[3]}, "
#             f"{clean[4]} {clean[5]} {clean[6]}, "
#             f"{clean[7]} {clean[8]} {clean[9]}"
#         )
#     return phone


def phone_confirmation_prompt(extracted_phone: str) -> str:
    """Returns the bot's confirmation message for a given number."""
    formatted = format_phone_for_speech(extracted_phone)
    return f"I have your contact number as {formatted}. Is that correct?"


import re

MONTH_NAMES = {
    "1": "January",  "01": "January",
    "2": "February", "02": "February",
    "3": "March",    "03": "March",
    "4": "April",    "04": "April",
    "5": "May",      "05": "May",
    "6": "June",     "06": "June",
    "7": "July",     "07": "July",
    "8": "August",   "08": "August",
    "9": "September","09": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}

def normalize_dob(dob_str: str) -> str:
    """
    Cleans DOB string from speech input.
    - Strips ordinal suffixes: 12th -> 12, 1st -> 1, 3rd -> 3
    - Converts numeric months to names: 12/12/2006 -> 12 December 2006
    """
    if not dob_str:
        return dob_str

    dob_str = dob_str.strip()

    # Remove ordinal suffixes from day numbers (1st, 2nd, 3rd, 12th, 21st etc.)
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
