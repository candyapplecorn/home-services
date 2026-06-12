import AppKit
import Foundation

private typealias CommandCompletion = @MainActor @Sendable (Int32, String) -> Void

private final class CommandRunner {
    private let root: String

    init() {
        let envRoot = ProcessInfo.processInfo.environment["HOME_SERVICES_ROOT"]
        if let envRoot, !envRoot.isEmpty {
            root = NSString(string: envRoot).expandingTildeInPath
        } else {
            root = NSString(string: "~/bin/home-services").expandingTildeInPath
        }
    }

    var rootPath: String {
        root
    }

    private var executablePath: String {
        "\(root)/bin/home-services"
    }

    func run(_ arguments: [String], completion: @escaping CommandCompletion) {
        let executablePath = self.executablePath
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            let output = Pipe()
            process.executableURL = URL(fileURLWithPath: executablePath)
            process.arguments = arguments
            process.standardOutput = output
            process.standardError = output

            do {
                try process.run()
                process.waitUntilExit()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                let text = String(data: data, encoding: .utf8) ?? ""
                Task { @MainActor in
                    completion(process.terminationStatus, text.trimmingCharacters(in: .whitespacesAndNewlines))
                }
            } catch {
                Task { @MainActor in
                    completion(127, "Failed to run \(executablePath): \(error.localizedDescription)")
                }
            }
        }
    }

    func runDetached(_ arguments: [String]) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = arguments
        try? process.run()
    }
}

private struct StartupState {
    var installed: Bool?
    var loaded: Bool?
}

private struct DictationHotkeys {
    var insert = "cmd+alt+ctrl+d"
    var review = "cmd+alt+ctrl+r"
    var clean = "cmd+alt+ctrl+c"

    static func load(rootPath: String) -> DictationHotkeys {
        let configPath = URL(fileURLWithPath: rootPath).appendingPathComponent("dictation/config.yaml")
        guard let text = try? String(contentsOf: configPath, encoding: .utf8) else {
            return DictationHotkeys()
        }

        var hotkeys = DictationHotkeys()
        var inHotkeys = false
        for rawLine in text.components(separatedBy: .newlines) {
            let trimmed = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty || trimmed.hasPrefix("#") {
                continue
            }
            if trimmed == "hotkeys:" {
                inHotkeys = true
                continue
            }
            if inHotkeys && !rawLine.hasPrefix(" ") && !rawLine.hasPrefix("\t") {
                break
            }
            guard inHotkeys, let colon = trimmed.firstIndex(of: ":") else {
                continue
            }
            let key = String(trimmed[..<colon]).trimmingCharacters(in: .whitespacesAndNewlines)
            let rawValue = String(trimmed[trimmed.index(after: colon)...])
            let value = cleanYamlScalar(rawValue)
            if value.isEmpty {
                continue
            }
            switch key {
            case "insert":
                hotkeys.insert = value
            case "review":
                hotkeys.review = value
            case "clean":
                hotkeys.clean = value
            default:
                continue
            }
        }
        return hotkeys
    }

