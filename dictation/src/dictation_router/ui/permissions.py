from __future__ import annotations

import logging
import subprocess
import sys


def describe_hotkey(spec: str) -> str:
    """Human-readable description of a config hotkey spec."""
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    labels: list[str] = []
    key = parts[-1] if parts else "?"

    for part in parts[:-1]:
        if part == "hyper":
            labels.extend(["Control", "Option", "Shift", "Command"])
        elif part in ("cmd", "command", "super"):
            labels.append("Command")
        elif part in ("alt", "option"):
            labels.append("Option")
        elif part in ("ctrl", "control"):
            labels.append("Control")
        elif part == "shift":
            labels.append("Shift")
        else:
            labels.append(part)

    return " + ".join(labels + [key.upper()])


def check_accessibility(logger: logging.Logger) -> bool:
    """Return True if this process can monitor input events."""
    if sys.platform != "darwin":
        return True

    try:
        import ctypes
        import ctypes.util

        lib_path = ctypes.util.find_library("ApplicationServices")
        if not lib_path:
            return True
        lib = ctypes.CDLL(lib_path)
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        trusted = bool(lib.AXIsProcessTrusted())
    except Exception:
        trusted = True

    if trusted:
        return True

    logger.error(
        "Accessibility permission required — global hotkeys will NOT work until enabled."
    )
    logger.error(
        "Fix: System Settings → Privacy & Security → Accessibility → enable %s",
        _parent_process_name(),
    )
    logger.error("Then quit and restart dictation-router.")
    return False


def _parent_process_name() -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(__import__("os").getppid())],
            capture_output=True,
            text=True,
            check=False,
        )
        name = result.stdout.strip()
        return name or "your terminal app"
    except OSError:
        return "your terminal app"
