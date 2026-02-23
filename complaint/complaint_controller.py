"""
Complaint Controller - DentalBot v2

Manages the complete complaint flow state machine.
Patient details always come from session["patient_data"].
Never asks for name or contact again.

Session keys used/written:
    complaint_step      : current step
    complaint_data      : partial complaint being built
"""

from utils.phone_utils import format_phone_for_speech
from utils.text_utils import title_case
from complaint.complaint_executor import save_complaint


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_complaint(user_input: str, session: dict) -> dict:
    """
    Process one turn of the complaint flow.

    Args:
        user_input : what the user said
        session    : the full call session dict (mutated in place)

    Returns:
        {
            "response" : str  — bot reply
            "complete" : bool — True when complaint is saved or flow ends
        }
    """
    step = session.get("complaint_step", "open_empathy")

    handlers = {
        "open_empathy":              _step_open_empathy,
        "collect_description":       _step_collect_description,
        "treatment_ask_which":       _step_treatment_ask_which,
        "treatment_ask_dentist":     _step_treatment_ask_dentist,
        "treatment_ask_date":        _step_treatment_ask_date,
        "confirm_complaint":         _step_confirm_complaint,
        "execute_save":              _step_execute_save,
    }

    handler = handlers.get(step)
    if handler:
        return handler(user_input, session)

    # Fallback
    session["complaint_step"] = "open_empathy"
    return _step_open_empathy(user_input, session)


# ─────────────────────────────────────────────────────────────────────────────
# STEPS
# ─────────────────────────────────────────────────────────────────────────────

def _step_open_empathy(user_input: str, session: dict) -> dict:
    """
    First response — always show empathy before anything else.
    Initialise complaint_data with patient info from session.
    """
    patient    = session.get("patient_data", {})
    first_name = patient.get("first_name", "")

    # Initialise complaint data — patient details from session
    session["complaint_data"] = {
        "patient_name":    f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
        "contact_number":  patient.get("contact_number", ""),
        "complaint_text":  None,
        "category":        None,
        "treatment_name":  None,
        "dentist_name":    None,
        "treatment_date":  None
    }

    # Check if user already described the issue in the initial message
    if _has_description(user_input):
        category = _classify_complaint_category(user_input)
        session["complaint_data"]["complaint_text"] = user_input.strip()
        session["complaint_data"]["category"]       = category

        if category == "treatment":
            session["complaint_step"] = "treatment_ask_which"
            return _reply(
                f"I'm so sorry to hear that, {first_name}. "
                f"That must have been really concerning. "
                f"I want to make sure this is properly looked into. "
                f"Which treatment was this regarding?",
                session
            )
        else:
            session["complaint_step"] = "confirm_complaint"
            return _step_confirm_complaint("", session)

    # No description yet — ask them to describe
    session["complaint_step"] = "collect_description"
    return _reply(
        f"I'm so sorry to hear you're having a concern, {first_name}. "
        f"I sincerely apologise for any inconvenience. "
        f"Could you please tell me what happened? "
        f"I'm here to listen and make sure this is addressed properly.",
        session
    )


def _step_collect_description(user_input: str, session: dict) -> dict:
    """Collect the full complaint description from the user."""
    if not user_input or len(user_input.strip()) < 5:
        return _reply(
            "I want to make sure I understand your concern properly. "
            "Could you please describe what happened?",
            session
        )

    complaint_text = user_input.strip()
    category       = _classify_complaint_category(complaint_text)

    session["complaint_data"]["complaint_text"] = complaint_text
    session["complaint_data"]["category"]       = category

    if category == "treatment":
        session["complaint_step"] = "treatment_ask_which"
        return _reply(
            "Thank you for letting me know. "
            "I completely understand your concern and I sincerely apologise. "
            "Could you tell me which treatment this was regarding?",
            session
        )
    else:
        session["complaint_step"] = "confirm_complaint"
        return _step_confirm_complaint("", session)


