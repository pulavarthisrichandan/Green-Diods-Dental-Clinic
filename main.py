# """
# DentalBot v2 -- main.py
# OpenAI Realtime API + Twilio WebSocket

# Fixes applied (cumulative):
#   1–15: (unchanged from prior versions — see history)
#   16. COMPLAINTS: two-path flow (general / treatment)
#   17. file_complaint handler: general = no verification
#   18. BOOKING: strict dentist/treatment extraction + single confirm-before-book
#   19. DOB: any user format → DD-MON-YYYY re-confirm before verify call
#   20. COMPLAINTS TYPE 1: collect first_name, last_name, contact_number (no DOB/verify)
#       COMPLAINTS TYPE 2: full save — patient_id, appointment_id, DOB, contact,
#                          treatment_name, dentist_name, date, time, extra_info
#   21. BUSINESS TYPE 2: extract caller_name+company_name from conversation, do NOT re-ask
#       BUSINESS TYPE 3: check known supplier list → update order by patient_id
#   22. NEVER ask repeated questions in any flow
# """

# import os
# import json
# import asyncio
# import traceback
# import websockets
# from fastapi import FastAPI, WebSocket, Request
# from fastapi.responses import Response
# from fastapi.websockets import WebSocketDisconnect
# from dotenv import load_dotenv
# from datetime import datetime

# from verification.verification_executor import (
#     verify_by_lastname_dob, verify_by_lastname_dob_contact, create_new_patient
# )
# from appointment.executor import (
#     check_dentist_availability, find_available_dentist, book_appointment,
#     get_patient_appointments, update_appointment, cancel_appointment
# )
# from complaint.complaint_executor import save_complaint
# from business.business_controller import (
#     handle_business_info, handle_insurance_query, handle_warranty_query,
#     classify_business_call, extract_order_info
# )
# from business.business_executor import (
#     log_business_call, update_order_by_patient_id,
#     update_order_status_by_patient_name, check_supplier, get_all_suppliers
# )
# from general_enquiry.enquiry_executor import (
#     get_patient_orders, get_upcoming_appointments, get_past_appointments
# )
# from knowledge_base.kb_controller import handle_kb_query
# from utils.phone_utils import extract_phone_from_text, format_phone_for_speech, normalize_dob

# from datetime import timedelta
# import re

# def normalize_relative_date(date_str: str) -> str:
#     """
#     Convert phrases like 'coming friday', 'this monday'
#     into DD-MON-YYYY format.
#     """
#     if not date_str:
#         return date_str

#     date_str = date_str.lower().strip()
#     today = datetime.now()

#     weekdays = {
#         "monday": 0, "tuesday": 1, "wednesday": 2,
#         "thursday": 3, "friday": 4,
#         "saturday": 5, "sunday": 6
#     }

#     for day_name, day_index in weekdays.items():
#         if day_name in date_str:
#             today_index = today.weekday()
#             delta = (day_index - today_index) % 7
#             if delta == 0:
#                 delta = 7
#             target_date = today + timedelta(days=delta)
#             return target_date.strftime("%d-%b-%Y").upper()

#     return date_str

# load_dotenv()
# app = FastAPI()

# # ---------------------------------------------------------------------------
# # CONFIG
# # ---------------------------------------------------------------------------

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# if not OPENAI_API_KEY:
#     raise RuntimeError("OPENAI_API_KEY is not set")

# OPENAI_REALTIME_URL      = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
# VOICE                    = "shimmer"
# TEMPERATURE              = 0.8
# VAD_THRESHOLD            = 0.75 
# PREFIX_PADDING_MS        = 300
# SILENCE_DURATION_MS      = 900
# CLOUD_RUN_WSS_BASE       = "wss://green-diods-dental-clinic-production.up.railway.app"

# # ---------------------------------------------------------------------------
# # SYSTEM INSTRUCTIONS
# # ---------------------------------------------------------------------------

# SYSTEM_INSTRUCTIONS = (
#     "You are Sarah, a warm and professional AI receptionist for Green Diode's Dental Clinic.\n\n"

#     "SERVICES (memorise — never call a function to list these):\n"
#     "1.Teeth Cleaning and Check-Up  2.Dental Implants  3.All-on-4 Dental Implants\n"
#     "4.Dental Fillings  5.Wisdom Teeth Removal  6.Emergency Dental Services\n"
#     "7.Clear Aligners  8.Dental Crowns and Bridges  9.Root Canal Treatment\n"
#     "10.Custom Mouthguards  11.Dental Veneers  12.Tooth Extraction\n"
#     "13.Gum Disease Treatment  14.Dentures  15.Braces  16.Teeth Whitening\n"
#     "17.Zoom Whitening  18.Children's Dentistry\n\n"

#     "SYMPTOM MAPPING (answer directly, no function call):\n"
#     "tooth pain/sensitivity -> Cleaning+Check-Up, Filling, or Root Canal\n"
#     "broken/cracked         -> Crowns+Bridges or Emergency Dental\n"
#     "severe/sudden pain     -> Emergency Dental Services\n"
#     "missing tooth          -> Implants, All-on-4, or Dentures\n"
#     "yellow/stained         -> Teeth Whitening or Zoom Whitening\n"
#     "crooked/bite           -> Clear Aligners or Braces\n"
#     "bleeding gums          -> Gum Disease Treatment\n"
#     "wisdom tooth pain      -> Wisdom Teeth Removal\n"
#     "chipped front tooth    -> Dental Veneers\n"
#     "sport/grinding         -> Custom Mouthguards\n"
#     "child dental issue     -> Children's Dentistry\n\n"

#     "FUNCTION ROUTING:\n"
#     "pricing/hours/payment/offers    -> get_business_information()\n"
#     "insurance                       -> get_insurance_information()\n"
#     "warranty                        -> get_warranty_information()\n"
#     "procedures/pre-post care        -> answer_dental_question()\n"
#     "order status                    -> get_my_order_status()\n"
#     "upcoming appointments           -> get_my_upcoming_appointments()\n"
#     "past treatment history          -> get_my_treatment_history()\n"
#     "NEVER call get_business_information() to list treatments\n\n"

#     "3-TIER ROUTING:\n"
#     "Tier1 pricing/hours -> get_business_information()\n"
#     "Tier2 what is X?    -> get_business_information() -> 2-3 sentence summary\n"
#     "Tier3 detailed procedure/recovery -> answer_dental_question()\n\n"

#     "PERSONALITY: warm, concise, English only, use first name after verification\n"
#     "GREETING on [CALL_STARTED]: Hello! Thank you for calling Green Diode's Dental Clinic. "
#     "I'm Sarah, how may I assist you today?\n\n"

#     """
#     SPEAKING STYLE — FOLLOW THESE EXACTLY
#     - Speak naturally like a real person, not a script reader
#     - Use contractions always: "I'll" not "I will", "you're" not "you are"
#     - Use natural filler transitions: "Of course!", "Absolutely!", "Sure thing!"
#     - When confirming details, sound warm: "Perfect, got that!" not "Confirmed."
#     - Vary sentence length — don't speak in uniform rhythm
#     - Show empathy: "Oh I'm sorry to hear that" / "That's great!"
#     - Never read structured lists — convert to natural spoken sentences
#     - Instead of "Date: 5th March, Time: 10 AM" say "the 5th of March at 10 in the morning"
#     """

#     # ── CALLER TYPE ──────────────────────────────────────────────────────────
#     "CALLER TYPE IDENTIFICATION — READ CAREFULLY:\n"
#     "\n"
#     "PATIENT (vast majority):\n"
#     "  Wants appointment, has tooth pain, asks about treatment/price,\n"
#     "  wants to cancel/reschedule, has a complaint, asks about order.\n"
#     "  -> ALWAYS verify/register patient first. NEVER call log_supplier_call().\n"
#     "\n"
#     "BUSINESS / SUPPLIER (rare — explicit only):\n"
#     "  ONLY when caller EXPLICITLY says: 'I'm from [company]', sales rep,\n"
#     "  delivery courier, or mentions placing/delivering an order.\n"
#     "  -> Call check_known_supplier() first. Then route to Type 2 or Type 3.\n"
#     "\n"
#     "CRITICAL: general inquiry / 'I have a question' / 'I want to book' -> PATIENT.\n\n"

#     # ── VERIFICATION ─────────────────────────────────────────────────────────
#     "VERIFICATION:\n\n"
#     "Only ask 'Are you an existing or new patient?' when intent is BOOK, UPDATE, or CANCEL.\n"
#     "Do NOT ask for general questions about address, hours, pricing, insurance.\n\n"

#     "VERIFICATION RULE:\n"
#     "Only ask whether the caller is an existing or new patient\n"
#     "IF AND ONLY IF the user intent is:\n"
#     "- Book appointment\n"
#     "- Treatment-related complaint\n"
#     "- Order status\n\n"

#     "For general enquiries (hours, pricing, insurance, address, procedures),"
#     "DO NOT ask verification or patient type."

#     "STEP 0 — MANDATORY FIRST QUESTION (with one exception):"
#     "Always ask: 'Are you an existing patient with us, or is this your first visit?'"
#     "-> EXISTING -> EXISTING PATIENT FLOW"
#     "-> NEW      -> NEW PATIENT FLOW"
#     "-> UNSURE   -> 'Have you visited us before?'"
#     "EXCEPTION — UPDATE or CANCEL: skip Step 0 entirely."
#     "Only existing patients have appointments."
#     "Go directly to EXISTING PATIENT FLOW (last name -> DOB -> verify)."
    

#     "EXISTING PATIENT FLOW:\n"
#     "  Step 1: Ask last name\n"
#     "  Step 2: Ask date of birth\n"
#     "  Step 3: ALWAYS convert DOB to DD-MON-YYYY and read back:\n"
#     "          'Just to confirm, that's the [DD] of [Month] [YYYY] — is that right?'\n"
#     "          Examples of what user might say -> what you confirm:\n"
#     "            '12/06/1990'     -> '12th of June 1990'\n"
#     "            '6-12-90'        -> '6th of December 1990'\n"
#     "            '15 03 2001'     -> '15th of March 2001'\n"
#     "            'fifteenth March 2001' -> '15th of March 2001'\n"
#     "          WAIT for user to say YES before calling verify_existing_patient()\n"
#     "  Step 4: Call verify_existing_patient()\n"
#     "    VERIFIED       -> read contact digit by digit, then assist\n"
#     "    MULTIPLE_FOUND -> ask contact number, call verify_with_contact_number()\n"
#     "    NOT_FOUND      -> offer to retry or create new account\n\n"

#     "NEW PATIENT FLOW (no skipping):\n"
#     "  Step 1: first name  Step 2: last name  Step 3: DOB (confirm as DD-MON-YYYY)\n"
#     "  Step 4: contact (read back digit by digit)"
#     "  Step 5: Ask clearly: 'Do you have private health insurance? If yes, which provider?, or if you want you can skip this'\n"
#     "  Step 6: insurance is REQUIRED (if none, store as \"None\")\n"
#     "  Step 7: call create_new_patient() immediately\n"
#     "  Step 8: wait for status=CREATED, then say account is ready\n\n"

