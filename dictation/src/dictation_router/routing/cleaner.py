from __future__ import annotations

import re


def clean_transcript(text: str) -> str:
    """Simple local cleanup: capitalization, punctuation, duplicate words."""
    text = text.strip()
    if not text:
        return text

    text = re.sub(r"\s+", " ", text)
    text = _remove_duplicate_words(text)
    text = _fix_punctuation(text)
    text = _fix_capitalization(text)
    return text.strip()


def _remove_duplicate_words(text: str) -> str:
    words = text.split(" ")
    if len(words) < 2:
        return text

    result = [words[0]]
    for word in words[1:]:
        if word.lower() != result[-1].lower():
            result.append(word)
    return " ".join(result)


def _fix_punctuation(text: str) -> str:
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])([^\s])", r"\1 \2", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _fix_capitalization(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s.capitalize() if s else s for s in sentences)
