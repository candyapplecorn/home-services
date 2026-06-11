# Home Services Roadmap

## Product Direction

`home-services` should become a reliable local control plane for personal always-on utilities, with the macOS menu bar app as the primary user surface and the CLI as the dependable service runner.

Core principles:

- Local-first by default
- Fast start, stop, and status visibility
- First-class no-GUI operation for shell, SSH, terminal, and managed-machine workflows
- Low-maintenance setup on a single machine
- Clear logs, diagnostics, and recovery paths
- Small services that can evolve independently
- Cross-platform paths considered where they do not slow down the macOS-first workflow

## Near-Term Work

### Menu Bar Utility

- Finish the native macOS menu bar app as the default control surface.
- Add clear service state for each managed service: `dictation-router` and `moviewatch`.
- Surface doctor results in a readable modal or window instead of raw command output.
- Add quick actions for start, stop, restart, tmux attach, logs, and dictation config.
- Improve error states when `tmux`, virtualenv, model files, or permissions are missing.

### CLI and Service Management

- Keep `bin/home-services` as the stable automation interface.
- Preserve a first-class no-GUI workflow that can run entirely from shell commands, including the original tmux-style model of launching dictation and moviewatch in separate panes from one alias or command.
- Treat menu bar and tray apps as optional control surfaces, not required runtime dependencies.
- Normalize status output so the menu bar app can parse it safely.
- Add per-service status, not just session status.
- Add lightweight health checks for process state, Whisper model presence, and required macOS permissions.
- Preserve backward-compatible aliases.
- Provide a single command or alias-compatible entrypoint that starts the full no-GUI service stack in a tmux layout, with separate panes for `moviewatch` and dictation.
- Document the no-GUI workflow as a supported path for SSH and managed-machine users who can run scripts but cannot install arbitrary GUI software.

### Dictation Router Reliability

- Tighten logging around recording duration, transcription duration, output length, and routing mode.
- Improve diagnostics for quiet speech, missing content, and skipped Whisper windows.
- Make insert, review, and clean behavior predictable when the active app changes during transcription.
- Add tests around routing, cleanup, config parsing, and threshold handling.

### Moviewatch Maintenance

- Document expected input and output behavior.
- Add guardrails for duplicate processing, failed conversions, and large files.
- Emit structured log lines that can be surfaced by the menu bar app.

## Mid-Term Work

### Menu Bar App v1

- Replace the `HS` text-only status with clearer state indicators.
- Add a compact status window showing service states, recent errors, log file locations, last successful dictation, and last moviewatch conversion.
- Add actions to tail or reveal relevant logs.
- Add launch-at-login support.
- Add app signing and notarization if distribution outside the local machine becomes useful.

### Dictation Product Improvements

- Add configurable transcription profiles: fast short dictation, long-form review, code/text cleanup, and high-accuracy mode.
- Add a local transcript history browser.
- Add retry and reprocess support for kept recordings.
- Add safer clipboard fallback behavior with clear logging.
- Add optional post-processing stages for punctuation cleanup, filler-word removal, notes/email formatting, and command-style dictation shortcuts.

### Voice Transcription Research Spike

Investigate popular features in existing voice transcription, dictation, and meeting transcription tools. Compare products such as macOS Dictation, Windows Voice Access, Dragon, Whisper-based desktop tools, Otter, Descript, MacWhisper, Superwhisper, Wispr Flow, and similar current tools.

Feature categories to compare:

