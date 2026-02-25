"""
DentalBot v2 -- main.py
OpenAI Realtime API + Twilio WebSocket

Fixes applied:
  1. create_new_patient() MANDATORY before booking (was being skipped)
  2. input_audio_buffer.clear after every bot turn (stops VAD echo / duplicate speech)
  3. response.done is intentionally empty (no duplicate response.create)
  4. log_supplier_call() NEVER for patients (stronger prompt + tool description)
  5. Per-call isolated state — concurrent callers never crash each other
  6. Barge-in uses local state variables not globals
"""

import os
import json
import asyncio
import traceback
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, Response
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
    classify_business_call, extract_order_info          # ✅ removed _ prefix
)
from business.business_executor import (
    log_business_call, update_order_status_by_patient_name
)
from general_enquiry.enquiry_executor import (
    get_patient_orders, get_upcoming_appointments, get_past_appointments
)
from knowledge_base.kb_controller import handle_kb_query  # ✅ was knowledge_base (wrong)
from utils.phone_utils import extract_phone_from_text, format_phone_for_speech, normalize_dob


load_dotenv()
app = FastAPI()


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

OPENAI_REALTIME_URL          = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
VOICE                        = "marin"   # try: "coral", "marin", or "cedar"
TEMPERATURE                  = 0.8
VAD_THRESHOLD                = 0.5
PREFIX_PADDING_MS            = 300
SILENCE_DURATION_MS          = 600
CLOUD_RUN_WSS_BASE           = "wss://green-diods-dental-clinic-production.up.railway.app"


