"""
Business Controller - DentalBot v2

Handles 4 distinct intents:
    BUSINESS_INFO → Clinic hours, dentist info, pricing, payments, offers
    INSURANCE     → Insurance questions (from insurance_warranty_rules.txt only)
    WARRANTY      → Warranty questions (from insurance_warranty_rules.txt only)
    BUSINESS      → Supplier / agent / lab / third-party calls

All answers come from rules text files only.
"""

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()


# ─────────────────────────────────────────────────────────────────────────────
# LOAD RULES FILES AT STARTUP
# ─────────────────────────────────────────────────────────────────────────────

def _load_rules(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), '..', 'config', filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"[Rules file not found: {filename} — {e}]"


BUSINESS_RULES           = _load_rules("business_rules.txt")
INSURANCE_WARRANTY_RULES = _load_rules("insurance_warranty_rules.txt")


# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS INFO
# ─────────────────────────────────────────────────────────────────────────────

def handle_business_info(user_input: str, session: dict) -> dict:
    """
    Handle clinic hours, dentist info, pricing, payment methods, offers.
    Source: business_rules.txt ONLY.
    """
    patient_name = ""
    if session.get("verified") and session.get("patient_data"):
        patient_name = session["patient_data"].get("first_name", "")

    system_prompt = f"""You are Sarah, a warm dental clinic receptionist.

Answer the patient's question using ONLY the information in the
BUSINESS RULES below. Do not invent or add any information.

BUSINESS RULES:
{BUSINESS_RULES}

RESPONSE RULES:
- Keep the answer concise and conversational (1-4 sentences for voice)
- Use the patient's first name if available: "{patient_name}"
- Never fetch from any website
- Never mention internal IDs
- If the question is not covered in the rules, say:
  "I'm sorry, I don't have that specific information right now.
   Please call us during business hours and our team will assist you."
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0.3,
            max_tokens=300
        )
        return {
            "status":   "SUCCESS",
            "response": response.choices[0].message.content.strip(),
            "source":   "business_rules"
        }
    except Exception as e:
        return {
            "status":   "ERROR",
            "response": (
                "I'm sorry, I'm having trouble retrieving that information right now. "
                "Please call us during business hours and our team will help you."
            )
        }


# ─────────────────────────────────────────────────────────────────────────────
# INSURANCE
# ─────────────────────────────────────────────────────────────────────────────

def handle_insurance_query(user_input: str, session: dict) -> dict:
    """
    Handle insurance questions.
    Source: insurance_warranty_rules.txt [INSURANCE] section ONLY.
    """
    patient_name = ""
    if session.get("verified") and session.get("patient_data"):
        patient_name = session["patient_data"].get("first_name", "")

    system_prompt = f"""You are Sarah, a warm dental clinic receptionist.

Answer the patient's insurance question using ONLY the [INSURANCE]
section of the rules below.

INSURANCE & WARRANTY RULES:
{INSURANCE_WARRANTY_RULES}

STRICT RULES:
1. Answer ONLY from the [INSURANCE] section
2. If the patient asks anything more detailed than what is written
   (specific rebate amounts, claim eligibility, exact coverage),
   say EXACTLY:
   "For more detailed information on this, I'd recommend speaking
    directly with your dentist or contacting your insurance provider,
    as they'll be able to give you the most accurate guidance."
3. Keep responses conversational and concise for voice
4. Use patient's first name if available: "{patient_name}"
5. Never invent information not present in the rules
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0.2,
            max_tokens=250
        )
        return {
            "status":   "SUCCESS",
            "response": response.choices[0].message.content.strip(),
            "source":   "insurance_rules"
        }
    except Exception as e:
        return {
            "status":   "ERROR",
            "response": (
                "I'm sorry, I'm having difficulty retrieving that information. "
                "I'd recommend speaking with your dentist directly for insurance guidance."
            )
        }


# ─────────────────────────────────────────────────────────────────────────────
# WARRANTY
# ─────────────────────────────────────────────────────────────────────────────