#     "After verification: patient is verified for the entire call.\n"
#     "Use their first name. NEVER ask name/contact again.\n\n"

#     # ── GOLDEN RULES ─────────────────────────────────────────────────────────
#     "GOLDEN RULES (never break):\n"
#     "1. NEVER ask appointment ID — use get_my_appointments()\n"
#     "2. NEVER mention any internal ID in responses\n"
#     "3. NEVER ask name or contact after verification\n"
#     "4. NEVER give medication advice or diagnose\n"
#     "5. After booking — say date, time, dentist only\n"
#     "6. NEVER say 'schedule a consultation'\n"
#     "7. Phone readback ALWAYS digit by digit\n"
#     "8. NEVER ask repeated questions — if info already given, use it\n\n"

#     # ── TREATMENT INFORMATION RULES ──────────────────────────────────────────
#     "TREATMENT INFORMATION RULE:\n"
#     "Only describe treatments exactly as listed in SERVICES.\n"
#     "Never suggest consultation.\n"
#     "Never suggest additional treatments beyond what the user asked.\n"
#     "If user asks about a treatment not listed, say:\n"
#     "I'm sorry, we don't currently offer that treatment."
#     "Never invent treatments.\n"

#     "CLINIC DETAILS (from memory, no function call):\n"
#     "- Address: 123, Building, Melbourne Central, Melbourne, Victoria\n"
#     "- Phone: 03 6160 3456\n"
#     "- Hours: Monday–Friday 9:00 AM–6:00 PM, Saturday–Sunday CLOSED\n\n"

#     "DENTISTS:\n"
#     "Dr. Emily Carter    (General Dentistry)\n"
#     "Dr. James Nguyen    (Cosmetic and Restorative)\n"
#     "Dr. Sarah Mitchell  (Orthodontics and Periodontics)\n\n"

#     # ── BOOKING ──────────────────────────────────────────────────────────────
#     "BOOKING (only after patient is verified or created):\n"
#     "\n"
#     "DETAIL EXTRACTION — CRITICAL:\n"
#     "  - Listen carefully and extract EXACTLY what the user says\n"
#     "  - Treatment: use the EXACT treatment name the user mentioned\n"
#     "    e.g. user says 'cleaning' -> use 'Teeth Cleaning and Check-Up'\n"
#     "         user says 'filling'  -> use 'Dental Fillings'\n"
#     "         user says 'implant'  -> use 'Dental Implants'\n"
#     "  - Dentist: map partial names to full names:\n"
#     "    'James' / 'Nguyen' / 'James Nguyen' -> 'Dr. James Nguyen'\n"
#     "    'Emily' / 'Carter' / 'Emily Carter' -> 'Dr. Emily Carter'\n"
#     "    'Sarah Mitchell' / 'Mitchell'       -> 'Dr. Sarah Mitchell'\n"
#     "    NEVER substitute a different dentist than what the user said\n"
#     "  - Date/Time: extract exactly what user said\n"
#     "\n"
#     "BOOKING FLOW:\n"
#     "  1. Collect all details (treatment, date, time, dentist preference)\n"
#     "  2. If specific dentist -> check_slot_availability()\n"
#     "     If no preference    -> find_any_available_dentist()\n"
#     "  3. Read back ONCE: 'So that's [treatment] on [date] at [time] with [dentist] — shall I go ahead?'\n"
#     "  4. Patient says YES -> call book_appointment() immediately\n"
#     "  5. NEVER book without explicit YES\n"
#     "  6. NEVER ask to confirm treatment/dentist separately — confirm EVERYTHING in one go\n\n"

#     # ── UPDATE / CANCEL ───────────────────────────────────────────────────────
#     "UPDATE/CANCEL:\n"
#     "  Skip Step 0 (existing patients only).\n"
#     "  Go directly to EXISTING PATIENT FLOW (last name -> DOB -> verify).\n"
#     "  After verification: call get_my_appointments() -> read as numbered list\n"
#     "  Use appointment_index (1,2,3…) for update or cancel\n"
#     "  CANCEL: confirm with patient -> cancel_my_appointment() after YES\n\n"

#     # ── COMPLAINTS ───────────────────────────────────────────────────────────
#     "COMPLAINTS — TWO-TYPE FLOW:\n"
#     "\n"
#     "STEP 1: Ask 'Is your complaint about something general — like our service, staff,\n"
#     "or environment — or is it about a specific treatment you received here?'\n"
#     "\n"
#     "TYPE 1 — GENERAL COMPLAINT (no verification):\n"
#     "  Examples: refund, rude staff, bad environment, billing issue, long wait, parking.\n"
#     "  Steps:\n"
#     "  1. Empathy: 'I'm so sorry to hear that, I completely understand your frustration.'\n"
#     "  2. Ask: 'Could you describe what happened?'\n"
#     "  3. Ask: 'May I take your first name, last name, and best contact number?\n"
#     "     (these are for our records so the manager can follow up with you)'\n"
#     "  4. Confirm: '[Name], just to confirm — [complaint summary]. Shall I log this?\n"
#     "  5. YES -> call file_complaint(category=general, first_name, last_name, contact_number)\n"
#     "  6. Say: 'Done! I've logged your complaint and our manager will be in touch.'\n"
#     "  !!! NEVER ask for DOB. NEVER verify. NEVER ask 'new or existing'. !!!\n"
#     "\n"
#     "TYPE 2 — TREATMENT COMPLAINT (verification required):\n"
#     "  Examples: bad treatment, problem with filling/crown/implant, medication issue,\n"
#     "            pain/problem after a procedure, issue with dentist.\n"
#     "  Steps:\n"
#     "  1. Empathy: 'I'm really sorry to hear you've had a problem with your treatment.'\n"
#     "  2. Say: 'I'll need to quickly verify your identity to pull up your records.'\n"
#     "  3. Follow EXISTING PATIENT FLOW (last name -> DOB -> verify)\n"
#     "  4. After verification ask: 'Which treatment is the complaint about?'\n"
#     "  5. Ask: 'Was this with a specific dentist?'\n"
#     "  6. Ask: 'Roughly when was the treatment?'\n"
#     "  7. Ask: 'Is there anything else you'd like to add?'\n"
#     "  8. Confirm ALL details once\n"
#     "  9. YES -> call file_complaint(category=treatment, all fields)\n"
#     "  10. Say: 'Logged! Our team will review and contact you within 2 business days.'\n"
#     "\n"
#     "COMPLAINT RULES:\n"
#     "  - Ask TYPE 1 or TYPE 2 question FIRST — never jump to verification\n"
#     "  - TYPE 1: NEVER ask last name alone first, NEVER ask DOB, NEVER verify\n"
#     "  - TYPE 2: must verify before filing\n"
#     "  - NEVER mention complaint ID\n"
#     "  - Always empathy BEFORE any question\n\n"

#     "CRITICAL:\n"
#     "Never ask verification before determining whether complaint is general or treatment-related."

#     # ── BUSINESS / SUPPLIER CALLS ─────────────────────────────────────────────
#     "BUSINESS CALL ROUTING — THREE TYPES:\n"
#     "\n"
#     "TYPE 1 — PATIENT GENERAL ENQUIRY:\n"
#     "  Questions about treatments, prices, hours, insurance, warranty.\n"
#     "  -> Answer directly using get_business_information() / get_insurance_information() etc.\n"
#     "  -> Never verify patient for general enquiries.\n"
#     "\n"
#     "TYPE 2 — AGENT / VENDOR CALL (delay, invoice, promotion, etc.):\n"
#     "  Caller says: 'I'm from [company], calling about [purpose]'\n"
#     "  Extract from what caller already said — DO NOT re-ask name/company if already given.\n"
#     "  Steps:\n"
#     "  1. If name or company not yet given -> ask ONCE: 'May I have your name and company?'\n"
#     "  2. Ask: 'And your best contact number?'\n"
#     "  3. Ask: 'Thank you — could you briefly describe the purpose of your call?'\n"
#     "  4. Call log_supplier_call() with all collected details\n"
#     "  5. Say: 'Thank you, [name]. I've noted your message and will pass it to our management.'\n"
#     "  !!! Never commit to payments, approvals, or deliveries. !!!\n"
#     "  !!! Never share patient personal information. !!!\n"
#     "\n"
#     "TYPE 3 — SUPPLIER ORDER-READY CALL:\n"
#     "  Caller says: 'I'm from [supplier] and the order for patient [X] is ready for delivery.'\n"
#     "  Valid supplier list (check with check_known_supplier()):\n"
#     "    - AusDental Labs Pty Ltd       (Crowns, Bridges, Veneers, Tooth Caps)\n"
#     "    - MedPro Orthodontics          (Braces, Clear Aligners, Retainers)\n"
#     "    - Southern Implant Supply Co.  (Implants, Abutments)\n"
#     "    - PrecisionDenture Works       (Dentures, Partial Plates)\n"
#     "    - OralCraft Technologies       (Mouthguards, Night Guards)\n"
#     "  Steps:\n"
#     "  1. Call check_known_supplier(company_name) to verify\n"
#     "     - NOT_FOUND -> 'I'm sorry, I don't have you on our supplier list. Let me log your details.'\n"
#     "                     -> treat as TYPE 2\n"
#     "  2. FOUND -> 'Thank you for calling! Which patient is this order for?'\n"
#     "  3. Ask for patient_id OR last name. Collect product name.\n"
#     "  4. Call update_supplier_order(patient_id, product_name) to mark order as ready\n"
#     "  5. Also call log_supplier_call() to record the call\n"
#     "  6. Say: 'Perfect, I've updated the order status to ready for [patient name].\n"
#     "     Our team will arrange collection. Thank you!'\n"
#     "  Products that require orders: Dentures, Braces, Clear Aligners, Dental Implants,\n"
#     "    Crowns/Bridges, Veneers, Tooth Caps, Custom Mouthguards, Root Canal Crowns.\n\n"

#     "MID-FLOW: unrelated question -> answer -> 'Shall we continue?' -> YES resume\n\n"
#     "ENDING: Thank you for calling Green Diode's Dental Clinic. Have a wonderful day!\n\n"

#     "TURN-TAKING RULES:\n"
#     "After asking ANY question, stop speaking and wait silently for the user to respond.\n"
#     "Never ask a follow-up until the current question is answered.\n"
#     "Never assume information the user has not provided.\n"
#     "NEVER ask a question you already have the answer to."
# )


# # ---------------------------------------------------------------------------
# # SAFE OPENAI SEND
# # ---------------------------------------------------------------------------

# async def safe_openai_send(openai_ws, payload: dict):
#     if not openai_ws:
#         return
#     try:
#         await openai_ws.send(json.dumps(payload))
#     except websockets.exceptions.ConnectionClosed:
#         print("[OpenAI WS] Send skipped — socket already closed")
#     except Exception as e:
#         print("[OpenAI WS ERROR]", e)


# # ---------------------------------------------------------------------------
# # SESSION HELPERS
# # ---------------------------------------------------------------------------