    private static func cleanYamlScalar(_ value: String) -> String {
        var cleaned = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if let comment = cleaned.firstIndex(of: "#") {
            cleaned = String(cleaned[..<comment]).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if cleaned.count >= 2,
           let first = cleaned.first,
           let last = cleaned.last,
           (first == "\"" && last == "\"") || (first == "'" && last == "'") {
            cleaned.removeFirst()
            cleaned.removeLast()
        }
        return cleaned
    }
}

private struct MenuHotkey {
    var keyEquivalent: String
    var modifiers: NSEvent.ModifierFlags
    var display: String
}

private func parseMenuHotkey(_ hotkey: String) -> MenuHotkey? {
    let parts = hotkey
        .split(separator: "+")
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        .filter { !$0.isEmpty }
    guard !parts.isEmpty else {
        return nil
    }

    var modifiers: NSEvent.ModifierFlags = []
    var displayModifiers: [String] = []
    let modifierParts = parts.dropLast()
    let keyPart = String(parts.last!)

    func addModifier(_ modifier: NSEvent.ModifierFlags, _ symbol: String) {
        if !modifiers.contains(modifier) {
            modifiers.insert(modifier)
            displayModifiers.append(symbol)
        }
    }

    for part in modifierParts {
        switch part {
        case "hyper":
            addModifier(.control, "⌃")
            addModifier(.option, "⌥")
            addModifier(.shift, "⇧")
            addModifier(.command, "⌘")
        case "ctrl", "control":
            addModifier(.control, "⌃")
        case "alt", "option", "opt":
            addModifier(.option, "⌥")
        case "shift":
            addModifier(.shift, "⇧")
        case "cmd", "command", "meta", "super":
            addModifier(.command, "⌘")
        default:
            return nil
        }
    }

    let keyEquivalent: String
    let displayKey: String
    switch keyPart {
    case "space":
        keyEquivalent = " "
        displayKey = "Space"
    case "enter":
        keyEquivalent = "\r"
        displayKey = "↩"
    case "tab":
        keyEquivalent = "\t"
        displayKey = "⇥"
    case "escape":
        keyEquivalent = "\u{1b}"
        displayKey = "⎋"
    default:
        guard keyPart.count == 1 else {
            return nil
        }
        keyEquivalent = keyPart.lowercased()
        displayKey = keyPart.uppercased()
    }

    guard !modifiers.isEmpty else {
        return nil
    }

    return MenuHotkey(
        keyEquivalent: keyEquivalent,
        modifiers: modifiers,
        display: displayModifiers.joined() + displayKey
    )
}

private func displayHotkey(_ hotkey: String) -> String {
    parseMenuHotkey(hotkey)?.display ?? hotkey
}

private func copyToClipboard(_ text: String) {
    let pasteboard = NSPasteboard.general
    pasteboard.clearContents()
    pasteboard.setString(text, forType: .string)
}

private struct CrashAlert: Decodable {
    var id: String
    var type: String
    var title: String
    var message: String
    var reason: String?
    var details: String?
    var jobId: String?
    var jobPath: String?
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case title
        case message
        case reason
        case details
        case jobId = "job_id"
        case jobPath = "job_path"
        case createdAt = "created_at"
    }
}

private func formatCrashAlert(_ alert: CrashAlert, sourceURL: URL? = nil) -> String {
    var lines = [
        alert.title,
        "",
        alert.message
    ]
    if let reason = alert.reason, !reason.isEmpty {
        lines.append("")
        lines.append("Reason: \(reason)")
    }
    if let jobId = alert.jobId, !jobId.isEmpty {
        lines.append("Job: \(jobId)")
    }
    if let jobPath = alert.jobPath, !jobPath.isEmpty {
        lines.append("Job path: \(jobPath)")
    }
    if let createdAt = alert.createdAt, !createdAt.isEmpty {
        lines.append("Created: \(createdAt)")
    }
    if let sourceURL {
        lines.append("Alert file: \(sourceURL.path)")
    }
    if let details = alert.details, !details.isEmpty {
        lines.append("")
        lines.append("[Details]")
        lines.append(details)
    }
    return lines.joined(separator: "\n")
}

@MainActor
private final class CrashAlertWindowController: NSWindowController, NSWindowDelegate {
    private let detailsScroll = NSScrollView()
    private let detailsButton = NSButton()
    private var detailsVisible = false
    private var didDismiss = false
    private let alertText: String
    private let alertURL: URL
    private let onDismiss: () -> Void
    private let openDiagnostics: () -> Void

    init(
        alert: CrashAlert,
        alertURL: URL,
        onDismiss: @escaping () -> Void,
        openDiagnostics: @escaping () -> Void
    ) {
        self.alertText = formatCrashAlert(alert, sourceURL: alertURL)
        self.alertURL = alertURL
        self.onDismiss = onDismiss
        self.openDiagnostics = openDiagnostics

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 250),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Home Services Alert"
        window.isReleasedWhenClosed = false

