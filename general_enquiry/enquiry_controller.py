"""
General Enquiry Controller - DentalBot v2

Handles all patient account-related enquiries:
    - Order / item status          (dentures ready? crown arrived?)
    - Upcoming appointment details (when is my next appointment?)
    - Treatment history            (what treatments have I had?)

Patient is already verified. All lookups use patient_id from session.
No IDs are ever mentioned to the patient.

Session keys used/written:
    enquiry_step       : current step
    enquiry_sub_type   : 'order' | 'upcoming' | 'history' | 'unknown'
"""

from openai import OpenAI
from dotenv import load_dotenv
import os

from general_enquiry.enquiry_executor import (
    get_patient_orders,
    get_upcoming_appointments,
    get_past_appointments
)
from utils.phone_utils import format_phone_for_speech

load_dotenv()
client = OpenAI()


# ─────────────────────────────────────────────────────────────────────────────
# RULES FILE
# ─────────────────────────────────────────────────────────────────────────────

def _load_enquiry_rules() -> str:
    path = os.path.join(
        os.path.dirname(__file__), 'enquiry_rules.txt'
    )
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""

ENQUIRY_RULES = _load_enquiry_rules()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_general_enquiry(user_input: str, session: dict) -> dict:
    """
    Process a general enquiry from a verified patient.

    Args:
        user_input : what the user said
        session    : full call session (mutated in place)

    Returns:
        {
            "response" : str  — bot reply
            "complete" : bool — True when enquiry is answered
        }
    """
    step = session.get("enquiry_step", "classify_and_fetch")

    handlers = {
        "classify_and_fetch": _step_classify_and_fetch,
        "clarify_sub_type":   _step_clarify_sub_type,
    }

    handler = handlers.get(step)
    if handler:
        return handler(user_input, session)

    # Fallback
    session["enquiry_step"] = "classify_and_fetch"
    return _step_classify_and_fetch(user_input, session)


# ─────────────────────────────────────────────────────────────────────────────
# STEPS
# ─────────────────────────────────────────────────────────────────────────────

def _step_classify_and_fetch(user_input: str, session: dict) -> dict:
    """
    Classify the enquiry sub-type and fetch relevant data from DB.
    """
    sub_type = _classify_enquiry_type(user_input)
    patient  = session.get("patient_data", {})
    patient_id  = patient.get("patient_id")
    first_name  = patient.get("first_name", "")

    # ── ORDER STATUS ───────────────────────────────────────────────
    if sub_type == "order":
        result = get_patient_orders(patient_id)

        if result["status"] == "NO_ORDERS":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I don't see any pending orders for you at the moment, "
                    f"{first_name}. If you were expecting something, "
                    f"please let us know and we'll look into it for you. "
                    f"Is there anything else I can help with?"
                ),
                "complete": True
            }

        if result["status"] == "ERROR":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I'm sorry {first_name}, I encountered an issue "
                    f"retrieving your order information. "
                    f"Please call us during business hours and we'll "
                    f"check on it for you right away."
                ),
                "complete": True
            }

        # Build natural language response from order data
        orders    = result["orders"]
        response  = _build_order_response(first_name, orders)
        _cleanup_enquiry(session)
        return {"response": response, "complete": True}

    # ── UPCOMING APPOINTMENTS ──────────────────────────────────────
    elif sub_type == "upcoming":
        result = get_upcoming_appointments(patient_id)

        if result["status"] == "NO_UPCOMING":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I don't see any upcoming appointments for you, "
                    f"{first_name}. Would you like to book one?"
                ),
                "complete": True
            }

        if result["status"] == "ERROR":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I'm sorry, I had trouble retrieving your "
                    f"appointment details. Please try again shortly."
                ),
                "complete": True
            }

        response = _build_upcoming_response(first_name, result["appointments"])
        _cleanup_enquiry(session)
        return {"response": response, "complete": True}

    # ── TREATMENT HISTORY ──────────────────────────────────────────
    elif sub_type == "history":
        result = get_past_appointments(patient_id)

        if result["status"] == "NO_HISTORY":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I don't see any previous treatment records for you, "
                    f"{first_name}. Is there anything else I can help you with?"
                ),
                "complete": True
            }

        if result["status"] == "ERROR":
            _cleanup_enquiry(session)
            return {
                "response": (
                    f"I'm sorry, I had trouble retrieving your "
                    f"treatment history. Please try again shortly."
                ),
                "complete": True
            }

        response = _build_history_response(first_name, result["appointments"])
        _cleanup_enquiry(session)
        return {"response": response, "complete": True}

    # ── UNCLEAR — ask once ─────────────────────────────────────────
    else:
        session["enquiry_step"] = "clarify_sub_type"
        return {
            "response": (
                f"Of course, {first_name}! I can help with that. "
                f"Are you asking about:\n"
                f"  - An order or item (like dentures or a crown)?\n"
                f"  - Your upcoming appointments?\n"
                f"  - Your past treatment history?"
            ),
            "complete": False
        }