# def make_new_session(call_sid: str) -> dict:
#     return {
#         "call_sid":               call_sid,
#         "stream_sid":             None,
#         "created_at":             datetime.now(),
#         "verified":               False,
#         "patient_data":           None,
#         "current_flow":           None,
#         "fetched_appointments":   [],
#         "is_speaking":            False,
#         "interruption_pending":   False,
#         "current_response_id":    None,
#         "greeting_sent":          False,
#         "conversation_history":   [],
#         "last_assistant_item_id": None,
#         "audio_start_time":       None,
#         "elapsed_ms":             0,
#         "audio_queue":            [],
#         # ✅ FIX 21: track supplier context so we don't re-ask
#         "supplier_context": {
#             "caller_name":   None,
#             "company_name":  None,
#             "contact_number": None,
#             "is_known_supplier": False,
#         },
#     }


# def update_history(session: dict, role: str, content: str):
#     session["conversation_history"].append({
#         "role":      role,
#         "content":   content,
#         "timestamp": datetime.now().isoformat()
#     })


# # ---------------------------------------------------------------------------
# # SESSION CONFIG + TOOLS
# # ---------------------------------------------------------------------------

# def get_session_config() -> dict:
#     return {
#         "type": "session.update",
#         "session": {
#             "modalities":                ["text", "audio"],
#             "instructions":              SYSTEM_INSTRUCTIONS,
#             "voice":                     VOICE,
#             "input_audio_format":        "g711_ulaw",
#             "output_audio_format":       "g711_ulaw",
#             "input_audio_transcription": {"model": "whisper-1"},
#             "turn_detection": {
#                 "type":                "server_vad",
#                 "threshold":           VAD_THRESHOLD,
#                 "prefix_padding_ms":   PREFIX_PADDING_MS,
#                 "silence_duration_ms": SILENCE_DURATION_MS
#             },
#             "temperature":                TEMPERATURE,
#             "max_response_output_tokens": 1024,
#             "tools": [
#                 # ── VERIFICATION ──────────────────────────────────────────────
#                 {
#                     "type": "function", "name": "verify_existing_patient",
#                     "description": (
#                         "Verify existing patient by last name and date of birth. "
#                         "ONLY call after user has confirmed DOB in DD-MON-YYYY format."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "last_name":     {"type": "string"},
#                             "date_of_birth": {"type": "string",
#                                               "description": "DD-MON-YYYY e.g. 15 Jun 1990"}
#                         },
#                         "required": ["last_name", "date_of_birth"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "verify_with_contact_number",
#                     "description": "Disambiguate when multiple patients share last name + DOB.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "last_name":      {"type": "string"},
#                             "date_of_birth":  {"type": "string"},
#                             "contact_number": {"type": "string"}
#                         },
#                         "required": ["last_name", "date_of_birth", "contact_number"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "create_new_patient",
#                     "description": (
#                         "Register a new patient. MUST call immediately after collecting "
#                         "first_name, last_name, DOB, contact. Do NOT say account ready before this returns."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "first_name":     {"type": "string"},
#                             "last_name":      {"type": "string"},
#                             "date_of_birth":  {"type": "string"},
#                             "contact_number": {"type": "string"},
#                             "insurance_info": {"type": "string"}
#                         },
#                         "required": ["first_name", "last_name", "date_of_birth", "contact_number"]
#                     }
#                 },
#                 # ── APPOINTMENTS ──────────────────────────────────────────────
#                 {
#                     "type": "function", "name": "check_slot_availability",
#                     "description": "Check if a specific dentist is available at a given date/time.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "date":         {"type": "string"},
#                             "time":         {"type": "string"},
#                             "dentist_name": {"type": "string",
#                                              "description": "MUST be exact: Dr. Emily Carter | Dr. James Nguyen | Dr. Sarah Mitchell"}
#                         },
#                         "required": ["date", "time", "dentist_name"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "find_any_available_dentist",
#                     "description": "Find any available dentist when patient has no preference.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "date": {"type": "string"},
#                             "time": {"type": "string"}
#                         },
#                         "required": ["date", "time"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "book_appointment",
#                     "description": (
#                         "Book appointment ONLY after patient says YES to full confirmation. "
#                         "preferred_dentist MUST match exactly what the user said "
#                         "(mapped to Dr. Emily Carter / Dr. James Nguyen / Dr. Sarah Mitchell). "
#                         "preferred_treatment MUST be the EXACT treatment user requested."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "preferred_treatment": {"type": "string"},
#                             "preferred_date":      {"type": "string"},
#                             "preferred_time":      {"type": "string"},
#                             "preferred_dentist":   {"type": "string",
#                                                     "description": "Exact full name with Dr. prefix"}
#                         },
#                         "required": ["preferred_treatment", "preferred_date",
#                                      "preferred_time", "preferred_dentist"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "get_my_appointments",
#                     "description": "Get all confirmed appointments. ALWAYS call before update/cancel.",
#                     "parameters": {"type": "object", "properties": {}}
#                 },
#                 {
#                     "type": "function", "name": "update_my_appointment",
#                     "description": "Update an appointment using appointment_index from get_my_appointments.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "appointment_index": {"type": "integer"},
#                             "new_treatment":     {"type": "string"},
#                             "new_date":          {"type": "string"},
#                             "new_time":          {"type": "string"},
#                             "new_dentist":       {"type": "string"}
#                         },
#                         "required": ["appointment_index"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "cancel_my_appointment",
#                     "description": "Cancel appointment after patient confirms YES.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "appointment_index": {"type": "integer"},
#                             "reason":            {"type": "string"}
#                         },
#                         "required": ["appointment_index"]
#                     }
#                 },
#                 # ── COMPLAINTS ────────────────────────────────────────────────
#                 {
#                     "type": "function", "name": "file_complaint",
#                     "description": (
#                         "Save a complaint.\n"
#                         "TYPE 1 (general): NO verification. "
#                         "Required: complaint_text, complaint_category=general, "
#                         "first_name, last_name, contact_number.\n"
#                         "TYPE 2 (treatment): patient MUST be verified first. "
#                         "Required: complaint_text, complaint_category=treatment. "
#                         "Also provide: treatment_name, dentist_name, treatment_date, "
#                         "treatment_time, additional_info. "
#                         "patient_id and appointment_id come from verified session.\n"
#                         "NEVER ask for DOB for a general complaint."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "complaint_text":     {"type": "string"},
#                             "complaint_category": {"type": "string", "enum": ["general", "treatment"]},
#                             # TYPE 1 fields
#                             "first_name":         {"type": "string"},
#                             "last_name":          {"type": "string"},
#                             "contact_number":     {"type": "string"},
#                             # TYPE 2 fields
#                             "treatment_name":     {"type": "string"},
#                             "dentist_name":       {"type": "string"},
#                             "treatment_date":     {"type": "string"},
#                             "treatment_time":     {"type": "string"},
#                             "additional_info":    {"type": "string"},
#                             "appointment_id":     {"type": "integer",
#                                                    "description": "From fetched_appointments if known"}
#                         },
#                         "required": ["complaint_text", "complaint_category"]
#                     }
#                 },
#                 # ── BUSINESS / GENERAL ENQUIRY ────────────────────────────────
#                 {
#                     "type": "function", "name": "get_business_information",
#                     "description": "Get pricing, hours, payment, offers, dentist info.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"query": {"type": "string"}},
#                         "required": ["query"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "get_insurance_information",
#                     "description": "Get health insurance info. Insurance questions only.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"query": {"type": "string"}},
#                         "required": ["query"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "get_warranty_information",
#                     "description": "Get dental warranty policy. Warranty questions only.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"query": {"type": "string"}},
#                         "required": ["query"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "answer_dental_question",
#                     "description": "Answer questions about procedures, pre/post care, recovery. NOT for pricing.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"query": {"type": "string"}},
#                         "required": ["query"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "get_my_order_status",
#                     "description": "Check status of patient's dental order (dentures, braces, etc.).",
#                     "parameters": {"type": "object", "properties": {}}
#                 },
#                 {
#                     "type": "function", "name": "get_my_upcoming_appointments",
#                     "description": "Get upcoming appointments for verified patient.",
#                     "parameters": {"type": "object", "properties": {}}
#                 },
#                 {
#                     "type": "function", "name": "get_my_treatment_history",
#                     "description": "Get past treatment history for verified patient.",
#                     "parameters": {"type": "object", "properties": {}}
#                 },
#                 # ── BUSINESS / SUPPLIER CALLS ──────────────────────────────────
#                 {
#                     "type": "function", "name": "check_known_supplier",
#                     "description": (
#                         "Check if the calling company is an authorised supplier. "
#                         "ALWAYS call this first when a business caller mentions a company name. "
#                         "Returns FOUND (with supplier details) or NOT_FOUND."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "company_name": {"type": "string",
#                                              "description": "Company name as stated by caller"}
#                         },
#                         "required": ["company_name"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "update_supplier_order",
#                     "description": (
#                         "Mark a patient order as ready after a VERIFIED supplier confirms delivery. "
#                         "Use patient_id when available. Falls back to patient_last_name if no ID. "
#                         "Also call log_supplier_call() to record the call."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "patient_id":        {"type": "integer",
#                                                   "description": "Patient ID if provided by supplier"},
#                             "patient_last_name": {"type": "string",
#                                                   "description": "Last name fallback if no patient_id"},
#                             "product_name":      {"type": "string",
#                                                   "description": "Product being delivered e.g. Dentures, Braces"}
#                         },
#                         "required": ["product_name"]
#                     }
#                 },
#                 {
#                     "type": "function", "name": "log_supplier_call",
#                     "description": (
#                         "Log a call from a supplier, agent, or business. "
#                         "For TYPE 2 agent calls (delay, invoice, promotion). "
#                         "Also call this alongside update_supplier_order for TYPE 3 calls. "
#                         "NEVER for patient calls."
#                     ),
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "caller_name":    {"type": "string"},
#                             "company_name":   {"type": "string"},
#                             "contact_number": {"type": "string"},
#                             "purpose":        {"type": "string"}
#                         },
#                         "required": ["purpose"]
#                     }
#                 },
#             ],
#             "tool_choice": "auto"
#         }
#     }


# # ---------------------------------------------------------------------------
# # FUNCTION CALL HANDLER
# # ---------------------------------------------------------------------------

# async def handle_function_call(function_name, arguments, call_id, session, openai_ws, disarm_fn=None):
#     print(f"[FUNCTION] {function_name}")
#     print(f"[ARGS]     {json.dumps(arguments, indent=2)}")
#     result = {}

#     try:

#         # ── VERIFICATION ──────────────────────────────────────────────────────
#         if function_name == "verify_existing_patient":
#             r = verify_by_lastname_dob(
#                 last_name=arguments.get("last_name", ""),
#                 dob=normalize_dob(arguments.get("date_of_birth", ""))
#             )
#             if r["status"] == "VERIFIED":
#                 session["patient_data"] = r
#                 session["verified"]     = True
#                 result = {
#                     "status":         "VERIFIED",
#                     "first_name":     r["first_name"],
#                     "last_name":      r["last_name"],
#                     "date_of_birth":  r["date_of_birth"],
#                     "contact_spoken": format_phone_for_speech(r.get("contact_number", ""))
#                 }
#             elif r["status"] == "MULTIPLE_FOUND":
#                 result = {"status": "MULTIPLE_FOUND", "message": r["message"]}
#             else:
#                 result = {"status": "NOT_FOUND", "message": r.get("message", "No account found.")}

