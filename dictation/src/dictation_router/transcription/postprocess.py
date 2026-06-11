from __future__ import annotations

import re


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
