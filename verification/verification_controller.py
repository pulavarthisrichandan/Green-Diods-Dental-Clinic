"""
Verification Controller - DentalBot v2

Manages the complete verification state machine for a call session.
Called by main.py on every user message until verification is complete.

Session keys used/written by this controller:
    verified            : bool
    patient_data        : dict  (patient record — internal, never shown to user)
    verification_step   : str   (current step in state machine)
    is_new_customer     : bool
    pending_*           : temporary values collected during the flow
"""

from utils.phone_utils import extract_phone_from_text, format_phone_for_speech
from utils.date_time_utils import dob_to_db_format
from utils.text_utils import title_case
from verification.verification_executor import (
    verify_by_lastname_dob,
    verify_by_lastname_dob_contact,
    create_new_patient
)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_verification(user_input: str, session: dict) -> dict:
    """
    Process one turn of the verification flow.

    Args:
        user_input : what the user just said
        session    : the call session dict (mutated in place)

    Returns:
        {
            "response"    : str   — what the bot should say
            "verified"    : bool  — True once verification is complete
            "patient_data": dict  — populated once verified, else None
            "done"        : bool  — True once this flow is finished
                                    (verified OR permanently failed)
        }
    """
    step = session.get("verification_step", "ask_new_or_existing")

    # ── Route to correct step handler ─────────────────────────────
    handlers = {
        "ask_new_or_existing":              _step_ask_new_or_existing,
        # Existing flow
        "existing_ask_lastname":            _step_existing_ask_lastname,
        "existing_ask_dob":                 _step_existing_ask_dob,
        "existing_disambiguate_contact":    _step_existing_disambiguate_contact,
        "existing_confirm_contact":         _step_existing_confirm_contact,
        # New patient flow
        "new_ask_firstname":                _step_new_ask_firstname,
        "new_ask_lastname":                 _step_new_ask_lastname,
        "new_ask_dob":                      _step_new_ask_dob,
        "new_ask_contact":                  _step_new_ask_contact,
        "new_confirm_contact":              _step_new_confirm_contact,
        "new_ask_insurance":                _step_new_ask_insurance,
    }

    handler = handlers.get(step)
    if handler:
        return handler(user_input, session)

    # Fallback — should never reach here
    session["verification_step"] = "ask_new_or_existing"
    return _not_understood(session)


# ─────────────────────────────────────────────────────────────────────────────
# STEP: ASK NEW OR EXISTING
# ─────────────────────────────────────────────────────────────────────────────

def _step_ask_new_or_existing(user_input: str, session: dict) -> dict:
    decision = _detect_new_or_existing(user_input)

    if decision == "existing":
        session["is_new_customer"]     = False
        session["verification_step"]   = "existing_ask_lastname"
        return _reply(
            "Welcome back! Could you please tell me your last name?",
            session
        )

    elif decision == "new":
        session["is_new_customer"]   = True
        session["verification_step"] = "new_ask_firstname"
        return _reply(
            "Great, let's get you set up! May I have your first name please?",
            session
        )

    else:
        # Unclear — ask again
        return _reply(
            "Are you a new patient with us, or have you visited us before?",
            session
        )


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING PATIENT STEPS
# ─────────────────────────────────────────────────────────────────────────────

def _step_existing_ask_lastname(user_input: str, session: dict) -> dict:
    session["pending_last_name"]   = user_input.strip()
    session["verification_step"]   = "existing_ask_dob"
    return _reply(
        "Thank you. And your date of birth please? "
        "You can say it as day, month, year — for example, 15 March 1990.",
        session
    )


def _step_existing_ask_dob(user_input: str, session: dict) -> dict:
    dob = _parse_spoken_dob(user_input)
    session["pending_dob"]       = dob
    session["verification_step"] = "noop"  # will be set inside

    result = verify_by_lastname_dob(session["pending_last_name"], dob)

    if result["status"] == "VERIFIED":
        session["pending_patient"]   = result
        session["verification_step"] = "existing_confirm_contact"
        masked = _mask_contact(result["contact_number"])
        return _reply(
            f"I found your record. To confirm your identity — "
            f"is your contact number {masked}?",
            session
        )

    elif result["status"] == "MULTIPLE_FOUND":
        session["verification_step"] = "existing_disambiguate_contact"
        return _reply(result["message"], session)

    elif result["status"] == "NOT_FOUND":
        session["verification_step"] = "ask_new_or_existing"
        return _reply(
            "I'm sorry, I couldn't find an account with that name and date of birth. "
            "Would you like to try again, or shall I create a new account for you?",
            session
        )

    else:
        session["verification_step"] = "ask_new_or_existing"
        return _reply(
            "I'm sorry, something went wrong on our end. "
            "Could you please try again?",
            session
        )


