"""
DentalBot v2 -- main.py
OpenAI Realtime API + Twilio WebSocket

Fixes applied (cumulative):
  1-17: (see prior history)
  18: booking extraction + single confirm-before-book
  19: DOB any-format -> DD-MON-YYYY
  20: complaints type 1 (first/last/contact) + type 2 (full patient data)
  21: supplier check + order-by-patient-id + no-repeat questions
  22: FIX A - no upfront new/existing question (wait for intent)
      FIX B - treatment answers only from services list, never suggest consultation
      FIX C - barge-in triggers on ANY active response, not just is_speaking==True
"""

import os
import json
import asyncio
import traceback
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import Response
from fastapi.websockets import WebSocketDisconnect
from dotenv import load_dotenv
from datetime import datetime

from verification.verification_executor import (
    verify_by_lastname_dob, verify_by_lastname_dob_contact, create_new_patient
)
from appointment.executor import (
    check_dentist_availability, find_available_dentist, book_appointment,
    get_patient_appointments, update_appointment, cancel_appointment
)
from complaint.complaint_executor import save_complaint
from business.business_controller import (
    handle_business_info, handle_insurance_query, handle_warranty_query,
    classify_business_call, extract_order_info
)
from business.business_executor import (
    log_business_call, update_order_by_patient_id,
    update_order_status_by_patient_name, check_supplier, get_all_suppliers
)
from general_enquiry.enquiry_executor import (
    get_patient_orders, get_upcoming_appointments, get_past_appointments
)
from knowledge_base.kb_controller import handle_kb_query
from utils.phone_utils import extract_phone_from_text, format_phone_for_speech, normalize_dob

load_dotenv()
app = FastAPI()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

OPENAI_REALTIME_URL  = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
VOICE                = "coral"
TEMPERATURE          = 0.8
VAD_THRESHOLD        = 0.75
PREFIX_PADDING_MS    = 300
SILENCE_DURATION_MS  = 700   # ✅ FIX C: slightly lower for snappier barge-in
CLOUD_RUN_WSS_BASE   = "wss://green-diods-dental-clinic-production.up.railway.app"

