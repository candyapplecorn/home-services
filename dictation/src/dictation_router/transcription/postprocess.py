from __future__ import annotations

import re


def normalize_transcript_newlines(text: str) -> str:
    """Join Whisper's accidental hard-wrapped prose lines without flattening paragraphs."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").strip()
    if not cleaned:
        return cleaned

    paragraphs = re.split(r"\n[ \t]*\n+", cleaned)
    normalized = [_normalize_paragraph_newlines(paragraph) for paragraph in paragraphs]
    return "\n\n".join(paragraph for paragraph in normalized if paragraph).strip()


def _normalize_paragraph_newlines(paragraph: str) -> str:
    lines = [line.strip() for line in paragraph.split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    if _looks_structured(lines):
        return "\n".join(lines)

    joined = " ".join(lines)
    return re.sub(r"[ \t]{2,}", " ", joined).strip()


def _looks_structured(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False

    structured = 0
    for line in lines:
        if re.match(r"^(```|~~~)", line):
            return True
        if re.match(r"^#{1,6}\s+\S", line):
            structured += 1
        elif re.match(r"^([-*+•]|\d+[.)])\s+\S", line):
            structured += 1
        elif re.match(r"^\S[^:]{0,40}:\s*$", line):
            structured += 1

    return structured >= 2


def strip_edge_hallucinations(text: str, hallucinations: list[str]) -> tuple[str, list[str]]:
    """Remove configured hallucination tokens at transcript edges."""
    cleaned = text.strip()
    removed: list[str] = []
    if not cleaned or not hallucinations:
        return cleaned, removed

    token_pattern = "|".join(re.escape(token) for token in hallucinations if token)
    if not token_pattern:
        return cleaned, removed

    if re.fullmatch(token_pattern, cleaned, re.IGNORECASE):
        return "", [cleaned]

    leading = re.compile(rf"^({token_pattern})(?:[\s,.;:!?-]+)(.+)$", re.IGNORECASE | re.DOTALL)
    trailing = re.compile(rf"^(.+?)(?:[\s,.;:!?-]+)({token_pattern})[\s,.;:!?-]*$", re.IGNORECASE | re.DOTALL)

    while True:
        match = leading.match(cleaned)
        if not match:
            break
        removed.append(match.group(1))
        cleaned = match.group(2).strip()

    while True:
        match = trailing.match(cleaned)
        if not match:
            break
        removed.append(match.group(2))
        cleaned = match.group(1).strip()

    glued_suffix = re.compile(rf"^(.{{4,}})({token_pattern})$", re.IGNORECASE | re.DOTALL)
    while True:
        match = glued_suffix.match(cleaned)
        if not match:
            break
        stem = match.group(1)
        suffix = match.group(2)
        if not stem[-1].isalpha():
            break
        removed.append(suffix)
        cleaned = stem.strip()

    return cleaned, removed