#         elif function_name == "verify_with_contact_number":
#             phone = extract_phone_from_text(arguments.get("contact_number", ""))
#             r = verify_by_lastname_dob_contact(
#                 last_name=arguments.get("last_name", ""),
#                 dob=normalize_dob(arguments.get("date_of_birth", "")),
#                 contact_number=phone
#             )
#             if r["status"] == "VERIFIED":
#                 session["patient_data"] = r
#                 session["verified"]     = True
#                 result = {"status": "VERIFIED",
#                           "first_name": r["first_name"], "last_name": r["last_name"]}
#             else:
#                 result = {"status": "NOT_FOUND", "message": r.get("message", "Could not verify.")}

#         elif function_name == "create_new_patient":

#             phone = extract_phone_from_text(arguments.get("contact_number", ""))
#             insurance = arguments.get("insurance_info")

#             if not insurance or insurance.strip() == "":
#                 insurance = "None"

#             r = create_new_patient(
#                 first_name=arguments.get("first_name", ""),
#                 last_name=arguments.get("last_name", ""),
#                 dob=normalize_dob(arguments.get("date_of_birth", "")),
#                 contact_number=phone,
#                 insurance_info=insurance
#             )

#             if r["status"] == "CREATED":
#                 session["patient_data"] = r
#                 session["verified"] = True

#                 result = {
#                     "status": "CREATED",
#                     "first_name": r["first_name"],
#                     "last_name": r["last_name"],
#                     "message": "Account created successfully."
#                 }

#             else:
#                 result = {
#                     "status": "ERROR",
#                     "message": r.get("message", "Could not create account.")
#                 }

#         # ── APPOINTMENTS ──────────────────────────────────────────────────────
#         elif function_name == "check_slot_availability":
#             result = check_dentist_availability(
#                 date_str=arguments.get("date", ""),
#                 time_str=arguments.get("time", ""),
#                 dentist_name=arguments.get("dentist_name", "")
#             )

#         elif function_name == "find_any_available_dentist":
#             result = find_available_dentist(
#                 date_str=arguments.get("date", ""),
#                 time_str=arguments.get("time", "")
#             )

#         elif function_name == "book_appointment":
#             if not session.get("verified") or not session.get("patient_data"):
#                 result = {"status": "ERROR", "message": "Patient must be verified first."}
#             else:
#                 p = session["patient_data"]
#                 r = book_appointment(
#                     patient_id=p["patient_id"],
#                     first_name=p["first_name"],
#                     last_name=p["last_name"],
#                     date_of_birth=p["date_of_birth"],
#                     contact_number=p["contact_number"],
#                     preferred_treatment=arguments.get("preferred_treatment", ""),
#                     preferred_date=arguments.get("preferred_date", ""),
#                     preferred_time=arguments.get("preferred_time", ""),
#                     preferred_dentist=arguments.get("preferred_dentist", "")
#                 )
#                 if r["status"] == "BOOKED":
#                     result = {
#                         "status":    "BOOKED",
#                         "treatment": r["treatment"],
#                         "date":      r["date"],
#                         "time":      r["time"],
#                         "dentist":   r["dentist"]
#                     }
#                 else:
#                     result = {"status": "ERROR", "message": r.get("message", "Booking failed.")}

#         elif function_name == "get_my_appointments":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 r = get_patient_appointments(session["patient_data"]["patient_id"])
#                 if r["status"] == "SUCCESS":
#                     appts = r["appointments"]
#                     session["fetched_appointments"] = appts
#                     result = {
#                         "status": "SUCCESS",
#                         "appointments": [
#                             {
#                                 "index":     i,
#                                 "treatment": a["treatment"],
#                                 "date":      a["date"],
#                                 "time":      a["time"],
#                                 "dentist":   a["dentist"],
#                                 "status":    a["status"]
#                             }
#                             for i, a in enumerate(appts, 1)
#                         ],
#                         "count": len(appts)
#                     }
#                 else:
#                     result = {"status": r["status"], "message": r.get("message", "")}

#         elif function_name == "update_my_appointment":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 idx   = arguments.get("appointment_index", 1) - 1
#                 appts = session.get("fetched_appointments", [])
#                 if not appts:
#                     r2 = get_patient_appointments(session["patient_data"]["patient_id"])
#                     if r2["status"] == "SUCCESS":
#                         appts = r2["appointments"]
#                         session["fetched_appointments"] = appts
#                 if 0 <= idx < len(appts):
#                     fields = {}
#                     if arguments.get("new_treatment"): fields["preferred_treatment"] = arguments["new_treatment"]
#                     if arguments.get("new_date"):      fields["preferred_date"]      = arguments["new_date"]
#                     if arguments.get("new_time"):      fields["preferred_time"]      = arguments["new_time"]
#                     if arguments.get("new_dentist"):   fields["preferred_dentist"]   = arguments["new_dentist"]
#                     r = update_appointment(appts[idx]["_id"], fields)
#                     if r["status"] == "UPDATED":
#                         session["fetched_appointments"] = []
#                         result = {
#                             "status":    "UPDATED",
#                             "treatment": r["treatment"],
#                             "date":      r["date"],
#                             "time":      r["time"],
#                             "dentist":   r["dentist"]
#                         }
#                     else:
#                         result = {"status": "ERROR", "message": r.get("message", "Update failed.")}
#                 else:
#                     result = {"status": "ERROR", "message": "Invalid index. Call get_my_appointments first."}

#         elif function_name == "cancel_my_appointment":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 idx   = arguments.get("appointment_index", 1) - 1
#                 appts = session.get("fetched_appointments", [])
#                 if not appts:
#                     r2 = get_patient_appointments(session["patient_data"]["patient_id"])
#                     if r2["status"] == "SUCCESS":
#                         appts = r2["appointments"]
#                         session["fetched_appointments"] = appts
#                 if 0 <= idx < len(appts):
#                     r = cancel_appointment(appts[idx]["_id"], arguments.get("reason"))
#                     if r["status"] == "CANCELLED":
#                         session["fetched_appointments"] = []
#                         result = {
#                             "status":    "CANCELLED",
#                             "treatment": r["treatment"],
#                             "date":      r["date"],
#                             "time":      r["time"],
#                             "dentist":   r["dentist"]
#                         }
#                     else:
#                         result = {"status": "ERROR", "message": r.get("message", "Cancel failed.")}
#                 else:
#                     result = {"status": "ERROR", "message": "Invalid index. Call get_my_appointments first."}

#         # ── COMPLAINTS ────────────────────────────────────────────────────────
#         elif function_name == "file_complaint":
#             # ✅ FIX 20: full two-type complaint handling
#             category = arguments.get("complaint_category", "general").lower()

#             if category == "treatment":
#                 if not session.get("verified") or not session.get("patient_data"):
#                     result = {"status": "ERROR",
#                               "message": "Patient must be verified for a treatment complaint."}
#                 else:
#                     p = session["patient_data"]
#                     # Try to find appointment_id from fetched_appointments if user mentioned one
#                     appt_id = arguments.get("appointment_id")
#                     if not appt_id and session.get("fetched_appointments"):
#                         # Use first appointment as reference if none specified
#                         appt_id = None  # Let complaint_executor handle None

#                     r = save_complaint(
#                         complaint_category="treatment",
#                         complaint_text=arguments.get("complaint_text", ""),
#                         first_name=p["first_name"],
#                         last_name=p["last_name"],
#                         contact_number=p.get("contact_number"),
#                         patient_id=p["patient_id"],
#                         appointment_id=appt_id,
#                         date_of_birth=p.get("date_of_birth"),
#                         treatment_name=arguments.get("treatment_name"),
#                         dentist_name=arguments.get("dentist_name"),
#                         treatment_date=arguments.get("treatment_date"),
#                         treatment_time=arguments.get("treatment_time"),
#                         additional_info=arguments.get("additional_info"),
#                     )
#                     result = r if r["status"] != "SAVED" else {
#                         "status":  "SAVED",
#                         "message": r["message"]
#                     }

#             else:  # general
#                 r = save_complaint(
#                     complaint_category="general",
#                     complaint_text=arguments.get("complaint_text", ""),
#                     first_name=arguments.get("first_name"),
#                     last_name=arguments.get("last_name"),
#                     contact_number=arguments.get("contact_number"),
#                 )
#                 result = r if r["status"] != "SAVED" else {
#                     "status":  "SAVED",
#                     "message": r["message"]
#                 }

#         # ── GENERAL ENQUIRY ───────────────────────────────────────────────────
#         elif function_name == "get_business_information":
#             r = handle_business_info(user_input=arguments.get("query", ""), session=session)
#             result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

#         elif function_name == "get_insurance_information":
#             r = handle_insurance_query(user_input=arguments.get("query", ""), session=session)
#             result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

#         elif function_name == "get_warranty_information":
#             r = handle_warranty_query(user_input=arguments.get("query", ""), session=session)
#             result = {"status": r.get("status", "SUCCESS"), "response": r.get("response", "")}

#         elif function_name == "answer_dental_question":
#             query = arguments.get("query", "")
#             r = handle_kb_query(user_input=query, session=session)

#             # Hard restriction: never allow consultation suggestion
#             response_text = r.get("response", "")
#             if "consultation" in response_text.lower():
#                 response_text = response_text.replace("consultation", "")

#             result = {"status": r.get("source", "kb"), "response": response_text}

#         elif function_name == "get_my_order_status":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 r = get_patient_orders(session["patient_data"]["patient_id"])
#                 if r["status"] == "SUCCESS":
#                     result = {
#                         "status": "SUCCESS",
#                         "orders": [{"product": o["product_name"],
#                                     "status":  o["order_status"],
#                                     "notes":   o.get("notes", "")} for o in r["orders"]],
#                         "count": r["count"]
#                     }
#                 else:
#                     result = {"status": r["status"], "message": r.get("message", "No orders found.")}

#         elif function_name == "get_my_upcoming_appointments":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 r = get_upcoming_appointments(session["patient_data"]["patient_id"])
#                 if r["status"] == "SUCCESS":
#                     result = {
#                         "status": "SUCCESS",
#                         "appointments": [{"treatment": a["treatment"], "date": a["date"],
#                                           "time": a["time"], "dentist": a["dentist"]}
#                                          for a in r["appointments"]],
#                         "count": r["count"]
#                     }
#                 else:
#                     result = {"status": r["status"], "message": r.get("message", "None found.")}

#         elif function_name == "get_my_treatment_history":
#             if not session.get("verified"):
#                 result = {"status": "ERROR", "message": "Patient not verified."}
#             else:
#                 r = get_past_appointments(session["patient_data"]["patient_id"])
#                 if r["status"] == "SUCCESS":
#                     result = {
#                         "status": "SUCCESS",
#                         "appointments": [{"treatment": a["treatment"], "date": a["date"],
#                                           "dentist": a["dentist"]}
#                                          for a in r["appointments"][:5]],
#                         "count": r["count"]
#                     }
#                 else:
#                     result = {"status": r["status"], "message": r.get("message", "None found.")}

