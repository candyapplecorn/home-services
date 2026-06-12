from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class DestinationSnapshot:
    app_name: str
    bundle_id: str
    pid: str
    window_title: str
    focused_role: str
    focused_subrole: str
    focused_description: str
    captured_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "app_name": self.app_name,
            "bundle_id": self.bundle_id,
            "pid": self.pid,
            "window_title": self.window_title,
            "focused_role": self.focused_role,
            "focused_subrole": self.focused_subrole,
            "focused_description": self.focused_description,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "DestinationSnapshot | None":
        if not data:
            return None
        return cls(
            app_name=str(data.get("app_name", "")),
            bundle_id=str(data.get("bundle_id", "")),
            pid=str(data.get("pid", "")),
            window_title=str(data.get("window_title", "")),
            focused_role=str(data.get("focused_role", "")),
            focused_subrole=str(data.get("focused_subrole", "")),
            focused_description=str(data.get("focused_description", "")),
            captured_at=str(data.get("captured_at", "")),
        )

    def same_target(self, other: "DestinationSnapshot | None") -> bool:
        if other is None:
            return False
        return (
            self.bundle_id,
            self.pid,
            self.window_title,
            self.focused_role,
            self.focused_subrole,
        ) == (
            other.bundle_id,
            other.pid,
            other.window_title,
            other.focused_role,
            other.focused_subrole,
        )

    def can_compare_target(self, other: "DestinationSnapshot | None") -> bool:
        if other is None:
            return False
        required_fields = (
            self.bundle_id,
            self.pid,
            self.window_title,
            self.focused_role,
            other.bundle_id,
            other.pid,
            other.window_title,
            other.focused_role,
        )
        return all(required_fields)


@dataclass(frozen=True)
class InsertabilityResult:
    insertable: bool
    reason: str
    current_destination: DestinationSnapshot | None = None


TEXT_INPUT_ROLES = {
    "AXTextArea",
    "AXTextField",
    "AXComboBox",
    "AXSearchField",
}

APP_ALLOWLIST_ROLES = {
    "com.apple.Terminal": {"AXTextArea"},
    "com.googlecode.iterm2": {"AXTextArea"},
    "com.tinyspeck.slackmacgap": {"AXTextArea", "AXTextField"},
}


def capture_destination_snapshot(timeout_s: float = 0.7) -> DestinationSnapshot | None:
    script_lines = [
        'tell application "System Events"',
        "set frontProc to first application process whose frontmost is true",
        'set appName to ""',
        'set bundleId to ""',
        'set pidValue to ""',
        "try",
        "set appName to (name of frontProc) as text",
        "end try",
        "try",
        "set bundleId to (bundle identifier of frontProc) as text",
        "end try",
        "try",
        "set pidValue to (unix id of frontProc) as text",
        "end try",
        'set windowTitle to ""',
        "try",
        "set windowTitle to (name of front window of frontProc) as text",
        "end try",
        'set roleName to ""',
        "try",
        'set focusedElem to value of attribute "AXFocusedUIElement" of frontProc',
        'set roleName to (value of attribute "AXRole" of focusedElem) as text',
        "end try",
        "return appName & linefeed & bundleId & linefeed & pidValue & linefeed & windowTitle & linefeed & roleName",
        "end tell",
    ]
    command = ["osascript"]
    for line in script_lines:
        command.extend(["-e", line])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    lines = result.stdout.splitlines()
    while len(lines) < 5:
        lines.append("")
    return DestinationSnapshot(
        app_name=lines[0].strip(),
        bundle_id=lines[1].strip(),
        pid=lines[2].strip(),
        window_title=lines[3].strip(),
        focused_role=lines[4].strip(),
        focused_subrole="",
        focused_description="",
        captured_at=datetime.now(UTC).isoformat(),
    )


def inspect_insertability(
    stop_destination: DestinationSnapshot | None = None,
    require_same_destination: bool = False,
) -> InsertabilityResult:
    current = capture_destination_snapshot()
    if current is None:
        return InsertabilityResult(True, "destination_unknown_allowed")

    if (
        require_same_destination
        and current.can_compare_target(stop_destination)
        and not current.same_target(stop_destination)
    ):
        return InsertabilityResult(False, "focus_changed", current)

    if not current.focused_role:
        return InsertabilityResult(True, "focused_role_unknown_allowed", current)

    allowed_roles = APP_ALLOWLIST_ROLES.get(current.bundle_id)
    if current.focused_role in TEXT_INPUT_ROLES or (
        allowed_roles is not None and current.focused_role in allowed_roles
    ):
        return InsertabilityResult(True, "insertable", current)

    return InsertabilityResult(False, f"not_insertable:{current.focused_role or 'unknown_role'}", current)
