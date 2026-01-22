from __future__ import annotations

import os
import uuid
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .ai_client import AIResult, build_ai_client, enforce_guardrails, parse_response
from .data_sources import load_listings, search_listings
from .sheets import read_sheet_dicts
from .profile_extractor import extract_profile_fields
from .storage import Storage

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

storage = Storage(DATA_DIR / "app.db")
if os.getenv("PERSIST_CHAT_HISTORY", "").lower() not in {"1", "true", "yes"}:
    storage.clear_chat_history()
DEFAULT_SYSTEM_PROMPT = """You are an after-hours AI receptionist for a real-estate team. Non-negotiables:
- Never invent addresses, prices, beds/baths, acreage, or availability—only use details supplied in the [Listings] sheet context.
- If the visitor wants a tour, first ask whether they are working with an agent and whether they have a pre-approval letter before offering to coordinate.
- If the visitor greets you, greet back and ask what brings them in today; do not assume a property or schedule.
- Keep replies concise (≤3 short sentences) and ask exactly one question per turn.
- Collect the best email/phone and preferred contact method before confirming anything.
- If data is missing, say you'll confirm with the team and collect contact + preferred time.
- Mention only properties that appear in [Listings]; otherwise say you'll confirm."""
TOOLING_PROMPT = """For property specs or address requests, call lookup_listings with the provided beds/baths/sqft/price/acreage/location. Return best match first; if top is pending, include an active alternative.
When listing results include image URLs, emit image tokens <image1 src="URL" alt="ADDRESS"></image1> up to <image5>. Hyperlink the address if listing_url is present.
If no listing matches, ask for budget/bed/bath/sqft/location and offer team follow-up.
If asked for unrelated work, say you are the real-estate reception bot and steer back to property needs.
Before offering a tour, ask whether they are working with an agent and whether they have a pre-approval letter.
Never ask more than one question per turn—pick the highest-priority question only.
Do not call log_lead unless the current user message contains name AND email/phone AND a property/interest. If contact or property is missing, ask for exactly one missing item instead of calling the tool.
If a user asks for photos/images and the listing has no image URLs, say the demo feed has no photos for that address and offer to share when available."""

ROUTING_TOOL_PROMPT = """You are a routing classifier.
Return ONLY a record_routing tool call based on the latest user message and the assistant reply.
Do not include any natural language."""


def _load_tenant_configs(force: bool = False) -> Dict[str, Dict[str, Any]]:
    raise HTTPException(status_code=501, detail="Tenant configuration via Keys tab has been removed.")


def _get_runtime_config(sheet_id_override: Optional[str] = None) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if AI_PROVIDER in {"openai", "cloud"} and not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is required for cloud provider.")
    return {
        "api_key": api_key,
        "model": os.getenv("MODEL_NAME", MODEL_NAME),
        "sheet_id": sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID"),
    }


def load_system_prompt(sheet_id_override: Optional[str] = None) -> str:
    sheet_id = sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID")
    prompt_range = os.getenv("SHEETS_PROMPT_RANGE", "Settings!A:C")
    system_text = ""
    business_name = ""
    if sheet_id:
        rows = read_sheet_dicts(sheet_id, prompt_range)
        for row in rows:
            system_text = system_text or (row.get("system_prompt") or row.get("system") or "").strip()
            business_name = business_name or (row.get("business_name") or "").strip()

    prompt_path = Path(os.getenv("SYSTEM_PROMPT_PATH", "prompt.txt")).resolve()
    file_prompt = ""
    try:
        file_prompt = prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        file_prompt = ""

    if not file_prompt:
        base = DEFAULT_SYSTEM_PROMPT
    else:
        base = file_prompt
    parts = [base]
    if system_text:
        parts.append(f"Tone/style: {system_text}")
    if business_name:
        parts.append(f"Business name: {business_name}")
    if load_listings(sheet_id_override):
        parts.append(
            "Real-estate guardrails: If a visitor wants a tour, always ask whether they are working with an agent and if they have a pre-approval letter before offering times. Only discuss addresses/prices that appear in [Listings]; do not invent availability."
        )
    return "\n\n".join([p for p in parts if p])


AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5-mini")

AI_CLIENT = None
AI_CLIENT_ERROR: Optional[str] = None
try:
    AI_CLIENT = build_ai_client(AI_PROVIDER, model_name=MODEL_NAME)
except Exception as exc:  # pragma: no cover - startup guard
    AI_CLIENT_ERROR = str(exc)


class ChatRequest(BaseModel):
    business_id: Optional[str] = None  # retained for backward compatibility; ignored
    conversation_id: Optional[str]
    message: str
    sheet_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    routing: Dict[str, str]
    conversation_id: str
    profile: Dict[str, Optional[str]]
    lead_captured: bool = False


class LeadRequest(BaseModel):
    business_id: Optional[str] = None  # retained for backward compatibility; ignored
    conversation_id: Optional[str]
    name: str
    email: str
    phone: str
    contact_method: str
    preferred_time: Optional[str] = ""
    intent: str
    urgency: Optional[str] = "unknown"
    summary: str
    sheet_id: Optional[str] = None


class LeadResponse(BaseModel):
    ok: bool


app = FastAPI(title="AI Receptionist Demo")

cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
allow_all_origins = "*" in cors_origins or not cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEDULING_KEYWORDS = (
    "schedule",
    "appointment",
    "available",
    "availability",
    "consult",
    "visit",
    "pickup",
    "pick up",
)

FOCUS_DESCRIPTIONS = {
    "need": "Clarify what they need (product/service/issue) before moving on.",
    "timeline": "Confirm the timing or deadline before anything else.",
    "constraints": "Ask about any requirements, location, or constraints.",
    "budget": "Ask if there is a budget or range to stay within.",
    "contact": "Collect the visitor name plus email/phone so a teammate can follow up.",
    "schedule": "Offer current openings only if the visitor wants to book now.",
    "confirm": "Confirm next steps or offer to send a recap.",
}

FOCUS_QUESTIONS = {
    "need": "What do you need help with today?",
    "timeline": "When do you need this by?",
    "constraints": "Are there any must-haves or constraints I should note?",
    "budget": "Is there a budget or range I should keep in mind?",
    "contact": "What’s the best name and email or phone number for the follow-up?",
    "schedule": "Would you like me to hold one of the current openings?",
    "confirm": "Shall I send a quick recap with next steps?",
}

TOOL_DEFINITIONS_PRIMARY = [
    {
        "type": "function",
        "function": {
            "name": "lookup_listings",
            "description": "Search listings by beds/baths/sqft/price/acreage/location and return best matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "beds": {"type": "integer"},
                    "baths": {"type": "number"},
                    "sqft_target": {"type": "integer"},
                    "price_min": {"type": "integer"},
                    "price_max": {"type": "integer"},
                    "acreage_min": {"type": "number"},
                    "acreage_max": {"type": "number"},
                    "location": {"type": "string", "description": "city/state/zip/address keyword"},
                    "limit": {"type": "integer", "default": 4},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_lead",
            "description": "Record visitor contact info and session summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "contact_method": {"type": "string", "description": "email, text, or call"},
                    "preferred_time": {"type": "string", "description": "Preferred time window"},
                    "intent": {"type": "string"},
                    "urgency": {"type": "string"},
                    "summary": {"type": "string"},
                    "interest": {"type": "string", "description": "listing address or name"},
                },
                "required": [],
            },
        },
    },
]

TOOL_DEFINITIONS_ROUTING = [
    {
        "type": "function",
        "function": {
            "name": "record_routing",
            "description": "Capture routing metadata for the current assistant response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "buy, book, pricing, question, support, or other",
                    },
                    "lead_capture": {"type": "string", "description": "yes or no"},
                    "urgency": {
                        "type": "string",
                        "description": "today, this_week, soon, flexible, or unknown",
                    },
                    "next_step": {
                        "type": "string",
                        "description": "ask_need, ask_timeline, ask_constraints, ask_budget, ask_contact, ask_schedule, or confirm_submission",
                    },
                    "summary": {"type": "string"},
                },
                "required": [],
            },
        },
    },
]

FILLER_PHRASES = [
    "looking forward to",
    "let me know if you have any other questions",
    "feel free to",
    "happy to help",
]

DATE_REGEX = re.compile(
    r"(\b\d{4}-\d{2}-\d{2}\b)|(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s+\d{1,2}(?:st|nd|rd|th)?",
    re.IGNORECASE,
)
TOOL_CALL_JSON_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
def _format_date_label(date_str: str) -> str:
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.strftime("%b %d")
    except ValueError:
        return date_str


def determine_stage_and_focus(profile: Dict[str, Any]) -> Tuple[str, str]:
    profile = profile or {}
    urgency = profile.get("urgency") or "unknown"
    timeline_known = bool(profile.get("requested_date")) or urgency not in {"", "unknown", None}
    need_known = bool(profile.get("product_name") or profile.get("product_type") or profile.get("summary"))
    constraints_known = bool(profile.get("inventory_status") or profile.get("consult_type"))
    budget_known = bool(profile.get("budget"))
    contact_known = bool(profile.get("contact_email") or profile.get("contact_phone"))
    name_known = bool(profile.get("contact_name"))

    if not need_known:
        return "discover", "need"
    if not timeline_known:
        return "timeline", "timeline"
    if not constraints_known:
        return "constraints", "constraints"
    if not budget_known:
        return "budget", "budget"
    if not contact_known or not name_known:
        return "contact", "contact"
    if contact_known and name_known and timeline_known:
        return "schedule", "schedule"
    return "confirm", "confirm"


def build_profile_prompt(profile: Dict[str, Any], stage: str, focus: str) -> str:
    profile = profile or {}
    known = []
    if profile.get("contact_name"):
        known.append(f"Name: {profile['contact_name']}")
    if profile.get("product_name"):
        inv = f" ({profile['inventory_status']})" if profile.get("inventory_status") else ""
        sku = f" [{profile['product_sku']}]" if profile.get("product_sku") else ""
        known.append(f"Item: {profile['product_name']}{inv}{sku}")
    if profile.get("requested_date"):
        known.append(f"Timeline: {profile['requested_date']}")
    elif profile.get("urgency") and profile["urgency"] not in ("unknown", ""):
        known.append(f"Urgency: {profile['urgency']}")
    if profile.get("consult_type"):
        known.append(f"Type: {profile['consult_type']}")
    if profile.get("budget"):
        known.append(f"Budget: {profile['budget']}")
    if profile.get("contact_email") or profile.get("contact_phone"):
        known.append("Contact on file")
    known_text = ", ".join(known) if known else "None yet"
    focus_text = FOCUS_DESCRIPTIONS.get(focus, "Ask the next qualifying question.")
    checklist = (
        "Checklist (use only if relevant; do not interrogate): "
        "need, timing, constraints, budget, contact."
    )
    return (
        "[Profile Context]\n"
        f"Stage: {stage}\n"
        f"Known: {known_text}\n"
        f"Next focus: {focus_text}\n"
        f"{checklist}\n"
        "Guidelines: Ask exactly one question, keep ≤3 short sentences, avoid filler closings, and stay within the listings data provided."
    )


