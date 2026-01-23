from __future__ import annotations

import re
from datetime import datetime
from typing import Dict

CONSULT_TYPES = {
    "virtual": "virtual",
    "video": "virtual",
    "in person": "in-person",
    "showroom": "in-person",
}
ISO_DATE_PATTERN = re.compile(r"(202[5-9]|203\d)-\d{2}-\d{2}")
MONTH_DAY_PATTERN = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{1,2})", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\s]{7,}\d)")
NAME_PATTERNS = [
    re.compile(r"\bmy name is ([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
    re.compile(r"\bname is ([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
    re.compile(r"\bnames ([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
    re.compile(r"\bi am ([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
    re.compile(r"\bi'm ([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
    re.compile(r"\bname[: ]+([A-Za-z][A-Za-z' -]{1,40})", re.IGNORECASE),
]
NAME_STOP_WORDS = {"phone", "number", "email", "call", "text", "at"}

AGENT_YES_PATTERNS = [re.compile(r"\b(have|working with|got) an agent\b", re.IGNORECASE), re.compile(r"\byes\b.*agent", re.IGNORECASE)]
AGENT_NO_PATTERNS = [re.compile(r"\b(no|dont|don't) have.*agent\b", re.IGNORECASE), re.compile(r"\bno agent\b", re.IGNORECASE), re.compile(r"\bnot working with.*agent", re.IGNORECASE)]

PRE_APPROVAL_YES_PATTERNS = [re.compile(r"\b(have|got).*(pre-?approv|letter)\b", re.IGNORECASE), re.compile(r"\bpre-?approved\b", re.IGNORECASE)]
PRE_APPROVAL_NO_PATTERNS = [re.compile(r"\b(no|dont|don't) have.*(pre-?approv|letter)\b", re.IGNORECASE), re.compile(r"\bnot.*pre-?approved\b", re.IGNORECASE)]


def extract_profile_fields(message: str) -> Dict[str, str]:
    lowered = message.lower()
    profile: Dict[str, str] = {}

    # Agent Status
    for p in AGENT_YES_PATTERNS:
        if p.search(message):
            profile["agent_status"] = "yes"
            break
    if "agent_status" not in profile:
        for p in AGENT_NO_PATTERNS:
            if p.search(message):
                profile["agent_status"] = "no"
                break

    # Pre-approval Status
    for p in PRE_APPROVAL_YES_PATTERNS:
        if p.search(message):
            profile["pre_approval"] = "yes"
            break
    if "pre_approval" not in profile:
        for p in PRE_APPROVAL_NO_PATTERNS:
            if p.search(message):
                profile["pre_approval"] = "no"
                break

    for pattern in NAME_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        raw_name = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
        if raw_name:
            parts = []
            for part in raw_name.split():
                if part.lower() in NAME_STOP_WORDS:
                    break
                parts.append(part)
            clean_name = " ".join(parts).strip()
            if clean_name:
                profile.setdefault("contact_name", clean_name)
                break

    for keyword, ctype in CONSULT_TYPES.items():
        if keyword in lowered:
            profile.setdefault("consult_type", ctype)

    iso_match = ISO_DATE_PATTERN.search(message)
    if iso_match:
        profile.setdefault("requested_date", iso_match.group(0))
    else:
        month_match = MONTH_DAY_PATTERN.search(message)
        if month_match:
            month_str, day_str = month_match.groups()
            try:
                parsed = datetime.strptime(f"{month_str} {day_str} 2026", "%b %d %Y")
                profile.setdefault("requested_date", parsed.strftime("%Y-%m-%d"))
            except ValueError:
                pass

    email_match = EMAIL_PATTERN.search(message)
    if email_match:
        profile.setdefault("contact_email", email_match.group(0))

    phone_match = PHONE_PATTERN.search(message)
    if phone_match:
        profile.setdefault("contact_phone", phone_match.group(1))

    if not profile.get("contact_name") and (email_match or phone_match):
        contact_start = None
        if email_match:
            contact_start = email_match.start()
        if phone_match:
            contact_start = phone_match.start() if contact_start is None else min(contact_start, phone_match.start())
        if contact_start:
            prefix = message[:contact_start].strip().strip(",;:-")
            if "," in prefix:
                prefix = prefix.split(",")[-1].strip()
            tokens = [t for t in re.split(r"\s+", prefix) if t]
            if tokens:
                candidate = " ".join(tokens[-3:]).strip(" .,:;")
                if candidate and all(part.isalpha() for part in candidate.split()):
                    if candidate.lower() not in NAME_STOP_WORDS:
                        profile.setdefault("contact_name", candidate)

    return profile