def _step_treatment_ask_which(user_input: str, session: dict) -> dict:
    """Collect which treatment the complaint is about."""
    if not user_input or len(user_input.strip()) < 2:
        return _reply(
            "Could you tell me which dental treatment this was regarding? "
            "For example, a filling, root canal, cleaning, or another procedure?",
            session
        )

    session["complaint_data"]["treatment_name"] = user_input.strip()
    session["complaint_step"] = "treatment_ask_dentist"

    return _reply(
        "Thank you. Do you remember which dentist treated you? "
        "If you're not sure, that's completely fine — just say 'not sure'.",
        session
    )


def _step_treatment_ask_dentist(user_input: str, session: dict) -> dict:
    """Collect which dentist the complaint is about (optional)."""
    t = user_input.lower().strip()

    not_sure_phrases = [
        "not sure", "don't know", "don't remember", "can't remember",
        "no idea", "unsure", "not sure", "forget", "forgotten", "nope", "no"
    ]

    if any(phrase in t for phrase in not_sure_phrases):
        session["complaint_data"]["dentist_name"] = None
    else:
        session["complaint_data"]["dentist_name"] = user_input.strip()

    session["complaint_step"] = "treatment_ask_date"
    return _reply(
        "And do you remember approximately when this treatment took place? "
        "You can say something like 'last week', '10 February', or just "
        "'not sure' if you can't recall.",
        session
    )


def _step_treatment_ask_date(user_input: str, session: dict) -> dict:
    """Collect treatment date (optional)."""
    from utils.date_time_utils import parse_date, format_date_for_db

    t = user_input.lower().strip()
    not_sure_phrases = [
        "not sure", "don't know", "don't remember", "can't remember",
        "no idea", "unsure", "forget", "forgotten", "nope", "no"
    ]

    if any(phrase in t for phrase in not_sure_phrases):
        session["complaint_data"]["treatment_date"] = None
    else:
        parsed = parse_date(user_input)
        if parsed:
            session["complaint_data"]["treatment_date"] = format_date_for_db(parsed)
        else:
            # Store as raw text if date can't be parsed
            session["complaint_data"]["treatment_date"] = user_input.strip()

    session["complaint_step"] = "confirm_complaint"
    return _step_confirm_complaint("", session)


def _step_confirm_complaint(user_input: str, session: dict) -> dict:
    """
    Read back the complaint details and ask for confirmation.
    If called with non-empty user_input, it's a yes/no response.
    """
    # If user_input is a confirmation response
    if user_input:
        if _is_yes(user_input):
            session["complaint_step"] = "execute_save"
            return _step_execute_save("yes", session)
        elif _is_no(user_input):
            # Let them re-describe
            session["complaint_step"] = "collect_description"
            session["complaint_data"]["complaint_text"] = None
            session["complaint_data"]["category"]       = None
            session["complaint_data"]["treatment_name"] = None
            session["complaint_data"]["dentist_name"]   = None
            session["complaint_data"]["treatment_date"] = None
            return _reply(
                "Of course, let's go over it again. "
                "Could you please describe your concern?",
                session
            )
        else:
            return _reply(
                "Could you please say yes to confirm or no to make changes?",
                session
            )

    # Build confirmation message
    data       = session.get("complaint_data", {})
    patient    = session.get("patient_data", {})
    first_name = patient.get("first_name", "")
    contact_spoken = format_phone_for_speech(data.get("contact_number", ""))

    lines = [
        f"Thank you, {first_name}. Let me confirm your complaint details:",
        f"  Name          : {data.get('patient_name', '')}",
        f"  Contact       : {contact_spoken}",
        f"  Type          : {'Treatment-related' if data.get('category') == 'treatment' else 'General'}",
    ]

    if data.get("treatment_name"):
        lines.append(f"  Treatment     : {data.get('treatment_name')}")
    if data.get("dentist_name"):
        lines.append(f"  Dentist       : {data.get('dentist_name')}")
    if data.get("treatment_date"):
        lines.append(f"  Treatment Date: {data.get('treatment_date')}")

    lines.append(f"  Complaint     : {data.get('complaint_text', '')}")
    lines.append("Is everything correct?")

    session["complaint_step"] = "execute_save"
    return _reply("\n".join(lines), session)