def should_offer_schedule(
    stage: str,
    message: str,
    extracted: Dict[str, str],
    profile: Dict[str, Any],
) -> bool:
    lowered = message.lower()
    if any(keyword in lowered for keyword in SCHEDULING_KEYWORDS):
        return True
    if extracted.get("requested_date"):
        return True
    urgency = extracted.get("urgency") or profile.get("urgency")
    if stage in {"schedule", "confirm"} and urgency in {"today", "this_week", "soon"}:
        return True
    return False


def build_site_context(sheet_id_override: Optional[str] = None) -> str:
    parts = []
    sheet_id = sheet_id_override or os.getenv("SHEETS_SPREADSHEET_ID")
    prompt_range = os.getenv("SHEETS_PROMPT_RANGE", "Settings!A:C")
    fallback_about = os.getenv(
        "FALLBACK_ABOUT",
        "We provide an after-hours AI receptionist that answers FAQs about your real-estate listings and captures contact details for follow-up.",
    )
    if sheet_id:
        rows = read_sheet_dicts(sheet_id, prompt_range)
        for row in rows:
            about_text = (row.get("about") or "").strip()
            if about_text:
                parts.append("[About]\n" + about_text)
                break
    if not parts and fallback_about:
        parts.append("[About]\n" + fallback_about)

    listings = load_listings(sheet_id)
    if listings:
        listing_lines = []
        for listing in listings[:10]:
            listing_lines.append(
                f"- {listing.get('address','')}: {listing.get('beds','?')}bd/{listing.get('baths','?')}ba"
                f" | {listing.get('sqft','')} sqft | ${listing.get('price','')} | status={listing.get('status','')}"
                f" | acres={listing.get('acres','')}"
            )
        parts.append("[Listings]\n" + "\n".join(listing_lines))

    if not parts:
        return ""
    inner = "Site info (read-only):\n" + "\n\n".join(parts)
    return "<SHEETDATA456>\n" + inner + "\n</SHEETDATA456>"


def update_conversation_profile(
    conversation_id: str,
    user_extracted: Dict[str, str],
    routing: Dict[str, str],
) -> Tuple[Dict[str, Any], str, str]:
    existing = storage.get_profile(conversation_id) or {}
    merged = existing.copy()
    for key, value in user_extracted.items():
        if value:
            merged[key] = value
    for key in ("intent", "urgency", "summary"):
        value = routing.get(key)
        if value:
            merged[key] = value
    stage, focus = determine_stage_and_focus(merged)
    merged["stage"] = stage
    storage.upsert_profile(
        conversation_id,
        {k: v for k, v in merged.items() if k in {
            "stage",
            "intent",
            "urgency",
            "contact_name",
            "product_type",
            "product_sku",
            "product_name",
            "inventory_status",
            "style",
            "metal",
            "stone",
            "shape",
            "budget",
            "ring_size",
            "consult_type",
            "requested_date",
            "contact_email",
            "contact_phone",
            "summary",
        } and v},
    )
    merged["conversation_id"] = conversation_id
    return merged, stage, focus


def contact_acknowledgment(old_profile: Dict[str, Any], new_profile: Dict[str, Any]) -> str:
    ack_parts = []
    if new_profile.get("contact_email") and new_profile.get("contact_email") != (old_profile or {}).get("contact_email"):
        ack_parts.append("email")
    if new_profile.get("contact_phone") and new_profile.get("contact_phone") != (old_profile or {}).get("contact_phone"):
        ack_parts.append("number")
    if not ack_parts:
        return ""
    label = " and ".join(ack_parts)
    return f"Thanks—I’ve noted your {label}."


def remove_filler_phrases(text: str) -> str:
    cleaned = text
    for phrase in FILLER_PHRASES:
        cleaned = re.sub(phrase, '', cleaned, flags=re.IGNORECASE)
    return ' '.join(cleaned.split())


def split_sentences(text: str) -> list[str]:
    return [seg.strip() for seg in re.split(r'(?<=[.!?])\s+', text.strip()) if seg.strip()]


def contains_date_reference(sentence: str) -> bool:
    return bool(DATE_REGEX.search(sentence))


def build_focus_question(focus: str, allow_schedule: bool) -> str:
    if focus == "schedule" and not allow_schedule:
        return FOCUS_QUESTIONS["timeline"]
    return FOCUS_QUESTIONS.get(focus, FOCUS_QUESTIONS["timeline"])


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": str(raw)}