def _step_existing_disambiguate_contact(user_input: str, session: dict) -> dict:
    """Called when multiple patients share the same last_name + DOB."""
    phone = extract_phone_from_text(user_input)
    if not phone:
        return _reply(
            "I'm sorry, I didn't quite catch that. "
            "Could you please say your contact number again?",
            session
        )

    result = verify_by_lastname_dob_contact(
        session["pending_last_name"],
        session["pending_dob"],
        phone
    )

    if result["status"] == "VERIFIED":
        session["pending_patient"]   = result
        session["verification_step"] = "existing_confirm_contact"
        masked = _mask_contact(result["contact_number"])
        return _reply(
            f"Got it. Just to confirm — is your contact number {masked}?",
            session
        )

    else:
        session["verification_step"] = "ask_new_or_existing"
        return _reply(
            "I'm sorry, I was unable to verify your details. "
            "Please contact us directly for assistance, "
            "or would you like to create a new account?",
            session
        )


def _step_existing_confirm_contact(user_input: str, session: dict) -> dict:
    """User confirms (yes/no) that the masked contact number is theirs."""
    if _is_yes(user_input):
        patient = session.pop("pending_patient", {})
        session["verified"]          = True
        session["patient_data"]      = patient
        session["verification_step"] = "done"
        return {
            "response":    (
                f"Perfect, you're all verified! "
                f"How can I help you today, {patient.get('first_name', '')}?"
            ),
            "verified":    True,
            "patient_data": patient,
            "done":        True
        }

    elif _is_no(user_input):
        # Wipe pending data, start again
        session.pop("pending_patient", None)
        session.pop("pending_last_name", None)
        session.pop("pending_dob", None)
        session["verification_step"] = "ask_new_or_existing"
        return _reply(
            "I'm sorry about that. Let's try again — "
            "are you a new patient or an existing patient?",
            session
        )

    else:
        masked = _mask_contact(
            session.get("pending_patient", {}).get("contact_number", "")
        )
        return _reply(
            f"I'm sorry, I didn't catch that. "
            f"Is your contact number {masked}? Please say yes or no.",
            session
        )


# ─────────────────────────────────────────────────────────────────────────────
# NEW PATIENT STEPS
# ─────────────────────────────────────────────────────────────────────────────

def _step_new_ask_firstname(user_input: str, session: dict) -> dict:
    session["new_first_name"]    = title_case(user_input.strip())
    session["verification_step"] = "new_ask_lastname"
    return _reply("And your last name?", session)


def _step_new_ask_lastname(user_input: str, session: dict) -> dict:
    session["new_last_name"]     = title_case(user_input.strip())
    session["verification_step"] = "new_ask_dob"
    return _reply(
        "Thank you. What is your date of birth? "
        "You can say it as day, month, year — for example, 15 March 1990.",
        session
    )


def _step_new_ask_dob(user_input: str, session: dict) -> dict:
    dob = _parse_spoken_dob(user_input)
    session["new_dob"]           = dob
    session["verification_step"] = "new_ask_contact"
    return _reply(
        "Great. And your contact number please? "
        "Please say each digit clearly.",
        session
    )


def _step_new_ask_contact(user_input: str, session: dict) -> dict:
    phone = extract_phone_from_text(user_input)
    session["new_contact_raw"]   = user_input   # keep original for retry
    session["new_contact"]       = phone
    session["verification_step"] = "new_confirm_contact"

    if phone:
        spoken = format_phone_for_speech(phone)
        return _reply(
            f"I have your number as {spoken}. Is that correct?",
            session
        )
    else:
        return _reply(
            "I'm sorry, I had trouble catching that number. "
            "Could you please say your contact number again, "
            "one digit at a time?",
            session
        )


def _step_new_confirm_contact(user_input: str, session: dict) -> dict:
    if _is_yes(user_input):
        session["verification_step"] = "new_ask_insurance"
        return _reply(
            "Do you have any health insurance? "
            "If yes, which provider — for example, Medibank, Bupa, HCF, or similar?",
            session
        )

    elif _is_no(user_input):
        # Re-ask the contact number
        session["new_contact"]       = None
        session["verification_step"] = "new_ask_contact"
        return _reply(
            "I'm sorry about that. Could you please say your contact number "
            "again, one digit at a time?",
            session
        )

    else:
        spoken = format_phone_for_speech(session.get("new_contact", ""))
        return _reply(
            f"Just to confirm — is {spoken} your contact number? Please say yes or no.",
            session
        )


