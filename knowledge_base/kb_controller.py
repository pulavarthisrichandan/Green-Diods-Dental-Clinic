"""
Knowledge Base Controller - DentalBot v2

Source: config/kb_rules.txt ONLY.

Boundaries:
    ✅ Treatment explanations, procedure steps, pre/post care, dental tips
    ❌ Insurance / warranty   → redirect to business module
    ❌ Pricing / hours        → redirect to business_info
    ❌ Medical diagnoses      → redirect to dentist
    ❌ Medication advice      → redirect to dentist
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()


# ─────────────────────────────────────────────────────────────────────────────
# LOAD KB RULES AT STARTUP
# ─────────────────────────────────────────────────────────────────────────────

def _load_kb_rules() -> str:
    path = os.path.join(os.path.dirname(__file__), '..', 'config', 'kb_rules.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"[KB rules file not found: {e}]"


KB_RULES = _load_kb_rules()


# ─────────────────────────────────────────────────────────────────────────────
# SCOPE GUARD — keyword check before calling LLM (saves cost)
# ─────────────────────────────────────────────────────────────────────────────

def _is_out_of_scope(text: str) -> tuple[bool, str]:
    t = text.lower()

    insurance_keywords = [
        "insurance", "medibank", "bupa", "hcf", "nib", "cbhs",
        "hbf", "ahm", "health fund", "health insurance", "rebate",
        "claim", "hicaps", "cover", "coverage", "covered"
    ]
    warranty_keywords = [
        "warranty", "guarantee", "warranted", "claim warranty",
        "warranty claim", "warranty period", "warranty terms"
    ]
    medication_keywords = [
        "medication", "medicine", "drug", "tablet", "antibiotic",
        "painkiller", "ibuprofen", "paracetamol", "prescription",
        "dosage", "dose", "take how many", "what medication"
    ]
    diagnosis_keywords = [
        "do i have", "is this", "am i", "diagnose", "diagnosis",
        "what disease", "what condition", "what infection",
        "what is wrong with", "should i be worried about"
    ]

    if any(kw in t for kw in insurance_keywords):
        return True, (
            "For insurance-related questions, I can share some general "
            "information. Would you like me to do that, or shall I continue "
            "with your other question?"
        )
    if any(kw in t for kw in warranty_keywords):
        return True, (
            "For warranty-related questions, I can share some general "
            "information about our warranty policy. Would you like that?"
        )
    if any(kw in t for kw in medication_keywords):
        return True, (
            "I'm sorry, I'm not able to provide medication advice. "
            "For specific medication recommendations, please consult "
            "your dentist directly — they'll be able to guide you best."
        )
    if any(kw in t for kw in diagnosis_keywords):
        return True, (
            "I'm sorry, I'm not able to provide a diagnosis. "
            "For any specific concerns about your dental health, "
            "I'd strongly recommend booking an appointment with one "
            "of our dentists — they'll be able to properly assess and advise you."
        )

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_kb_query(user_input: str, session: dict) -> dict:
    """
    Answer a dental treatment or health question using kb_rules.txt.
    Returns: { "response": str, "complete": bool, "source": str }
    """
    if not user_input or not user_input.strip():
        return {
            "response": "Could you please repeat your question? I want to make sure I give you the right information.",
            "complete": True,
            "source":   "empty_input"
        }

    # Scope check first — no LLM cost
    out_of_scope, redirect_msg = _is_out_of_scope(user_input)
    if out_of_scope:
        return {"response": redirect_msg, "complete": True, "source": "out_of_scope"}

    patient_name = ""
    if session.get("verified") and session.get("patient_data"):
        patient_name = session["patient_data"].get("first_name", "")

    history     = session.get("conversation_history", [])
    recent      = history[-6:] if len(history) > 6 else history
    context_str = _build_context(recent)

    system_prompt = f"""You are Sarah, a warm dental clinic receptionist.

Answer the patient's question using ONLY the information in the
KNOWLEDGE BASE below. Do not use any external knowledge.

KNOWLEDGE BASE:
{KB_RULES}

STRICT RULES:
1. Answer ONLY from the knowledge base above
2. If the question is not covered → say:
   "I'm sorry, I don't have specific information on that.
    I'd recommend consulting your dentist directly for the most accurate advice."
3. NEVER provide medication names, dosages, or drug advice
4. NEVER provide a diagnosis or clinical assessment
5. NEVER answer insurance or warranty questions from this module
6. Keep answers conversational and concise (2-5 sentences for voice)
7. Use the patient's first name if available: "{patient_name}"
8. If the patient asks a follow-up, answer in context — do not repeat from scratch

CONVERSATION CONTEXT (last few turns):
{context_str}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0.3,
            max_tokens=350
        )
        answer = _sanitize_response(response.choices[0].message.content.strip())
        return {"response": answer, "complete": True, "source": "kb_rules"}

    except Exception as e:
        return {
            "response": (
                "I'm sorry, I'm having a little trouble retrieving that information right now. "
                "Please feel free to ask again, or I can have our team call you back with the answer."
            ),
            "complete": True,
            "source":   "error"
        }


def handle_kb_followup(user_input: str, session: dict) -> dict:
    """Follow-up KB questions — uses same handler, context via session history."""
    return handle_kb_query(user_input, session)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_context(history: list) -> str:
    """Build context string from recent conversation history."""
    if not history:
        return "No prior context."
    lines = []
    for msg in history:
        role    = "Patient" if msg.get("role") == "user" else "Sarah"
        content = msg.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "No prior context."


def _sanitize_response(response: str) -> str:
    """
    Safety net — if LLM accidentally includes medication names,
    replace with a standard redirect.
    """
    medication_terms = [
        "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin",
        "penicillin", "metronidazole", "clindamycin", "codeine",
        "tramadol", "diclofenac", "naproxen", "aspirin",
        "mg", "milligram", "tablet", "capsule", "antibiotic",
        "take 2", "take one", "twice daily", "three times"
    ]
    if any(term in response.lower() for term in medication_terms):
        return (
            "For specific medication or dosage advice, "
            "I'd recommend speaking directly with your dentist "
            "or pharmacist — they'll be able to give you "
            "the most accurate and safe guidance."
        )
    return response