# ---------------------------------------------------------------------------
# SYSTEM INSTRUCTIONS
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = (
    "You are Sarah, a warm and professional AI receptionist for Green Diode's Dental Clinic.\n\n"

    "SERVICES (memorise -- never call a function to list these):\n"
    "1.Teeth Cleaning and Check-Up  2.Dental Implants  3.All-on-4 Dental Implants\n"
    "4.Dental Fillings  5.Wisdom Teeth Removal  6.Emergency Dental Services\n"
    "7.Clear Aligners  8.Dental Crowns and Bridges  9.Root Canal Treatment\n"
    "10.Custom Mouthguards  11.Dental Veneers  12.Tooth Extraction\n"
    "13.Gum Disease Treatment  14.Dentures  15.Braces  16.Teeth Whitening\n"
    "17.Zoom Whitening  18.Children's Dentistry\n\n"

    "SYMPTOM MAPPING (answer directly, no function call):\n"
    "tooth pain/sensitivity -> Cleaning+Check-Up, Filling, or Root Canal\n"
    "broken/cracked         -> Crowns+Bridges or Emergency Dental\n"
    "severe/sudden pain     -> Emergency Dental Services\n"
    "missing tooth          -> Implants, All-on-4, or Dentures\n"
    "yellow/stained         -> Teeth Whitening or Zoom Whitening\n"
    "crooked/bite           -> Clear Aligners or Braces\n"
    "bleeding gums          -> Gum Disease Treatment\n"
    "wisdom tooth pain      -> Wisdom Teeth Removal\n"
    "chipped front tooth    -> Dental Veneers\n"
    "sport/grinding         -> Custom Mouthguards\n"
    "child dental issue     -> Children's Dentistry\n\n"

    "FUNCTION ROUTING:\n"
    "pricing/hours/payment/offers    -> get_business_information()\n"
    "insurance                       -> get_insurance_information()\n"
    "warranty                        -> get_warranty_information()\n"
    "procedures/pre-post care        -> answer_dental_question()\n"
    "order status                    -> get_my_order_status()\n"
    "upcoming appointments           -> get_my_upcoming_appointments()\n"
    "past treatment history          -> get_my_treatment_history()\n"
    "NEVER call get_business_information() to list treatments\n\n"

    "3-TIER ROUTING:\n"
    "Tier1 pricing/hours -> get_business_information()\n"
    "Tier2 what is X?    -> get_business_information() -> 2-3 sentence summary\n"
    "Tier3 detailed procedure/recovery -> answer_dental_question()\n\n"

    "PERSONALITY: warm, concise, English only, use first name after verification\n"
    "GREETING on [CALL_STARTED]: Hello! Thank you for calling Green Diode's Dental Clinic. "
    "I'm Sarah, how may I assist you today?\n\n"

    """
    SPEAKING STYLE — FOLLOW THESE EXACTLY
    - Speak naturally like a real person, not a script reader
    - Use contractions always: "I'll" not "I will", "you're" not "you are", "we've" not "we have"
    - Use natural filler transitions: "Of course!", "Absolutely!", "Sure thing!", "Let me check that for you"
    - When confirming details, sound warm: "Perfect, got that!" not "Confirmed."
    - Vary your sentence length — don't speak in uniform rhythm
    - Pause naturally between thoughts — don't rush
    - Show empathy with tone: "Oh I'm sorry to hear that" / "That's great!"
    - Never read out structured lists — convert them to natural spoken sentences
    - Instead of "Your appointment is: Date: 5th March, Time: 10 AM" say "You're booked in for the 5th of March at 10 in the morning"
    """

    "CALLER TYPE IDENTIFICATION -- READ CAREFULLY:\n"
    "\n"
    "PATIENT (the vast majority of calls):\n"
    "  Identify as PATIENT if caller: wants an appointment, has tooth pain, asks\n"
    "  about treatment or price, wants to cancel/reschedule, has a complaint,\n"
    "  asks about their order, says I am a patient, or asks ANY dental question.\n"
    "  -> ALWAYS verify/register the patient first. NEVER call log_supplier_call().\n"
    "\n"
    "BUSINESS/SUPPLIER (rare -- explicit only):\n"
    "  ONLY call log_supplier_call() when caller EXPLICITLY says they are from\n"
    "  a company, lab, or business: I am from ABC Lab, sales rep, delivery courier.\n"
    "\n"
    "CRITICAL: general inquiry, I have a question, I want to book -> PATIENT.\n"
    "  Never call log_supplier_call() for these. Verify and assist.\n\n"

    "VERIFICATION:\n\n"
    "Starting of the call - Only ask 'Are you an existing patient or a new patient?' "
    "when the user's intent is to BOOK, UPDATE, or CANCEL an appointment.\n"
    "Do NOT ask this for general questions about address, hours, pricing, services, "
    "insurance, or any non-appointment enquiry. Answer those directly.\n\n"

    "STEP 0 -- MANDATORY FIRST QUESTION (with one exception):\n"
    " Before collecting ANY details, ALWAYS ask:\n"
    " 'Are you an existing patient with us, or is this your first visit?'\n"
    " -> If EXISTING patient -> follow EXISTING PATIENT FLOW\n"
    " -> If NEW patient -> follow NEW PATIENT FLOW\n"
    " -> If UNSURE -> ask: Have you visited us before?\n"
    " EXCEPTION -- UPDATE or CANCEL: If the caller says they want to UPDATE\n"
    " or CANCEL an appointment, SKIP this question entirely.\n"
    " Only existing patients have appointments. Go directly to\n"
    " EXISTING PATIENT FLOW: ask last name -> ask DOB -> verify.\n"
    " NEVER jump to asking last name before this question is answered\n"
    " (except for the update/cancel exception above).\n\n"

    "EXISTING PATIENT FLOW:\n"
    "  Step 1: Ask last name\n"
    "  Step 2: Ask date of birth\n"
    "  Step 3: Call verify_existing_patient() -- do not skip or delay\n"
    "    VERIFIED       -> read contact digit by digit to confirm, then assist\n"
    "    MULTIPLE_FOUND -> ask contact number, call verify_with_contact_number()\n"
    "    NOT_FOUND      -> offer to retry or create new account\n\n"

    "DOB READBACK: If the patient says a month as a number (e.g. 12 12 2006), "
    "convert it to the month name and read it back for confirmation: "
    "'Just to confirm, that's the 12th of December 2006, is that correct?'\n"
    "Always confirm DOB in DD Month YYYY format before calling any verify function.\n\n"

    "NEW PATIENT FLOW (mandatory -- follow every step, no skipping):\n"
    "  Step 1: Collect first name\n"
    "  Step 2: Collect last name\n"
    "  Step 3: Collect date of birth\n"
    "  Step 4: Collect contact number -> read back digit by digit -> patient confirms\n"
    "  Step 5: Ask for health insurance (optional -- patient may say none or skip)\n"
    "  Step 6: CALL create_new_patient() RIGHT NOW WITH ALL COLLECTED DETAILS\n"
    "          !!! YOU MUST CALL THIS FUNCTION BEFORE DOING ANYTHING ELSE !!!\n"
    "          !!! DO NOT say account is set up before calling the function !!!\n"
    "          !!! DO NOT ask about treatment or booking before calling it  !!!\n"
    "          The patient does not exist in the system until you call this. !!!\n"
    "  Step 7: Wait for create_new_patient() to return status=CREATED\n"
    "  Step 8: Only AFTER status=CREATED: say account is ready, then assist\n\n"

    "After verification or creation: patient is verified for the entire call.\n"
    "Use their first name from that point onwards.\n\n"

    "GOLDEN RULES (never break):\n"
    "1. NEVER ask appointment ID -> use get_my_appointments()\n"
    "2. NEVER mention any internal ID in responses\n"
    "3. NEVER ask name or contact after verification\n"
    "4. NEVER give medication advice or diagnose\n"
    "5. After booking -> say date, time, dentist only\n"
    "6. NEVER say schedule a consultation\n"
    "7. Phone readback ALWAYS digit by digit: 0,4,6,2... is that correct?\n\n"

    "CLINIC DETAILS — Always answer these from memory, no function call needed:\n"
    "- Address: 123, Building, Melbourne Central, Melbourne, Victoria\n"
    "- Phone: 03 6160 3456\n"
    "- Hours: Monday to Friday 9:00 AM – 6:00 PM, Saturday and Sunday CLOSED\n\n"

    "DENTISTS:\n"
    "Dr. Emily Carter (General Dentistry)\n"
    "Dr. James Nguyen (Cosmetic and Restorative)\n"
    "Dr. Sarah Mitchell (Orthodontics and Periodontics)\n\n"

    "BOOKING (only after patient is verified or created):\n"
    "Collect: treatment, date/time, dentist preference\n"
    "Specific dentist -> check_slot_availability()\n"
    "No preference   -> find_any_available_dentist()\n"
    "Confirm ALL details -> patient says YES -> call book_appointment()\n\n"

    "UPDATE/CANCEL:\n"
    "IMPORTANT: Only existing patients have appointments.\n"
    "NEVER ask if they are new or existing -- skip Step 0.\n"
    "Go directly to EXISTING PATIENT FLOW (ask last name + DOB).\n"
    "1. After verification: call get_my_appointments() -> read as numbered list\n"
    "2. Use appointment_index (1,2,3...) for update or cancel\n"
    "CANCEL: confirm -> cancel_my_appointment() after YES\n\n"

    "COMPLAINTS (post-verification):\n"
    "Empathy first -> describe -> general or treatment -> confirm -> file_complaint()\n"
    "NEVER mention complaint ID\n\n"

    "MID-FLOW: unrelated question -> answer -> ask shall we continue -> YES resume\n\n"
    "ENDING: Thank you for calling Green Diode's Dental Clinic. Have a wonderful day!\n\n"

    "TURN-TAKING RULES:\n"
    "After asking ANY question, you MUST stop speaking completely and wait silently "
    "for the user to respond.\n"
    "Never ask a follow-up question until the user has answered the current one.\n"
    "Never assume or acknowledge information the user has not yet provided."
)