#         # ── BUSINESS / SUPPLIER ────────────────────────────────────────────────
#         elif function_name == "check_known_supplier":
#             # ✅ FIX 21: check supplier + store in session
#             company_name = arguments.get("company_name", "")
#             r = check_supplier(company_name)
#             if r["status"] == "FOUND":
#                 session["supplier_context"]["company_name"]      = r["supplier"]["company_name"]
#                 session["supplier_context"]["is_known_supplier"] = True
#                 result = {
#                     "status":       "FOUND",
#                     "company_name": r["supplier"]["company_name"],
#                     "specialty":    r["supplier"]["specialty"],
#                     "message":      f"Verified supplier: {r['supplier']['company_name']}."
#                 }
#             else:
#                 session["supplier_context"]["is_known_supplier"] = False
#                 result = {"status": "NOT_FOUND", "message": r["message"]}

#         elif function_name == "update_supplier_order":
#             # ✅ FIX 21: update order by patient_id first, fallback to name
#             patient_id   = arguments.get("patient_id")
#             last_name    = arguments.get("patient_last_name")
#             product_name = arguments.get("product_name", "")

#             if patient_id:
#                 r = update_order_by_patient_id(
#                     patient_id=int(patient_id),
#                     product_name=product_name,
#                     new_status="ready",
#                     notes=f"Supplier confirmed order ready — {session['supplier_context'].get('company_name','')}"
#                 )
#             elif last_name:
#                 r = update_order_status_by_patient_name(
#                     patient_name=last_name,
#                     product_name=product_name,
#                     new_status="ready",
#                     notes=f"Supplier confirmed order ready — {session['supplier_context'].get('company_name','')}"
#                 )
#             else:
#                 r = {"status": "ERROR",
#                      "message": "Need patient_id or patient_last_name to update order."}

#             result = r

#         elif function_name == "log_supplier_call":
#             # ✅ FIX 21: merge caller details from session if already known
#             ctx = session.get("supplier_context", {})
#             caller_name    = arguments.get("caller_name") or ctx.get("caller_name")
#             company_name   = arguments.get("company_name") or ctx.get("company_name")
#             contact_number = arguments.get("contact_number") or ctx.get("contact_number")

#             # Store whatever we learn into session
#             if arguments.get("caller_name"):
#                 session["supplier_context"]["caller_name"]    = arguments["caller_name"]
#             if arguments.get("company_name"):
#                 session["supplier_context"]["company_name"]   = arguments["company_name"]
#             if arguments.get("contact_number"):
#                 session["supplier_context"]["contact_number"] = arguments["contact_number"]

#             log_business_call(
#                 caller_name=caller_name,
#                 company_name=company_name,
#                 contact_number=contact_number,
#                 purpose=arguments.get("purpose"),
#                 full_notes=json.dumps(arguments)
#             )
#             result = {
#                 "status":  "LOGGED",
#                 "message": f"Call from {caller_name or 'caller'} ({company_name or 'unknown company'}) logged. Management will follow up."
#             }

#         else:
#             result = {"error": f"Unknown function: {function_name}"}

#     except Exception as e:
#         print("========== FUNCTION / DB ERROR ==========")
#         traceback.print_exc()
#         print("=========================================")
#         result = {"status": "ERROR", "message": str(e)}

#     if disarm_fn:
#         disarm_fn()

#     await safe_openai_send(openai_ws, {
#         "type": "conversation.item.create",
#         "item": {"type": "function_call_output",
#                  "call_id": call_id,
#                  "output": json.dumps(result)}
#     })
#     await safe_openai_send(openai_ws, {"type": "response.create"})
#     print(f"[RESULT] {json.dumps(result, indent=2)}")


# # ---------------------------------------------------------------------------
# # TWILIO WEBHOOK
# # ---------------------------------------------------------------------------

# @app.api_route("/voice", methods=["GET", "POST"])
# async def voice(request: Request):
#     twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
# <Response>
#     <Connect>
#         <Stream url="{CLOUD_RUN_WSS_BASE}/media-stream"/>
#     </Connect>
# </Response>"""
#     return Response(content=twiml, media_type="application/xml")


# # ---------------------------------------------------------------------------
# # MAIN WEBSOCKET
# # ---------------------------------------------------------------------------

# @app.websocket("/media-stream")
# async def handle_media_stream(websocket: WebSocket):
#     import time
#     print("=" * 70)
#     print("[CALL START] New WebSocket connection")
#     print("=" * 70)
#     await websocket.accept()

#     call_sid    = None
#     stream_sid  = None
#     session     = None
#     openai_ws   = None
#     call_active = {"running": True}

#     try:
#         openai_ws = await websockets.connect(
#             OPENAI_REALTIME_URL,
#             additional_headers={
#                 "Authorization": f"Bearer {OPENAI_API_KEY}",
#                 "OpenAI-Beta": "realtime=v1"
#             }
#         )
#         print("[OpenAI] WebSocket connected successfully")
#     except Exception as e:
#         print(f"[OpenAI] Connection FAILED: {e}")
#         await websocket.close()
#         return

#     async def receive_from_openai():
#         nonlocal session
#         pending_fn      = None
#         pending_call_id = None
#         pending_args    = ""

#         wd = {"task": None, "armed": False}

#         async def watchdog():
#             await asyncio.sleep(1.5)
#             if not wd["armed"]:
#                 return
#             if session and session.get("is_speaking"):
#                 return
#             print("[WATCHDOG] Bot silent — nudge")
#             try:
#                 if not session.get("is_speaking"):
#                     await safe_openai_send(openai_ws, {"type": "response.create"})
#             except Exception as e:
#                 print(f"[WATCHDOG ERROR] {e}")
#             wd["armed"] = False

#         def arm_watchdog():
#             if wd["task"] and not wd["task"].done():
#                 wd["task"].cancel()
#             wd["armed"] = True
#             wd["task"]  = asyncio.create_task(watchdog())

#         def disarm_watchdog():
#             if wd["task"] and not wd["task"].done():
#                 wd["task"].cancel()
#             wd["armed"] = False
#             wd["task"]  = None

#         try:
#             await safe_openai_send(openai_ws, get_session_config())
#             print("[OpenAI] Session config sent", flush=True)

#             async for message in openai_ws:
#                 data       = json.loads(message)
#                 event_type = data.get("type", "")
#                 print(f"[OpenAI EVENT] {event_type}", flush=True)

#                 try:
#                     if event_type == "session.updated":
#                         if session and not session.get("greeting_sent") and not session.get("verified"):
#                             session["greeting_sent"] = True
#                             await safe_openai_send(openai_ws, {
#                                 "type": "conversation.item.create",
#                                 "item": {
#                                     "type": "message",
#                                     "role": "user",
#                                     "content": [{"type": "input_text", "text": "[CALL_STARTED]"}]
#                                 }
#                             })
#                             await safe_openai_send(openai_ws, {"type": "response.create"})

#                     elif event_type == "response.output_item.added":
#                         # Ensure Twilio playback stream is ready
#                         if stream_sid:
#                             try:
#                                 await websocket.send_json({
#                                     "event": "mark",
#                                     "streamSid": stream_sid,
#                                     "mark": {"name": "start_playback"}
#                                 })
#                             except Exception:
#                                 pass
#                         if session:
#                             session["last_assistant_item_id"] = data.get("item", {}).get("id")
#                             session["audio_start_time"]       = None
#                             session["elapsed_ms"]             = 0
#                             session["audio_queue"].clear()

#                     elif event_type == "response.audio.delta":
#                         disarm_watchdog()
#                         if stream_sid and "delta" in data:
#                             if session:
#                                 session["is_speaking"] = True
#                                 session["audio_queue"].append(data["delta"])
#                                 if session["audio_start_time"] is None:
#                                     session["audio_start_time"] = time.time()
#                             await websocket.send_json({
#                                 "event":     "media",
#                                 "streamSid": stream_sid,
#                                 "media":     {"payload": data["delta"]}
#                             })

#                     elif event_type == "response.audio.done":
#                         if session:
#                             session["is_speaking"]      = False
#                             session["audio_queue"]      = []
#                             session["audio_start_time"] = None
#                             session["elapsed_ms"]       = 0
#                         print("[BOT] Done speaking")
#                         try:
#                             await safe_openai_send(openai_ws, {"type": "input_audio_buffer.clear"})
#                         except Exception:
#                             pass

#                     elif event_type == "response.created":
#                         if session:
#                             session["current_response_id"] = data.get("response", {}).get("id")

#                     elif event_type == "response.done":
#                         pass  # intentionally empty

#                     elif event_type == "input_audio_buffer.speech_started":

#                         if session and session.get("is_speaking"):

#                             print("[BARGE-IN] User interrupted — stopping bot")

#                             # ONLY clear if bot is speaking
#                             try:
#                                 await websocket.send_json({
#                                     "event": "clear",
#                                     "streamSid": stream_sid
#                                 })
#                             except Exception:
#                                 pass

#                             if session["audio_start_time"] is not None:
#                                 session["elapsed_ms"] = int(
#                                     (time.time() - session["audio_start_time"]) * 1000
#                                 )
#                             else:
#                                 session["elapsed_ms"] = 0

#                             try:
#                                 await safe_openai_send(openai_ws, {"type": "response.cancel"})
#                             except Exception:
#                                 pass

#                             if session["last_assistant_item_id"]:
#                                 try:
#                                     await safe_openai_send(openai_ws, {
#                                         "type": "conversation.item.truncate",
#                                         "item_id": session["last_assistant_item_id"],
#                                         "content_index": 0,
#                                         "audio_end_ms": session["elapsed_ms"]
#                                     })
#                                 except Exception:
#                                     pass

#                             session["audio_queue"].clear()
#                             session["last_assistant_item_id"] = None
#                             session["audio_start_time"] = None
#                             session["elapsed_ms"] = 0
#                             session["is_speaking"] = False

#                         else:
#                             print("[USER] Speaking (no barge-in needed)")

#                     elif event_type == "input_audio_buffer.speech_stopped":
#                         if session:
#                             session["interruption_pending"] = False

#                     elif event_type == "input_audio_buffer.cleared":
#                         pass

#                     elif event_type == "response.function_call_arguments.start":
#                         pending_fn      = data.get("name")
#                         pending_call_id = data.get("call_id")
#                         pending_args    = ""

#                     elif event_type == "response.function_call_arguments.delta":
#                         pending_args += data.get("delta", "")

#                     elif event_type == "response.function_call_arguments.done":
#                         fn  = data.get("name")      or pending_fn
#                         cid = data.get("call_id")   or pending_call_id
#                         raw = data.get("arguments") or pending_args
#                         try:
#                             args = json.loads(raw or "{}")
#                         except json.JSONDecodeError:
#                             args = {}
#                         if fn:
#                             await handle_function_call(fn, args, cid, session, openai_ws, disarm_watchdog)
#                         pending_fn = pending_call_id = None
#                         pending_args = ""

#                     elif event_type == "conversation.item.input_audio_transcription.completed":
#                         transcript = data.get("transcript", "")
#                         if transcript and session:
#                             print(f"[USER] {transcript}")
#                             update_history(session, "user", transcript)

#                     elif event_type == "response.audio_transcript.done":
#                         transcript = data.get("transcript", "")
#                         if transcript and session:
#                             print(f"[BOT]  {transcript}")
#                             update_history(session, "assistant", transcript)