def handle_warranty_query(user_input: str, session: dict) -> dict:
    """
    Handle warranty questions.
    Source: insurance_warranty_rules.txt [WARRANTY] section ONLY.
    """
    patient_name = ""
    if session.get("verified") and session.get("patient_data"):
        patient_name = session["patient_data"].get("first_name", "")

    system_prompt = f"""You are Sarah, a warm dental clinic receptionist.

Answer the patient's warranty question using ONLY the [WARRANTY]
section of the rules below.

INSURANCE & WARRANTY RULES:
{INSURANCE_WARRANTY_RULES}

STRICT RULES:
1. Answer ONLY from the [WARRANTY] section
2. If the patient asks anything more specific than what is written
   (exact warranty period for a specific treatment, claim escalation),
   say EXACTLY:
   "For more detailed information on this, I'd recommend speaking
    directly with your dentist who will be able to guide you better
    based on your specific situation."
3. Keep responses conversational and concise for voice
4. Use patient's first name if available: "{patient_name}"
5. Never invent information not present in the rules
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0.2,
            max_tokens=250
        )
        return {
            "status":   "SUCCESS",
            "response": response.choices[0].message.content.strip(),
            "source":   "warranty_rules"
        }
    except Exception as e:
        return {
            "status":   "ERROR",
            "response": (
                "I'm sorry, I'm having difficulty retrieving that information. "
                "I'd recommend speaking with your dentist directly for warranty guidance."
            )
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFY BUSINESS CALL
# ✅ PUBLIC function — main.py imports this directly as classify_business_call
# ─────────────────────────────────────────────────────────────────────────────

def classify_business_call(user_input: str) -> str:
    """
    Classify the type of business call.
    Returns: 'order_ready' | 'invoice' | 'promotion' | 'general'
    Called directly by main.py in the logsuppliercall handler.
    """
    if not user_input:
        return "general"

    t = user_input.lower()

    order_keywords     = [
        "ready", "order is ready", "order ready", "pickup",
        "denture", "crown", "x-ray", "xray", "mouthguard",
        "appliance", "lab work", "has been completed",
        "is complete", "available for collection"
    ]
    invoice_keywords   = [
        "invoice", "billing", "payment", "bill", "outstanding",
        "account", "overdue", "statement", "charge", "fee"
    ]
    promotion_keywords = [
        "promotion", "offer", "partnership", "collaborate",
        "product range", "services", "advertise", "market",
        "business opportunity", "introduce", "represent"
    ]

    order_score     = sum(1 for kw in order_keywords     if kw in t)
    invoice_score   = sum(1 for kw in invoice_keywords   if kw in t)
    promotion_score = sum(1 for kw in promotion_keywords if kw in t)

    scores = {
        "order_ready": order_score,
        "invoice":     invoice_score,
        "promotion":   promotion_score
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACT ORDER INFO
# ✅ PUBLIC function — main.py imports this directly as extract_order_info
# ─────────────────────────────────────────────────────────────────────────────

def extract_order_info(user_input: str) -> dict:
    """
    Extract patient name and product name from an order-ready message.
    e.g. "The dentures for John Smith are ready"
    Called directly by main.py in the logsuppliercall handler.
    """
    system_prompt = """Extract from this supplier/lab message:
- The patient's name (who the order is for)
- The product/item name (e.g. dentures, crown, x-ray, mouthguard)

Return ONLY valid JSON:
{
    "patient_name": "full name of the patient or null",
    "product_name": "name of the product/item or null"
}
If a field is not mentioned, use null."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0,
            max_tokens=80,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"patient_name": None, "product_name": None}


# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS CALLER HANDLER (full flow)
# ─────────────────────────────────────────────────────────────────────────────

def handle_business_caller(user_input: str, session: dict) -> dict:
    """
    Handle BUSINESS intent — supplier, agent, lab, or company caller.
    Routes to correct sub-handler based on call type.
    """
    extracted = _extract_business_caller_info(user_input, session)
    sub_type  = classify_business_call(user_input)

    if sub_type == "order_ready":
        return _handle_order_ready(user_input, extracted, session)
    elif sub_type == "invoice":
        return _handle_invoice_call(extracted, session)
    elif sub_type == "promotion":
        return _handle_promotion_call(extracted, session)
    else:
        return _handle_generic_business_call(extracted, session)