# ---------------------------------------------------------------------------
# SESSION HELPERS
# ---------------------------------------------------------------------------

def make_new_session(call_sid: str) -> dict:
    """Creates a brand new isolated session for one call."""
    return {
        "call_sid":             call_sid,
        "stream_sid":           None,
        "created_at":           datetime.now(),
        "verified":             False,
        "patient_data":         None,
        "current_flow":         None,
        "fetched_appointments": [],
        "is_speaking":          False,
        "interruption_pending": False,
        "current_response_id":  None,
        "greeting_sent":        False,
        "conversation_history": [],
        # ── Barge-in state — per call, never shared ──
        "last_assistant_item_id": None,
        "audio_start_time":       None,
        "elapsed_ms":             0,
        "audio_queue":            [],
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
                {
                    "type": "function", "name": "verify_existing_patient",
                    "description": "Verify existing patient by last name and date of birth.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "last_name":     {"type": "string"},
                            "date_of_birth": {"type": "string", "description": "e.g. 15 March 1990"}
                        },
                        "required": ["last_name", "date_of_birth"]
                    }
                },
                {
                    "type": "function", "name": "verify_with_contact_number",
                    "description": "Disambiguate multiple patients with same last name and DOB.",
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
                        "Register a new patient account. MUST be called immediately after "
                        "collecting all details (first name, last name, DOB, contact, insurance). "
                        "Do NOT say account is set up or proceed to booking before calling this. "
                        "The patient is not verified until this returns status=CREATED."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "first_name":     {"type": "string"},
                            "last_name":      {"type": "string"},
                            "date_of_birth":  {"type": "string"},
                            "contact_number": {"type": "string"},
                            "insurance_info": {"type": "string", "description": "Provider name or null"}
                        },
                        "required": ["first_name", "last_name", "date_of_birth", "contact_number"]
                    }
                },
                {
                    "type": "function", "name": "check_slot_availability",
                    "description": "Check if a specific dentist is available at a given date/time.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date":         {"type": "string"},
                            "time":         {"type": "string"},
                            "dentist_name": {"type": "string",
                                             "description": "Dr. Emily Carter | Dr. James Nguyen | Dr. Sarah Mitchell"}
                        },
                        "required": ["date", "time", "dentist_name"]
                    }
                },
                {
                    "type": "function", "name": "find_any_available_dentist",
                    "description": "Find first available dentist when patient has no preference.",
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
                        "Book appointment ONLY after patient says YES to confirmation. "
                        "Patient must be verified (create_new_patient or verify_existing_patient called first). "
                        "Patient details come from the verified session."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "preferred_treatment": {"type": "string"},
                            "preferred_date":      {"type": "string"},
                            "preferred_time":      {"type": "string"},
                            "preferred_dentist":   {"type": "string"}
                        },
                        "required": ["preferred_treatment", "preferred_date", "preferred_time", "preferred_dentist"]
                    }
                },
                {
                    "type": "function", "name": "get_my_appointments",
                    "description": "Get all active appointments. ALWAYS call before update or cancel.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "update_my_appointment",
                    "description": "Update appointment. Use appointment_index from get_my_appointments.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "appointment_index": {"type": "integer", "description": "1-based index"},
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
                    "description": "Cancel appointment after patient confirms.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "appointment_index": {"type": "integer"},
                            "reason":            {"type": "string"}
                        },
                        "required": ["appointment_index"]
                    }
                },
                {
                    "type": "function", "name": "file_complaint",
                    "description": "Save patient complaint after confirmation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "complaint_text":     {"type": "string"},
                            "complaint_category": {"type": "string", "enum": ["general", "treatment"]},
                            "treatment_name":     {"type": "string"},
                            "dentist_name":       {"type": "string"},
                            "treatment_date":     {"type": "string"}
                        },
                        "required": ["complaint_text", "complaint_category"]
                    }
                },
                {
                    "type": "function", "name": "get_business_information",
                    "description": "Get clinic hours, pricing, payment options, offers, dentist info.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_insurance_information",
                    "description": "Get health insurance info. Insurance questions only.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_warranty_information",
                    "description": "Get dental warranty policy. Warranty questions only.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "answer_dental_question",
                    "description": "Answer questions about procedures, pre/post care, recovery. NOT for pricing.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                },
                {
                    "type": "function", "name": "get_my_order_status",
                    "description": "Check status of patient dental order.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "get_my_upcoming_appointments",
                    "description": "Get upcoming appointments for the verified patient.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "get_my_treatment_history",
                    "description": "Get past treatment history for the verified patient.",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "type": "function", "name": "log_supplier_call",
                    "description": (
                        "Log a call from a supplier, dental lab, sales agent, or company. "
                        "ONLY when caller EXPLICITLY says they are from a business or company. "
                        "NEVER for a patient asking about appointments, treatments, or prices. "
                        "When in doubt, treat as patient."
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
                }
            ],
            "tool_choice": "auto"
        }
    }