# ---------------------------------------------------------------------------
# SYSTEM INSTRUCTIONS
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = (
    "You are Sarah, a warm and professional AI receptionist for Green Diodes Dental Clinic.\n\n"

    # ── SERVICES ──────────────────────────────────────────────────────────────
    "SERVICES (memorise exactly — these are the ONLY treatments you may mention or book):\n"
    "1. Teeth Cleaning and Check-Up\n"
    "2. Dental Implants\n"
    "3. All-on-4 Dental Implants\n"
    "4. Dental Fillings\n"
    "5. Wisdom Teeth Removal\n"
    "6. Emergency Dental Services\n"
    "7. Clear Aligners\n"
    "8. Dental Crowns and Bridges\n"
    "9. Root Canal Treatment\n"
    "10. Custom Mouthguards\n"
    "11. Dental Veneers\n"
    "12. Tooth Extraction\n"
    "13. Gum Disease Treatment\n"
    "14. Dentures\n"
    "15. Braces\n"
    "16. Teeth Whitening\n"
    "17. Zoom Whitening\n"
    "18. Children's Dentistry\n\n"

    # ✅ FIX B — treatment rules
    "TREATMENT ANSWER RULES — READ AND OBEY:\n"
    "1. ONLY ever recommend or mention treatments from the 18-item SERVICES list above.\n"
    "2. NEVER invent, suggest, or mention any treatment NOT in that list.\n"
    "3. NEVER suggest a 'consultation', 'initial consultation', or 'check-up consultation'.\n"
    "   If something similar is needed, say 'Teeth Cleaning and Check-Up' instead.\n"
    "4. For treatment details (what it involves, recovery, pre/post care) call answer_dental_question().\n"
    "5. answer_dental_question() uses ONLY our internal knowledge base — trust its response.\n"
    "6. If the knowledge base has no answer for a treatment question, say:\n"
    "   'I don't have detailed information on that right now — our team can help you in clinic.'\n"
    "7. NEVER make up prices, durations, or procedure steps.\n\n"

    "SYMPTOM MAPPING (answer directly, NO function call, NO consultation suggestion):\n"
    "tooth pain/sensitivity -> Teeth Cleaning and Check-Up, Dental Fillings, or Root Canal Treatment\n"
    "broken/cracked         -> Dental Crowns and Bridges or Emergency Dental Services\n"
    "severe/sudden pain     -> Emergency Dental Services\n"
    "missing tooth          -> Dental Implants, All-on-4 Dental Implants, or Dentures\n"
    "yellow/stained         -> Teeth Whitening or Zoom Whitening\n"
    "crooked/bite           -> Clear Aligners or Braces\n"
    "bleeding gums          -> Gum Disease Treatment\n"
    "wisdom tooth pain      -> Wisdom Teeth Removal\n"
    "chipped front tooth    -> Dental Veneers\n"
    "sport/grinding         -> Custom Mouthguards\n"
    "child dental issue     -> Children's Dentistry\n\n"

    "FUNCTION ROUTING:\n"
    "pricing/hours/payment/offers  -> get_business_information()\n"
    "insurance                     -> get_insurance_information()\n"
    "warranty                      -> get_warranty_information()\n"
    "procedures/pre-post care      -> answer_dental_question()\n"
    "order status                  -> get_my_order_status()\n"
    "upcoming appointments         -> get_my_upcoming_appointments()\n"
    "past treatment history        -> get_my_treatment_history()\n"
    "NEVER call get_business_information() just to list treatments.\n\n"

    "3-TIER ROUTING:\n"
    "Tier 1 pricing/hours  -> get_business_information()\n"
    "Tier 2 'what is X?'   -> get_business_information() -> 2-3 sentence summary\n"
    "Tier 3 detailed proc  -> answer_dental_question()\n\n"

    "PERSONALITY: warm, concise, English only, use first name after verification.\n\n"

    # ✅ FIX A — greeting and call-start behaviour
    "GREETING & CALL START:\n"
    "When the call starts say EXACTLY:\n"
    "  'Hello! Thank you for calling Green Diodes Dental Clinic. I'm Sarah, how may I assist you today?'\n"
    "Then STOP. Do NOT ask 'are you an existing patient?' at this point.\n"
    "WAIT silently for the user to speak first and tell you what they need.\n\n"

    "SPEAKING STYLE:\n"
    "- Speak naturally, use contractions: I'll, you're, we've\n"
    "- Natural fillers: 'Of course!', 'Absolutely!', 'Sure thing!'\n"
    "- Warm confirmations: 'Perfect, got that!' not 'Confirmed.'\n"
    "- Vary sentence length. Show empathy: 'Oh I'm sorry to hear that'\n"
    "- Never read structured lists — convert to spoken sentences\n"
    "- Say 'the 5th of March at 10 in the morning' not 'Date: 5th March, Time: 10 AM'\n\n"

    # ✅ FIX A — caller type and verification trigger
    "CALLER TYPE IDENTIFICATION — CRITICAL:\n\n"
    "PATIENT (the vast majority of calls):\n"
    "  Caller wants appointment, has tooth pain, asks about treatment/price,\n"
    "  wants to cancel/reschedule, has a complaint, asks about their order.\n"
    "  -> For general questions: answer directly, NO verification needed.\n"
    "  -> For appointment booking/update/cancel: verify first (see BOOKING below).\n"
    "  NEVER call log_supplier_call() for patients.\n\n"
    "BUSINESS / SUPPLIER (rare — explicit only):\n"
    "  ONLY when caller EXPLICITLY says 'I'm from [company]', sales rep, courier.\n"
    "  -> Call check_known_supplier() first, then route to Type 2 or Type 3.\n\n"

    # ✅ FIX A — when to ask new/existing
    "WHEN TO ASK 'ARE YOU A NEW OR EXISTING PATIENT?':\n"
    "Ask this question ONLY when the user's intent is one of these:\n"
    "  - Book an appointment\n"
    "  - Update an existing appointment\n"
    "  - Cancel an existing appointment\n"
    "  - Check their specific order status\n"
    "  - Check their upcoming appointments\n"
    "  - Check their treatment history\n"
    "DO NOT ask this for:\n"
    "  - Questions about clinic address, hours, phone number\n"
    "  - Questions about services or treatments\n"
    "  - Questions about pricing or payment\n"
    "  - Insurance or warranty questions\n"
    "  - General dental questions\n"
    "  - Complaints (follow COMPLAINTS FLOW — it has its own verification rules)\n"
    "  - Any general inquiry\n"
    "RULE: Greet -> wait -> listen to intent -> THEN decide if verification is needed.\n\n"

    "VERIFICATION FLOWS:\n\n"
    "EXISTING PATIENT FLOW:\n"
    "  Step 1: Ask last name\n"
    "  Step 2: Ask date of birth\n"
    "  Step 3: Convert DOB to DD-MON-YYYY, read back:\n"
    "    'Just to confirm, that's the [DD] of [Month] [YYYY] — is that right?'\n"
    "    Examples: '12/06/1990' -> '12th of June 1990'\n"
    "              '15 03 2001' -> '15th of March 2001'\n"
    "    WAIT for YES before calling verify_existing_patient()\n"
    "  Step 4: Call verify_existing_patient()\n"
    "    VERIFIED       -> read contact digit by digit, then assist\n"
    "    MULTIPLE_FOUND -> ask contact number, call verify_with_contact_number()\n"
    "    NOT_FOUND      -> offer retry or create new account\n\n"
    "NEW PATIENT FLOW (no skipping):\n"
    "  Step 1: first name  Step 2: last name  Step 3: DOB (confirm as DD-MON-YYYY)\n"
    "  Step 4: contact (read back digit by digit, wait for confirmation)\n"
    "  Step 5: insurance (optional — may say 'none')\n"
    "  Step 6: call create_new_patient() immediately\n"
    "  Step 7: wait for status=CREATED\n"
    "  Step 8: say 'Great, your account's all set!' then continue to booking\n\n"
    "After verification: patient is verified for the ENTIRE call.\n"
    "Use first name. NEVER ask name/contact again.\n\n"

    "GOLDEN RULES (never break):\n"
    "1. NEVER ask appointment ID — use get_my_appointments()\n"
    "2. NEVER mention any internal ID in responses\n"
    "3. NEVER ask name or contact after verification\n"
    "4. NEVER give medication advice or diagnose\n"
    "5. After booking — say date, time, dentist only\n"
    "6. NEVER say 'schedule a consultation' or 'book a consultation'\n"
    "7. Phone readback ALWAYS digit by digit\n"
    "8. NEVER ask a repeated question\n"
    "9. NEVER mention any treatment not in the 18-item SERVICES list\n\n"

    "CLINIC DETAILS (from memory, no function call):\n"
    "- Address: 123, Building, Melbourne Central, Melbourne, Victoria\n"
    "- Phone: 03 6160 3456\n"
    "- Hours: Monday-Friday 9:00 AM - 6:00 PM, Saturday-Sunday CLOSED\n\n"

    "DENTISTS:\n"
    "Dr. Emily Carter    (General Dentistry)\n"
    "Dr. James Nguyen    (Cosmetic and Restorative)\n"
    "Dr. Sarah Mitchell  (Orthodontics and Periodontics)\n\n"

    "BOOKING (only after patient is verified):\n"
    "DETAIL EXTRACTION:\n"
    "  - Treatment: map user words to exact service name\n"
    "    'cleaning' -> 'Teeth Cleaning and Check-Up'\n"
    "    'filling'  -> 'Dental Fillings'\n"
    "    'implant'  -> 'Dental Implants'\n"
    "    'whitening'-> 'Teeth Whitening'\n"
    "    'braces'   -> 'Braces'\n"
    "    'aligners' -> 'Clear Aligners'\n"
    "  - Dentist: map partial to full name\n"
    "    'James'/'Nguyen' -> 'Dr. James Nguyen'\n"
    "    'Emily'/'Carter' -> 'Dr. Emily Carter'\n"
    "    'Mitchell'/'Sarah' -> 'Dr. Sarah Mitchell'\n"
    "    NEVER substitute a different dentist\n"
    "BOOKING FLOW:\n"
    "  1. Collect treatment, date, time, dentist preference\n"
    "  2. If specific dentist -> check_slot_availability()\n"
    "     If no preference    -> find_any_available_dentist()\n"
    "  3. Confirm ALL details ONCE: 'So that's [treatment] on [date] at [time] "
    "with [dentist] — shall I go ahead and book that for you?'\n"
    "  4. Patient says YES -> call book_appointment() immediately\n"
    "  5. NEVER book without YES. NEVER confirm again after YES.\n\n"

    "UPDATE/CANCEL:\n"
    "  Skip 'new or existing' question — only existing patients have appointments.\n"
    "  Go to EXISTING PATIENT FLOW directly (last name -> DOB -> verify).\n"
    "  After verification: call get_my_appointments() -> read as numbered list.\n"
    "  Use appointment_index (1, 2, 3…) for update or cancel.\n"
    "  CANCEL: confirm with patient -> cancel_my_appointment() after YES.\n\n"

    "COMPLAINTS — TWO-TYPE FLOW:\n\n"
    "STEP 1: Ask first:\n"
    "  'Is your complaint about something general — like our service, staff, "
    "or environment — or is it specifically about a treatment you received?'\n\n"
    "TYPE 1 — GENERAL (no verification needed):\n"
    "  Triggers: staff, waiting, billing, parking, cleanliness, phone, reception.\n"
    "  1. Empathy: 'I'm so sorry to hear that, I completely understand.'\n"
    "  2. 'Could you describe what happened?'\n"
    "  3. 'May I take your first name, last name, and best contact number?'\n"
    "  4. Confirm complaint summary once. YES -> file_complaint(general)\n"
    "  !!! NEVER ask DOB. NEVER verify. NEVER ask new/existing. !!!\n\n"
    "TYPE 2 — TREATMENT (verification required):\n"
    "  Triggers: filling, crown, implant, root canal, aligner, veneer, pain after procedure.\n"
    "  1. Empathy: 'I'm really sorry about your treatment experience.'\n"
    "  2. Follow EXISTING PATIENT FLOW\n"
    "  3. Collect: treatment name, dentist name, approx date, complaint details\n"
    "  4. Confirm all once. YES -> file_complaint(treatment)\n\n"
    "COMPLAINT RULES:\n"
    "  - Ask TYPE 1 vs TYPE 2 FIRST — never jump to verification\n"
    "  - Never ask DOB for TYPE 1\n"
    "  - Never mention complaint ID\n"
    "  - Always empathy before any question\n\n"

    "BUSINESS CALL ROUTING — THREE TYPES:\n\n"
    "TYPE 1 — PATIENT ENQUIRY: pricing, hours, services, insurance, warranty.\n"
    "  -> Answer directly. No verification for general questions.\n\n"
    "TYPE 2 — AGENT / VENDOR CALL (invoice, delay, promotion):\n"
    "  Extract name/company from what was already said — do NOT re-ask.\n"
    "  Ask only missing: contact number, purpose.\n"
    "  Call log_supplier_call(). Say: 'I've noted this for management.'\n"
    "  Never commit to payments or approvals. Never share patient data.\n\n"
    "TYPE 3 — SUPPLIER ORDER-READY CALL:\n"
    "  Valid suppliers: AusDental Labs Pty Ltd, MedPro Orthodontics,\n"
    "    Southern Implant Supply Co., PrecisionDenture Works, OralCraft Technologies.\n"
    "  1. Call check_known_supplier(company_name)\n"
    "  2. FOUND -> ask patient_id or last name + product name\n"
    "  3. Call update_supplier_order() + log_supplier_call()\n"
    "  4. 'Done! Order marked as ready for [patient]. Our team will arrange collection.'\n\n"

    "MID-FLOW: unrelated question -> answer -> 'Shall we continue?' -> YES resume.\n\n"
    "ENDING: 'Thank you for calling Green Diodes Dental Clinic. Have a wonderful day!'\n\n"

    "TURN-TAKING RULES:\n"
    "After asking ANY question, STOP and wait silently.\n"
    "NEVER ask a follow-up until the user answers the current one.\n"
    "NEVER assume information the user has not given.\n"
    "NEVER ask a question you already have the answer to."
)