def _step_new_ask_insurance(user_input: str, session: dict) -> dict:
    low = user_input.lower()
    if any(w in low for w in ["no", "none", "don't", "do not", "not have", "nope", "nah"]):
        insurance = None
    else:
        insurance = user_input.strip()

    # Create the account
    result = create_new_patient(
        first_name=     session.get("new_first_name"),
        last_name=      session.get("new_last_name"),
        dob=            session.get("new_dob"),
        contact_number= session.get("new_contact"),
        insurance_info= insurance
    )

    # Clean up temporary session keys
    for key in ["new_first_name", "new_last_name", "new_dob",
                "new_contact", "new_contact_raw"]:
        session.pop(key, None)

    if result["status"] == "CREATED":
        session["verified"]          = True
        session["patient_data"]      = result
        session["verification_step"] = "done"
        return {
            "response": (
                f"Your account has been created successfully, "
                f"{result['first_name']}! "
                f"How can I help you today?"
            ),
            "verified":     True,
            "patient_data": result,
            "done":         True
        }

    else:
        session["verification_step"] = "ask_new_or_existing"
        return _reply(
            "I'm sorry, there was an issue creating your account. "
            "Could we try again from the beginning?",
            session
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _reply(response_text: str, session: dict) -> dict:
    """Standard return format for non-final steps."""
    return {
        "response":     response_text,
        "verified":     False,
        "patient_data": None,
        "done":         False
    }


def _not_understood(session: dict) -> dict:
    return _reply(
        "I'm sorry, I didn't quite catch that. "
        "Are you a new patient or an existing patient with us?",
        session
    )


def _detect_new_or_existing(text: str) -> str | None:
    """
    Returns 'new', 'existing', or None (unclear).
    """
    t = text.lower()
    new_keywords = [
        "new", "never", "first time", "first visit",
        "don't have", "do not have", "no account",
        "haven't been", "new patient"
    ]
    existing_keywords = [
        "existing", "old", "been before", "visited",
        "already", "have account", "returning",
        "been there", "came before", "i have"
    ]

    if any(w in t for w in new_keywords):
        return "new"
    if any(w in t for w in existing_keywords):
        return "existing"
    return None


def _is_yes(text: str) -> bool:
    yes_words = [
        "yes", "yeah", "yep", "yup", "correct", "right",
        "sure", "ok", "okay", "that's right", "confirmed",
        "that is correct", "that's correct", "affirmative"
    ]
    t = text.lower()
    return any(w in t for w in yes_words)


def _is_no(text: str) -> bool:
    no_words = [
        "no", "nope", "nah", "not right", "incorrect",
        "wrong", "that's wrong", "that is wrong",
        "that's not", "not correct"
    ]
    t = text.lower()
    return any(w in t for w in no_words)


def _mask_contact(number: str) -> str:
    """
    Read back contact number with only last 4 digits visible.
    '0462361789' → 'ending in 1 7 8 9'
    Full number is read for confirmation to protect privacy
    while still being useful.
    """
    from utils.phone_utils import format_phone_for_speech
    return format_phone_for_speech(number)


def _parse_spoken_dob(text: str) -> str:
    """
    Parse spoken DOB to DD-MM-YYYY.

    Handles:
        "15 March 1990"       → "15-03-1990"
        "15-03-1990"          → "15-03-1990"
        "third of June 1985"  → "03-06-1985"
        "1990-03-15"          → "15-03-1990"
    """
    import re
    from utils.date_time_utils import MONTH_NAMES, dob_to_db_format

    # Ordinal words to numbers
    ORDINALS = {
        "first": "1", "second": "2", "third": "3", "fourth": "4",
        "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8",
        "ninth": "9", "tenth": "10", "eleventh": "11", "twelfth": "12",
        "thirteenth": "13", "fourteenth": "14", "fifteenth": "15",
        "sixteenth": "16", "seventeenth": "17", "eighteenth": "18",
        "nineteenth": "19", "twentieth": "20", "twenty-first": "21",
        "twenty-second": "22", "twenty-third": "23", "twenty-fourth": "24",
        "twenty-fifth": "25", "twenty-sixth": "26", "twenty-seventh": "27",
        "twenty-eighth": "28", "twenty-ninth": "29", "thirtieth": "30",
        "thirty-first": "31"
    }

    t = text.lower().strip()

    # Replace ordinals
    for word, num in ORDINALS.items():
        t = t.replace(word, num)

    # Remove "of", "the"
    t = re.sub(r"\b(of|the)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Try direct parsing first
    attempt = dob_to_db_format(text.strip())
    if re.match(r"\d{2}-\d{2}-\d{4}", attempt):
        return attempt

    # Match: DD MonthName YYYY
    m = re.search(r"(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})", t)
    if m:
        day   = m.group(1).zfill(2)
        month = MONTH_NAMES.get(m.group(2).lower()[:3])
        year  = m.group(3)
        if month:
            return f"{day}-{str(month).zfill(2)}-{year}"

    # Match: MonthName DD YYYY
    m = re.search(r"([a-zA-Z]+)\s+(\d{1,2})\s+(\d{4})", t)
    if m:
        month = MONTH_NAMES.get(m.group(1).lower()[:3])
        day   = m.group(2).zfill(2)
        year  = m.group(3)
        if month:
            return f"{day}-{str(month).zfill(2)}-{year}"

    # Fallback — return as-is for GPT to interpret
    return text.strip()
