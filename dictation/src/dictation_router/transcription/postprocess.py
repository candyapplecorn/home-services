from __future__ import annotations

import re
from collections.abc import Mapping

OPEN_DOUBLE_QUOTE = "\uE000OPEN_DOUBLE_QUOTE\uE000"
CLOSE_DOUBLE_QUOTE = "\uE000CLOSE_DOUBLE_QUOTE\uE000"
OPEN_SINGLE_QUOTE = "\uE000OPEN_SINGLE_QUOTE\uE000"
CLOSE_SINGLE_QUOTE = "\uE000CLOSE_SINGLE_QUOTE\uE000"

DEFAULT_SPOKEN_PUNCTUATION: tuple[tuple[str, str], ...] = (
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("newline", "\n"),
    ("line break", "\n"),
    ("three periods", "..."),
    ("three dots", "..."),
    ("triple dot", "..."),
    ("triple dots", "..."),
    ("ellipsis", "..."),
    ("ellipses", "..."),
    ("ellipse", "..."),
    ("elipses", "..."),
    ("dot dot dot", "..."),
    ("period", "."),
    ("full stop", "."),
    ("comma", ","),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("exclamation", "!"),
    ("semicolon", ";"),
    ("semi colon", ";"),
    ("colon", ":"),
    ("open parenthesis", "("),
    ("opening parenthesis", "("),
    ("left parenthesis", "("),
    ("left parentheses", "("),
    ("open parentheses", "("),
    ("close parenthesis", ")"),
    ("closing parenthesis", ")"),
    ("right parenthesis", ")"),
    ("right parentheses", ")"),
    ("close parentheses", ")"),
    ("open bracket", "["),
    ("opening bracket", "["),
    ("left bracket", "["),
    ("open square bracket", "["),
    ("left square bracket", "["),
    ("close bracket", "]"),
    ("closing bracket", "]"),
    ("right bracket", "]"),
    ("close square bracket", "]"),
    ("right square bracket", "]"),
    ("open brace", "{"),
    ("opening brace", "{"),
    ("left brace", "{"),
    ("open curly brace", "{"),
    ("left curly brace", "{"),
    ("close brace", "}"),
    ("closing brace", "}"),
    ("right brace", "}"),
    ("close curly brace", "}"),
    ("right curly brace", "}"),
    ("open angle bracket", "<"),
    ("left angle bracket", "<"),
    ("less than sign", "<"),
    ("close angle bracket", ">"),
    ("right angle bracket", ">"),
    ("greater than sign", ">"),
    ("open double quote", OPEN_DOUBLE_QUOTE),
    ("opening double quote", OPEN_DOUBLE_QUOTE),
    ("left double quote", OPEN_DOUBLE_QUOTE),
    ("close double quote", CLOSE_DOUBLE_QUOTE),
    ("closing double quote", CLOSE_DOUBLE_QUOTE),
    ("right double quote", CLOSE_DOUBLE_QUOTE),
    ("end double quote", CLOSE_DOUBLE_QUOTE),
    ("open quote", OPEN_DOUBLE_QUOTE),
    ("opening quote", OPEN_DOUBLE_QUOTE),
    ("left quote", OPEN_DOUBLE_QUOTE),
    ("close quote", CLOSE_DOUBLE_QUOTE),
    ("closing quote", CLOSE_DOUBLE_QUOTE),
    ("right quote", CLOSE_DOUBLE_QUOTE),
    ("end quote", CLOSE_DOUBLE_QUOTE),
    ("open single quote", OPEN_SINGLE_QUOTE),
    ("opening single quote", OPEN_SINGLE_QUOTE),
    ("left single quote", OPEN_SINGLE_QUOTE),
    ("close single quote", CLOSE_SINGLE_QUOTE),
    ("closing single quote", CLOSE_SINGLE_QUOTE),
    ("right single quote", CLOSE_SINGLE_QUOTE),
    ("end single quote", CLOSE_SINGLE_QUOTE),
    ("single quote", "'"),
    ("apostrophe", "'"),
    ("double quote", '"'),
    ("quote", OPEN_DOUBLE_QUOTE),
    ("backslash", "\\"),
    ("back slash", "\\"),
    ("forward slash", "/"),
    ("slash", "/"),
    ("hyphen", "-"),
    ("dash", "-"),
    ("minus sign", "-"),
    ("minus", "-"),
    ("subtract", "-"),
    ("plus sign", "+"),
    ("plus", "+"),
    ("multiply sign", "*"),
    ("multiplication sign", "*"),
    ("multiply", "*"),
    ("asterisk", "*"),
    ("star symbol", "*"),
    ("star sign", "*"),
    ("open star", "*"),
    ("equals sign", "="),
    ("equal sign", "="),
    ("equals", "="),
    ("underscore", "_"),
    ("under score", "_"),
    ("hash sign", "#"),
    ("pound sign", "#"),
    ("number sign", "#"),
    ("hash", "#"),
    ("hashtag", "#"),
    ("at sign", "@"),
    ("ampersand", "&"),
    ("and sign", "&"),
    ("percent sign", "%"),
    ("percentage sign", "%"),
    ("percent", "%"),
    ("percentage", "%"),
    ("caret sign", "^"),
    ("carat sign", "^"),
    ("carrot sign", "^"),
    ("caret", "^"),
    ("carat", "^"),
    ("carrot", "^"),
    ("dollar sign", "$"),
    ("tilde", "~"),
    ("pipe symbol", "|"),
    ("vertical bar", "|"),
    ("tab", "\t"),
    ("et cetera", "etc."),
    ("etcetera", "etc."),
)