# ---------------------------------------------------------------------------
# SAFE OPENAI SEND
# ---------------------------------------------------------------------------

async def safe_openai_send(openai_ws, payload: dict):
    if not openai_ws:
        return
    try:
        await openai_ws.send(json.dumps(payload))
    except websockets.exceptions.ConnectionClosed:
        print("[OpenAI WS] Send skipped — socket closed")
    except Exception as e:
        print("[OpenAI WS ERROR]", e)


# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------

def make_new_session(call_sid: str) -> dict:
    return {
        "call_sid":               call_sid,
        "stream_sid":             None,
        "created_at":             datetime.now(),
        "verified":               False,
        "patient_data":           None,
        "current_flow":           None,
        "fetched_appointments":   [],
        "is_speaking":            False,
        "interruption_pending":   False,
        "current_response_id":    None,
        "greeting_sent":          False,
        "conversation_history":   [],
        "last_assistant_item_id": None,
        "audio_start_time":       None,
        "elapsed_ms":             0,
        "audio_queue":            [],
        "supplier_context": {
            "caller_name":       None,
            "company_name":      None,
            "contact_number":    None,
            "is_known_supplier": False,
        },
    }


def update_history(session: dict, role: str, content: str):
    session["conversation_history"].append({
        "role":      role,
        "content":   content,
        "timestamp": datetime.now().isoformat()
    })


# ---------------------------------------------------------------------------
# SESSION CONFIG + TOOLS
# ---------------------------------------------------------------------------