        super.init(window: window)
        window.delegate = self
        buildContent(in: window, alert: alert)
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show() {
        window?.center()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func buildContent(in window: NSWindow, alert: CrashAlert) {
        let titleLabel = NSTextField(labelWithString: alert.title)
        titleLabel.font = .boldSystemFont(ofSize: 16)
        titleLabel.lineBreakMode = .byWordWrapping
        titleLabel.maximumNumberOfLines = 0

        let messageLabel = NSTextField(labelWithString: alert.message)
        messageLabel.lineBreakMode = .byWordWrapping
        messageLabel.maximumNumberOfLines = 0

        let reasonLabel = NSTextField(labelWithString: alert.reason.map { "Reason: \($0)" } ?? "")
        reasonLabel.textColor = .secondaryLabelColor
        reasonLabel.lineBreakMode = .byWordWrapping
        reasonLabel.maximumNumberOfLines = 0
        reasonLabel.isHidden = alert.reason == nil

        let jobLabel = NSTextField(labelWithString: alert.jobId.map { "Job: \($0)" } ?? "")
        jobLabel.textColor = .secondaryLabelColor
        jobLabel.lineBreakMode = .byTruncatingMiddle
        jobLabel.isHidden = alert.jobId == nil

        let detailsView = NSTextView()
        detailsView.isEditable = false
        detailsView.isSelectable = true
        detailsView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        detailsView.textColor = .labelColor
        detailsView.backgroundColor = .textBackgroundColor
        detailsView.textContainerInset = NSSize(width: 10, height: 10)
        detailsView.isVerticallyResizable = true
        detailsView.isHorizontallyResizable = false
        detailsView.autoresizingMask = [.width]
        detailsView.minSize = NSSize(width: 0, height: 0)
        detailsView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        detailsView.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
        detailsView.textContainer?.widthTracksTextView = true
        detailsView.frame = NSRect(x: 0, y: 0, width: 600, height: 220)
        detailsView.string = alertText

        detailsScroll.hasVerticalScroller = true
        detailsScroll.hasHorizontalScroller = false
        detailsScroll.autohidesScrollers = true
        detailsScroll.borderType = .bezelBorder
        detailsScroll.documentView = detailsView
        detailsScroll.isHidden = true

        let dismissButton = NSButton(title: "Dismiss", target: self, action: #selector(dismissAlert))
        dismissButton.bezelStyle = .rounded
        dismissButton.keyEquivalent = "\r"

        let diagnosticsButton = NSButton(title: "Open Diagnostics", target: self, action: #selector(openDiagnosticsWindow))
        diagnosticsButton.bezelStyle = .rounded

        let copyButton = NSButton(title: "Copy Details", target: self, action: #selector(copyDetails))
        copyButton.bezelStyle = .rounded

        let openAlertButton = NSButton(title: "Open Alert File", target: self, action: #selector(openAlertFile))
        openAlertButton.bezelStyle = .rounded

        detailsButton.title = "Show Details"
        detailsButton.target = self
        detailsButton.action = #selector(toggleDetails)
        detailsButton.bezelStyle = .rounded

        let buttonRow = NSStackView(views: [diagnosticsButton, openAlertButton, copyButton, detailsButton, dismissButton])
        buttonRow.orientation = .horizontal
        buttonRow.alignment = .centerY
        buttonRow.distribution = .gravityAreas
        buttonRow.spacing = 10

        let stack = NSStackView(views: [titleLabel, messageLabel, reasonLabel, jobLabel, detailsScroll, buttonRow])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false

        window.contentView = NSView()
        window.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 18),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -18),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 18),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -18),
            detailsScroll.heightAnchor.constraint(equalToConstant: 220),
            detailsScroll.widthAnchor.constraint(equalTo: stack.widthAnchor),
            buttonRow.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
    }

    @objc private func toggleDetails() {
        detailsVisible.toggle()
        detailsScroll.isHidden = !detailsVisible
        detailsButton.title = detailsVisible ? "Hide Details" : "Show Details"
        guard let window else { return }
        var frame = window.frame
        let delta: CGFloat = 250
        if detailsVisible {
            frame.origin.y -= delta
            frame.size.height += delta
        } else {
            frame.origin.y += delta
            frame.size.height -= delta
        }
        window.setFrame(frame, display: true, animate: true)
    }

    @objc private func openDiagnosticsWindow() {
        openDiagnostics()
    }

    @objc private func copyDetails() {
        copyToClipboard(alertText)
    }

    @objc private func openAlertFile() {
        NSWorkspace.shared.open(alertURL)
    }

    @objc private func dismissAlert() {
        window?.close()
    }

    func windowWillClose(_ notification: Notification) {
        if didDismiss {
            return
        }
        didDismiss = true
        onDismiss()
    }
}

@MainActor
private final class DiagnosticsWindowController: NSWindowController, NSWindowDelegate {
    private let runner: CommandRunner
    private let textView = NSTextView()
    private var sections: [String: String] = [:]
    private let orderedSections = [
        "Status",
        "Startup",
        "Paths",
        "Crash Alerts",
        "Recent Dictation Log",
        "Doctor"
    ]

