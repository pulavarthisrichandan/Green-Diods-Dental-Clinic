"""
LLM Intent Classifier - DentalBot v2
Classifies user intent with full context awareness.
"""

import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()


def classify_intent(user_input: str, conversation_history: list) -> dict:
    """
    Classify user message into one of the defined intents.

    Returns:
        {
            "intent": str,
            "confidence": float,
            "reasoning": str
        }

    Intents:
        APPOINTMENT     — Book a new appointment
        UPDATE_CANCEL   — Modify or cancel an existing appointment
        GENERAL_ENQUIRY — Patient asking about their orders / treatment status
        COMPLAINT       — Filing a complaint
        BUSINESS        — Supplier, agent, lab, or business call
        KB              — General dental treatment/procedure questions
        INSURANCE       — Insurance-related questions
        WARRANTY        — Warranty-related questions
        BUSINESS_INFO   — Clinic hours, dentist info, pricing, payment options
    """

    system_prompt = """You are an intent classifier for a dental clinic AI receptionist.

Classify the user message into EXACTLY ONE of these intents:

APPOINTMENT
  → User wants to book a NEW appointment
  Examples: "I need an appointment", "I want to book a cleaning", "Can I schedule a check-up"

UPDATE_CANCEL
  → User wants to update or cancel an EXISTING appointment
  Examples: "I need to cancel", "Can I reschedule?", "I want to change my appointment time"

GENERAL_ENQUIRY
  → Patient asking about their order/treatment status (dentures ready, x-ray, etc.)
  Examples: "I want to know about my order", "Has my denture arrived?", "I have an enquiry about my treatment"

COMPLAINT
  → User wants to make a complaint
  Examples: "I want to complain", "I had a bad experience", "I'm not happy with the service"

BUSINESS
  → Supplier, agent, lab, or third-party company calling
  Examples: "I'm calling from a dental lab", "Your order is ready", "I have an invoice", "I want to offer promotions"

KB
  → Questions about specific dental treatments, procedures, precautions, post-care
  Examples: "What happens during a root canal?", "How do I care for my filling?", "What is a crown?"

INSURANCE
  → Questions specifically about health insurance
  Examples: "Do you accept Medibank?", "How does insurance work here?", "What insurance do you take?"

WARRANTY
  → Questions specifically about dental warranty
  Examples: "Is there a warranty?", "What is your warranty policy?", "Can I claim warranty?"

BUSINESS_INFO
  → Questions about clinic hours, dentist info, pricing, payment methods, offers
  Examples: "What are your hours?", "How much does cleaning cost?", "Who are your dentists?", "Do you accept Afterpay?"

RULES:
- If caller mentions being from a company/lab/supplier → BUSINESS (not KB)
- If patient asks about their specific order status → GENERAL_ENQUIRY
- If patient asks about dental procedures in general → KB
- If patient asks about clinic hours/dentists/pricing → BUSINESS_INFO
- Insurance questions → INSURANCE (never KB)
- Warranty questions → WARRANTY (never KB)
- Use conversation history to resolve ambiguity

Return ONLY valid JSON:
{
    "intent": "<one of the intents above>",
    "confidence": 0.0-1.0,
    "reasoning": "one sentence explanation"
}"""

    context_messages = conversation_history[-4:] if conversation_history else []
    context_text = ""
    if context_messages:
        context_text = "Recent conversation:\n"
        for msg in context_messages:
            role = "User" if msg["role"] == "user" else "Bot"
            context_text += f"{role}: {msg['content']}\n"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": f"{context_text}\nCurrent message: {user_input}"}
            ],
            temperature=0.1,
            max_tokens=100,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {
            "intent": "KB",
            "confidence": 0.5,
            "reasoning": f"fallback due to error: {str(e)}"
        }