def _step_clarify_sub_type(user_input: str, session: dict) -> dict:
    """
    User replied to the clarification question.
    Re-classify with more context and fetch.
    """
    session["enquiry_step"] = "classify_and_fetch"
    return _step_classify_and_fetch(user_input, session)


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_order_response(first_name: str, orders: list) -> str:
    """Build a natural language response for order status enquiries."""
    if len(orders) == 1:
        o = orders[0]
        return (
            f"{o['status_text']} "
            f"Is there anything else I can help you with, {first_name}?"
        )

    # Multiple orders
    lines = [f"Here's an update on your orders, {first_name}:"]
    for i, o in enumerate(orders, 1):
        lines.append(f"  {i}. {o['status_text']}")
    lines.append("Is there anything else I can help you with?")
    return "\n".join(lines)


def _build_upcoming_response(first_name: str, appointments: list) -> str:
    """Build response for upcoming appointment enquiries."""
    if len(appointments) == 1:
        a = appointments[0]
        return (
            f"Your next appointment is a {a['treatment']} "
            f"on {a['date']} at {a['time']} "
            f"with {a['dentist']}. "
            f"Is there anything else I can help you with, {first_name}?"
        )

    lines = [f"You have {len(appointments)} upcoming appointments, {first_name}:"]
    for i, a in enumerate(appointments, 1):
        lines.append(
            f"  {i}. {a['treatment']} on {a['date']} "
            f"at {a['time']} with {a['dentist']}"
        )
    lines.append("Would you like to update or cancel any of these?")
    return "\n".join(lines)


def _build_history_response(first_name: str, appointments: list) -> str:
    """Build response for treatment history enquiries."""
    # Limit to last 5 for voice clarity
    recent = appointments[:5]

    if len(recent) == 1:
        a = recent[0]
        return (
            f"Your most recent treatment was a {a['treatment']} "
            f"on {a['date']} with {a['dentist']}. "
            f"Is there anything else I can help you with, {first_name}?"
        )

    lines = [f"Here are your most recent treatments, {first_name}:"]
    for i, a in enumerate(recent, 1):
        lines.append(
            f"  {i}. {a['treatment']} on {a['date']} with {a['dentist']}"
        )
    lines.append("Is there anything else I can help you with?")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _classify_enquiry_type(text: str) -> str:
    """
    Classify enquiry into: 'order' | 'upcoming' | 'history' | 'unknown'
    """
    t = text.lower()

    order_keywords = [
        "order", "denture", "crown", "mouthguard", "x-ray", "xray",
        "ready", "arrived", "come in", "collected", "pickup",
        "item", "appliance", "lab", "waiting for", "been made",
        "when will", "is it ready", "has it arrived"
    ]
    upcoming_keywords = [
        "next appointment", "upcoming", "when is my appointment",
        "appointment coming", "scheduled", "booked appointment",
        "when do i come in", "my appointment", "next visit",
        "coming appointment", "do i have an appointment"
    ]
    history_keywords = [
        "past", "history", "previous", "last treatment", "last visit",
        "been treated", "had done", "treatments i've had",
        "what did i have", "what was done", "last time i came",
        "last appointment", "treatment record"
    ]

    order_score    = sum(1 for kw in order_keywords    if kw in t)
    upcoming_score = sum(1 for kw in upcoming_keywords if kw in t)
    history_score  = sum(1 for kw in history_keywords  if kw in t)

    scores = {
        "order":    order_score,
        "upcoming": upcoming_score,
        "history":  history_score
    }

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def _cleanup_enquiry(session: dict):
    """Clear enquiry flow keys from session."""
    session.pop("enquiry_step",    None)
    session.pop("enquiry_sub_type", None)
    session["current_flow"] = None