def _step_execute_save(user_input: str, session: dict) -> dict:
    """Save complaint to DB after confirmation."""
    if not _is_yes(user_input):
        # Re-confirm
        session["complaint_step"] = "confirm_complaint"
        return _reply(
            "Could you please say yes to confirm or no if you'd like to make changes?",
            session
        )

    data = session.get("complaint_data", {})

    result = save_complaint(
        patient_name=       data.get("patient_name"),
        contact_number=     data.get("contact_number"),
        complaint_text=     data.get("complaint_text"),
        complaint_category= data.get("category", "general"),
        treatment_name=     data.get("treatment_name"),
        dentist_name=       data.get("dentist_name"),
        treatment_date=     data.get("treatment_date")
    )

    # Clear complaint state
    session.pop("complaint_step", None)
    session.pop("complaint_data",  None)
    session["current_flow"] = None

    if result["status"] == "SAVED":
        contact_spoken = result.get("contact_spoken", "")
        patient_name   = result.get("patient_name", "")

        return {
            "response": (
                f"Your complaint has been recorded, {patient_name}. "
                f"Our management team will review this carefully and "
                f"reach out to you on {contact_spoken} within 2 business days. "
                f"I sincerely apologise for the experience you've had, "
                f"and we will do our very best to make it right. "
                f"Is there anything else I can help you with?"
            ),
            "complete": True
        }

    # Save failed
    return {
        "response": (
            "I'm so sorry, I encountered an issue saving your complaint. "
            "Could we please try again? I want to make sure this is recorded properly."
        ),
        "complete": False
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _reply(text: str, session: dict) -> dict:
    return {"response": text, "complete": False}


def _is_yes(text: str) -> bool:
    yes_words = [
        "yes", "yeah", "yep", "yup", "correct", "right",
        "sure", "ok", "okay", "confirmed", "that's right",
        "that is correct", "sounds good", "go ahead"
    ]
    return any(w in text.lower() for w in yes_words)


def _is_no(text: str) -> bool:
    no_words = [
        "no", "nope", "nah", "not right", "incorrect",
        "wrong", "change", "different", "not correct"
    ]
    return any(w in text.lower() for w in no_words)


def _has_description(text: str) -> bool:
    """
    Check if the initial trigger message already contains
    a meaningful description (more than just "I want to complain").
    """
    trigger_only = [
        "complaint", "complain", "issue", "problem",
        "not happy", "unhappy", "bad experience", "feedback"
    ]
    t = text.lower().strip()

    # If it's just a short trigger phrase, no description yet
    if len(t.split()) <= 5:
        for phrase in trigger_only:
            if t == phrase or t == f"i want to {phrase}" or t == f"i have a {phrase}":
                return False

    # Longer messages likely contain the description already
    return len(text.split()) > 8


def _classify_complaint_category(text: str) -> str:
    """
    Classify complaint as 'general' or 'treatment'.

    Treatment keywords: specific procedures, dentist actions,
                        pain after procedure, dental work issues.
    General keywords  : waiting, staff, reception, billing, hours.
    """
    treatment_keywords = [
        "filling", "crown", "implant", "root canal", "extraction",
        "whitening", "veneer", "aligner", "invisalign", "denture",
        "bridge", "cleaning", "scale", "treatment", "procedure",
        "dentist did", "after the", "during the", "tooth hurts",
        "pain after", "still hurts", "came loose", "fell out",
        "cracked", "broke", "sensitive after", "dr.", "doctor",
        "gum bleed", "swelling after", "infection after"
    ]
    general_keywords = [
        "wait", "waiting", "too long", "reception", "receptionist",
        "staff", "rude", "unhelpful", "billing", "invoice", "charged",
        "overcharged", "appointment", "cancelled on me", "no show",
        "parking", "location", "hours", "closed", "phone", "call back",
        "never called", "hygiene", "cleanliness", "dirty"
    ]

    t = text.lower()
    treatment_score = sum(1 for kw in treatment_keywords if kw in t)
    general_score   = sum(1 for kw in general_keywords   if kw in t)

    if treatment_score > general_score:
        return "treatment"
    if general_score > treatment_score:
        return "general"

    # Default: if ambiguous, ask treatment-focused questions
    # since treatment complaints need more detail
    return "general"
