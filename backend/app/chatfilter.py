"""Keep only scientist-facing chat. Drop prompts, tags, and sandbox instructions."""

from __future__ import annotations

import re

from backend.app.models import Message, Speaker

INTERNAL_MARKERS = (
    "you are devin running this investigation",
    "stay in this same devin",
    "do not run science on the operator",
    "do not move work to",
    "do not ask them to install",
    "operator follow-up:",
    "operator objective",
    "prefix your reply",
    "prefix turns with",
    "playbooks/protein_engineering",
    "playbooks/protein-engineering",
    "follow playbook protein-engineering",
    "follow playbooks/",
    "the laptop is only a control",
    "importing artifacts from",
    "science is running in a devin",
    "working in the sandbox",
    "restoring results from the sandbox",
    "attachment download failed",
    "sandbox job failed",
    "prefer the orchestration",
    "when the command finishes, attach",
    "--- playbooks/",
    "internal operating instructions",
    "internal note, not for chat",
    "chat rules for every reply",
)

TAG = re.compile(r"^\[(?:planner|search|structure|design|reviewer|system)\]\s*", re.I)
ATTACHMENT = re.compile(r"ATTACHMENT:\{[\s\S]*?\}")
ATTACHMENT_URL = re.compile(r"https://(?:app|api)\.devin\.ai/attachments/\S+")


def clean_body(text: str) -> str:
    body = ATTACHMENT.sub("", text)
    body = ATTACHMENT_URL.sub("", body)
    body = TAG.sub("", body.strip())
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def is_internal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in INTERNAL_MARKERS)


def visible_messages(messages: list[Message]) -> list[Message]:
    visible: list[Message] = []
    for message in messages:
        if message.speaker == Speaker.system:
            continue
        body = clean_body(message.body)
        if not body or is_internal(body) or is_internal(message.body):
            continue
        visible.append(message.model_copy(update={"body": body, "artifact_ids": []}))
    return visible