def get_session_config() -> dict:
    return {
        "type": "session.update",
        "session": {
            "modalities":                ["text", "audio"],
            "instructions":              SYSTEM_INSTRUCTIONS,
            "voice":                     VOICE,
            "input_audio_format":        "g711_ulaw",
            "output_audio_format":       "g711_ulaw",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type":                "server_vad",
                "threshold":           VAD_THRESHOLD,
                "prefix_padding_ms":   PREFIX_PADDING_MS,
                "silence_duration_ms": SILENCE_DURATION_MS
            },
            "temperature":                TEMPERATURE,
            "max_response_output_tokens": 1024,
            "tools": [
                # ── VERIFICATION ──────────────────────────────────────────────
                {
                    "type": "function", "name": "verify_existing_patient",
                    "description": (
                        "Verify existing patient by last name and date of birth. "
                        "ONLY call after user has confirmed DOB in DD-MON-YYYY format."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "last_name":     {"type": "string"},
                            "date_of_birth": {"type": "string",
                                              "description": "DD-MON-YYYY e.g. 15 Jun 1990"}
                        },
                        "required": ["last_name", "date_of_birth"]
                    }
                },
                {
                    "type": "function", "name": "verify_with_contact_number",
                    "description": "Disambiguate when multiple patients share last name + DOB.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "last_name":      {"type": "string"},
                            "date_of_birth":  {"type": "string"},
                            "contact_number": {"type": "string"}
                        },
                        "required": ["last_name", "date_of_birth", "contact_number"]
                    }
                },
                {
                    "type": "function", "name": "create_new_patient",
                    "description": (
                        "Register a new patient. Call immediately after collecting "
                        "first_name, last_name, DOB, contact. "
                        "Do NOT say account ready before this returns status=CREATED."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "first_name":     {"type": "string"},
                            "last_name":      {"type": "string"},
                            "date_of_birth":  {"type": "string"},
                            "contact_number": {"type": "string"},
                            "insurance_info": {"type": "string"}
                        },
                        "required": ["first_name", "last_name", "date_of_birth", "contact_number"]
                    }
                },
                # ── APPOINTMENTS ──────────────────────────────────────────────
                {
                    "type": "function", "name": "check_slot_availability",
                    "description": "Check if a specific dentist is available at a given date/time.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date":         {"type": "string"},
                            "time":         {"type": "string"},
                            "dentist_name": {
                                "type": "string",
                                "description": "MUST be exact: Dr. Emily Carter | Dr. James Nguyen | Dr. Sarah Mitchell"
                            }
                        },
                        "required": ["date", "time", "dentist_name"]
                    }
                },
                {
                    "type": "function", "name": "find_any_available_dentist",
                    "description": "Find any available dentist when patient has no preference.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "time": {"type": "string"}
                        },
                        "required": ["date", "time"]
                    }
                },
                {
                    "type": "function", "name": "book_appointment",
                    "description": (
                        "Book appointment ONLY after patient says YES to full confirmation. "
                        "preferred_dentist MUST be exact full name with Dr. prefix. "
                        "preferred_treatment MUST be from the 18-item SERVICES list exactly."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "preferred_treatment": {"type": "string"},
                            "preferred_date":      {"type": "string"},
                            "preferred_time":      {"type": "string"},
                            "preferred_dentist":   {"type": "string"}
                        },
                        "required": ["preferred_treatment", "preferred_date",
                                     "preferred_time", "preferred_dentist"]
                    }
                },
                {
                    "type": "function", "name": "get_my_appointments",
                    "description": "Get all confirmed appointments. ALWAYS call before update/cancel.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "update_my_appointment",
                    "description": "Update appointment using appointment_index from get_my_appointments.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "appointment_index": {"type": "integer"},
                            "new_treatment":     {"type": "string"},
                            "new_date":          {"type": "string"},
                            "new_time":          {"type": "string"},
                            "new_dentist":       {"type": "string"}
                        },
                        "required": ["appointment_index"]
                    }
                },
                {
                    "type": "function", "name": "cancel_my_appointment",
                    "description": "Cancel appointment after patient says YES.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "appointment_index": {"type": "integer"},
                            "reason":            {"type": "string"}
                        },
                        "required": ["appointment_index"]
                    }
                },
                # ── COMPLAINTS ────────────────────────────────────────────────
                {
                    "type": "function", "name": "file_complaint",
                    "description": (
                        "Save a complaint.\n"
                        "TYPE 1 (general): NO verification needed. "
                        "Required: complaint_text, complaint_category=general, "
                        "first_name, last_name, contact_number.\n"
                        "TYPE 2 (treatment): patient MUST be verified. "
                        "Required: complaint_text, complaint_category=treatment, "
                        "treatment_name, dentist_name, treatment_date. "
                        "patient_id comes from verified session.\n"
                        "NEVER ask for DOB for a general complaint."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "complaint_text":     {"type": "string"},
                            "complaint_category": {"type": "string", "enum": ["general", "treatment"]},
                            "first_name":         {"type": "string"},
                            "last_name":          {"type": "string"},
                            "contact_number":     {"type": "string"},
                            "treatment_name":     {"type": "string"},
                            "dentist_name":       {"type": "string"},
                            "treatment_date":     {"type": "string"},
                            "treatment_time":     {"type": "string"},
                            "additional_info":    {"type": "string"},
                            "appointment_id":     {"type": "integer"}
                        },
                        "required": ["complaint_text", "complaint_category"]
                    }
                },
                # ── GENERAL ENQUIRY ───────────────────────────────────────────
                {
                    "type": "function", "name": "get_business_information",
                    "description": "Get pricing, hours, payment options, offers, dentist info.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_insurance_information",
                    "description": "Get health insurance info.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_warranty_information",
                    "description": "Get dental warranty policy.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "answer_dental_question",
                    "description": (
                        "Answer questions about dental procedures, pre/post care, recovery. "
                        "Uses ONLY internal knowledge base. NOT for pricing. "
                        "NEVER suggest 'consultation'. "
                        "ONLY reference treatments from the clinic's 18-item SERVICES list."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_my_order_status",
                    "description": "Check status of patient's dental order.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "get_my_upcoming_appointments",
                    "description": "Get upcoming appointments for verified patient.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "get_my_treatment_history",
                    "description": "Get past treatment history for verified patient.",
                    "parameters": {"type": "object", "properties": {}}
                },
                # ── SUPPLIER ──────────────────────────────────────────────────
                {
                    "type": "function", "name": "check_known_supplier",
                    "description": (
                        "Check if calling company is an authorised supplier. "
                        "ALWAYS call first when a business caller mentions a company. "
                        "Returns FOUND or NOT_FOUND."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"}
                        },
                        "required": ["company_name"]
                    }
                },
                {
                    "type": "function", "name": "update_supplier_order",
                    "description": (
                        "Mark a patient order as ready after a VERIFIED supplier confirms. "
                        "Use patient_id when available, else patient_last_name. "
                        "Also call log_supplier_call() for the same call."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "patient_id":        {"type": "integer"},
                            "patient_last_name": {"type": "string"},
                            "product_name":      {"type": "string"}
                        },
                        "required": ["product_name"]
                    }
                },
                {
                    "type": "function", "name": "log_supplier_call",
                    "description": (
                        "Log a call from a supplier, agent, or business. "
                        "For TYPE 2 agent calls. Also call alongside update_supplier_order. "
                        "NEVER for patient calls."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "caller_name":    {"type": "string"},
                            "company_name":   {"type": "string"},
                            "contact_number": {"type": "string"},
                            "purpose":        {"type": "string"}
                        },
                        "required": ["purpose"]
                    }
                },
            ],
            "tool_choice": "auto"
        }
    }


