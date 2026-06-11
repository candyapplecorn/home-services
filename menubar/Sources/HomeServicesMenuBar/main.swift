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
    private var detailLines: [String] = []
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem.button?.title = "HS"
        statusItem.button?.toolTip = "Home Services"
        statusItem.menu = menu
        rebuildMenu()
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
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
            if let first = lines.first {
                if first == "status=running" {
                    self.statusLine = "Running"
                } else if first == "status=stopped" {
                    self.statusLine = "Stopped"
                } else if first == "status=missing-tmux" {
                    self.statusLine = "tmux Missing"
                } else {
                    self.statusLine = first
                }
            } else {
                self.statusLine = status == 0 ? "Running" : "Unavailable"
            }
            self.detailLines = Array(lines.dropFirst())
            self.statusItem.button?.title = self.statusLine == "Running" ? "HS" : "HS!"
            self.rebuildMenu()
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
        runner.run(["start"]) { [weak self] _, _ in self?.refreshStatus() }
    }

    @objc private func stopServices() {
        runner.run(["stop"]) { [weak self] _, _ in self?.refreshStatus() }
    }

    @objc private func restartServices() {
        runner.run(["restart"]) { [weak self] _, _ in self?.refreshStatus() }
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

    @objc private func openTmuxSession() {
        let command = "\(shellQuote(runner.rootPath))/bin/home-services attach"
        let script = """
        tell application "Terminal"
          do script "\(escapeAppleScript(command))"
          activate
        end tell
        """
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