def _extract_tool_call_blocks(content: str) -> list[str]:
    blocks = []
    if not content:
        return blocks
    lowered = content.lower()
    start = 0
    while True:
        idx = lowered.find("<tool_call>", start)
        if idx == -1:
            break
        after = idx + len("<tool_call>")
        end = lowered.find("</tool_call>", after)
        if end != -1:
            blocks.append(content[after:end])
            start = end + len("</tool_call>")
            continue
        next_call = lowered.find("<tool_call>", after)
        routing_start = lowered.find("<routing>", after)
        candidates = [pos for pos in (next_call, routing_start) if pos != -1]
        stop = min(candidates) if candidates else len(content)
        blocks.append(content[after:stop])
        start = stop
    return blocks


def _strip_tool_call_blocks(content: str) -> str:
    if not content:
        return ""
    cleaned = re.sub(r"<tool_call>.*?(</tool_call>|$)", "", content, flags=re.DOTALL | re.IGNORECASE)
    cleaned_lines = cleaned.strip().splitlines()
    if not cleaned_lines:
        return ""
    for idx, line in enumerate(cleaned_lines):
        if line.strip().lower().startswith("routing:"):
            cleaned_lines = cleaned_lines[:idx]
            break
    routing_keys = {"intent", "lead_capture", "urgency", "stage", "next_step", "summary"}
    trailing = []
    for line in reversed(cleaned_lines):
        key = line.split(":", 1)[0].strip().lower()
        if key in routing_keys:
            trailing.append(line)
        else:
            break
    if len(trailing) >= 2:
        cleaned_lines = cleaned_lines[: len(cleaned_lines) - len(trailing)]
    return "\n".join(cleaned_lines).strip()


def _extract_tool_call_payload(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1].strip()
    if candidate.startswith("{{") and candidate.endswith("}}"):
        candidate = candidate[1:-1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        normalized = candidate.replace("{{", "{").replace("}}", "}")
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return None


def _parse_tool_calls(message: Dict[str, Any]) -> list[Dict[str, str]]:
    tool_calls = message.get("tool_calls") or []
    if not tool_calls and message.get("function_call"):
        tool_calls = [{"id": str(uuid.uuid4()), "function": message.get("function_call", {})}]
    normalized = []
    for call in tool_calls:
        function = call.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        normalized.append(
            {
                "id": call.get("id") or str(uuid.uuid4()),
                "name": name,
                "arguments": function.get("arguments", ""),
            }
        )
    if normalized:
        return normalized

    content = message.get("content") or ""
    for match in TOOL_CALL_JSON_RE.finditer(content):
        payload = _extract_tool_call_payload(match.group(1))
        if not payload:
            continue
        name = payload.get("name")
        if not name:
            continue
        arguments = payload.get("arguments", "")
        normalized.append(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "arguments": arguments,
            }
        )
    if normalized:
        return normalized
    for block in _extract_tool_call_blocks(content):
        payload = _extract_tool_call_payload(block)
        if not payload:
            continue
        name = payload.get("name")
        if not name:
            continue
        arguments = payload.get("arguments", "")
        normalized.append(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "arguments": arguments,
            }
        )
    return normalized


def _sanitize_routing(value: Dict[str, Any]) -> Dict[str, str]:
    cleaned = {
        "intent": str(value.get("intent") or "other").strip().lower(),
        "lead_capture": str(value.get("lead_capture") or "no").strip().lower(),
        "urgency": str(value.get("urgency") or "unknown").strip().lower(),
        "next_step": str(value.get("next_step") or "ask_need").strip().lower(),
        "summary": str(value.get("summary") or "").strip(),
    }
    allowed_intents = {"buy", "book", "pricing", "question", "support", "other"}
    allowed_lead = {"yes", "no"}
    allowed_urgency = {"today", "this_week", "soon", "flexible", "unknown"}
    allowed_steps = {
        "ask_need",
        "ask_timeline",
        "ask_constraints",
        "ask_budget",
        "ask_contact",
        "ask_schedule",
        "confirm_submission",
    }
    if cleaned["intent"] not in allowed_intents:
        cleaned["intent"] = "other"
    if cleaned["lead_capture"] not in allowed_lead:
        cleaned["lead_capture"] = "no"
    if cleaned["urgency"] not in allowed_urgency:
        cleaned["urgency"] = "unknown"
    if cleaned["next_step"] not in allowed_steps:
        cleaned["next_step"] = "ask_need"
    return cleaned