# ─────────────────────────────────────────────────────────────────────────────
# PRIVATE SUB-HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def _handle_order_ready(user_input: str, extracted: dict, session: dict) -> dict:
    from business.business_executor import update_order_status_by_patient_name, log_business_call

    order_info = extract_order_info(user_input)

    log_business_call(
        caller_name=    extracted.get("caller_name"),
        company_name=   extracted.get("company_name"),
        contact_number= extracted.get("contact_number"),
        purpose=        "order_ready",
        full_notes=     user_input
    )

    db_result = None
    if order_info.get("patient_name") and order_info.get("product_name"):
        db_result = update_order_status_by_patient_name(
            patient_name= order_info["patient_name"],
            product_name= order_info["product_name"],
            new_status=   "ready",
            notes=        user_input
        )

    caller  = extracted.get("caller_name",  "")
    company = extracted.get("company_name", "your company")
    product = order_info.get("product_name", "the item")
    patient = order_info.get("patient_name", "the patient")

    if db_result and db_result.get("status") == "UPDATED":
        response = (
            f"Thank you{', ' + caller if caller else ''}! "
            f"I've noted that {product} for {patient} is ready. "
            f"I'll inform our management team right away. "
            f"Thank you for calling!"
        )
    else:
        response = (
            f"Thank you{', ' + caller if caller else ''} from {company}! "
            f"I've noted that {product} for {patient} is ready. "
            f"I'll pass this on to our management team immediately. "
            f"Thank you for letting us know!"
        )

    return {"status": "LOGGED", "response": response, "sub_type": "order_ready"}


def _handle_invoice_call(extracted: dict, session: dict) -> dict:
    from business.business_executor import log_business_call

    log_business_call(
        caller_name=    extracted.get("caller_name"),
        company_name=   extracted.get("company_name"),
        contact_number= extracted.get("contact_number"),
        purpose=        "invoice_billing",
        full_notes=     extracted.get("raw_input", "")
    )

    caller  = extracted.get("caller_name",  "")
    company = extracted.get("company_name", "your company")
    contact = extracted.get("contact_number", "")

    response = (
        f"Thank you{', ' + caller if caller else ''} from {company}! "
        f"I've noted your billing query and passed it on to our management team. "
        f"{'They will contact you on ' + contact + ' shortly.' if contact else 'They will be in touch with you shortly.'} "
        f"Thank you for calling!"
    )
    return {"status": "LOGGED", "response": response, "sub_type": "invoice"}


def _handle_promotion_call(extracted: dict, session: dict) -> dict:
    from business.business_executor import log_business_call

    log_business_call(
        caller_name=    extracted.get("caller_name"),
        company_name=   extracted.get("company_name"),
        contact_number= extracted.get("contact_number"),
        purpose=        "promotion_partnership",
        full_notes=     extracted.get("raw_input", "")
    )

    caller  = extracted.get("caller_name",  "")
    company = extracted.get("company_name", "your company")

    response = (
        f"That sounds great{', ' + caller if caller else ''}! "
        f"Thank you for reaching out from {company}. "
        f"I've passed your details on to our management team. "
        f"They will get back to you within 2 to 3 business days. "
        f"Thank you for calling!"
    )
    return {"status": "LOGGED", "response": response, "sub_type": "promotion"}


def _handle_generic_business_call(extracted: dict, session: dict) -> dict:
    from business.business_executor import log_business_call

    log_business_call(
        caller_name=    extracted.get("caller_name"),
        company_name=   extracted.get("company_name"),
        contact_number= extracted.get("contact_number"),
        purpose=        "general_business",
        full_notes=     extracted.get("raw_input", "")
    )

    caller  = extracted.get("caller_name",  "")
    company = extracted.get("company_name", "your company")

    response = (
        f"Thank you{', ' + caller if caller else ''} from {company}! "
        f"I've noted your message and passed it on to our management team. "
        f"They will be in touch with you shortly. Thank you for calling!"
    )
    return {"status": "LOGGED", "response": response, "sub_type": "general"}


def _extract_business_caller_info(user_input: str, session: dict) -> dict:
    system_prompt = """Extract the following fields from this business caller's message.
Return ONLY valid JSON with these exact keys:
{
    "caller_name":    "name of the person calling or null",
    "company_name":   "name of the company/lab/supplier or null",
    "contact_number": "contact number they provided or null",
    "purpose":        "brief one-sentence summary of why they are calling"
}
If a field is not mentioned, use null. Do not invent any information."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_input}
            ],
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        data["raw_input"] = user_input
        return data
    except Exception:
        return {
            "caller_name":    None,
            "company_name":   None,
            "contact_number": None,
            "purpose":        user_input[:200],
            "raw_input":      user_input
        }