#                     elif event_type == "error":
#                         err = data.get("error", {})
#                         print(f"[OpenAI ERROR] {err.get('type')}: {err.get('message')}", flush=True)

#                 except Exception as inner_e:
#                     print(f"[LOOP ERROR] Failed handling '{event_type}': {inner_e}")
#                     traceback.print_exc()
#                     continue

#         except websockets.exceptions.ConnectionClosed as e:
#             print(f"[OpenAI] Connection closed — Code: {e.code} Reason: {e.reason}", flush=True)
#         except Exception as e:
#             print(f"[OpenAI RECEIVE ERROR] {type(e).__name__}: {e}", flush=True)
#             traceback.print_exc()
#         finally:
#             disarm_watchdog()

#     async def receive_from_twilio():
#         nonlocal call_sid, stream_sid, session
#         try:
#             async for message in websocket.iter_text():
#                 data       = json.loads(message)
#                 event_type = data.get("event", "")

#                 if event_type == "start":
#                     stream_sid = data["start"]["streamSid"]
#                     call_sid   = data["start"].get("callSid", stream_sid)
#                     session    = make_new_session(call_sid)
#                     session["stream_sid"] = stream_sid
#                     print(f"[Twilio] Connected | Stream: {stream_sid}")

#                 elif event_type == "media":
#                     if openai_ws and data.get("media", {}).get("payload"):
#                         await safe_openai_send(openai_ws, {
#                             "type":  "input_audio_buffer.append",
#                             "audio": data["media"]["payload"]
#                         })

#                 elif event_type == "stop":
#                     print("[Twilio] Call ended by Twilio")
#                     call_active["running"] = False
#                     if openai_ws:
#                         try:
#                             await openai_ws.close()
#                         except Exception:
#                             pass
#                     break

#                 else:
#                     print(f"[Twilio] Unknown event ignored: {event_type}")

#         except WebSocketDisconnect:
#             print("[Twilio] Caller disconnected")
#             call_active["running"] = False
#             if openai_ws:
#                 try:
#                     await openai_ws.close()
#                 except Exception:
#                     pass
#         except Exception as e:
#             print(f"[Twilio RECEIVE ERROR] {e}")
#             traceback.print_exc()

#     async def keep_alive():
#         """Send silent session.update ping every 25s to prevent Twilio 60s timeout."""
#         try:
#             while call_active["running"]:
#                 await asyncio.sleep(25)
#                 if not call_active["running"]:
#                     break
#                 if not openai_ws:
#                     continue
#                 try:
#                     await safe_openai_send(openai_ws, {
#                         "type": "session.update",
#                         "session": {
#                             "turn_detection": {
#                                 "type":                "server_vad",
#                                 "threshold":           VAD_THRESHOLD,
#                                 "prefix_padding_ms":   PREFIX_PADDING_MS,
#                                 "silence_duration_ms": SILENCE_DURATION_MS
#                             }
#                         }
#                     })
#                     print("[KEEPALIVE] Ping sent")
#                 except websockets.exceptions.ConnectionClosed:
#                     print("[KEEPALIVE] OpenAI WS closed — stopping")
#                     break
#                 except Exception as e:
#                     print("[KEEPALIVE ERROR]", e)
#                     break
#         except asyncio.CancelledError:
#             print("[KEEPALIVE] cancelled")

#     try:
#         tasks = [
#             asyncio.create_task(receive_from_twilio()),
#             asyncio.create_task(receive_from_openai()),
#             asyncio.create_task(keep_alive())
#         ]
#         done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
#         for task in pending:
#             task.cancel()
#     except Exception as e:
#         print(f"[HANDLER ERROR] {e}")
#         traceback.print_exc()
#     finally:
#         call_active["running"] = False
#         print("[CALL END] Cleaning up...")
#         if session:
#             last = session["conversation_history"][-1]["content"] if session["conversation_history"] else "none"
#             print(f"[CALL END] Verified: {session['verified']} | Last: {last}")
#         if openai_ws:
#             try:
#                 await openai_ws.close()
#             except Exception:
#                 pass
#         print("[CALL END] Done\n")


# # ---------------------------------------------------------------------------
# # HEALTH CHECK
# # ---------------------------------------------------------------------------

# @app.get("/health")
# def health():
#     return {"status": "ok"}


# # ---------------------------------------------------------------------------
# # RUN
# # ---------------------------------------------------------------------------

# if __name__ == "__main__":
#     import uvicorn
#     print("=" * 70)
#     print("  DentalBot v2")
#     print(f"  Voice    : {VOICE}")
#     print(f"  Fixes    : booking extraction | DOB any-format | complaint two-type |")
#     print(f"             supplier check | order-by-patient-id | no-repeat-questions")
#     print("=" * 70)
#     uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))