    init(runner: CommandRunner) {
        self.runner = runner

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 560),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Home Services Diagnostics"
        window.isReleasedWhenClosed = false

        super.init(window: window)
        window.delegate = self
        buildContent(in: window)
        refresh()
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show() {
        window?.center()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        return false
    }

    private func buildContent(in window: NSWindow) {
        let refreshButton = NSButton(
            title: "Refresh",
            target: self,
            action: #selector(refreshButtonClicked)
        )
        refreshButton.bezelStyle = .rounded

        let copyButton = NSButton(
            title: "Copy",
            target: self,
            action: #selector(copyButtonClicked)
        )
        copyButton.bezelStyle = .rounded

        let openSnapshotButton = NSButton(
            title: "Open Snapshot",
            target: self,
            action: #selector(openSnapshotButtonClicked)
        )
        openSnapshotButton.bezelStyle = .rounded

        let title = NSTextField(labelWithString: "Diagnostics")
        title.font = .boldSystemFont(ofSize: 18)

        let header = NSStackView(views: [title, NSView(), copyButton, openSnapshotButton, refreshButton])
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 12

        textView.isEditable = false
        textView.isSelectable = true
        textView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        textView.textContainerInset = NSSize(width: 12, height: 12)
        textView.drawsBackground = true
        textView.backgroundColor = .textBackgroundColor
        textView.textColor = .labelColor
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.minSize = NSSize(width: 0, height: 0)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
        textView.textContainer?.widthTracksTextView = true
        textView.string = "Loading..."

        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .bezelBorder
        textView.frame = NSRect(x: 0, y: 0, width: 720, height: 480)
        scrollView.documentView = textView

        let stack = NSStackView(views: [header, scrollView])
        stack.orientation = .vertical
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false

        window.contentView = NSView()
        window.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -16),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 16),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -16),
            header.heightAnchor.constraint(equalToConstant: 32),
            scrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 420)
        ])
    }

    @objc private func refreshButtonClicked() {
        refresh()
    }

    @objc private func copyButtonClicked() {
        copyToClipboard(renderedDiagnostics())
    }

    @objc private func openSnapshotButtonClicked() {
        let snapshotURL = writeSnapshot()
        NSWorkspace.shared.open(snapshotURL)
    }

    private func refresh() {
        sections = [
            "Status": "Loading...",
            "Startup": "Loading...",
            "Paths": "Loading...",
            "Crash Alerts": "Loading...",
            "Recent Dictation Log": "Loading...",
            "Doctor": "Loading..."
        ]
        render()
        loadSection(title: "Status", arguments: ["status"])
        loadSection(title: "Startup", arguments: ["startup-status"])
        loadSection(title: "Paths", arguments: ["logs"])
        loadCrashAlertsSection()
        loadRecentDictationLogSection()
        loadSection(title: "Doctor", arguments: ["doctor"])
    }

    private func loadSection(title: String, arguments: [String]) {
        runner.run(arguments) { [weak self] status, output in
            guard let self else { return }
            let body = output.isEmpty ? "No output." : output
            let prefix = status == 0 ? "" : "exit_status=\(status)\n"
            self.sections[title] = self.cap(prefix + body)
            self.render()
        }
    }

    private func render() {
        textView.string = renderedDiagnostics()
    }

    private func renderedDiagnostics() -> String {
        orderedSections.map { section in
            """
            [\(section)]
            \(sections[section] ?? "Loading...")
            """
        }.joined(separator: "\n\n")
    }

    private func cap(_ text: String, maxCharacters: Int = 8000) -> String {
        if text.count <= maxCharacters {
            return text
        }
        let end = text.index(text.startIndex, offsetBy: maxCharacters)
        return String(text[..<end]) + "\n... output truncated ..."
    }

    private func loadCrashAlertsSection() {
        DispatchQueue.global(qos: .userInitiated).async {
            let text = DiagnosticsWindowController.renderCrashAlerts()
            Task { @MainActor in
                self.sections["Crash Alerts"] = self.cap(text, maxCharacters: 12000)
                self.render()
            }
        }
    }

    nonisolated private static func renderCrashAlerts() -> String {
        let fileManager = FileManager.default
        let alertsDirectory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DictationRouter/alerts", isDirectory: true)
        var lines: [String] = []
        appendAlerts(from: alertsDirectory, label: "Pending", to: &lines)
        appendAlerts(
            from: alertsDirectory.appendingPathComponent("shown", isDirectory: true),
            label: "Shown",
            to: &lines
        )
        if lines.isEmpty {
            if fileManager.fileExists(atPath: alertsDirectory.path) {
                return "No crash alerts found."
            }
            return "Crash alert directory does not exist yet: \(alertsDirectory.path)"
        }
        return lines.joined(separator: "\n\n")
    }

    nonisolated private static func appendAlerts(from directory: URL, label: String, to lines: inout [String]) {
        let fileManager = FileManager.default
        guard let urls = try? fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.contentModificationDateKey]
        ) else {
            return
        }

        let jsonFiles = urls
            .filter { $0.pathExtension == "json" }
            .sorted {
                let left = ((try? $0.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate) ?? Date.distantPast
                let right = ((try? $1.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate) ?? Date.distantPast
                return left > right
            }
            .prefix(8)

        for url in jsonFiles {
            if let data = try? Data(contentsOf: url),
               let alert = try? JSONDecoder().decode(CrashAlert.self, from: data) {
                lines.append("[\(label)]\n" + formatCrashAlert(alert, sourceURL: url))
            } else {
                lines.append("[\(label)]\nUnreadable alert file: \(url.path)")
            }
        }
    }

    private func loadRecentDictationLogSection() {
        DispatchQueue.global(qos: .userInitiated).async {
            let text = DiagnosticsWindowController.renderRecentDictationLog()
            Task { @MainActor in
                self.sections["Recent Dictation Log"] = self.cap(text, maxCharacters: 14000)
                self.render()
            }
        }
    }

    nonisolated private static func renderRecentDictationLog() -> String {
        let logsDirectory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DictationRouter/logs", isDirectory: true)
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: logsDirectory,
            includingPropertiesForKeys: [.contentModificationDateKey]
        ) else {
            return "Dictation log directory does not exist yet: \(logsDirectory.path)"
        }

        let latest = urls
            .filter { $0.pathExtension == "log" }
            .max {
                let left = ((try? $0.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate) ?? Date.distantPast
                let right = ((try? $1.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate) ?? Date.distantPast
                return left < right
            }
        guard let latest else {
            return "No dictation logs found in \(logsDirectory.path)"
        }
        guard let text = try? String(contentsOf: latest, encoding: .utf8) else {
            return "Could not read \(latest.path)"
        }

        let lines = text.components(separatedBy: .newlines)
        let tail = lines.suffix(120).joined(separator: "\n")
        return "file=\(latest.path)\n\n\(tail)"
    }

    private func writeSnapshot() -> URL {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/HomeServices/logs", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let url = directory.appendingPathComponent("diagnostics-\(formatter.string(from: Date())).txt")
        try? renderedDiagnostics().write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}

@MainActor
private final class AppDelegate: NSObject, NSApplicationDelegate {
    private let runner = CommandRunner()
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private var statusLine = "Checking..."
    private var dictationState = "unknown"
    private var detailLines: [String] = []
    private var startupState = StartupState()
    private var lastStartupRefresh = Date.distantPast
    private var hotkeys = DictationHotkeys()
    private var timer: Timer?
    private var diagnosticsWindowController: DiagnosticsWindowController?
    private var crashAlertControllers: [CrashAlertWindowController] = []
    private var crashAlertPathsBeingShown: Set<String> = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        hotkeys = DictationHotkeys.load(rootPath: runner.rootPath)
        statusItem.button?.title = "HS"
        statusItem.button?.toolTip = "Home Services"
        statusItem.menu = menu
        rebuildMenu()
        refreshStatus()
        refreshStartupStatus(force: true)
        checkForCrashAlerts()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshStatus()
                self?.checkForCrashAlerts()
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
    }

    private func refreshStatus() {
        runner.run(["status"]) { [weak self] status, output in
            guard let self else { return }
            let lines = output.split(separator: "\n").map(String.init)
            let state = lines.first { $0.hasPrefix("dictation_state=") }?
                .replacingOccurrences(of: "dictation_state=", with: "")
            self.dictationState = state ?? "unknown"

            if let first = lines.first {
                if first == "status=running" {
                    if self.dictationState == "starting" {
                        self.statusLine = "Starting"
                    } else if self.dictationState == "recording" {
                        self.statusLine = "Recording"
                    } else if self.dictationState == "processing" {
                        self.statusLine = "Processing"
                    } else {
                        self.statusLine = "Running"
                    }
                } else if first == "status=stopped" {
                    self.statusLine = "Stopped"
                } else if first == "status=degraded" {
                    self.statusLine = "Degraded"
                } else if first == "status=missing-tmux" {
                    self.statusLine = "tmux Missing"
                } else {
                    self.statusLine = first
                }
            } else {
                self.statusLine = status == 0 ? "Running" : "Unavailable"
            }
            self.detailLines = Array(lines.dropFirst()).filter { !$0.hasPrefix("dictation_state=") }
            self.updateStatusButton()
            self.rebuildMenu()
            self.refreshStartupStatusIfNeeded()
        }
    }

    private func refreshStartupStatusIfNeeded() {
        if Date().timeIntervalSince(lastStartupRefresh) >= 10 {
            refreshStartupStatus(force: true)
        }
    }

    private func refreshStartupStatus(force: Bool = false) {
        if !force && Date().timeIntervalSince(lastStartupRefresh) < 10 {
            return
        }
        lastStartupRefresh = Date()
        runner.run(["startup-status"]) { [weak self] _, output in
            guard let self else { return }
            let lines = output.split(separator: "\n").map(String.init)
            let installed = lines.first { $0.hasPrefix("startup_installed=") }?
                .replacingOccurrences(of: "startup_installed=", with: "")
            let loaded = lines.first { $0.hasPrefix("startup_loaded=") }?
                .replacingOccurrences(of: "startup_loaded=", with: "")
            self.startupState.installed = installed == "yes" ? true : (installed == "no" ? false : nil)
            self.startupState.loaded = loaded == "yes" ? true : (loaded == "no" ? false : nil)
            self.rebuildMenu()
        }
    }

    private var crashAlertsDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/DictationRouter/alerts", isDirectory: true)
    }

    private func checkForCrashAlerts() {
        let fileManager = FileManager.default
        guard let urls = try? fileManager.contentsOfDirectory(
            at: crashAlertsDirectory,
            includingPropertiesForKeys: nil
        ) else {
            return
        }

        let candidates = urls
            .filter { $0.pathExtension == "json" && !$0.lastPathComponent.hasSuffix(".tmp") }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }

        for url in candidates {
            if crashAlertPathsBeingShown.contains(url.path) {
                continue
            }
            showCrashAlert(at: url)
            break
        }
    }

    private func showCrashAlert(at url: URL) {
        guard let data = try? Data(contentsOf: url),
              let alert = try? JSONDecoder().decode(CrashAlert.self, from: data),
              alert.type == "unrecoverable_recording_loss" else {
            moveCrashAlertToShown(url)
            return
        }

        crashAlertPathsBeingShown.insert(url.path)
        var controller: CrashAlertWindowController?
        controller = CrashAlertWindowController(
            alert: alert,
            alertURL: url,
            onDismiss: { [weak self, weak controller] in
                guard let self else { return }
                self.crashAlertPathsBeingShown.remove(url.path)
                self.moveCrashAlertToShown(url)
                if let controller {
                    self.crashAlertControllers.removeAll { $0 === controller }
                }
            },
            openDiagnostics: { [weak self] in
                self?.openDiagnostics()
            }
        )
        if let controller {
            crashAlertControllers.append(controller)
            controller.show()
        }
    }

    private func moveCrashAlertToShown(_ url: URL) {
        let fileManager = FileManager.default
        let shownDirectory = crashAlertsDirectory.appendingPathComponent("shown", isDirectory: true)
        try? fileManager.createDirectory(at: shownDirectory, withIntermediateDirectories: true)
        let destination = shownDirectory.appendingPathComponent(url.lastPathComponent)
        if fileManager.fileExists(atPath: destination.path) {
            try? fileManager.removeItem(at: destination)
        }
        try? fileManager.moveItem(at: url, to: destination)
    }

    private func updateStatusButton() {
        switch dictationState {
        case "starting":
            setStatusSymbol(
                "hourglass",
                fallback: "...",
                tint: .systemYellow,
                tooltip: "Home Services: Starting Recording"
            )
        case "recording":
            setStatusSymbol(
                "record.circle.fill",
                fallback: "REC",
                tint: .systemRed,
                tooltip: "Home Services: Recording"
            )
        case "processing":
            setStatusSymbol(
                "hourglass",
                fallback: "...",
                tint: .systemOrange,
                tooltip: "Home Services: Processing"
            )
        default:
            guard let button = statusItem.button else { return }
            button.image = nil
            button.imagePosition = .noImage
            button.contentTintColor = nil
            button.title = statusLine == "Running" ? "HS" : "HS!"
            button.toolTip = "Home Services: \(statusLine)"
        }
    }

    private func setStatusSymbol(_ symbolName: String, fallback: String, tint: NSColor, tooltip: String) {
        guard let button = statusItem.button else { return }
        button.toolTip = tooltip
        button.contentTintColor = tint
        if let image = NSImage(systemSymbolName: symbolName, accessibilityDescription: tooltip) {
            image.isTemplate = true
            button.image = image
            button.imagePosition = .imageOnly
            button.title = ""
        } else {
            button.image = nil
            button.imagePosition = .noImage
            button.title = fallback
        }
    }

    private func rebuildMenu() {
        menu.removeAllItems()
        hotkeys = DictationHotkeys.load(rootPath: runner.rootPath)

        let servicesStopped = statusLine == "Stopped"
        let servicesDegraded = statusLine == "Degraded"
        let servicesRunning = ["Running", "Starting", "Recording", "Processing"].contains(statusLine)
        let servicesKnown = servicesStopped || servicesDegraded || servicesRunning
        let canStartServices = servicesStopped || servicesDegraded
        let canStopServices = servicesRunning || servicesDegraded
        let canUseTmux = servicesKnown

        let status = NSMenuItem(title: "Status: \(statusLine)", action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)

        for line in detailLines {
            let item = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        menu.addItem(.separator())
        menu.addItem(actionItem("Start Services", #selector(startServices), enabled: canStartServices))
        menu.addItem(actionItem("Stop Services", #selector(stopServices), enabled: canStopServices))
        menu.addItem(actionItem("Restart Services", #selector(restartServices), enabled: canUseTmux))
        menu.addItem(actionItem("Open tmux Session", #selector(openTmuxSession), enabled: canUseTmux))

        menu.addItem(.separator())
        let recordingStatus = NSMenuItem(title: "Dictation: \(dictationStateDisplay)", action: nil, keyEquivalent: "")
        recordingStatus.isEnabled = false
        menu.addItem(recordingStatus)
        menu.addItem(hotkeyItem("Insert / Stop Dictation", hotkeys.insert))
        menu.addItem(hotkeyItem("Review / Stop Dictation", hotkeys.review))
        menu.addItem(hotkeyItem("Clean / Stop Dictation", hotkeys.clean))

        menu.addItem(.separator())
        menu.addItem(actionItem("Open Dictation Config", #selector(openConfig)))
        menu.addItem(actionItem("Open Logs", #selector(openLogs)))
        menu.addItem(actionItem("Open Diagnostics", #selector(openDiagnostics)))
        menu.addItem(actionItem("Run Doctor", #selector(runDoctor)))

        menu.addItem(.separator())
        addStartupTaskItems()
        menu.addItem(actionItem("Create Desktop Launcher", #selector(createDesktopLauncher)))

        menu.addItem(.separator())
        let rootItem = NSMenuItem(title: "Root: \(runner.rootPath)", action: nil, keyEquivalent: "")
        rootItem.isEnabled = false
        menu.addItem(rootItem)

        menu.addItem(.separator())
        menu.addItem(actionItem("Quit", #selector(quit)))
    }

    private var dictationStateDisplay: String {
        switch dictationState {
        case "starting":
            return "starting"
        case "recording":
            return "recording"
        case "processing":
            return "processing"
        case "idle":
            return "idle"
        default:
            return "unknown"
        }
    }

    private func addStartupTaskItems() {
        if let installed = startupState.installed {
            let label = startupState.loaded == true ? "Startup Task: Installed" : "Startup Task: Installed, Not Loaded"
            let status = NSMenuItem(title: installed ? label : "Startup Task: Not Installed", action: nil, keyEquivalent: "")
            status.isEnabled = false
            menu.addItem(status)
            if installed {
                menu.addItem(actionItem("Uninstall Startup Task...", #selector(uninstallStartupTask)))
            } else {
                menu.addItem(actionItem("Install Startup Task...", #selector(installStartupTask)))
            }
        } else {
            let item = NSMenuItem(title: "Startup Task: Checking...", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
    }

    private func actionItem(_ title: String, _ selector: Selector, enabled: Bool = true) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = self
        item.isEnabled = enabled
        return item
    }

    private func hotkeyItem(_ title: String, _ hotkey: String) -> NSMenuItem {
        guard let parsed = parseMenuHotkey(hotkey) else {
            let item = NSMenuItem(title: "\(title) (\(displayHotkey(hotkey)))", action: nil, keyEquivalent: "")
            item.isEnabled = false
            return item
        }

        let item = NSMenuItem(title: title, action: nil, keyEquivalent: parsed.keyEquivalent)
        item.keyEquivalentModifierMask = parsed.modifiers
        item.isEnabled = false
        return item
    }

    @objc private func startServices() {
        runInTerminal("start")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.refreshStatus()
        }
    }

    @objc private func stopServices() {
        guard confirmDestructiveAction(title: "Stop Home Services?", message: "This will stop the running tmux session and all services in it.") else {
            return
        }
        runner.run(["stop"]) { [weak self] _, _ in self?.refreshStatus() }
    }

    @objc private func restartServices() {
        guard confirmDestructiveAction(title: "Restart Home Services?", message: "This will stop the running tmux session and start a new one.") else {
            return
        }
        runInTerminal("restart")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.refreshStatus()
        }
    }

    @objc private func openConfig() {
        runner.runDetached(["open-config"])
    }

    @objc private func openLogs() {
        runner.runDetached(["open-logs"])
    }

    @objc private func openDiagnostics() {
        if diagnosticsWindowController == nil {
            diagnosticsWindowController = DiagnosticsWindowController(runner: runner)
        }
        diagnosticsWindowController?.show()
    }

    @objc private func runDoctor() {
        runner.run(["doctor"]) { [weak self] _, output in
            self?.showAlert(title: "Home Services Doctor", message: output.isEmpty ? "No output." : output)
        }
    }

    @objc private func installStartupTask() {
        guard confirmAction(
            title: "Install Startup Task?",
            message: "Home Services will start its background tmux session automatically when you log in.",
            continueTitle: "Install",
            alertStyle: .informational
        ) else {
            return
        }

        runner.run(["install-startup"]) { [weak self] status, output in
            self?.showAlert(
                title: status == 0 ? "Startup Task Installed" : "Startup Task Failed",
                message: output.isEmpty ? "No output." : output
            )
            self?.refreshStatus()
            self?.refreshStartupStatus(force: true)
        }
    }

    @objc private func uninstallStartupTask() {
        guard confirmAction(
            title: "Remove Startup Task?",
            message: "Home Services will stop launching automatically when you log in. Running services are not stopped.",
            continueTitle: "Remove",
            alertStyle: .warning
        ) else {
            return
        }

        runner.run(["uninstall-startup"]) { [weak self] status, output in
            self?.showAlert(
                title: status == 0 ? "Startup Task Removed" : "Startup Task Removal Failed",
                message: output.isEmpty ? "No output." : output
            )
            self?.refreshStatus()
            self?.refreshStartupStatus(force: true)
        }
    }

    @objc private func createDesktopLauncher() {
        runner.run(["install-desktop-shortcut"]) { [weak self] status, output in
            self?.showAlert(
                title: status == 0 ? "Desktop Launcher Created" : "Desktop Launcher Failed",
                message: output.isEmpty ? "No output." : output
            )
        }
    }

    @objc private func openTmuxSession() {
        runInTerminal("attach")
    }

    private func runInTerminal(_ commandName: String) {
        let command = "\(shellQuote(runner.rootPath))/bin/home-services \(commandName)"
        let script: String
        if FileManager.default.fileExists(atPath: "/Applications/iTerm.app") {
            script = """
            tell application "iTerm"
              create window with default profile
              tell current session of current window
                write text "\(escapeAppleScript(command))"
              end tell
              activate
            end tell
            """
        } else {
            script = """
            tell application "Terminal"
              do script "\(escapeAppleScript(command))"
              activate
            end tell
            """
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func showAlert(title: String, message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    private func confirmDestructiveAction(title: String, message: String) -> Bool {
        confirmAction(title: title, message: message, continueTitle: "Continue", alertStyle: .warning)
    }

    private func confirmAction(title: String, message: String, continueTitle: String, alertStyle: NSAlert.Style) -> Bool {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = alertStyle
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: continueTitle)
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertSecondButtonReturn
    }
}

private func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

private func escapeAppleScript(_ value: String) -> String {
    value
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
}

let app = NSApplication.shared
private let delegate = AppDelegate()
app.delegate = delegate
app.run()
