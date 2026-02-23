"""
Business Session Handler - DentalBot v2

Manages multi-turn business caller flows.
Some business calls require follow-up questions
(e.g., supplier doesn't mention patient name → ask for it).

Session keys used/written:
    biz_step      : current step in business caller flow
    biz_data      : partial extracted caller info
"""

from business.business_controller import (
    handle_business_caller,
    handle_business_info,
    handle_insurance_query,
    handle_warranty_query,
    _extract_business_caller_info,
    _classify_business_call
)


def handle_business_flow(user_input: str, session: dict, intent: str) -> dict:
    """
    Master dispatcher for all business-related intents.

    intent: 'BUSINESS' | 'BUSINESS_INFO' | 'INSURANCE' | 'WARRANTY'

    Returns:
        {
            "response" : str  — bot reply
            "complete" : bool — True when flow is done
        }
    """
    if intent == "BUSINESS_INFO":
        result = handle_business_info(user_input, session)
        return {
            "response": result.get("response", ""),
            "complete": True
        }

    if intent == "INSURANCE":
        result = handle_insurance_query(user_input, session)
        return {
            "response": result.get("response", ""),
            "complete": True
        }

    if intent == "WARRANTY":
        result = handle_warranty_query(user_input, session)
        return {
            "response": result.get("response", ""),
            "complete": True
        }

    if intent == "BUSINESS":
        return _handle_business_caller_flow(user_input, session)

    # Fallback
    return {
        "response": "I'm sorry, could you please repeat that?",
        "complete": True
    }


# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS CALLER MULTI-TURN FLOW
# ─────────────────────────────────────────────────────────────────────────────

def _handle_business_caller_flow(user_input: str, session: dict) -> dict:
    """
    Handle supplier/agent/lab calls.
    If the initial message has all the info → process immediately.
    If missing critical info → ask a single follow-up question.
    """
    step = session.get("biz_step", "extract_and_process")

    if step == "extract_and_process":
        return _biz_extract_and_process(user_input, session)

    elif step == "ask_patient_name":
        return _biz_ask_patient_name(user_input, session)

    elif step == "ask_product_name":
        return _biz_ask_product_name(user_input, session)

    # Fallback
    return _biz_extract_and_process(user_input, session)


def _biz_extract_and_process(user_input: str, session: dict) -> dict:
    """
    Try to extract all info and process.
    If key info is missing for order_ready calls, ask for it.
    """
    from business.business_controller import _extract_order_info

    sub_type  = _classify_business_call(user_input)
    extracted = _extract_business_caller_info(user_input, session)

    session["biz_data"] = {
        "sub_type":     sub_type,
        "extracted":    extracted,
        "raw_input":    user_input
    }

    # For order_ready calls — if patient name or product is missing, ask
    if sub_type == "order_ready":
        order_info = _extract_order_info(user_input)

        if not order_info.get("patient_name"):
            session["biz_step"] = "ask_patient_name"
            session["biz_data"]["order_info"] = order_info
            return {
                "response": (
                    "Thank you for letting us know! "
                    "Could you please tell me which patient this order is for?"
                ),
                "complete": False
            }

        if not order_info.get("product_name"):
            session["biz_step"] = "ask_product_name"
            session["biz_data"]["order_info"] = order_info
            return {
                "response": (
                    "Thank you! And which item is ready — "
                    "for example, dentures, crown, mouthguard?"
                ),
                "complete": False
            }

        session["biz_data"]["order_info"] = order_info

    # All info present — process now
    result = handle_business_caller(user_input, session)
    _cleanup_biz_session(session)

    return {
        "response": result.get("response", ""),
        "complete": True
    }


def _biz_ask_patient_name(user_input: str, session: dict) -> dict:
    """User just provided the patient name."""
    biz_data = session.get("biz_data", {})
    order_info = biz_data.get("order_info", {})
    order_info["patient_name"] = user_input.strip()
    session["biz_data"]["order_info"] = order_info

    # Check if product name is also missing
    if not order_info.get("product_name"):
        session["biz_step"] = "ask_product_name"
        return {
            "response": (
                "Thank you! And which item is ready — "
                "for example, dentures, crown, mouthguard?"
            ),
            "complete": False
        }

    # Have everything now — process
    result = handle_business_caller(
        biz_data.get("raw_input", ""), session
    )
    _cleanup_biz_session(session)

    return {
        "response": result.get("response", ""),
        "complete": True
    }


def _biz_ask_product_name(user_input: str, session: dict) -> dict:
    """User just provided the product/item name."""
    biz_data = session.get("biz_data", {})
    order_info = biz_data.get("order_info", {})
    order_info["product_name"] = user_input.strip()
    session["biz_data"]["order_info"] = order_info

    result = handle_business_caller(
        biz_data.get("raw_input", ""), session
    )
    _cleanup_biz_session(session)

    return {
        "response": result.get("response", ""),
        "complete": True
    }


def _cleanup_biz_session(session: dict):
    """Clean up business flow session keys after completion."""
    session.pop("biz_step", None)
    session.pop("biz_data", None)
    session["current_flow"] = None
