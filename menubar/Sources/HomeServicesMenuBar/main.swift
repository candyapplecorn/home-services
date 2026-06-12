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

@MainActor
private final class AppDelegate: NSObject, NSApplicationDelegate {
    private let runner = CommandRunner()
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private var statusLine = "Checking..."
    private var dictationState = "unknown"
    private var detailLines: [String] = []
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem.button?.title = "HS"
        statusItem.button?.toolTip = "Home Services"
        statusItem.menu = menu
        rebuildMenu()
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshStatus()
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
                    if self.dictationState == "recording" {
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
        }
    }

    private func updateStatusButton() {
        switch dictationState {
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

        let status = NSMenuItem(title: "Status: \(statusLine)", action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)

        for line in detailLines {
            let item = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        menu.addItem(.separator())
        menu.addItem(actionItem("Start Services", #selector(startServices)))
        menu.addItem(actionItem("Stop Services", #selector(stopServices)))
        menu.addItem(actionItem("Restart Services", #selector(restartServices)))
        menu.addItem(actionItem("Open tmux Session", #selector(openTmuxSession)))

        menu.addItem(.separator())
        menu.addItem(actionItem("Open Dictation Config", #selector(openConfig)))
        menu.addItem(actionItem("Open Logs", #selector(openLogs)))
        menu.addItem(actionItem("Run Doctor", #selector(runDoctor)))

        menu.addItem(.separator())
        menu.addItem(actionItem("Install Startup Task...", #selector(installStartupTask)))
        menu.addItem(actionItem("Uninstall Startup Task...", #selector(uninstallStartupTask)))
        menu.addItem(actionItem("Create Desktop Launcher", #selector(createDesktopLauncher)))

        menu.addItem(.separator())
        let rootItem = NSMenuItem(title: "Root: \(runner.rootPath)", action: nil, keyEquivalent: "")
        rootItem.isEnabled = false
        menu.addItem(rootItem)

        menu.addItem(.separator())
        menu.addItem(actionItem("Quit", #selector(quit)))
    }

    private func actionItem(_ title: String, _ selector: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = self
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