# ---------------------------------------------------------------------------
# FUNCTION CALL HANDLER  (unchanged logic from v21)
# ---------------------------------------------------------------------------

async def handle_function_call(function_name, arguments, call_id, session, openai_ws, disarm_fn=None):
    print(f"[FUNCTION] {function_name}")
    print(f"[ARGS]     {json.dumps(arguments, indent=2)}")
    result = {}

    try:
        if function_name == "verify_existing_patient":
            r = verify_by_lastname_dob(
                last_name=arguments.get("last_name", ""),
                dob=normalize_dob(arguments.get("date_of_birth", ""))
            )
            if r["status"] == "VERIFIED":
                session["patient_data"] = r
                session["verified"]     = True
                result = {
                    "status":         "VERIFIED",
                    "first_name":     r["first_name"],
                    "last_name":      r["last_name"],
                    "date_of_birth":  r["date_of_birth"],
                    "contact_spoken": format_phone_for_speech(r.get("contact_number", ""))
                }
            elif r["status"] == "MULTIPLE_FOUND":
                result = {"status": "MULTIPLE_FOUND", "message": r["message"]}
            else:
                result = {"status": "NOT_FOUND", "message": r.get("message", "No account found.")}

        elif function_name == "verify_with_contact_number":
            phone = extract_phone_from_text(arguments.get("contact_number", ""))
            r = verify_by_lastname_dob_contact(
                last_name=arguments.get("last_name", ""),
                dob=normalize_dob(arguments.get("date_of_birth", "")),
                contact_number=phone
            )
            if r["status"] == "VERIFIED":
                session["patient_data"] = r
                session["verified"]     = True
                result = {"status": "VERIFIED",
                          "first_name": r["first_name"], "last_name": r["last_name"]}
            else:
                result = {"status": "NOT_FOUND", "message": r.get("message", "Could not verify.")}

        elif function_name == "create_new_patient":
            phone = extract_phone_from_text(arguments.get("contact_number", ""))
            r = create_new_patient(
                first_name=arguments.get("first_name", ""),
                last_name=arguments.get("last_name", ""),
                dob=normalize_dob(arguments.get("date_of_birth", "")),
                contact_number=phone,
                insurance_info=arguments.get("insurance_info")
            )
            if r["status"] == "CREATED":
                session["patient_data"] = r
                session["verified"]     = True
                result = {
                    "status":     "CREATED",
                    "first_name": r["first_name"],
                    "last_name":  r["last_name"],
                    "message":    "Account created. Patient verified and ready to book."
                }
            else:
                result = {"status": "ERROR", "message": r.get("message", "Could not create account.")}

        elif function_name == "check_slot_availability":
            result = check_dentist_availability(
                date_str=arguments.get("date", ""),
                time_str=arguments.get("time", ""),
                dentist_name=arguments.get("dentist_name", "")
            )

        elif function_name == "find_any_available_dentist":
            result = find_available_dentist(
                date_str=arguments.get("date", ""),
                time_str=arguments.get("time", "")
            )

        elif function_name == "book_appointment":
            if not session.get("verified") or not session.get("patient_data"):
                result = {"status": "ERROR", "message": "Patient must be verified first."}
            else:
                p = session["patient_data"]
                r = book_appointment(
                    patient_id=p["patient_id"],
                    first_name=p["first_name"],
                    last_name=p["last_name"],
                    date_of_birth=p["date_of_birth"],
                    contact_number=p["contact_number"],
                    preferred_treatment=arguments.get("preferred_treatment", ""),
                    preferred_date=arguments.get("preferred_date", ""),
                    preferred_time=arguments.get("preferred_time", ""),
                    preferred_dentist=arguments.get("preferred_dentist", "")
                )
                if r["status"] == "BOOKED":
                    result = {
                        "status":    "BOOKED",
                        "treatment": r["treatment"],
                        "date":      r["date"],
                        "time":      r["time"],
                        "dentist":   r["dentist"]
                    }
                else:
                    result = {"status": "ERROR", "message": r.get("message", "Booking failed.")}

        elif function_name == "get_my_appointments":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                r = get_patient_appointments(session["patient_data"]["patient_id"])
                if r["status"] == "SUCCESS":
                    appts = r["appointments"]
                    session["fetched_appointments"] = appts
                    result = {
                        "status": "SUCCESS",
                        "appointments": [
                            {"index": i, "treatment": a["treatment"], "date": a["date"],
                             "time": a["time"], "dentist": a["dentist"], "status": a["status"]}
                            for i, a in enumerate(appts, 1)
                        ],
                        "count": len(appts)
                    }
                else:
                    result = {"status": r["status"], "message": r.get("message", "")}

        elif function_name == "update_my_appointment":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                idx   = arguments.get("appointment_index", 1) - 1
                appts = session.get("fetched_appointments", [])
                if not appts:
                    r2 = get_patient_appointments(session["patient_data"]["patient_id"])
                    if r2["status"] == "SUCCESS":
                        appts = r2["appointments"]
                        session["fetched_appointments"] = appts
                if 0 <= idx < len(appts):
                    fields = {}
                    if arguments.get("new_treatment"): fields["preferred_treatment"] = arguments["new_treatment"]
                    if arguments.get("new_date"):      fields["preferred_date"]      = arguments["new_date"]
                    if arguments.get("new_time"):      fields["preferred_time"]      = arguments["new_time"]
                    if arguments.get("new_dentist"):   fields["preferred_dentist"]   = arguments["new_dentist"]
                    r = update_appointment(appts[idx]["_id"], fields)
                    if r["status"] == "UPDATED":
                        session["fetched_appointments"] = []
                        result = {"status": "UPDATED", "treatment": r["treatment"],
                                  "date": r["date"], "time": r["time"], "dentist": r["dentist"]}
                    else:
                        result = {"status": "ERROR", "message": r.get("message", "Update failed.")}
                else:
                    result = {"status": "ERROR", "message": "Invalid index. Call get_my_appointments first."}

        elif function_name == "cancel_my_appointment":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                idx   = arguments.get("appointment_index", 1) - 1
                appts = session.get("fetched_appointments", [])
                if not appts:
                    r2 = get_patient_appointments(session["patient_data"]["patient_id"])
                    if r2["status"] == "SUCCESS":
                        appts = r2["appointments"]
                        session["fetched_appointments"] = appts
                if 0 <= idx < len(appts):
                    r = cancel_appointment(appts[idx]["_id"], arguments.get("reason"))
                    if r["status"] == "CANCELLED":
                        session["fetched_appointments"] = []
                        result = {"status": "CANCELLED", "treatment": r["treatment"],
                                  "date": r["date"], "time": r["time"], "dentist": r["dentist"]}
                    else:
                        result = {"status": "ERROR", "message": r.get("message", "Cancel failed.")}
                else:
                    result = {"status": "ERROR", "message": "Invalid index. Call get_my_appointments first."}

        elif function_name == "file_complaint":
            category = arguments.get("complaint_category", "general").lower()
            if category == "treatment":
                if not session.get("verified") or not session.get("patient_data"):
                    result = {"status": "ERROR", "message": "Patient must be verified for a treatment complaint."}
                else:
                    p = session["patient_data"]
                    appt_id = arguments.get("appointment_id")
                    r = save_complaint(
                        complaint_category="treatment",
                        complaint_text=arguments.get("complaint_text", ""),
                        first_name=p["first_name"],
                        last_name=p["last_name"],
                        contact_number=p.get("contact_number"),
                        patient_id=p["patient_id"],
                        appointment_id=appt_id,
                        date_of_birth=p.get("date_of_birth"),
                        treatment_name=arguments.get("treatment_name"),
                        dentist_name=arguments.get("dentist_name"),
                        treatment_date=arguments.get("treatment_date"),
                        treatment_time=arguments.get("treatment_time"),
                        additional_info=arguments.get("additional_info"),
                    )
                    result = r if r["status"] != "SAVED" else {"status": "SAVED", "message": r["message"]}
            else:
                r = save_complaint(
                    complaint_category="general",
                    complaint_text=arguments.get("complaint_text", ""),
                    first_name=arguments.get("first_name"),
                    last_name=arguments.get("last_name"),
                    contact_number=arguments.get("contact_number"),
                )
                result = r if r["status"] != "SAVED" else {"status": "SAVED", "message": r["message"]}

        elif function_name == "get_business_information":
            r = handle_business_info(user_input=arguments.get("query", ""), session=session)
            result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

        elif function_name == "get_insurance_information":
            r = handle_insurance_query(user_input=arguments.get("query", ""), session=session)
            result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

        elif function_name == "get_warranty_information":
            r = handle_warranty_query(user_input=arguments.get("query", ""), session=session)
            result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

        elif function_name == "answer_dental_question":
            r = handle_kb_query(user_input=arguments.get("query", ""), session=session)
            result = {"status": r.get("source", "kb"), "response": r.get("response", "")}

        elif function_name == "get_my_order_status":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                r = get_patient_orders(session["patient_data"]["patient_id"])
                if r["status"] == "SUCCESS":
                    result = {
                        "status": "SUCCESS",
                        "orders": [{"product": o["product_name"], "status": o["order_status"],
                                    "notes": o.get("notes", "")} for o in r["orders"]],
                        "count": r["count"]
                    }
                else:
                    result = {"status": r["status"], "message": r.get("message", "No orders found.")}

        elif function_name == "get_my_upcoming_appointments":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                r = get_upcoming_appointments(session["patient_data"]["patient_id"])
                if r["status"] == "SUCCESS":
                    result = {
                        "status": "SUCCESS",
                        "appointments": [{"treatment": a["treatment"], "date": a["date"],
                                          "time": a["time"], "dentist": a["dentist"]}
                                         for a in r["appointments"]],
                        "count": r["count"]
                    }
                else:
                    result = {"status": r["status"], "message": r.get("message", "None found.")}

        elif function_name == "get_my_treatment_history":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                r = get_past_appointments(session["patient_data"]["patient_id"])
                if r["status"] == "SUCCESS":
                    result = {
                        "status": "SUCCESS",
                        "appointments": [{"treatment": a["treatment"], "date": a["date"],
                                          "dentist": a["dentist"]}
                                         for a in r["appointments"][:5]],
                        "count": r["count"]
                    }
                else:
                    result = {"status": r["status"], "message": r.get("message", "None found.")}

        elif function_name == "check_known_supplier":
            company_name = arguments.get("company_name", "")
            r = check_supplier(company_name)
            if r["status"] == "FOUND":
                session["supplier_context"]["company_name"]      = r["supplier"]["company_name"]
                session["supplier_context"]["is_known_supplier"] = True
                result = {
                    "status":       "FOUND",
                    "company_name": r["supplier"]["company_name"],
                    "specialty":    r["supplier"]["specialty"],
                    "message":      f"Verified supplier: {r['supplier']['company_name']}."
                }
            else:
                session["supplier_context"]["is_known_supplier"] = False
                result = {"status": "NOT_FOUND", "message": r["message"]}

        elif function_name == "update_supplier_order":
            patient_id   = arguments.get("patient_id")
            last_name    = arguments.get("patient_last_name")
            product_name = arguments.get("product_name", "")
            if patient_id:
                r = update_order_by_patient_id(
                    patient_id=int(patient_id), product_name=product_name,
                    new_status="ready",
                    notes=f"Supplier confirmed — {session['supplier_context'].get('company_name','')}"
                )
            elif last_name:
                r = update_order_status_by_patient_name(
                    patient_name=last_name, product_name=product_name,
                    new_status="ready",
                    notes=f"Supplier confirmed — {session['supplier_context'].get('company_name','')}"
                )
            else:
                r = {"status": "ERROR", "message": "Need patient_id or patient_last_name."}
            result = r

        elif function_name == "log_supplier_call":
            ctx = session.get("supplier_context", {})
            caller_name    = arguments.get("caller_name")    or ctx.get("caller_name")
            company_name   = arguments.get("company_name")   or ctx.get("company_name")
            contact_number = arguments.get("contact_number") or ctx.get("contact_number")
            if arguments.get("caller_name"):
                session["supplier_context"]["caller_name"]    = arguments["caller_name"]
            if arguments.get("company_name"):
                session["supplier_context"]["company_name"]   = arguments["company_name"]
            if arguments.get("contact_number"):
                session["supplier_context"]["contact_number"] = arguments["contact_number"]
            log_business_call(
                caller_name=caller_name, company_name=company_name,
                contact_number=contact_number, purpose=arguments.get("purpose"),
                full_notes=json.dumps(arguments)
            )
            result = {
                "status":  "LOGGED",
                "message": f"Call from {caller_name or 'caller'} ({company_name or 'unknown'}) logged."
            }

        else:
            result = {"error": f"Unknown function: {function_name}"}

    except Exception as e:
        print("========== FUNCTION ERROR ==========")
        traceback.print_exc()
        print("====================================")
        result = {"status": "ERROR", "message": str(e)}

    if disarm_fn:
        disarm_fn()

    await safe_openai_send(openai_ws, {
        "type": "conversation.item.create",
        "item": {"type": "function_call_output", "call_id": call_id,
                 "output": json.dumps(result)}
    })
    await safe_openai_send(openai_ws, {"type": "response.create"})
    print(f"[RESULT] {json.dumps(result, indent=2)}")