"""
DentalBot v2 -- main.py
OpenAI Realtime API + Twilio WebSocket

Fixes applied (cumulative):
  1–15: (unchanged from prior versions — see history)
  16. COMPLAINTS: two-path flow (general / treatment)
  17. file_complaint handler: general = no verification
  18. BOOKING: strict dentist/treatment extraction + single confirm-before-book
  19. DOB: any user format → DD-MON-YYYY re-confirm before verify call
  20. COMPLAINTS TYPE 1: collect first_name, last_name, contact_number (no DOB/verify)
      COMPLAINTS TYPE 2: full save — patient_id, appointment_id, DOB, contact,
                         treatment_name, dentist_name, date, time, extra_info
  21. BUSINESS TYPE 2: extract caller_name+company_name from conversation, do NOT re-ask
      BUSINESS TYPE 3: check known supplier list → update order by patient_id
  22. NEVER ask repeated questions in any flow
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

OPENAI_REALTIME_URL      = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
VOICE                    = "coral"
TEMPERATURE              = 0.8
VAD_THRESHOLD            = 0.90   # raised: reduces false triggers from phone line noise
PREFIX_PADDING_MS        = 500    # raised: needs more audio before treating as speech
SILENCE_DURATION_MS      = 700    # lowered: still responds quickly after real speech
CLOUD_RUN_WSS_BASE       = "wss://green-diods-dental-clinic-production.up.railway.app"

# ---------------------------------------------------------------------------
# SYSTEM INSTRUCTIONS
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = (
    "You are Sarah, a warm and professional AI receptionist for Green Diode's Dental Clinic.\n\n"

    "SERVICES (memorise — never call a function to list these):\n"
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

    "TREATMENT ANSWER RULES — NEVER BREAK:\n"
    "1. ONLY recommend treatments from the 18-item SERVICES list above.\n"
    "2. NEVER suggest any treatment NOT in that list.\n"
    "3. NEVER suggest a 'consultation' — use 'Teeth Cleaning and Check-Up' instead.\n"
    "4. answer_dental_question() uses ONLY internal KB. Trust its response.\n"
    "5. If KB has no answer: 'I don't have that detail — our team can help in clinic.'\n"
    "6. NEVER invent prices, durations, or procedure steps.\n\n"

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
    - Use contractions always: "I'll" not "I will", "you're" not "you are"
    - Use natural filler transitions: "Of course!", "Absolutely!", "Sure thing!"
    - When confirming details, sound warm: "Perfect, got that!" not "Confirmed."
    - Vary sentence length — don't speak in uniform rhythm
    - Show empathy: "Oh I'm sorry to hear that" / "That's great!"
    - Never read structured lists — convert to natural spoken sentences
    - Instead of "Date: 5th March, Time: 10 AM" say "the 5th of March at 10 in the morning"
    """

    # ── CALLER TYPE ──────────────────────────────────────────────────────────
    "CALLER TYPE IDENTIFICATION — READ CAREFULLY:\n"
    "\n"
    "PATIENT (vast majority):\n"
    "  Wants appointment, has tooth pain, asks about treatment/price,\n"
    "  wants to cancel/reschedule, has a complaint, asks about order.\n"
    "  -> ALWAYS verify/register patient first. NEVER call log_supplier_call().\n"
    "\n"
    "BUSINESS / SUPPLIER (rare — explicit only):\n"
    "  ONLY when caller EXPLICITLY says: 'I'm from [company]', sales rep,\n"
    "  delivery courier, or mentions placing/delivering an order.\n"
    "  -> Call check_known_supplier() first. Then route to Type 2 or Type 3.\n"
    "\n"
    "CRITICAL: general inquiry / 'I have a question' / 'I want to book' -> PATIENT.\n\n"

    # ── VERIFICATION ─────────────────────────────────────────────────────────
    "VERIFICATION:\n\n"
    "Only ask 'Are you an existing or new patient?' when intent is BOOK, UPDATE, or CANCEL.\n"
    "Do NOT ask for general questions about address, hours, pricing, insurance.\n\n"

    "CALL START BEHAVIOUR:\n"
    "After greeting, STOP and WAIT silently for the caller to say what they need.\n"
    "Do NOT ask 'Are you an existing or new patient?' right after the greeting.\n"
    "Listen to their intent first, then decide.\n\n"

    "STEP 0 — WHEN TO ASK 'Are you an existing patient or a new patient?':\n"
    "Ask ONLY when intent is: BOOK, UPDATE, or CANCEL an appointment,\n"
    "  check order status, upcoming appointments, or treatment history.\n"
    "DO NOT ASK for: address, hours, phone, services, pricing, payment,\n"
    "  insurance, warranty, dental questions, or complaints (own rules apply).\n"
    "EXCEPTION — UPDATE/CANCEL: skip Step 0. Only existing patients have appointments.\n"
    "  Go directly to EXISTING PATIENT FLOW (last name -> DOB -> verify).\n"
    "When Step 0 IS required:\n"
    "  -> EXISTING -> EXISTING PATIENT FLOW\n"
    "  -> NEW      -> NEW PATIENT FLOW\n"
    "  -> UNSURE   -> 'Have you visited us before?'\n\n"

    "EXISTING PATIENT FLOW:\n"
    "  Step 1: Ask last name\n"
    "  Step 2: Ask date of birth\n"
    "  Step 3: ALWAYS convert DOB to DD-MON-YYYY and read back:\n"
    "          'Just to confirm, that's the [DD] of [Month] [YYYY] — is that right?'\n"
    "          Examples of what user might say -> what you confirm:\n"
    "            '12/06/1990'     -> '12th of June 1990'\n"
    "            '6-12-90'        -> '6th of December 1990'\n"
    "            '15 03 2001'     -> '15th of March 2001'\n"
    "            'fifteenth March 2001' -> '15th of March 2001'\n"
    "          WAIT for user to say YES before calling verify_existing_patient()\n"
    "  Step 4: Call verify_existing_patient()\n"
    "    VERIFIED       -> read contact digit by digit, then assist\n"
    "    MULTIPLE_FOUND -> ask contact number, call verify_with_contact_number()\n"
    "    NOT_FOUND      -> offer to retry or create new account\n\n"

    "NEW PATIENT FLOW (no skipping):\n"
    "  Step 1: first name  Step 2: last name  Step 3: DOB (confirm as DD-MON-YYYY)\n"
    "  Step 4: contact (read back digit by digit)  Step 5: insurance (optional)\n"
    "  Step 6: call create_new_patient() immediately\n"
    "  Step 7: wait for status=CREATED, then say account is ready\n\n"

    "After verification: patient is verified for the entire call.\n"
    "Use their first name. NEVER ask name/contact again.\n\n"

    # ── GOLDEN RULES ─────────────────────────────────────────────────────────
    "GOLDEN RULES (never break):\n"
    "1. NEVER ask appointment ID — use get_my_appointments()\n"
    "2. NEVER mention any internal ID in responses\n"
    "3. NEVER ask name or contact after verification\n"
    "4. NEVER give medication advice or diagnose\n"
    "5. After booking — say date, time, dentist only\n"
    "6. NEVER say 'schedule a consultation'\n"
    "7. Phone readback ALWAYS digit by digit\n"
    "8. NEVER ask repeated questions — if info already given, use it\n"
    "9. NEVER mention any treatment not in the 18-item SERVICES list\n\n"

    "CLINIC DETAILS (from memory, no function call):\n"
    "- Address: 123, Building, Melbourne Central, Melbourne, Victoria\n"
    "- Phone: 03 6160 3456\n"
    "- Hours: Monday–Friday 9:00 AM–6:00 PM, Saturday–Sunday CLOSED\n\n"

    "DENTISTS:\n"
    "Dr. Emily Carter    (General Dentistry)\n"
    "Dr. James Nguyen    (Cosmetic and Restorative)\n"
    "Dr. Sarah Mitchell  (Orthodontics and Periodontics)\n\n"

    # ── BOOKING ──────────────────────────────────────────────────────────────
    "BOOKING (only after patient is verified or created):\n"
    "\n"
    "DETAIL EXTRACTION — CRITICAL:\n"
    "  - Listen carefully and extract EXACTLY what the user says\n"
    "  - Treatment: use the EXACT treatment name the user mentioned\n"
    "    e.g. user says 'cleaning' -> use 'Teeth Cleaning and Check-Up'\n"
    "         user says 'filling'  -> use 'Dental Fillings'\n"
    "         user says 'implant'  -> use 'Dental Implants'\n"
    "  - Dentist: map partial names to full names:\n"
    "    'James' / 'Nguyen' / 'James Nguyen' -> 'Dr. James Nguyen'\n"
    "    'Emily' / 'Carter' / 'Emily Carter' -> 'Dr. Emily Carter'\n"
    "    'Sarah Mitchell' / 'Mitchell'       -> 'Dr. Sarah Mitchell'\n"
    "    NEVER substitute a different dentist than what the user said\n"
    "  - Date/Time: extract exactly what user said\n"
    "\n"
    "BOOKING FLOW:\n"
    "  1. Collect all details (treatment, date, time, dentist preference)\n"
    "  2. If specific dentist -> check_slot_availability()\n"
    "     If no preference    -> find_any_available_dentist()\n"
    "  3. Read back ONCE: 'So that's [treatment] on [date] at [time] with [dentist] — shall I go ahead?'\n"
    "  4. Patient says YES -> call book_appointment() immediately\n"
    "  5. NEVER book without explicit YES\n"
    "  6. NEVER ask to confirm treatment/dentist separately — confirm EVERYTHING in one go\n\n"

    # ── UPDATE / CANCEL ───────────────────────────────────────────────────────
    "UPDATE/CANCEL:\n"
    "  Skip Step 0 (existing patients only).\n"
    "  Go directly to EXISTING PATIENT FLOW (last name -> DOB -> verify).\n"
    "  After verification: call get_my_appointments() -> read as numbered list\n"
    "  Use appointment_index (1,2,3…) for update or cancel\n"
    "  CANCEL: confirm with patient -> cancel_my_appointment() after YES\n\n"

    # ── COMPLAINTS ───────────────────────────────────────────────────────────
    "COMPLAINTS — TWO-TYPE FLOW:\n"
    "\n"
    "STEP 1: Ask 'Is your complaint about something general — like our service, staff,\n"
    "or environment — or is it about a specific treatment you received here?'\n"
    "\n"
    "TYPE 1 — GENERAL COMPLAINT (no verification):\n"
    "  Examples: refund, rude staff, bad environment, billing issue, long wait, parking.\n"
    "  Steps:\n"
    "  1. Empathy: 'I'm so sorry to hear that, I completely understand your frustration.'\n"
    "  2. Ask: 'Could you describe what happened?'\n"
    "  3. Ask: 'May I take your first name, last name, and best contact number?\n"
    "     (these are for our records so the manager can follow up with you)'\n"
    "  4. Confirm: '[Name], just to confirm — [complaint summary]. Shall I log this?\n"
    "  5. YES -> call file_complaint(category=general, first_name, last_name, contact_number)\n"
    "  6. Say: 'Done! I've logged your complaint and our manager will be in touch.'\n"
    "  !!! NEVER ask for DOB. NEVER verify. NEVER ask 'new or existing'. !!!\n"
    "\n"
    "TYPE 2 — TREATMENT COMPLAINT (verification required):\n"
    "  Examples: bad treatment, problem with filling/crown/implant, medication issue,\n"
    "            pain/problem after a procedure, issue with dentist.\n"
    "  Steps:\n"
    "  1. Empathy: 'I'm really sorry to hear you've had a problem with your treatment.'\n"
    "  2. Say: 'I'll need to quickly verify your identity to pull up your records.'\n"
    "  3. Follow EXISTING PATIENT FLOW (last name -> DOB -> verify)\n"
    "  4. After verification ask: 'Which treatment is the complaint about?'\n"
    "  5. Ask: 'Was this with a specific dentist?'\n"
    "  6. Ask: 'Roughly when was the treatment?'\n"
    "  7. Ask: 'Is there anything else you'd like to add?'\n"
    "  8. Confirm ALL details once\n"
    "  9. YES -> call file_complaint(category=treatment, all fields)\n"
    "  10. Say: 'Logged! Our team will review and contact you within 2 business days.'\n"
    "\n"
    "COMPLAINT RULES:\n"
    "  - Ask TYPE 1 or TYPE 2 question FIRST — never jump to verification\n"
    "  - TYPE 1: NEVER ask last name alone first, NEVER ask DOB, NEVER verify\n"
    "  - TYPE 2: must verify before filing\n"
    "  - NEVER mention complaint ID\n"
    "  - Always empathy BEFORE any question\n\n"

    # ── BUSINESS / SUPPLIER CALLS ─────────────────────────────────────────────
    "BUSINESS CALL ROUTING — THREE TYPES:\n"
    "\n"
    "TYPE 1 — PATIENT GENERAL ENQUIRY:\n"
    "  Questions about treatments, prices, hours, insurance, warranty.\n"
    "  -> Answer directly using get_business_information() / get_insurance_information() etc.\n"
    "  -> Never verify patient for general enquiries.\n"
    "\n"
    "TYPE 2 — AGENT / VENDOR CALL (delay, invoice, promotion, etc.):\n"
    "  Caller says: 'I'm from [company], calling about [purpose]'\n"
    "  Extract from what caller already said — DO NOT re-ask name/company if already given.\n"
    "  Steps:\n"
    "  1. If name or company not yet given -> ask ONCE: 'May I have your name and company?'\n"
    "  2. Ask: 'And your best contact number?'\n"
    "  3. Ask: 'Thank you — could you briefly describe the purpose of your call?'\n"
    "  4. Call log_supplier_call() with all collected details\n"
    "  5. Say: 'Thank you, [name]. I've noted your message and will pass it to our management.'\n"
    "  !!! Never commit to payments, approvals, or deliveries. !!!\n"
    "  !!! Never share patient personal information. !!!\n"
    "\n"
    "TYPE 3 — SUPPLIER ORDER-READY CALL:\n"
    "  Caller says: 'I'm from [supplier] and the order for patient [X] is ready for delivery.'\n"
    "  Valid supplier list (check with check_known_supplier()):\n"
    "    - AusDental Labs Pty Ltd       (Crowns, Bridges, Veneers, Tooth Caps)\n"
    "    - MedPro Orthodontics          (Braces, Clear Aligners, Retainers)\n"
    "    - Southern Implant Supply Co.  (Implants, Abutments)\n"
    "    - PrecisionDenture Works       (Dentures, Partial Plates)\n"
    "    - OralCraft Technologies       (Mouthguards, Night Guards)\n"
    "  Steps:\n"
    "  1. Call check_known_supplier(company_name) to verify\n"
    "     - NOT_FOUND -> 'I'm sorry, I don't have you on our supplier list. Let me log your details.'\n"
    "                     -> treat as TYPE 2\n"
    "  2. FOUND -> 'Thank you for calling! Which patient is this order for?'\n"
    "  3. Ask for patient_id OR last name. Collect product name.\n"
    "  4. Call update_supplier_order(patient_id, product_name) to mark order as ready\n"
    "  5. Also call log_supplier_call() to record the call\n"
    "  6. Say: 'Perfect, I've updated the order status to ready for [patient name].\n"
    "     Our team will arrange collection. Thank you!'\n"
    "  Products that require orders: Dentures, Braces, Clear Aligners, Dental Implants,\n"
    "    Crowns/Bridges, Veneers, Tooth Caps, Custom Mouthguards, Root Canal Crowns.\n\n"

    "MID-FLOW: unrelated question -> answer -> 'Shall we continue?' -> YES resume\n\n"
    "ENDING: Thank you for calling Green Diode's Dental Clinic. Have a wonderful day!\n\n"

    "TURN-TAKING RULES:\n"
    "After asking ANY question, stop speaking and wait silently for the user to respond.\n"
    "Never ask a follow-up until the current question is answered.\n"
    "Never assume information the user has not provided.\n"
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
        print("[OpenAI WS] Send skipped — socket already closed")
    except Exception as e:
        print("[OpenAI WS ERROR]", e)