# ---------------------------------------------------------------------------
# FUNCTION CALL HANDLER
# response.create sent EXACTLY ONCE here. Never in response.done.
# ---------------------------------------------------------------------------

async def handle_function_call(function_name, arguments, call_id, session, openai_ws):
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
                result = {"status": "VERIFIED", "first_name": r["first_name"], "last_name": r["last_name"]}
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
                    "message":    "Account created. Patient is now verified and ready to book."
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
                            {
                                "index":     i,
                                "treatment": a["treatment"],
                                "date":      a["date"],
                                "time":      a["time"],
                                "dentist":   a["dentist"],
                                "status":    a["status"]
                            }
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
                        result = {
                            "status":    "UPDATED",
                            "treatment": r["treatment"],
                            "date":      r["date"],
                            "time":      r["time"],
                            "dentist":   r["dentist"]
                        }
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
                        result = {
                            "status":    "CANCELLED",
                            "treatment": r["treatment"],
                            "date":      r["date"],
                            "time":      r["time"],
                            "dentist":   r["dentist"]
                        }
                    else:
                        result = {"status": "ERROR", "message": r.get("message", "Cancel failed.")}
                else:
                    result = {"status": "ERROR", "message": "Invalid index. Call get_my_appointments first."}

        elif function_name == "file_complaint":
            if not session.get("verified"):
                result = {"status": "ERROR", "message": "Patient not verified."}
            else:
                p          = session["patient_data"]
                first_name = p["first_name"]
                last_name  = p["last_name"]
                r = save_complaint(
                    patient_name=f"{first_name} {last_name}",
                    contact_number=p["contact_number"],
                    complaint_text=arguments.get("complaint_text", ""),
                    complaint_category=arguments.get("complaint_category", "general"),
                    treatment_name=arguments.get("treatment_name"),
                    dentist_name=arguments.get("dentist_name"),
                    treatment_date=arguments.get("treatment_date")
                )
                if r["status"] == "SAVED":
                    result = {
                        "status":  "SAVED",
                        "message": f"Complaint recorded. Team contacts {first_name} in 2 business days."
                    }
                else:
                    result = {"status": "ERROR", "message": r.get("message", "Could not save.")}

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
                                    "description": o["status_text"]} for o in r["orders"]],
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
                                          "dentist": a["dentist"]} for a in r["appointments"][:5]],
                        "count": r["count"]
                    }
                else:
                    result = {"status": r["status"], "message": r.get("message", "None found.")}

        elif function_name == "log_supplier_call":
            sub_type = classify_business_call(arguments.get("purpose", ""))   # ✅ was _classify_business_call
            log_business_call(
                caller_name=arguments.get("caller_name"),
                company_name=arguments.get("company_name"),
                contact_number=arguments.get("contact_number"),
                purpose=arguments.get("purpose"),
                full_notes=json.dumps(arguments)
            )
            if sub_type == "order_ready":
                oi = extract_order_info(arguments.get("purpose", ""))          # ✅ was _extract_order_info
                if oi.get("patient_name") and oi.get("product_name"):
                    update_order_status_by_patient_name(
                        patient_name=oi["patient_name"],
                        product_name=oi["product_name"],
                        new_status="ready",
                        notes=arguments.get("purpose")
                    )
            caller_name  = arguments.get("caller_name", "")
            company_name = arguments.get("company_name", "your company")
            result = {
                "status":  "LOGGED",
                "message": f"Call from {caller_name} ({company_name}) logged. Management will follow up."
            }


        else:
            result = {"error": f"Unknown function: {function_name}"}

    except Exception as e:
        print("========== FUNCTION / DB ERROR ==========")
        traceback.print_exc()
        print("=========================================")
        result = {"status": "ERROR", "message": str(e)}

    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)}
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))
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
# Each call gets completely isolated state via make_new_session()
# No module-level globals for barge-in or audio — concurrent calls are safe
# ---------------------------------------------------------------------------

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    import time
    print("=" * 70)
    print("[CALL START] New WebSocket connection")
    print("=" * 70)
    await websocket.accept()

    call_sid   = None
    stream_sid = None
    session    = None   # will be set to make_new_session() on Twilio "start" event
    openai_ws  = None

    try:
        openai_ws = await websockets.connect(
            OPENAI_REALTIME_URL,
            additional_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
        )
        print("[OpenAI] WebSocket connected successfully")
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
            await asyncio.sleep(0.8)
            if not wd["armed"]:
                return
            print("[WATCHDOG] Bot silent -- nudge")
            try:
                await openai_ws.send(json.dumps({"type": "response.create"}))
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
            await openai_ws.send(json.dumps(get_session_config()))
            print("[OpenAI] Session config sent", flush=True)

            async for message in openai_ws:
                data       = json.loads(message)
                event_type = data.get("type", "")
                print(f"[OpenAI EVENT] {event_type}", flush=True)

                try:

                    if event_type == "session.updated":
                        if session and not session.get("greeting_sent"):
                            session["greeting_sent"] = True
                            await openai_ws.send(json.dumps({
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "[CALL_STARTED]"}]
                                }
                            }))
                            await openai_ws.send(json.dumps({"type": "response.create"}))

                    # ── Bot response starting — track item ID in session ──
                    elif event_type == "response.output_item.added":
                        if session:
                            session["last_assistant_item_id"] = data.get("item", {}).get("id")
                            session["audio_start_time"]       = None
                            session["elapsed_ms"]             = 0
                            session["audio_queue"].clear()

                    # ── Bot audio chunk ──
                    elif event_type == "response.audio.delta":
                        disarm_watchdog()
                        if stream_sid and "delta" in data:
                            if session:
                                session["is_speaking"] = True
                                session["audio_queue"].append(data["delta"])
                                # Start audio timer on first chunk
                                if session["audio_start_time"] is None:
                                    session["audio_start_time"] = time.time()
                            print("[BOT] Speaking...")
                            await websocket.send_json({
                                "event":     "media",
                                "streamSid": stream_sid,
                                "media":     {"payload": data["delta"]}
                            })

                    # ── Bot finished speaking ──
                    elif event_type == "response.audio.done":
                        if session:
                            session["is_speaking"]    = False
                            session["audio_queue"]    = []
                            session["audio_start_time"] = None
                            session["elapsed_ms"]     = 0
                        print("[BOT] Done speaking")
                        try:
                            await openai_ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                        except Exception:
                            pass

                    elif event_type == "response.created":
                        if session:
                            session["current_response_id"] = data.get("response", {}).get("id")

                    # ── ✅ response.done — DO NOTHING, keep call alive ──
                    elif event_type == "response.done":
                        pass

                    # ── ✅ BARGE-IN — uses per-call session state, not globals ──
                    elif event_type == "input_audio_buffer.speech_started":
                        print("[BARGE-IN] User interrupted — stopping bot")
                        if session:
                            # Calculate elapsed ms from session's own timer
                            if session["audio_start_time"] is not None:
                                session["elapsed_ms"] = int(
                                    (time.time() - session["audio_start_time"]) * 1000
                                )
                            else:
                                session["elapsed_ms"] = 0

                            # Step 1: Cancel active response
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))

                            # Step 2: Truncate at exact interruption point
                            if session["last_assistant_item_id"]:
                                await openai_ws.send(json.dumps({
                                    "type":          "conversation.item.truncate",
                                    "item_id":       session["last_assistant_item_id"],
                                    "content_index": 0,
                                    "audio_end_ms":  session["elapsed_ms"]
                                }))

                            # Step 3: Clear buffer and reset state
                            session["audio_queue"].clear()
                            session["last_assistant_item_id"] = None
                            session["audio_start_time"]       = None
                            session["elapsed_ms"]             = 0
                            session["is_speaking"]            = False

                    elif event_type == "input_audio_buffer.speech_stopped":
                        if session:
                            session["interruption_pending"] = False

                    # ── ✅ input_audio_buffer.cleared — DO NOTHING, not a close signal ──
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
                            await handle_function_call(fn, args, cid, session, openai_ws)
                            arm_watchdog()
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
                    # Log bad event but keep loop running — call stays alive
                    print(f"[LOOP ERROR] Failed handling '{event_type}': {inner_e}")
                    traceback.print_exc()
                    continue

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[OpenAI] Connection closed — Code: {e.code} Reason: {e.reason}", flush=True)
        except Exception as e:
            print(f"[OpenAI RECEIVE ERROR] {type(e).__name__}: {e}", flush=True)
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
                    # ✅ Each call gets its own isolated session
                    session = make_new_session(call_sid)
                    session["stream_sid"] = stream_sid
                    print(f"[Twilio] Connected | Stream: {stream_sid}")
                elif event_type == "media":
                    if openai_ws and data.get("media", {}).get("payload"):
                        await openai_ws.send(json.dumps({
                            "type":  "input_audio_buffer.append",
                            "audio": data["media"]["payload"]
                        }))
                elif event_type == "stop":
                    print("[Twilio] Call ended by Twilio")
                    if openai_ws:
                        await openai_ws.close()
                    break
        except WebSocketDisconnect:
            print("[Twilio] Caller disconnected")
        except Exception as e:
            print(f"[Twilio RECEIVE ERROR] {e}")

    try:
        await asyncio.gather(receive_from_twilio(), receive_from_openai())
    except Exception as e:
        print(f"[HANDLER ERROR] {e}")
        traceback.print_exc()
    finally:
        print("[CALL END] Cleaning up...")
        if session:
            print(f"[CALL END] Verified: {session['verified']} | Last bot: {session['conversation_history'][-1]['content'] if session['conversation_history'] else 'none'}")
        if openai_ws:
            try:
                await openai_ws.close()
            except Exception:
                pass
        print("[CALL END] Done\n")


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print("  DentalBot v2")
    print(f"  Voice    : {VOICE}")
    print(f"  Audio    : g711_ulaw passthrough")
    print(f"  VAD      : threshold={VAD_THRESHOLD}  silence={SILENCE_DURATION_MS}ms")
    print(f"  Fixes    : per-call isolation | barge-in | no false disconnects")
    print("=" * 70)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
    )