# ---------------------------------------------------------------------------
# TWILIO WEBHOOK
# ---------------------------------------------------------------------------

@app.api_route("/voice", methods=["GET", "POST"])
async def voice(request: Request):
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{CLOUD_RUN_WSS_BASE}/media-stream"/>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------------
# MAIN WEBSOCKET
# ---------------------------------------------------------------------------

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    import time
    print("=" * 70)
    print("[CALL START] New WebSocket connection")
    print("=" * 70)
    await websocket.accept()

    call_sid    = None
    stream_sid  = None
    session     = None
    openai_ws   = None
    call_active = {"running": True}

    try:
        openai_ws = await websockets.connect(
            OPENAI_REALTIME_URL,
            additional_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta":   "realtime=v1"
            }
        )
        print("[OpenAI] WebSocket connected")
    except Exception as e:
        print(f"[OpenAI] Connection FAILED: {e}")
        await websocket.close()
        return

    async def receive_from_openai():
        nonlocal session
        pending_fn      = None
        pending_call_id = None
        pending_args    = ""

        wd = {"task": None, "armed": False}

        async def watchdog():
            await asyncio.sleep(1.5)
            if not wd["armed"]:
                return
            if session and session.get("is_speaking"):
                return
            print("[WATCHDOG] Bot silent — nudge")
            try:
                await safe_openai_send(openai_ws, {"type": "response.create"})
            except Exception as e:
                print(f"[WATCHDOG ERROR] {e}")
            wd["armed"] = False

        def arm_watchdog():
            if wd["task"] and not wd["task"].done():
                wd["task"].cancel()
            wd["armed"] = True
            wd["task"]  = asyncio.create_task(watchdog())

        def disarm_watchdog():
            if wd["task"] and not wd["task"].done():
                wd["task"].cancel()
            wd["armed"] = False
            wd["task"]  = None

        try:
            await safe_openai_send(openai_ws, get_session_config())
            print("[OpenAI] Session config sent", flush=True)

            async for message in openai_ws:
                data       = json.loads(message)
                event_type = data.get("type", "")
                print(f"[OpenAI EVENT] {event_type}", flush=True)

                try:
                    # ── Session ready → send greeting trigger ─────────────────
                    if event_type == "session.updated":
                        if session and not session.get("greeting_sent"):
                            session["greeting_sent"] = True
                            await safe_openai_send(openai_ws, {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": "[CALL_STARTED]"}]
                                }
                            })
                            await safe_openai_send(openai_ws, {"type": "response.create"})

                    elif event_type == "response.output_item.added":
                        if session:
                            session["last_assistant_item_id"] = data.get("item", {}).get("id")
                            session["audio_start_time"]       = None
                            session["elapsed_ms"]             = 0
                            session["audio_queue"].clear()

                    elif event_type == "response.audio.delta":
                        disarm_watchdog()
                        if stream_sid and "delta" in data:
                            if session:
                                session["is_speaking"] = True
                                session["audio_queue"].append(data["delta"])
                                if session["audio_start_time"] is None:
                                    session["audio_start_time"] = time.time()
                            await websocket.send_json({
                                "event":     "media",
                                "streamSid": stream_sid,
                                "media":     {"payload": data["delta"]}
                            })

                    elif event_type == "response.audio.done":
                        if session:
                            session["is_speaking"]      = False
                            session["audio_queue"]      = []
                            session["audio_start_time"] = None
                            session["elapsed_ms"]       = 0
                        print("[BOT] Done speaking")
                        try:
                            await safe_openai_send(openai_ws, {"type": "input_audio_buffer.clear"})
                        except Exception:
                            pass

                    elif event_type == "response.created":
                        if session:
                            session["current_response_id"] = data.get("response", {}).get("id")

                    elif event_type == "response.done":
                        if session:
                            session["current_response_id"] = None  # ✅ FIX C: clear after done

                    # ✅ FIX C — BARGE-IN: trigger on ANY active response, not just is_speaking
                    elif event_type == "input_audio_buffer.speech_started":
                        if session:
                            # Interrupt if bot is currently speaking OR has an active response
                            should_interrupt = (
                                session.get("is_speaking")
                                or session.get("current_response_id") is not None
                                or session.get("last_assistant_item_id") is not None
                            )
                            if should_interrupt:
                                print("[BARGE-IN] User interrupted — stopping bot immediately")
                                # Calculate elapsed audio sent so far
                                if session["audio_start_time"] is not None:
                                    session["elapsed_ms"] = int(
                                        (time.time() - session["audio_start_time"]) * 1000
                                    )
                                else:
                                    session["elapsed_ms"] = 0
                                # Cancel the current response
                                try:
                                    await safe_openai_send(openai_ws, {"type": "response.cancel"})
                                except Exception:
                                    pass
                                # Truncate audio already streamed to Twilio
                                if session["last_assistant_item_id"]:
                                    try:
                                        await safe_openai_send(openai_ws, {
                                            "type":          "conversation.item.truncate",
                                            "item_id":       session["last_assistant_item_id"],
                                            "content_index": 0,
                                            "audio_end_ms":  session["elapsed_ms"]
                                        })
                                    except Exception:
                                        pass
                                # Reset state
                                session["audio_queue"].clear()
                                session["last_assistant_item_id"] = None
                                session["current_response_id"]    = None
                                session["audio_start_time"]       = None
                                session["elapsed_ms"]             = 0
                                session["is_speaking"]            = False
                            else:
                                print("[USER] Speaking — bot already silent, no interrupt needed")

                    elif event_type == "input_audio_buffer.speech_stopped":
                        if session:
                            session["interruption_pending"] = False

                    elif event_type == "input_audio_buffer.cleared":
                        pass

                    elif event_type == "response.function_call_arguments.start":
                        pending_fn      = data.get("name")
                        pending_call_id = data.get("call_id")
                        pending_args    = ""

                    elif event_type == "response.function_call_arguments.delta":
                        pending_args += data.get("delta", "")

                    elif event_type == "response.function_call_arguments.done":
                        fn  = data.get("name")      or pending_fn
                        cid = data.get("call_id")   or pending_call_id
                        raw = data.get("arguments") or pending_args
                        try:
                            args = json.loads(raw or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        if fn:
                            await handle_function_call(fn, args, cid, session, openai_ws, disarm_watchdog)
                        pending_fn = pending_call_id = None
                        pending_args = ""

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = data.get("transcript", "")
                        if transcript and session:
                            print(f"[USER] {transcript}")
                            update_history(session, "user", transcript)

                    elif event_type == "response.audio_transcript.done":
                        transcript = data.get("transcript", "")
                        if transcript and session:
                            print(f"[BOT]  {transcript}")
                            update_history(session, "assistant", transcript)

                    elif event_type == "error":
                        err = data.get("error", {})
                        print(f"[OpenAI ERROR] {err.get('type')}: {err.get('message')}", flush=True)

                except Exception as inner_e:
                    print(f"[LOOP ERROR] Failed handling '{event_type}': {inner_e}")
                    traceback.print_exc()
                    continue

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[OpenAI] Connection closed — Code: {e.code} Reason: {e.reason}", flush=True)
        except Exception as e:
            print(f"[OpenAI RECEIVE ERROR] {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
        finally:
            disarm_watchdog()

    async def receive_from_twilio():
        nonlocal call_sid, stream_sid, session
        try:
            async for message in websocket.iter_text():
                data       = json.loads(message)
                event_type = data.get("event", "")

                if event_type == "start":
                    stream_sid = data["start"]["streamSid"]
                    call_sid   = data["start"].get("callSid", stream_sid)
                    session    = make_new_session(call_sid)
                    session["stream_sid"] = stream_sid
                    print(f"[Twilio] Connected | Stream: {stream_sid}")

                elif event_type == "media":
                    if openai_ws and data.get("media", {}).get("payload"):
                        await safe_openai_send(openai_ws, {
                            "type":  "input_audio_buffer.append",
                            "audio": data["media"]["payload"]
                        })

                elif event_type == "stop":
                    print("[Twilio] Call ended")
                    call_active["running"] = False
                    if openai_ws:
                        try:
                            await openai_ws.close()
                        except Exception:
                            pass
                    break

                else:
                    print(f"[Twilio] Unknown event ignored: {event_type}")

        except WebSocketDisconnect:
            print("[Twilio] Caller disconnected")
            call_active["running"] = False
            if openai_ws:
                try:
                    await openai_ws.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Twilio RECEIVE ERROR] {e}")
            traceback.print_exc()

    async def keep_alive():
        try:
            while call_active["running"]:
                await asyncio.sleep(25)
                if not call_active["running"]:
                    break
                if not openai_ws:
                    continue
                try:
                    await safe_openai_send(openai_ws, {
                        "type": "session.update",
                        "session": {
                            "turn_detection": {
                                "type":                "server_vad",
                                "threshold":           VAD_THRESHOLD,
                                "prefix_padding_ms":   PREFIX_PADDING_MS,
                                "silence_duration_ms": SILENCE_DURATION_MS
                            }
                        }
                    })
                    print("[KEEPALIVE] Ping sent")
                except websockets.exceptions.ConnectionClosed:
                    print("[KEEPALIVE] OpenAI WS closed — stopping")
                    break
                except Exception as e:
                    print("[KEEPALIVE ERROR]", e)
                    break
        except asyncio.CancelledError:
            print("[KEEPALIVE] cancelled")

    try:
        tasks = [
            asyncio.create_task(receive_from_twilio()),
            asyncio.create_task(receive_from_openai()),
            asyncio.create_task(keep_alive())
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
    except Exception as e:
        print(f"[HANDLER ERROR] {e}")
        traceback.print_exc()
    finally:
        call_active["running"] = False
        print("[CALL END] Cleaning up...")
        if openai_ws:
            try:
                await openai_ws.close()
            except Exception:
                pass
        print("[CALL END] Done\n")


# ---------------------------------------------------------------------------
# HEALTH CHECK + RUN
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
