from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency when using fake mode only
    OpenAI = None  # type: ignore


ROUTING_DEFAULT = {
    "intent": "other",
    "lead_capture": "no",
    "next_step": "ask_need",
    "summary": "",
    "urgency": "unknown",
    "stage": "discover",
}


@dataclass
class AIResult:
    text: str
    routing: Dict[str, str]


class BaseAIClient:
    def generate(self, messages: List[Dict[str, str]]) -> str:  # pragma: no cover - interface only
        raise NotImplementedError
    def create_chat_completion(  # pragma: no cover - interface only
        self,
        messages: List[Dict[str, str]],
        tools=None,
        tool_choice: str | None = None,
    ):
        raise NotImplementedError


class OpenAIClient(BaseAIClient):
    def __init__(self, api_key: str, model: str) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package not installed. Install it to use OpenAI provider.")
        self.model = model
        # create per-tenant client instance
        self.client = OpenAI(api_key=api_key)

    @staticmethod
    def _content_to_text(content) -> str:
        """Coalesce OpenAI message content (str or list of parts) into plain text."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        parts: List[str] = []
        for part in content:
            # new SDK uses typed objects; fall back to dict access
            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")
            if text:
                parts.append(text)
        return "".join(parts)

    @staticmethod
    def _message_to_dict(message) -> Dict[str, any]:
        """Normalize OpenAI ChatCompletionMessage to the legacy dict shape expected elsewhere."""
        content_text = OpenAIClient._content_to_text(message.content).strip()
        tool_calls = []
        for tc in message.tool_calls or []:
            func = tc.function
            tool_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": getattr(func, "name", "") or (func.get("name") if isinstance(func, dict) else ""),
                        "arguments": getattr(func, "arguments", "") or (func.get("arguments") if isinstance(func, dict) else ""),
                    },
                }
            )
        return {"role": message.role, "content": content_text, "tool_calls": tool_calls}

    def generate(self, messages: List[Dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return self._content_to_text(response.choices[0].message.content).strip()

    def create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools=None,
        tool_choice: str | None = None,
    ):
        params = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        resp = self.client.chat.completions.create(**params)
        # Return a minimal legacy-compatible dict
        return {"choices": [{"message": self._message_to_dict(resp.choices[0].message)}]}


class FakeAIClient(BaseAIClient):
    """Rule-based stand-in for demos when no API key is set."""

    GENERIC_REPLIES = [
        "Thanks for reaching out! I can help explain our services or get you in touch with the right person.",
        "Happy to help. This line is just a placeholder while we gather your info for the team.",
        "Great question. I can collect a few details and have someone follow up shortly.",
    ]

    def generate(self, messages: List[Dict[str, str]]) -> str:
        user_message = messages[-1]["content"].lower()
        assistant_turns = len([m for m in messages if m["role"] == "assistant"])
        intent = "question"
        lead_capture = "no"
        next_step = "ask_need"
        summary = "Visitor has a general question."
        urgency = derive_urgency(messages[-1]["content"])

        if any(keyword in user_message for keyword in ("book", "appointment")):
            intent = "book"
            lead_capture = "yes"
            next_step = "ask_contact"
            summary = "Interested in booking."
            reply = "I can help reserve a spot. Let me grab a couple of quick details so the team can schedule you."
        elif any(keyword in user_message for keyword in ("price", "cost", "quote")):
            intent = "pricing"
            lead_capture = "yes"
            next_step = "ask_contact"
            summary = "Asking about pricing."
            reply = "Pricing depends on the package. I can pass this to the specialists—could you share the best contact info?"
        else:
            reply = random.choice(self.GENERIC_REPLIES)
            if assistant_turns >= 2:
                lead_capture = "yes"
                next_step = "ask_contact"
                summary = "Need more details from visitor."

        stage = "contact" if lead_capture == "yes" else "discover"
        routing_block = _format_routing_block(
            intent=intent,
            lead_capture=lead_capture,
            next_step=next_step,
            urgency=urgency,
            stage=stage,
            summary=summary,
        )
        return f"{reply}\n\n{routing_block}"


def _format_routing_block(
    intent: str,
    lead_capture: str,
    next_step: str,
    urgency: str,
    stage: str,
    summary: str,
) -> str:
    return (
        "<ROUTING>\n"
        f"intent: {intent}\n"
        f"lead_capture: {lead_capture}\n"
        f"urgency: {urgency}\n"
        f"stage: {stage}\n"
        f"next_step: {next_step}\n"
        f"summary: {summary}\n"
        "</ROUTING>"
    )


def parse_response(text: str) -> AIResult:
    """Split assistant text from the routing instructions block."""
    routing = ROUTING_DEFAULT.copy()
    pattern = re.compile(r"<ROUTING>(.*?)</ROUTING>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if match:
        routing_section = match.group(1)
        routing.update(_parse_routing_lines(routing_section))
        clean_text = (text[: match.start()] + text[match.end() :]).strip()
    else:
        clean_text = text.strip()
    clean_text = _strip_tool_call_artifacts(clean_text)
    # Normalize
    routing = {k: str(v).strip() for k, v in routing.items()}
    routing.setdefault("intent", "other")
    routing.setdefault("lead_capture", "no")
    routing.setdefault("next_step", "ask_need")
    routing.setdefault("stage", "discover")
    routing.setdefault("summary", "")
    routing.setdefault("urgency", "unknown")
    routing["lead_capture"] = routing["lead_capture"].lower()
    routing["intent"] = routing["intent"].lower()
    routing["next_step"] = routing["next_step"].lower()
    routing["urgency"] = routing["urgency"].lower()
    routing["stage"] = routing["stage"].lower()
    return AIResult(text=clean_text, routing=routing)


def _parse_routing_lines(block: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()
    return parsed


TOOL_CALL_STRIPPER = re.compile(r"<tool_call[^>]*>.*?(</tool_call>|$)", re.DOTALL | re.IGNORECASE)
LEAD_TERMS = [
    "buy",
    "purchase",
    "pickup",
    "pick up",
    "appointment",
    "book",
    "visit",
    "price",
    "budget",
    "quote",
]
HIGH_URGENCY_TERMS = {
    "today": "today",
    "tonight": "today",
    "asap": "today",
    "this week": "this_week",
    "next week": "this_week",
    "tomorrow": "this_week",
    "soon": "soon",
}


def _strip_tool_call_artifacts(text: str) -> str:
    if "<tool_call" not in text.lower():
        return text
    cleaned = TOOL_CALL_STRIPPER.sub("", text)
    if "<tool_call" in cleaned.lower():
        cleaned = cleaned.split("<tool_call", 1)[0]
    return cleaned.strip()


def derive_urgency(message: str) -> str:
    lowered = message.lower()
    for term, label in HIGH_URGENCY_TERMS.items():
        if term in lowered:
            return label
    if "week" in lowered or "2 weeks" in lowered:
        return "this_week"
    if "month" in lowered:
        return "soon"
    return "unknown"


def enforce_guardrails(
    user_message: str,
    routing: Dict[str, str],
    assistant_turns: int,
) -> Dict[str, str]:
    """Ensure lead capture prompts fire on critical phrases or after two replies."""
    text = user_message.lower()
    updated = routing.copy()

    updated["urgency"] = derive_urgency(user_message)

    if "no budget" in text or "whatever it costs" in text:
        updated["intent"] = "buy"
        updated["lead_capture"] = "yes"
        updated["summary"] = "Premium lead with no budget limit"
        updated["next_step"] = "ask_contact"
    elif any(term in text for term in LEAD_TERMS):
        if "price" in text or "budget" in text or "quote" in text:
            updated["intent"] = "pricing"
        elif "book" in text or "appointment" in text or "visit" in text:
            updated["intent"] = "book"
        else:
            updated["intent"] = "buy"
        updated["lead_capture"] = "yes"
        updated.setdefault("summary", "High intent inquiry")
        updated["next_step"] = "ask_contact"
    elif assistant_turns >= 2 and updated.get("lead_capture", "no") != "yes":
        updated["lead_capture"] = "yes"
        updated.setdefault("summary", "Continuing conversation, prompting for contact info")
        updated["next_step"] = "ask_contact"

    return updated


def build_ai_client(provider: str, model_name: str | None = None, api_key_override: str | None = None) -> BaseAIClient:
    provider = provider.lower()
    if provider in {"cloud", "openai"}:
        api_key = api_key_override or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for AI_PROVIDER=openai")
        model = model_name or os.getenv("MODEL_NAME", "gpt-5-mini")
        return OpenAIClient(api_key=api_key, model=model)
    return FakeAIClient()