# ---------------------------------------------------------------------------
# SESSION HELPERS
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
        # ✅ FIX 21: track supplier context so we don't re-ask
        "supplier_context": {
            "caller_name":   None,
            "company_name":  None,
            "contact_number": None,
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
            "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
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
                        "Register a new patient. MUST call immediately after collecting "
                        "first_name, last_name, DOB, contact. Do NOT say account ready before this returns."
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
                            "dentist_name": {"type": "string",
                                             "description": "MUST be exact: Dr. Emily Carter | Dr. James Nguyen | Dr. Sarah Mitchell"}
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
                        "preferred_dentist MUST match exactly what the user said "
                        "(mapped to Dr. Emily Carter / Dr. James Nguyen / Dr. Sarah Mitchell). "
                        "preferred_treatment MUST be the EXACT treatment user requested."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "preferred_treatment": {"type": "string"},
                            "preferred_date":      {"type": "string"},
                            "preferred_time":      {"type": "string"},
                            "preferred_dentist":   {"type": "string",
                                                    "description": "Exact full name with Dr. prefix"}
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
                    "description": "Update an appointment using appointment_index from get_my_appointments.",
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
                    "description": "Cancel appointment after patient confirms YES.",
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
                        "TYPE 1 (general): NO verification. "
                        "Required: complaint_text, complaint_category=general, "
                        "first_name, last_name, contact_number.\n"
                        "TYPE 2 (treatment): patient MUST be verified first. "
                        "Required: complaint_text, complaint_category=treatment. "
                        "Also provide: treatment_name, dentist_name, treatment_date, "
                        "treatment_time, additional_info. "
                        "patient_id and appointment_id come from verified session.\n"
                        "NEVER ask for DOB for a general complaint."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "complaint_text":     {"type": "string"},
                            "complaint_category": {"type": "string", "enum": ["general", "treatment"]},
                            # TYPE 1 fields
                            "first_name":         {"type": "string"},
                            "last_name":          {"type": "string"},
                            "contact_number":     {"type": "string"},
                            # TYPE 2 fields
                            "treatment_name":     {"type": "string"},
                            "dentist_name":       {"type": "string"},
                            "treatment_date":     {"type": "string"},
                            "treatment_time":     {"type": "string"},
                            "additional_info":    {"type": "string"},
                            "appointment_id":     {"type": "integer",
                                                   "description": "From fetched_appointments if known"}
                        },
                        "required": ["complaint_text", "complaint_category"]
                    }
                },
                # ── BUSINESS / GENERAL ENQUIRY ────────────────────────────────
                {
                    "type": "function", "name": "get_business_information",
                    "description": "Get pricing, hours, payment, offers, dentist info.",
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
                    "description": "Check status of patient's dental order (dentures, braces, etc.).",
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
                # ── BUSINESS / SUPPLIER CALLS ──────────────────────────────────
                {
                    "type": "function", "name": "check_known_supplier",
                    "description": (
                        "Check if the calling company is an authorised supplier. "
                        "ALWAYS call this first when a business caller mentions a company name. "
                        "Returns FOUND (with supplier details) or NOT_FOUND."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string",
                                             "description": "Company name as stated by caller"}
                        },
                        "required": ["company_name"]
                    }
                },
                {
                    "type": "function", "name": "update_supplier_order",
                    "description": (
                        "Mark a patient order as ready after a VERIFIED supplier confirms delivery. "
                        "Use patient_id when available. Falls back to patient_last_name if no ID. "
                        "Also call log_supplier_call() to record the call."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "patient_id":        {"type": "integer",
                                                  "description": "Patient ID if provided by supplier"},
                            "patient_last_name": {"type": "string",
                                                  "description": "Last name fallback if no patient_id"},
                            "product_name":      {"type": "string",
                                                  "description": "Product being delivered e.g. Dentures, Braces"}
                        },
                        "required": ["product_name"]
                    }
                },
                {
                    "type": "function", "name": "log_supplier_call",
                    "description": (
                        "Log a call from a supplier, agent, or business. "
                        "For TYPE 2 agent calls (delay, invoice, promotion). "
                        "Also call this alongside update_supplier_order for TYPE 3 calls. "
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
# FUNCTION CALL HANDLER
# ---------------------------------------------------------------------------

async def handle_function_call(function_name, arguments, call_id, session, openai_ws, disarm_fn=None):
    print(f"[FUNCTION] {function_name}")
    print(f"[ARGS]     {json.dumps(arguments, indent=2)}")
    result = {}

    try:

        # ── VERIFICATION ──────────────────────────────────────────────────────
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

        # ── APPOINTMENTS ──────────────────────────────────────────────────────
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

        # ── COMPLAINTS ────────────────────────────────────────────────────────
        elif function_name == "file_complaint":
            # ✅ FIX 20: full two-type complaint handling
            category = arguments.get("complaint_category", "general").lower()

            if category == "treatment":
                if not session.get("verified") or not session.get("patient_data"):
                    result = {"status": "ERROR",
                              "message": "Patient must be verified for a treatment complaint."}
                else:
                    p = session["patient_data"]
                    # Try to find appointment_id from fetched_appointments if user mentioned one
                    appt_id = arguments.get("appointment_id")
                    if not appt_id and session.get("fetched_appointments"):
                        # Use first appointment as reference if none specified
                        appt_id = None  # Let complaint_executor handle None

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
                    result = r if r["status"] != "SAVED" else {
                        "status":  "SAVED",
                        "message": r["message"]
                    }

            else:  # general
                r = save_complaint(
                    complaint_category="general",
                    complaint_text=arguments.get("complaint_text", ""),
                    first_name=arguments.get("first_name"),
                    last_name=arguments.get("last_name"),
                    contact_number=arguments.get("contact_number"),
                )
                result = r if r["status"] != "SAVED" else {
                    "status":  "SAVED",
                    "message": r["message"]
                }

        # ── GENERAL ENQUIRY ───────────────────────────────────────────────────
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
                        "orders": [{"product": o["product_name"],
                                    "status":  o["order_status"],
                                    "notes":   o.get("notes", "")} for o in r["orders"]],
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

        # ── BUSINESS / SUPPLIER ────────────────────────────────────────────────
        elif function_name == "check_known_supplier":
            # ✅ FIX 21: check supplier + store in session
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
            # ✅ FIX 21: update order by patient_id first, fallback to name
            patient_id   = arguments.get("patient_id")
            last_name    = arguments.get("patient_last_name")
            product_name = arguments.get("product_name", "")

            if patient_id:
                r = update_order_by_patient_id(
                    patient_id=int(patient_id),
                    product_name=product_name,
                    new_status="ready",
                    notes=f"Supplier confirmed order ready — {session['supplier_context'].get('company_name','')}"
                )
            elif last_name:
                r = update_order_status_by_patient_name(
                    patient_name=last_name,
                    product_name=product_name,
                    new_status="ready",
                    notes=f"Supplier confirmed order ready — {session['supplier_context'].get('company_name','')}"
                )
            else:
                r = {"status": "ERROR",
                     "message": "Need patient_id or patient_last_name to update order."}

            result = r

        elif function_name == "log_supplier_call":
            # ✅ FIX 21: merge caller details from session if already known
            ctx = session.get("supplier_context", {})
            caller_name    = arguments.get("caller_name") or ctx.get("caller_name")
            company_name   = arguments.get("company_name") or ctx.get("company_name")
            contact_number = arguments.get("contact_number") or ctx.get("contact_number")

            # Store whatever we learn into session
            if arguments.get("caller_name"):
                session["supplier_context"]["caller_name"]    = arguments["caller_name"]
            if arguments.get("company_name"):
                session["supplier_context"]["company_name"]   = arguments["company_name"]
            if arguments.get("contact_number"):
                session["supplier_context"]["contact_number"] = arguments["contact_number"]

            log_business_call(
                caller_name=caller_name,
                company_name=company_name,
                contact_number=contact_number,
                purpose=arguments.get("purpose"),
                full_notes=json.dumps(arguments)
            )
            result = {
                "status":  "LOGGED",
                "message": f"Call from {caller_name or 'caller'} ({company_name or 'unknown company'}) logged. Management will follow up."
            }

        else:
            result = {"error": f"Unknown function: {function_name}"}

    except Exception as e:
        print("========== FUNCTION / DB ERROR ==========")
        traceback.print_exc()
        print("=========================================")
        result = {"status": "ERROR", "message": str(e)}

    if disarm_fn:
        disarm_fn()

    await safe_openai_send(openai_ws, {
        "type": "conversation.item.create",
        "item": {"type": "function_call_output",
                 "call_id": call_id,
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

    call_sid      = None
    stream_sid    = None
    session       = None
    openai_ws     = None
    call_active   = {"running": True}
    # FIX D: prevents race where session.updated fires before Twilio 'start' sets session
    session_ready = asyncio.Event()

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
            # FIX D: wait for Twilio 'start' before sending session config
            # Prevents session.updated firing while session is still None
            try:
                await asyncio.wait_for(session_ready.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                print("[WARN] session_ready timeout — proceeding anyway", flush=True)
            await safe_openai_send(openai_ws, get_session_config())
            print("[OpenAI] Session config sent", flush=True)

            async for message in openai_ws:
                data       = json.loads(message)
                event_type = data.get("type", "")
                print(f"[OpenAI EVENT] {event_type}", flush=True)

                try:
                    if event_type == "session.updated":
                        if session and not session.get("greeting_sent"):
                            session["greeting_sent"] = True
                            await safe_openai_send(openai_ws, {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "[CALL_STARTED]"}]
                                }
                            })
                            # FIX E: wait 300ms so OpenAI commits the item before
                            # response.create runs — without this delay the model
                            # sees an empty conversation and returns empty response
                            await asyncio.sleep(0.3)
                            await safe_openai_send(openai_ws, {
                                "type": "response.create",
                                "response": {
                                    "modalities": ["text", "audio"],
                                    "instructions": (
                                        "The phone call has just connected. "
                                        "Say the greeting out loud RIGHT NOW: "
                                        "'Hello! Thank you for calling Green Diode\'s Dental Clinic. "
                                        "I\'m Sarah, how may I assist you today?' "
                                        "Speak it immediately then stop and wait silently for the caller."
                                    )
                                }
                            })

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
                        # FIX G: do NOT clear input_audio_buffer here —
                        # it discards speech the user already started saying
                        # while the bot was finishing its sentence.

                    elif event_type == "response.created":
                        if session:
                            session["current_response_id"] = data.get("response", {}).get("id")

                    elif event_type == "response.done":
                        # FIX F: clear so barge-in knows no active response remains
                        if session:
                            session["current_response_id"] = None

                    elif event_type == "input_audio_buffer.speech_started":
                        # FIX F: only interrupt when bot has audio truly in-flight
                        if (session
                                and session.get("is_speaking")
                                and session.get("last_assistant_item_id")):
                            print("[BARGE-IN] User interrupted — stopping bot")
                            if session["audio_start_time"] is not None:
                                session["elapsed_ms"] = int(
                                    (time.time() - session["audio_start_time"]) * 1000
                                )
                            else:
                                session["elapsed_ms"] = 0
                            # FIX F: only cancel if an active response exists
                            # cancelling a finished response → 'no active response' error
                            if session.get("current_response_id"):
                                try:
                                    await safe_openai_send(openai_ws, {"type": "response.cancel"})
                                except Exception:
                                    pass
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
                            session["audio_queue"].clear()
                            session["last_assistant_item_id"] = None
                            session["audio_start_time"]       = None
                            session["elapsed_ms"]             = 0
                            session["is_speaking"]            = False
                        else:
                            print("[USER] Speaking (no barge-in needed)")

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
                    session_ready.set()  # FIX D: unblock receive_from_openai

                elif event_type == "media":
                    if openai_ws and data.get("media", {}).get("payload"):
                        await safe_openai_send(openai_ws, {
                            "type":  "input_audio_buffer.append",
                            "audio": data["media"]["payload"]
                        })

                elif event_type == "stop":
                    print("[Twilio] Call ended by Twilio")
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
        """Send silent session.update ping every 25s to prevent Twilio 60s timeout."""
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
        if session:
            last = session["conversation_history"][-1]["content"] if session["conversation_history"] else "none"
            print(f"[CALL END] Verified: {session['verified']} | Last: {last}")
        if openai_ws:
            try:
                await openai_ws.close()
            except Exception:
                pass
        print("[CALL END] Done\n")


# ---------------------------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------------------------

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
    print(f"  Fixes    : booking extraction | DOB any-format | complaint two-type |")
    print(f"             supplier check | order-by-patient-id | no-repeat-questions")
    print("=" * 70)
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))