DEFAULT_SPOKEN_PUNCTUATION_REPLACEMENTS = {
    phrase: replacement for phrase, replacement in DEFAULT_SPOKEN_PUNCTUATION
}

SPOKEN_PUNCTUATION_PHRASES = tuple(
    re.escape(phrase)
    for phrase, _replacement in sorted(
        DEFAULT_SPOKEN_PUNCTUATION,
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

SPOKEN_PUNCTUATION_PATTERN = re.compile(
    r"\b(" + "|".join(SPOKEN_PUNCTUATION_PHRASES) + r")\b",
    re.IGNORECASE,
)

PROTECTED_SPOKEN_PUNCTUATION_PATTERN = re.compile(
    r"\b(?:literal|the word|word|called|named)\s+("
    + "|".join(SPOKEN_PUNCTUATION_PHRASES)
    + r")\b",
    re.IGNORECASE,
)


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


def apply_spoken_punctuation(
    text: str,
    configured_replacements: Mapping[str, str | None] | None = None,
) -> tuple[str, list[str]]:
    """Convert explicit dictation punctuation commands into punctuation marks."""
    if not text:
        return text, []

    replacements = _spoken_punctuation_replacements(configured_replacements)
    if not replacements:
        return text, []

    punctuation_pattern, protected_pattern = _spoken_punctuation_patterns(replacements)
    converted: list[str] = []
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(1))
        return f"\uE001PROTECTED_{len(protected) - 1}\uE001"

    def replace(match: re.Match[str]) -> str:
        spoken = match.group(1)
        replacement = replacements[spoken.lower()]
        converted.append(spoken)
        return replacement

    guarded = protected_pattern.sub(protect, text)
    cleaned = punctuation_pattern.sub(replace, guarded)
    for index, phrase in enumerate(protected):
        cleaned = cleaned.replace(f"\uE001PROTECTED_{index}\uE001", phrase)
    if not converted:
        return cleaned, converted

    return _normalize_spoken_punctuation_spacing(cleaned), converted


def _spoken_punctuation_replacements(
    configured_replacements: Mapping[str, str | None] | None,
) -> dict[str, str]:
    replacements = dict(DEFAULT_SPOKEN_PUNCTUATION_REPLACEMENTS)
    if not configured_replacements:
        return replacements

    for phrase, replacement in configured_replacements.items():
        normalized_phrase = phrase.strip().lower()
        if not normalized_phrase:
            continue
        if replacement is None:
            replacements.pop(normalized_phrase, None)
            continue
        replacements[normalized_phrase] = str(replacement)
    return replacements


def _spoken_punctuation_patterns(
    replacements: Mapping[str, str],
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    if replacements.keys() == DEFAULT_SPOKEN_PUNCTUATION_REPLACEMENTS.keys():
        return SPOKEN_PUNCTUATION_PATTERN, PROTECTED_SPOKEN_PUNCTUATION_PATTERN

    phrases = tuple(
        re.escape(phrase)
        for phrase in sorted(
            replacements,
            key=len,
            reverse=True,
        )
    )
    phrase_pattern = "|".join(phrases)
    return (
        re.compile(r"\b(" + phrase_pattern + r")\b", re.IGNORECASE),
        re.compile(
            r"\b(?:literal|the word|word|called|named)\s+("
            + phrase_pattern
            + r")\b",
            re.IGNORECASE,
        ),
    )


def _normalize_spoken_punctuation_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+([,.;:!?%\]\)\}])", r"\1", text)
    text = re.sub(r"([\[\(\{])[ \t]+", r"\1", text)
    text = re.sub(r"[ \t]+([.]{3})", r"\1", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"([.]{3})[ \t]*[,;:]+", r"\1", text)
    text = re.sub(r"([.]{3})[ \t]*([!?])", r"\1\2", text)
    text = re.sub(r",{2,}", ",", text)
    text = re.sub(rf"{OPEN_DOUBLE_QUOTE}[ \t]*", '"', text)
    text = re.sub(rf"[ \t]*{CLOSE_DOUBLE_QUOTE}", '"', text)
    text = re.sub(rf"{OPEN_SINGLE_QUOTE}[ \t]*", "'", text)
    text = re.sub(rf"[ \t]*{CLOSE_SINGLE_QUOTE}", "'", text)
    text = re.sub(r"(\w)[ \t]*'[ \t]*(\w)", r"\1'\2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


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
    trailing = re.compile(rf"^(.+?)([\s,.;:!?-]+)({token_pattern})[\s,.;:!?-]*$", re.IGNORECASE | re.DOTALL)

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
        removed.append(match.group(3))
        cleaned = _preserve_terminal_punctuation(match.group(1), match.group(2)).strip()

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


def _preserve_terminal_punctuation(stem: str, separator: str) -> str:
    stripped_stem = stem.rstrip()
    if not stripped_stem or stripped_stem[-1] in ".!?":
        return stripped_stem

    separator_marks = re.search(r"[.!?]+$", separator.strip())
    if separator_marks:
        return stripped_stem + separator_marks.group(0)

    return stripped_stem
