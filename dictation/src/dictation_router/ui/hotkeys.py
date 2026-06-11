from __future__ import annotations

from collections.abc import Callable

from pynput.keyboard import GlobalHotKeys, Key

MODIFIER_ALIASES = {
    "cmd": Key.cmd,
    "command": Key.cmd,
    "super": Key.cmd,
    "alt": Key.alt,
    "option": Key.alt,
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "shift": Key.shift,
}


def parse_hotkey(spec: str) -> str:
    """Convert config hotkey spec to pynput GlobalHotKeys format."""
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError(f"Invalid hotkey spec: {spec!r}")

    key_part = parts[-1]
    modifier_parts = parts[:-1]

    modifiers: list[Key] = []
    for part in modifier_parts:
        if part == "hyper":
            modifiers.extend([Key.ctrl, Key.alt, Key.shift, Key.cmd])
            continue
        key = MODIFIER_ALIASES.get(part)
        if key is None:
            raise ValueError(f"Unknown modifier in hotkey {spec!r}: {part}")
        modifiers.append(key)

    if len(key_part) == 1:
        key_token = key_part
    else:
        special = {
            "space": Key.space,
            "enter": Key.enter,
            "tab": Key.tab,
            "escape": Key.esc,
        }
        key_token = special.get(key_part, key_part)

    modifier_tokens = []
    for modifier in modifiers:
        name = modifier.name or str(modifier)
        modifier_tokens.append(f"<{name}>")

    return "+".join(modifier_tokens + [key_token])


class HotkeyManager:
    """Register global shortcuts and dispatch mode-specific callbacks."""

    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        """
        bindings: mapping of config hotkey spec -> callback, e.g.
            {"hyper+d": on_insert_toggle}
        """
        parsed = {parse_hotkey(spec): callback for spec, callback in bindings.items()}
        self._hotkeys = GlobalHotKeys(parsed)

    def start(self) -> None:
        self._hotkeys.start()

    def stop(self) -> None:
        self._hotkeys.stop()
