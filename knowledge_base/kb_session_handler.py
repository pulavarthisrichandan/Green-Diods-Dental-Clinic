"""
KB Session Handler - DentalBot v2

Wraps the KB controller with session state management.
KB is mostly single-turn — but handles follow-up questions
in context via conversation history.

Also provides the "return to previous flow" helper that
main.py uses after a KB interruption mid-flow.
"""

from knowledge_base.kb_controller import handle_kb_query


def handle_kb_flow(user_input: str, session: dict) -> dict:
    """
    Entry point for KB intent from main.py.

    Handles:
        1. Direct KB question  → answer + offer to continue if mid-flow
        2. Follow-up KB question → answer in context

    Returns:
        {
            "response"      : str  — bot reply
            "complete"      : bool — always True for KB
            "resume_flow"   : bool — True if there is a paused flow to return to
            "resume_prompt" : str  — what bot asks to resume (e.g., "Shall we continue
                                      with your appointment booking?")
        }
    """
    result = handle_kb_query(user_input, session)

    # Check if there's a paused flow to return to
    previous_flow = session.get("previous_flow")
    resume_prompt = ""
    resume_flow   = False

    if previous_flow:
        flow_labels = {
            "APPOINTMENT":    "your appointment booking",
            "UPDATE_CANCEL":  "your appointment update",
            "COMPLAINT":      "your complaint",
            "GENERAL_ENQUIRY":"your enquiry"
        }
        flow_label  = flow_labels.get(previous_flow, "what we were doing")
        resume_prompt = (
            f" Would you like to continue with {flow_label}, "
            f"or is there anything else I can help you with?"
        )
        resume_flow = True

    full_response = result["response"] + resume_prompt

    return {
        "response":      full_response,
        "complete":      True,
        "resume_flow":   resume_flow,
        "resume_prompt": resume_prompt,
        "source":        result.get("source", "kb_rules")
    }