def _tool_log_lead(
    args: Dict[str, Any],
    conversation_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    email = (args.get("email") or "").strip()
    phone = (args.get("phone") or "").strip()
    contact_method = (args.get("contact_method") or "").strip().lower()
    preferred_time = (args.get("preferred_time") or "").strip()
    intent = (args.get("intent") or profile.get("intent") or "other").strip()
    urgency = (args.get("urgency") or profile.get("urgency") or "unknown").strip()
    summary = (args.get("summary") or profile.get("summary") or "").strip()
    product_sku = (args.get("product_sku") or profile.get("product_sku") or "").strip()
    product_name = (args.get("product_name") or profile.get("product_name") or "").strip()
    requested_date = (args.get("requested_date") or profile.get("requested_date") or "").strip()

    if not (email or phone):
        return {"ok": False, "saved": False, "error": "missing_contact"}
    if not name:
        return {"ok": False, "saved": False, "error": "missing_name"}
    if contact_method not in {"email", "text", "call"}:
        contact_method = "text" if phone else "email"
    if storage.lead_exists(conversation_id, email, phone):
        return {"ok": True, "saved": False, "reason": "duplicate"}

    snapshot = (profile or {}).copy()
    if name:
        snapshot["contact_name"] = name
    if email:
        snapshot["contact_email"] = email
    if phone:
        snapshot["contact_phone"] = phone
    if product_sku:
        snapshot["product_sku"] = product_sku
    if product_name:
        snapshot["product_name"] = product_name
    if requested_date:
        snapshot["requested_date"] = requested_date
    if summary:
        snapshot["summary"] = summary

    profile_updates = {
        "contact_name": name or None,
        "contact_email": email or None,
        "contact_phone": phone or None,
        "product_sku": product_sku or None,
        "product_name": product_name or None,
        "requested_date": requested_date or None,
        "intent": intent or None,
        "urgency": urgency or None,
        "summary": summary or None,
    }
    merged_profile = (profile or {}).copy()
    merged_profile.update({k: v for k, v in profile_updates.items() if v})
    stage_after, _ = determine_stage_and_focus(merged_profile)
    merged_profile["stage"] = stage_after
    updated_profile = storage.upsert_profile(
        conversation_id,
        {k: v for k, v in merged_profile.items() if k in {
            "stage",
            "intent",
            "urgency",
            "contact_name",
            "product_type",
            "product_sku",
            "product_name",
            "inventory_status",
            "style",
            "metal",
            "stone",
            "shape",
            "budget",
            "ring_size",
            "consult_type",
            "requested_date",
            "contact_email",
            "contact_phone",
            "summary",
        } and v},
    )
    storage.save_lead(
        conversation_id,
        name,
        email,
        phone,
        contact_method,
        preferred_time,
        intent,
        urgency,
        summary,
        updated_profile,
    )
    if os.getenv("SHEETS_LEADS_URL"):
        try:
            requests.post(
                os.getenv("SHEETS_LEADS_URL"),
                json={
                    "conversation_id": conversation_id,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "contact_method": contact_method,
                    "preferred_time": preferred_time,
                    "intent": intent,
                    "urgency": urgency,
                    "summary": summary,
                    "profile": updated_profile,
                },
                timeout=6,
            )
        except Exception:
            pass
    sheet_id = tenant_sheet_id
    sheet_range = os.getenv("SHEETS_LEADS_RANGE", "Leads!A:J")
    if sheet_id:
        from .sheets import append_sheet_row  # lazy import

        append_sheet_row(
            sheet_id,
            sheet_range,
            [
                datetime.utcnow().isoformat(),
                name,
                email,
                phone,
                contact_method,
                preferred_time,
                intent,
                urgency,
                updated_profile.get("product_sku", ""),
                updated_profile.get("product_name", ""),
            ],
        )
    return {"ok": True, "saved": True}


def _tool_record_routing(args: Dict[str, Any]) -> Dict[str, str]:
    return _sanitize_routing(args or {})


def _run_routing_tool(
    user_message: str,
    assistant_reply: str,
    ai_client: Any,
) -> Optional[Dict[str, str]]:
    if not assistant_reply or ai_client is None or not hasattr(ai_client, "create_chat_completion"):
        return None
    messages = [
        {"role": "system", "content": ROUTING_TOOL_PROMPT},
        {
            "role": "user",
            "content": (
                "User message:\n"
                f"{user_message}\n\n"
                "Assistant reply:\n"
                f"{assistant_reply}"
            ),
        },
    ]
    try:
        result = ai_client.create_chat_completion(
            messages,
            tools=TOOL_DEFINITIONS_ROUTING,
            tool_choice={"type": "function", "function": {"name": "record_routing"}},
        )
    except Exception as exc:
        print(f"[routing_tool_error] {exc}")
        return None
    message = result["choices"][0]["message"]
    tool_calls = _parse_tool_calls(message)
    if not tool_calls:
        return None
    call = next((c for c in tool_calls if c.get("name") == "record_routing"), None)
    if not call:
        return None
    args = _safe_json_loads(call.get("arguments", ""))
    if not isinstance(args, dict):
        return None
    return _sanitize_routing(args)
    message = result["choices"][0]["message"]
    tool_calls = _parse_tool_calls(message)
    if not tool_calls:
        return None
    call = next((c for c in tool_calls if c.get("name") == "record_routing"), None)
    if not call:
        return None
    args = _safe_json_loads(call.get("arguments", ""))
    if not isinstance(args, dict):
        return None
    return _sanitize_routing(args)


def _dispatch_tool_call(
    call: Dict[str, str],
    conversation_id: str,
    profile: Dict[str, Any],
    sheet_id_override: Optional[str] = None,
) -> Dict[str, Any]:
    args = _safe_json_loads(call.get("arguments", ""))
    if not isinstance(args, dict):
        args = {"_raw": call.get("arguments", "")}
    if call["name"] == "lookup_listings":
        listings = load_listings(sheet_id_override)
        try:
            limit = int(args.get("limit") or 4)
        except (TypeError, ValueError):
            limit = 4
        filtered = search_listings(args, listings)[:limit]
        return {
            "found": bool(filtered),
            "count": len(filtered),
            "items": filtered,
        }
    if call["name"] == "log_lead":
        return _tool_log_lead(args, conversation_id, profile)
    if call["name"] == "record_routing":
        return _tool_record_routing(args)
    return {"ok": False, "error": "unknown_tool"}


def _extract_routing_from_events(tool_events: list[Dict[str, Any]]) -> Dict[str, str]:
    for event in tool_events:
        if event.get("name") == "record_routing" and isinstance(event.get("result"), dict):
            return _sanitize_routing(event["result"])
    return {}


def _last_log_lead_event(tool_events: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for event in reversed(tool_events):
        if event.get("name") == "log_lead" and isinstance(event.get("result"), dict):
            return event
    return None


def _has_log_lead_event(tool_events: list[Dict[str, Any]]) -> bool:
    return _last_log_lead_event(tool_events) is not None


def _run_with_tools(
    messages: list[Dict[str, Any]],
    conversation_id: str,
    profile: Dict[str, Any],
    extracted_fields: Dict[str, str],
    tools: list[Dict[str, Any]],
    tool_choice: str = "auto",
    ai_client: Any = None,
    sheet_id_override: Optional[str] = None,
) -> Tuple[str, list[Dict[str, Any]]]:
    if ai_client is None or not hasattr(ai_client, "create_chat_completion"):
        return "", []
    tool_messages = list(messages)
    tool_events: list[Dict[str, Any]] = []
    raw_text = ""
    last_text = ""
    for _ in range(3):
        result = ai_client.create_chat_completion(
            tool_messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        message = result["choices"][0]["message"]
        raw_text = _strip_tool_call_blocks(message.get("content") or "")
        tool_calls = _parse_tool_calls(message)
        if not tool_calls:
            if raw_text:
                return raw_text, tool_events
            if last_text:
                return last_text, tool_events
            return raw_text, tool_events
        if raw_text:
            last_text = raw_text

        assistant_content = _strip_tool_call_blocks(message.get("content") or "")
        tool_messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                    for call in tool_calls
                ],
            }
        )
        for call in tool_calls:
            tool_result = _dispatch_tool_call(call, conversation_id, profile, sheet_id_override)
            tool_events.append(
                {
                    "name": call["name"],
                    "arguments": call["arguments"],
                    "result": tool_result,
                }
            )
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(tool_result),
                }
            )
    return raw_text, tool_events