- Capture workflow: push-to-talk, toggle recording, continuous dictation, wake words, meeting capture, and file import.
- Accuracy controls: model choice, language support, speaker accents, vocabulary hints, and custom dictionaries.
- Editing workflow: transcript history, inline correction, reprocess audio, paragraph cleanup, and punctuation control.
- Output routing: type into active app, clipboard, file export, app-specific routing, and markdown formatting.
- AI cleanup: summarize, rewrite, remove filler words, and format as email, notes, tasks, or code.
- Privacy model: local-only, cloud-only, hybrid, and retention controls.
- Latency and performance: startup time, streaming versus batch transcription, and long-recording behavior.
- Hotkeys and ergonomics: global shortcuts, mode switching, audio/visual feedback, and menu bar controls.
- Reliability: permission handling, mic selection, failure recovery, and skipped speech detection.
- Integrations: calendar, notes apps, IDEs, browsers, Slack/email, and automation hooks.
- Accessibility: hands-free commands, correction commands, and screen reader compatibility.
- Pricing and positioning: one-time purchase, subscription, free/local/open-source options.

Deliverable: a short recommendation memo identifying which features are worth adding to `dictation-router`, which should be avoided, and which require more experimentation.

### Configuration and Setup

- Add a single source of truth for service definitions.
- Generate tmux layout, menu bar actions, and doctor checks from the same service registry if the repo grows.
- Improve `install.sh` idempotency and reporting.
- Add uninstall/reset docs for local support files and launch agents if added.

## Later Work

### Cross-Platform and Microsoft Windows Support

- Treat Windows as a later roadmap track after the macOS workflow is stable.
- Support constrained or managed Windows environments where users may be able to run scripts but cannot install arbitrary GUI utilities.
- Prioritize a no-GUI CLI workflow before Windows tray packaging; tray support should be optional, not required for parity.
- Define the Windows baseline around start, stop, status, doctor, logs, and attach-style workflows that map cleanly to the original two-pane service model.
- Separate platform-specific code from shared service logic.
- Replace or abstract macOS-only APIs: global hotkeys, Accessibility-driven text insertion, clipboard fallback behavior, microphone permission checks, audio feedback, menu bar UI, `open`, Terminal, AppleScript, and tmux assumptions.
- Define Windows equivalents: system tray app, Windows service or scheduled task supervisor, PowerShell CLI helpers, and Windows-native log/config locations.
- Add Windows install and service management for Python, ffmpeg, whisper.cpp or equivalent backend, model download and verification, microphone permissions, and start/stop/status/doctor commands.
- Account for transcription and model differences such as CUDA, DirectML, Vulkan, CPU-only fallback, binary names, model paths, audio device enumeration, and shell quoting.
- Add Windows packaging with a tray app, installer or scripted bootstrap, startup integration, and upgrade/uninstall path.
- Add a compatibility test matrix for macOS and Windows before committing to full parity.

### Unified Local Services Platform

- Support adding new personal services without editing the tmux script directly.
- Add a small service manifest format for name, command, working directory, logs, health check, and menu bar or tray actions.
- Consider replacing tmux as the runtime only if launch agents, Windows services, or a supervisor provide a clear operational benefit.

### Rich Dictation Workbench

- Add a native or lightweight local UI for transcript review.
- Support audio playback aligned with transcript text.
- Add per-app dictation rules for IDEs, browsers, docs, and chat.
- Add optional local LLM cleanup if latency and quality justify it.
- Add searchable transcript and recording archive with retention controls.

### Moviewatch Evolution

- Expand into a general media automation service if useful: watch folders, conversion presets, failure queue, manual retry, and notifications.
- Keep this separate from dictation concerns so the repo stays modular.

### Observability and Recovery

- Add a diagnostics dashboard.
- Add automatic stale-process detection.
- Add log rotation and retention policy.
- Add notifications for repeated failures.
- Add a support bundle command that collects safe diagnostics without private transcript/audio contents.

## Suggested Sequencing

1. Stabilize CLI status and doctor output.
2. Finish the macOS menu bar utility around that stable CLI contract.
3. Improve dictation reliability and transcript diagnostics.
4. Run the voice transcription feature research spike.
5. Use the spike results to choose the next dictation product features.
6. Generalize service definitions only after another service or platform needs the pattern.
7. Start Windows support as a focused cross-platform track once shared service contracts are stable.
