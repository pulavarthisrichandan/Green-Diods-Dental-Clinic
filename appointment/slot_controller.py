"""
Appointment Booking Controller - DentalBot v2

Manages the booking state machine for a call session.
Patient details come from session["patient_data"] — never re-asked.

Session keys used/written:
    booking_step         : current step in booking flow
    booking_data         : partial booking info being collected
    booking_confirmed    : True once user says yes to confirmation
"""

from utils.date_time_utils import format_date_for_speech, format_time_for_speech
from utils.phone_utils import format_phone_for_speech
from appointment.executor import (
    check_dentist_availability,
    find_available_dentist,
    book_appointment,
    get_patient_appointments,
    update_appointment,
    cancel_appointment,
    DENTISTS
)



# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_booking(user_input: str, session: dict) -> dict:
    """
    Process one turn of the appointment booking flow.

    Args:
        user_input   : what the user just said
        session      : the full call session dict (mutated in place)

    Returns:
        {
            "response"  : str   — bot reply
            "complete"  : bool  — True when booking is finished/cancelled
            "booked"    : bool  — True if appointment was successfully saved
        }
    """
    step = session.get("booking_step", "ask_treatment")

    # ── Allow user to cancel the booking mid-flow ──────────────────
    if _wants_to_cancel_flow(user_input) and step != "ask_treatment":
        return _cancel_flow(session)

    handlers = {
        "ask_treatment":         _step_ask_treatment,
        "ask_datetime":          _step_ask_datetime,
        "ask_dentist":           _step_ask_dentist,
        "check_availability":    _step_check_availability,
        "confirm_details":       _step_confirm_details,
        "execute_booking":       _step_execute_booking,
    }

    handler = handlers.get(step)
    if handler:
        return handler(user_input, session)

    # Fallback
    session["booking_step"] = "ask_treatment"
    return _reply(
        "Let's start your booking. What treatment would you like today?",
        session
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEPS
# ─────────────────────────────────────────────────────────────────────────────

def _step_ask_treatment(user_input: str, session: dict) -> dict:
    """First step — ask what treatment they need."""
    # If user_input is the initial trigger (e.g., "I want to book"),
    # just ask for the treatment
    if _is_initial_trigger(user_input):
        session["booking_step"] = "ask_treatment"
        session["booking_data"] = {}
        return _reply(
            "I'd be happy to book an appointment for you! "
            "What treatment are you looking for?",
            session
        )

    # Otherwise, user has given the treatment in this message
    treatment = _extract_treatment(user_input)
    if treatment:
        session["booking_data"] = {"preferred_treatment": treatment}
        session["booking_step"] = "ask_datetime"
        return _reply(
            f"Great, {treatment}. "
            "When would you like to come in? "
            "You can say something like 'next Monday at 2pm' or "
            "'coming Friday morning'.",
            session
        )

    # Treatment unclear — ask again
    dentist_list = ", ".join(DENTISTS)
    return _reply(
        "I'd be happy to help you book an appointment. "
        "What treatment are you looking for? We offer services like "
        "General Check-Up, Cleaning, Fillings, Root Canal, "
        "Teeth Whitening, Implants, and more.",
        session
    )


def _step_ask_datetime(user_input: str, session: dict) -> dict:
    """Collect preferred date and time from user."""
    from utils.date_time_utils import parse_date, parse_time
    import re

    # Try to extract date and time from input
    date_str, time_str = _extract_date_time(user_input)

    if not date_str and not time_str:
        return _reply(
            "Could you please tell me your preferred date and time? "
            "For example, 'next Monday at 2pm' or 'this Friday morning at 10'.",
            session
        )

    if date_str and not time_str:
        session["booking_data"]["pending_date"] = date_str
        return _reply(
            f"And what time would you prefer on {date_str}?",
            session
        )

    if not date_str and time_str:
        if "pending_date" in session.get("booking_data", {}):
            date_str = session["booking_data"]["pending_date"]
        else:
            return _reply(
                "What date would you prefer? "
                "You can say 'next Monday', 'this Friday', or give me a specific date.",
                session
            )

    # Both date and time captured
    session["booking_data"]["preferred_date"] = date_str
    session["booking_data"]["preferred_time"] = time_str
    session["booking_data"].pop("pending_date", None)
    session["booking_step"] = "ask_dentist"

    dentist_options = "\n".join(f"  - {d}" for d in DENTISTS)
    return _reply(
        f"Perfect. And which dentist would you prefer? "
        f"Our dentists are:\n{dentist_options}\n"
        "Or I can pick whoever is available at that time — just say 'any dentist'.",
        session
    )


def _step_ask_dentist(user_input: str, session: dict) -> dict:
    """Identify dentist preference."""
    dentist = _extract_dentist(user_input)

    if dentist == "any":
        session["booking_data"]["preferred_dentist"] = "any"
    elif dentist:
        session["booking_data"]["preferred_dentist"] = dentist
    else:
        dentist_list = "\n".join(f"  - {d}" for d in DENTISTS)
        return _reply(
            f"I didn't quite catch which dentist you'd prefer. "
            f"Our dentists are:\n{dentist_list}\n"
            "Or just say 'any dentist' if you have no preference.",
            session
        )

    session["booking_step"] = "check_availability"
    # Immediately proceed to availability check
    return _step_check_availability("", session)


def _step_check_availability(user_input: str, session: dict) -> dict:
    """Check dentist availability and handle alternatives."""
    data     = session.get("booking_data", {})
    date_str = data.get("preferred_date")
    time_str = data.get("preferred_time")
    dentist  = data.get("preferred_dentist")

    if dentist == "any":
        result = find_available_dentist(date_str, time_str)

        if result["status"] == "FOUND":
            data["preferred_dentist"] = result["dentist"]
            data["confirmed_date"]    = result["date"]
            data["confirmed_time"]    = result["time"]
            data["date_db"]           = result["date_db"]
            data["time_db"]           = result["time_db"]
            session["booking_step"]   = "confirm_details"
            return _step_confirm_details("", session)

        elif result["status"] == "NONE_AVAILABLE_SUGGEST":
            # Suggest alternative
            data["preferred_dentist"] = result["suggested_dentist"]
            data["confirmed_date"]    = result["suggested_date"]
            data["confirmed_time"]    = result["suggested_time"]
            data["date_db"]           = result["suggested_date_db"]
            data["time_db"]           = result["suggested_time_db"]
            session["booking_step"]   = "confirm_alternative"
            return _reply(
                f"All dentists are fully booked at that time. "
                f"The earliest available slot is with {result['suggested_dentist']} "
                f"on {result['suggested_date']} at {result['suggested_time']}. "
                f"Would you like to book that instead?",
                session
            )

        else:
            session["booking_step"] = "ask_datetime"
            return _reply(result.get("message", "No availability found. Please try a different time."), session)

    else:
        result = check_dentist_availability(date_str, time_str, dentist)

        if result["status"] == "AVAILABLE":
            data["confirmed_date"] = result["date"]
            data["confirmed_time"] = result["time"]
            data["date_db"]        = result["date_db"]
            data["time_db"]        = result["time_db"]
            session["booking_step"] = "confirm_details"
            return _step_confirm_details("", session)

        elif result["status"] == "NOT_AVAILABLE":
            if "suggested_date" in result:
                # Store suggestion for user to accept/reject
                session["booking_data"]["alt_date"]    = result["suggested_date"]
                session["booking_data"]["alt_time"]    = result["suggested_time"]
                session["booking_data"]["alt_date_db"] = result["suggested_date_db"]
                session["booking_data"]["alt_time_db"] = result["suggested_time_db"]
                session["booking_step"] = "confirm_alternative"
                return _reply(
                    f"{dentist} is not available at that time. "
                    f"The nearest available slot with {dentist} is "
                    f"{result['suggested_date']} at {result['suggested_time']}. "
                    f"Would you like to book that instead?",
                    session
                )
            else:
                session["booking_step"] = "ask_datetime"
                return _reply(result.get("message", "That slot is not available."), session)

        elif result["status"] == "INVALID":
            session["booking_step"] = "ask_datetime"
            return _reply(result["message"], session)

    session["booking_step"] = "ask_datetime"
    return _reply("I had trouble checking availability. Could you try a different time?", session)


def _step_confirm_details(user_input: str, session: dict) -> dict:
    """
    Read back ALL details and ask for confirmation before booking.
    Patient details come from session["patient_data"].
    """
    # If this step was triggered by user accepting an alternative,
    # check the response
    if user_input:
        if _is_yes(user_input):
            # Accept the confirmed slot — fall through to display
            alt = session["booking_data"]
            if "alt_date" in alt:
                alt["confirmed_date"] = alt.pop("alt_date")
                alt["confirmed_time"] = alt.pop("alt_time")
                alt["date_db"]        = alt.pop("alt_date_db")
                alt["time_db"]        = alt.pop("alt_time_db")
        elif _is_no(user_input):
            session["booking_step"] = "ask_datetime"
            return _reply(
                "No problem. What date and time would you prefer? "
                "You can say something like 'next Wednesday at 3pm'.",
                session
            )
        else:
            # This is the confirmation step — check yes/no
            if session.get("booking_step") == "execute_booking":
                return _step_execute_booking(user_input, session)

    patient = session.get("patient_data", {})
    data    = session.get("booking_data", {})

    contact_spoken = format_phone_for_speech(patient.get("contact_number", ""))

    confirmation_msg = (
        f"Let me confirm your appointment details:\n"
        f"  Name         : {patient.get('first_name', '')} {patient.get('last_name', '')}\n"
        f"  Date of Birth: {patient.get('date_of_birth', '')}\n"
        f"  Contact      : {contact_spoken}\n"
        f"  Treatment    : {data.get('preferred_treatment', '')}\n"
        f"  Dentist      : {data.get('preferred_dentist', '')}\n"
        f"  Date & Time  : {data.get('confirmed_date', '')} at {data.get('confirmed_time', '')}\n"
        f"Is everything correct?"
    )

    session["booking_step"] = "execute_booking"
    return _reply(confirmation_msg, session)


def _step_execute_booking(user_input: str, session: dict) -> dict:
    """Execute booking after user confirms all details."""
    if _is_yes(user_input):
        patient = session.get("patient_data", {})
        data    = session.get("booking_data", {})

        result = book_appointment(
            patient_id=          patient.get("patient_id"),
            first_name=          patient.get("first_name"),
            last_name=           patient.get("last_name"),
            date_of_birth=       patient.get("date_of_birth"),
            contact_number=      patient.get("contact_number"),
            preferred_treatment= data.get("preferred_treatment"),
            preferred_date=      data.get("date_db"),
            preferred_time=      data.get("time_db"),
            preferred_dentist=   data.get("preferred_dentist")
        )

        # Clear booking state
        session.pop("booking_step", None)
        session.pop("booking_data", None)
        session["current_flow"] = None

        if result["status"] == "BOOKED":
            return {
                "response": (
                    f"Your appointment is confirmed! "
                    f"We look forward to seeing you on "
                    f"{result['date']} at {result['time']} "
                    f"with {result['dentist']} for {result['treatment']}. "
                    f"Is there anything else I can help you with?"
                ),
                "complete": True,
                "booked":   True
            }
        else:
            return {
                "response": (
                    f"I'm sorry, I encountered an issue while booking: "
                    f"{result.get('message', 'Please try again.')} "
                    f"Would you like to try again?"
                ),
                "complete": False,
                "booked":   False
            }

    elif _is_no(user_input):
        session["booking_step"] = "ask_treatment"
        session["booking_data"] = {}
        return _reply(
            "No problem! What would you like to change? "
            "You can tell me a different treatment, date, time, or dentist.",
            session
        )

    else:
        return _reply(
            "Could you please say yes to confirm the booking, or no if you'd like to make changes?",
            session
        )


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE / CANCEL CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

def handle_update_cancel(user_input: str, session: dict) -> dict:
    """
    Manages update and cancel flows for a verified patient.
    Finds appointments internally using patient_id — never asks user for IDs.

    Session keys:
        uc_step           : current step
        uc_appointments   : fetched appointment list
        uc_target         : the appointment being modified (_id internal)
        uc_action         : 'update' or 'cancel'
    """
    step = session.get("uc_step", "fetch_appointments")

    # ✅ FIXED — remove the non-existent entry
    handlers = {
        "fetch_appointments":  _uc_fetch_appointments,
        "select_appointment":  _uc_select_appointment,
        "ask_what_to_change":  _uc_ask_what_to_change,
        "confirm_cancel":      _uc_confirm_cancel,
    }


    handler = handlers.get(step)
    if handler:
        return handler(user_input, session)

    session["uc_step"] = "fetch_appointments"
    return _uc_fetch_appointments("", session)


def _uc_fetch_appointments(user_input: str, session: dict) -> dict:
    patient_id = session["patient_data"]["patient_id"]
    result     = get_patient_appointments(patient_id)

    if result["status"] == "ERROR":
        return _uc_reply(f"I encountered an error: {result['message']}", session)

    appointments = result.get("appointments", [])
    session["uc_appointments"] = appointments

    if not appointments:
        session.pop("uc_step", None)
        session["current_flow"] = None
        first_name = session["patient_data"].get("first_name", "")
        return {
            "response": (
                f"I don't see any active appointments for you, {first_name}. "
                "Would you like to book a new one?"
            ),
            "complete": True
        }

    if len(appointments) == 1:
        session["uc_target"] = appointments[0]
        # Detect whether user wants to update or cancel
        action = _detect_action(user_input)
        session["uc_action"] = action or "update"

        if session["uc_action"] == "cancel":
            session["uc_step"] = "confirm_cancel"
            a = appointments[0]
            return _uc_reply(
                f"Just to confirm — you'd like to cancel your "
                f"{a['treatment']} appointment on {a['date']} at "
                f"{a['time']} with {a['dentist']}. Is that correct?",
                session
            )
        else:
            session["uc_step"] = "ask_what_to_change"
            a = appointments[0]
            return _uc_reply(
                f"I found your {a['treatment']} appointment on "
                f"{a['date']} at {a['time']} with {a['dentist']}. "
                f"What would you like to change?",
                session
            )

    # Multiple appointments — describe and ask
    session["uc_step"] = "select_appointment"
    lines = []
    for i, a in enumerate(appointments, 1):
        lines.append(
            f"  {i}. {a['treatment']} on {a['date']} at {a['time']} "
            f"with {a['dentist']}"
        )
    appt_list = "\n".join(lines)
    return _uc_reply(
        f"You have {len(appointments)} appointments:\n{appt_list}\n"
        "Which one would you like to update or cancel?",
        session
    )


def _uc_select_appointment(user_input: str, session: dict) -> dict:
    """User describes or numbers the appointment they want."""
    appointments = session.get("uc_appointments", [])
    target = _match_appointment(user_input, appointments)

    if not target:
        lines = []
        for i, a in enumerate(appointments, 1):
            lines.append(f"  {i}. {a['treatment']} on {a['date']} with {a['dentist']}")
        return _uc_reply(
            f"I'm sorry, I didn't quite catch that. Which appointment?\n"
            + "\n".join(lines),
            session
        )

    session["uc_target"] = target
    action = _detect_action(user_input)
    session["uc_action"] = action or "update"

    if session["uc_action"] == "cancel":
        session["uc_step"] = "confirm_cancel"
        return _uc_reply(
            f"Just to confirm — you'd like to cancel your "
            f"{target['treatment']} appointment on {target['date']} "
            f"at {target['time']} with {target['dentist']}. Is that correct?",
            session
        )

    session["uc_step"] = "ask_what_to_change"
    return _uc_reply(
        f"Got it — your {target['treatment']} on {target['date']} "
        f"at {target['time']} with {target['dentist']}. "
        "What would you like to change — the date, time, dentist, or treatment?",
        session
    )


def _uc_ask_what_to_change(user_input: str, session: dict) -> dict:
    """Collect what the user wants to update."""
    from utils.date_time_utils import parse_date, parse_time
    import re

    update_fields = {}

    date_str, time_str = _extract_date_time(user_input)
    if date_str:
        update_fields["preferred_date"] = date_str
    if time_str:
        update_fields["preferred_time"] = time_str

    new_dentist = _extract_dentist(user_input)
    if new_dentist and new_dentist != "any":
        update_fields["preferred_dentist"] = new_dentist

    new_treatment = _extract_treatment(user_input)
    if new_treatment:
        update_fields["preferred_treatment"] = new_treatment

    if not update_fields:
        return _uc_reply(
            "What would you like to change? You can update the date, time, "
            "dentist, or treatment.",
            session
        )

    target    = session["uc_target"]
    appt_id   = target["_id"]

    result = update_appointment(appt_id, update_fields)

    # Clear update/cancel state
    session.pop("uc_step", None)
    session.pop("uc_appointments", None)
    session.pop("uc_target", None)
    session.pop("uc_action", None)
    session["current_flow"] = None

    if result["status"] == "UPDATED":
        return {
            "response": (
                f"Done! Your appointment has been updated to "
                f"{result['treatment']} on {result['date']} at "
                f"{result['time']} with {result['dentist']}. "
                "Is there anything else I can help you with?"
            ),
            "complete": True
        }

    return {
        "response": f"I'm sorry, I couldn't update that: {result.get('message')}. Would you like to try again?",
        "complete": False
    }


def _uc_confirm_cancel(user_input: str, session: dict) -> dict:
    """User confirms or denies the cancellation."""
    if _is_yes(user_input):
        target  = session["uc_target"]
        appt_id = target["_id"]
        result  = cancel_appointment(appt_id)

        session.pop("uc_step", None)
        session.pop("uc_appointments", None)
        session.pop("uc_target", None)
        session.pop("uc_action", None)
        session["current_flow"] = None

        if result["status"] == "CANCELLED":
            return {
                "response": (
                    f"Your {result['treatment']} appointment on "
                    f"{result['date']} at {result['time']} has been cancelled. "
                    "Is there anything else I can help you with?"
                ),
                "complete": True
            }

        return {
            "response": f"I'm sorry, I couldn't cancel that: {result.get('message')}",
            "complete": False
        }

    elif _is_no(user_input):
        session.pop("uc_step", None)
        session["current_flow"] = None
        return {
            "response": "No problem! Your appointment is unchanged. Is there anything else?",
            "complete": True
        }

    return _uc_reply(
        "Could you please say yes to confirm the cancellation, or no to keep the appointment?",
        session
    )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _reply(text: str, session: dict) -> dict:
    return {"response": text, "complete": False, "booked": False}


def _uc_reply(text: str, session: dict) -> dict:
    return {"response": text, "complete": False}


def _cancel_flow(session: dict) -> dict:
    """User said they don't want to book anymore."""
    session.pop("booking_step", None)
    session.pop("booking_data", None)
    session["current_flow"] = None
    return {
        "response": "No problem, I've cancelled the booking process. Is there anything else I can help you with?",
        "complete": True,
        "booked":   False
    }


def _is_yes(text: str) -> bool:
    yes = ["yes", "yeah", "yep", "yup", "correct", "right",
           "sure", "ok", "okay", "go ahead", "confirmed",
           "that's correct", "that is correct", "sounds good"]
    return any(w in text.lower() for w in yes)


def _is_no(text: str) -> bool:
    no = ["no", "nope", "nah", "don't", "do not", "not right",
          "incorrect", "wrong", "cancel", "stop"]
    return any(w in text.lower() for w in no)


def _wants_to_cancel_flow(text: str) -> bool:
    cancel_phrases = [
        "don't want to book", "cancel the booking",
        "forget it", "never mind", "stop booking",
        "don't want appointment", "not anymore"
    ]
    t = text.lower()
    return any(p in t for p in cancel_phrases)


def _is_initial_trigger(text: str) -> bool:
    triggers = [
        "book", "appointment", "schedule", "want to book",
        "need an appointment", "make an appointment"
    ]
    t = text.lower()
    return any(w in t for w in triggers) and len(text.split()) < 8


def _extract_treatment(text: str) -> str | None:
    """Match treatment from user input."""
    treatments = {
        "check-up": "General Check-Up & Clean",
        "check up": "General Check-Up & Clean",
        "checkup": "General Check-Up & Clean",
        "general check": "General Check-Up & Clean",
        "clean": "General Check-Up & Clean",
        "cleaning": "General Check-Up & Clean",
        "scale": "Scale & Clean (Deep Clean)",
        "emergency": "Emergency Dental Consultation",
        "children": "Children's Dentistry",
        "child": "Children's Dentistry",
        "kids": "Children's Dentistry",
        "filling": "Dental Fillings",
        "fillings": "Dental Fillings",
        "crown": "Dental Crowns",
        "crowns": "Dental Crowns",
        "implant": "Dental Implants",
        "implants": "Dental Implants",
        "root canal": "Root Canal Treatment",
        "root": "Root Canal Treatment",
        "denture": "Dentures",
        "dentures": "Dentures",
        "bridge": "Dental Bridges",
        "bridges": "Dental Bridges",
        "whitening": "Teeth Whitening",
        "whiten": "Teeth Whitening",
        "veneer": "Dental Veneers",
        "veneers": "Dental Veneers",
        "invisalign": "Clear Aligners / Invisalign",
        "aligner": "Clear Aligners / Invisalign",
        "aligners": "Clear Aligners / Invisalign",
        "braces": "Clear Aligners / Invisalign",
        "wisdom": "Wisdom Teeth Removal",
        "wisdom teeth": "Wisdom Teeth Removal",
        "extraction": "Tooth Extraction",
        "extract": "Tooth Extraction",
        "remove tooth": "Tooth Extraction",
        "gum": "Gum Disease Treatment",
        "gums": "Gum Disease Treatment",
        "periodon": "Gum Disease Treatment",
        "consultation": "General Check-Up & Clean",
    }
    t = text.lower()
    for keyword, treatment in treatments.items():
        if keyword in t:
            return treatment
    return None


def _extract_dentist(text: str) -> str | None:
    """Match dentist from user input. Returns 'any' for no preference."""
    t = text.lower()
    any_phrases = [
        "any", "whoever", "anyone", "no preference",
        "don't mind", "doesn't matter", "any available",
        "any dentist", "available"
    ]
    if any(p in t for p in any_phrases):
        return "any"

    for dentist in DENTISTS:
        # Check last name or full name
        parts = dentist.lower().split()
        for part in parts:
            if len(part) > 2 and part in t:
                return dentist
    return None


def _extract_date_time(text: str) -> tuple[str | None, str | None]:
    """
    Extract date and time strings from natural language.
    Returns (date_str, time_str) — raw strings for the parser.
    """
    import re
    t = text.lower()

    # ── Time extraction ────────────────────────────────────────────
    time_str = None
    time_patterns = [
        r'\b(\d{1,2}:\d{2}\s*(?:am|pm))\b',
        r'\b(\d{1,2}\s*(?:am|pm))\b',
        r'\b(morning\s+\d{1,2}(?::\d{2})?)\b',
        r'\b(afternoon\s+\d{1,2}(?::\d{2})?)\b',
        r'\b(evening\s+\d{1,2}(?::\d{2})?)\b',
    ]
    for pattern in time_patterns:
        m = re.search(pattern, t)
        if m:
            time_str = m.group(1).strip()
            break

    # ── Date extraction ────────────────────────────────────────────
    date_str = None
    date_patterns = [
        r'\b(day after tomorrow)\b',
        r'\b(tomorrow)\b',
        r'\b(today)\b',
        r'\b(next\s+\w+day)\b',
        r'\b(coming\s+\w+day)\b',
        r'\b(this\s+\w+day)\b',
        r'\b(\w+day)\b',
        r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b',
        r'\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)\b',
        r'\b(in\s+\d+\s+days?)\b',
    ]
    for pattern in date_patterns:
        m = re.search(pattern, t)
        if m:
            date_str = m.group(1).strip()
            break

    return date_str, time_str


def _detect_action(text: str) -> str | None:
    """Detect whether user wants to update or cancel."""
    t = text.lower()
    if any(w in t for w in ["cancel", "remove", "delete", "don't need"]):
        return "cancel"
    if any(w in t for w in ["update", "change", "reschedule", "modify", "move"]):
        return "update"
    return None


def _match_appointment(text: str, appointments: list) -> dict | None:
    """
    Match which appointment the user is referring to.
    Handles: number ("first", "1", "second"), treatment name, date mention.
    """
    import re
    t = text.lower()

    # By number
    num_words = {"first": 0, "second": 1, "third": 2, "one": 0, "two": 1, "three": 2}
    for word, idx in num_words.items():
        if word in t and idx < len(appointments):
            return appointments[idx]

    m = re.search(r'\b(\d+)\b', t)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(appointments):
            return appointments[idx]

    # By treatment mention
    for a in appointments:
        if any(w in t for w in a["treatment"].lower().split()):
            return a

    # By dentist mention
    for a in appointments:
        dentist_parts = a["dentist"].lower().split()
        if any(p in t for p in dentist_parts if len(p) > 2):
            return a

    return None