def _append_routing_event(
    tool_events: list[Dict[str, Any]],
    routing: Optional[Dict[str, str]],
) -> None:
    if not routing:
        return
    tool_events.append(
        {
            "name": "record_routing",
            "arguments": routing,
            "result": routing,
        }
    )


def post_process_reply(
    text: str,
    stage: str,
    focus: str,
    allow_schedule: bool,
    contact_ack: str,
) -> str:
    response = text.strip()
    if contact_ack:
        response = f"{contact_ack} {response}".strip()
    # Enforce at most one question per turn.
    question_marks = [pos for pos, ch in enumerate(response) if ch == "?"]
    if len(question_marks) > 1:
        cutoff = question_marks[0] + 1
        response = response[:cutoff].strip()
    return response


@app.get("/api/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    print("AI Receptionist API v1.3")
    return HTMLResponse("<html><body><h3>AI Receptionist API v1.3 is running.</h3></body></html>")


@app.head("/")
def root_head() -> Response:
    print("AI Receptionist API v1.3 (HEAD)")
    return Response(status_code=200)


@app.get("/favicon.ico", status_code=204)
def favicon() -> None:
    return None


@app.get("/api/listings")
def listings_endpoint() -> Dict[str, Any]:
    return {"data": load_listings()}


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    runtime_cfg = _get_runtime_config(payload.sheet_id)
    sheet_id = runtime_cfg.get("sheet_id")
    print(f"[chat] sheet_id={sheet_id or 'none'}")
    system_prompt = load_system_prompt(sheet_id)
    ai_client = build_ai_client(
        AI_PROVIDER,
        model_name=runtime_cfg.get("model", MODEL_NAME),
        api_key_override=runtime_cfg.get("api_key"),
    )

    conversation_id = payload.conversation_id or str(uuid.uuid4())
    storage.ensure_conversation(conversation_id)

    history = storage.get_messages(conversation_id, limit=30)
    assistant_turns = len([msg for msg in history if msg["role"] == "assistant"])

    existing_profile = storage.get_profile(conversation_id)
    stage_before, focus_before = determine_stage_and_focus(existing_profile)
    extracted_fields = extract_profile_fields(payload.message)
    allow_schedule = should_offer_schedule(stage_before, payload.message, extracted_fields, existing_profile or {})
    user_content = payload.message

    profile_prompt = build_profile_prompt(existing_profile or {}, stage_before, focus_before)
    use_tools = AI_PROVIDER in {"openai", "cloud"}
    site_context = build_site_context(sheet_id_override=sheet_id)
    llm_messages = (
        [{"role": "system", "content": system_prompt}]
        + ([{"role": "system", "content": TOOLING_PROMPT}] if use_tools and TOOLING_PROMPT.strip() else [])
        + ([{"role": "system", "content": site_context}] if site_context else [])
        + [{"role": "system", "content": profile_prompt}]
        + history
        + [{"role": "user", "content": user_content}]
    )

    print("\n=== DEBUG: LLM MESSAGES SENT ===")
    print(json.dumps(llm_messages, indent=2))
    print("================================\n")

    try:
        if use_tools:
            raw_text, tool_events = _run_with_tools(
                llm_messages,
                conversation_id,
                existing_profile or {},
                extracted_fields,
                TOOL_DEFINITIONS_PRIMARY + TOOL_DEFINITIONS_ROUTING,
                "auto",
                ai_client,
                sheet_id,
            )
        else:
            raw_text = ai_client.generate(llm_messages)  # type: ignore[union-attr]
            tool_events = []
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - runtime guard
        import traceback

        print("[chat_error]", exc)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI provider error: {exc}") from exc

    print("\n=== DEBUG: LLM RAW OUTPUT ===")
    print(raw_text)
    print("=============================\n")
    if tool_events:
        print("=== DEBUG: TOOL CALLS ===")
        print(json.dumps(tool_events, indent=2))
        print("=========================\n")

    storage.log_message(conversation_id, "user", payload.message)

    ai_result: AIResult = parse_response(raw_text)
    tool_routing = _extract_routing_from_events(tool_events)
    if use_tools and not tool_routing:
        routing_result = _run_routing_tool(payload.message, ai_result.text, ai_client)
        tool_routing = routing_result or {}
        _append_routing_event(tool_events, tool_routing or None)
    base_routing = tool_routing or ai_result.routing
    routing = enforce_guardrails(payload.message, base_routing, assistant_turns)
    profile, stage_after, focus_after = update_conversation_profile(
        conversation_id,
        extracted_fields,
        routing,
    )
    routing["stage"] = stage_after
    contact_ack = contact_acknowledgment(existing_profile, profile)
    clean_reply = post_process_reply(ai_result.text, stage_after, focus_after, allow_schedule, contact_ack)
    lead_event = _last_log_lead_event(tool_events)
    lead_captured = False
    if lead_event:
        lead_result = lead_event.get("result") or {}
        if lead_result.get("ok") is False:
            error = lead_result.get("error")
            if error == "missing_name":
                clean_reply = "Thanks—what’s the best full name to put on the order?"
                routing["next_step"] = "ask_contact"
                routing["lead_capture"] = "yes"
            elif error == "missing_contact":
                clean_reply = "Thanks—what’s the best email or phone number to confirm this?"
                routing["next_step"] = "ask_contact"
                routing["lead_capture"] = "yes"
        else:
            lead_captured = True
            if not clean_reply:
                args = lead_event.get("arguments") or {}
                c_name = args.get("name") or "there"
                c_contact = args.get("phone") or args.get("email") or "your contact info"
                clean_reply = f"Thanks {c_name}. We'll contact you at {c_contact}. We look forward to seeing you soon!"

    storage.log_message(conversation_id, "assistant", clean_reply, routing=routing)

    return ChatResponse(
        reply=clean_reply,
        routing=routing,
        conversation_id=conversation_id,
        profile=profile,
        lead_captured=lead_captured,
    )


@app.post("/api/lead", response_model=LeadResponse)
def lead_endpoint(payload: LeadRequest) -> LeadResponse:
    runtime_cfg = _get_runtime_config(payload.sheet_id)
    tenant_sheet_id = runtime_cfg.get("sheet_id")
    print(f"[lead] sheet_id={tenant_sheet_id or 'none'}")
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    storage.ensure_conversation(conversation_id)
    profile = storage.get_profile(conversation_id) or {}
    profile_updates = {
        "contact_name": payload.name.strip() if payload.name else None,
        "contact_email": payload.email.strip() if payload.email else None,
        "contact_phone": payload.phone.strip() if payload.phone else None,
        "intent": payload.intent.strip(),
        "urgency": (payload.urgency or "unknown").strip(),
        "summary": payload.summary.strip(),
    }
    merged_profile = profile.copy()
    merged_profile.update({k: v for k, v in profile_updates.items() if v})
    stage_after, _ = determine_stage_and_focus(merged_profile)
    merged_profile["stage"] = stage_after
    updated_profile = storage.upsert_profile(
        conversation_id,
        {k: v for k, v in merged_profile.items() if k in {
            "stage",
            "intent",
            "urgency",
            "contact_name",
            "product_type",
            "product_sku",
            "product_name",
            "inventory_status",
            "style",
            "metal",
            "stone",
            "shape",
            "budget",
            "ring_size",
            "consult_type",
            "requested_date",
            "contact_email",
            "contact_phone",
            "summary",
        } and v},
    )
    storage.save_lead(
        conversation_id,
        payload.name.strip(),
        payload.email.strip(),
        payload.phone.strip(),
        (payload.contact_method or ("text" if payload.phone else "email")).strip(),
        (payload.preferred_time or "").strip(),
        payload.intent.strip(),
        (payload.urgency or "unknown").strip(),
        payload.summary.strip(),
        updated_profile,
    )
    # Optional webhook/Sheet append
    if os.getenv("SHEETS_LEADS_URL"):
        try:
            requests.post(
                os.getenv("SHEETS_LEADS_URL"),
                json={
                    "conversation_id": conversation_id,
                    "name": payload.name,
                    "email": payload.email,
                    "phone": payload.phone,
                    "contact_method": payload.contact_method,
                    "preferred_time": payload.preferred_time,
                    "intent": payload.intent,
                    "urgency": payload.urgency,
                    "summary": payload.summary,
                    "profile": updated_profile,
                },
                timeout=6,
            )
        except Exception:
            pass
    sheet_id = os.getenv("SHEETS_SPREADSHEET_ID")
    sheet_range = os.getenv("SHEETS_LEADS_RANGE", "Leads!A:J")
    if sheet_id:
        from .sheets import append_sheet_row  # lazy import

        append_sheet_row(
            sheet_id,
            sheet_range,
            [
                datetime.utcnow().isoformat(),
                payload.name,
                payload.email,
                payload.phone,
                payload.contact_method,
                payload.preferred_time,
                payload.intent,
                payload.urgency,
                updated_profile.get("product_sku", ""),
                updated_profile.get("product_name", ""),
            ],
        )
    return LeadResponse(ok=True)


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    leads = storage.list_leads()
    rows = ""
    for lead in leads:
        profile_snapshot = json.loads(lead.get('profile_json') or '{}')
        rows += (
            f"<tr><td>{lead['created_at']}</td><td>{lead['name']}</td><td>{lead['email']}</td>"
            f"<td>{lead['phone']}</td><td>{lead['intent']}</td><td>{lead['urgency']}</td>"
            f"<td>{profile_snapshot.get('product_name', '—')}</td>"
            f"<td>{profile_snapshot.get('product_sku', '—')}</td>"
            f"<td>{profile_snapshot.get('inventory_status', '—')}</td>"
            f"<td>{profile_snapshot.get('style', '—')}</td>"
            f"<td>{profile_snapshot.get('metal', '—')}</td>"
            f"<td>{profile_snapshot.get('requested_date', '—')}</td>"
            f"<td>{profile_snapshot.get('ring_size', '—')}</td>"
            f"<td>{lead['contact_method']}</td><td>{lead['preferred_time']}</td>"
            f"<td>{lead['summary']}</td><td>{lead['conversation_id']}</td></tr>"
        )
    html = f"""
    <html>
        <head>
            <title>Demo Leads</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 2rem; background: #f7f7f9; }}
                table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 10px 30px rgba(0,0,0,0.05); }}
                th, td {{ padding: 0.75rem; border-bottom: 1px solid #eee; text-align: left; font-size: 0.9rem; }}
                th {{ background: #0f172a; color: #fff; position: sticky; top: 0; }}
                tr:hover {{ background: #f0f4ff; }}
            </style>
        </head>
        <body>
            <h1>Captured Leads</h1>
            <p>Total: {len(leads)} · <a href="/admin/profiles">View conversation profiles</a></p>
            <table>
                <thead>
                    <tr>
                        <th>Created</th>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Phone</th>
                        <th>Intent</th>
                        <th>Urgency</th>
                        <th>Product</th>
                        <th>SKU</th>
                        <th>Inventory</th>
                        <th>Style</th>
                        <th>Metal</th>
                        <th>Requested date</th>
                        <th>Ring size</th>
                        <th>Pref. Contact</th>
                        <th>Preferred Time</th>
                        <th>Summary</th>
                        <th>Conversation</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else '<tr><td colspan="14">No leads yet.</td></tr>'}
                </tbody>
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/admin/profiles", response_class=HTMLResponse)
def admin_profiles() -> HTMLResponse:
    profiles = storage.list_profiles()
    rows = "".join(
        f"<tr><td>{p['updated_at']}</td><td>{p['conversation_id']}</td>"
        f"<td>{p.get('intent','')}</td><td>{p.get('urgency','')}</td>"
        f"<td>{p.get('product_type','')}</td><td>{p.get('product_sku','')}</td>"
        f"<td>{p.get('inventory_status','')}</td>"
        f"<td>{p.get('style','')}</td>"
        f"<td>{p.get('metal','')}</td><td>{p.get('shape','')}</td>"
        f"<td>{p.get('requested_date','')}</td><td>{p.get('ring_size','')}</td>"
        f"<td>{p.get('contact_email','')}</td><td>{p.get('contact_phone','')}</td>"
        f"<td>{p.get('summary','')}</td></tr>"
        for p in profiles
    )
    html = f"""
    <html>
        <head>
            <title>Conversation Profiles</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 2rem; background: #f7f7f9; }}
                table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 10px 30px rgba(0,0,0,0.05); }}
                th, td {{ padding: 0.75rem; border-bottom: 1px solid #eee; text-align: left; font-size: 0.9rem; }}
                th {{ background: #0f172a; color: #fff; position: sticky; top: 0; }}
                tr:hover {{ background: #f0f4ff; }}
            </style>
        </head>
        <body>
            <h1>Conversation Profiles</h1>
            <p>Total tracked: {len(profiles)} · <a href="/admin">Back to leads</a></p>
            <table>
                <thead>
                    <tr>
                        <th>Updated</th>
                        <th>Conversation</th>
                        <th>Intent</th>
                        <th>Urgency</th>
                        <th>Product</th>
                        <th>SKU</th>
                        <th>Inventory</th>
                        <th>Style</th>
                        <th>Metal</th>
                        <th>Shape</th>
                        <th>Requested date</th>
                        <th>Ring size</th>
                        <th>Email</th>
                        <th>Phone</th>
                        <th>Summary</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else '<tr><td colspan="13">No profiles yet.</td></tr>'}
                </tbody>
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=html)
