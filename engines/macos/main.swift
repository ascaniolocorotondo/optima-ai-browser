// Optima macOS engine.
// A small native window around the system WebKit (WKWebView), driven over
// stdin/stdout with one JSON object per line. Nothing external is installed:
// it uses the WebKit that ships with macOS and is compiled on your own Mac.

import Cocoa
import WebKit

// MARK: - Wire protocol

final class Wire {
    private let lock = NSLock()

    func send(_ obj: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: obj, options: []) else { return }
        lock.lock()
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
        lock.unlock()
    }

    func ok(_ id: Any, _ result: Any = NSNull()) { send(["id": id, "ok": true, "result": result]) }
    func fail(_ id: Any, _ error: String) { send(["id": id, "ok": false, "error": error]) }
}

/// A completion that fires at most once (load finished or timed out).
final class Once {
    private var fired = false
    private let fn: (Bool) -> Void
    init(_ fn: @escaping (Bool) -> Void) { self.fn = fn }
    func fire(timedOut: Bool) {
        if fired { return }
        fired = true
        fn(timedOut)
    }
}

// MARK: - Engine

final class Engine: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    let wire = Wire()
    let uaSuffix: String
    let title: String
    /// Opened by double-click (no assistant attached): behaves like a normal browser.
    let standalone: Bool

    var window: NSWindow!
    var webView: WKWebView!
    var addressLabel: NSTextField!
    var banner: NSView!
    var bannerLabel: NSTextField!
    var doneButton: NSButton!

    var humanDone = false
    var loadWaiters: [Once] = []
    var lastDialogs: [String] = []
    var lastNavError: String?

    init(uaSuffix: String, title: String, standalone: Bool) {
        self.uaSuffix = uaSuffix
        self.title = title
        self.standalone = standalone
    }

    // MARK: App setup

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        if standalone {
            webView.load(URLRequest(url: URL(string: "https://duckduckgo.com")!))
            window.makeFirstResponder(addressLabel)
        } else {
            // When the assistant drives the window, the page has focus, not the address bar.
            window.makeFirstResponder(webView)
            startReadingCommands()
            wire.send(["event": "ready"])
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func buildMenu() {
        // Without an Edit menu, Cmd+C / Cmd+V do not work inside the web view,
        // which matters when the human takes over to log in.
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Hide \(title)", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit \(title)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Open Location", action: #selector(focusAddress), keyEquivalent: "l")
        view.addItem(withTitle: "Reload", action: #selector(reloadPage), keyEquivalent: "r")
        view.addItem(withTitle: "Back", action: #selector(goBackAction), keyEquivalent: "[")
        view.addItem(withTitle: "Forward", action: #selector(goForwardAction), keyEquivalent: "]")
        viewItem.submenu = view
        main.addItem(viewItem)

        NSApp.mainMenu = main
    }

    @objc func reloadPage() { webView.reload() }
    @objc func focusAddress() { window.makeFirstResponder(addressLabel) }

    @objc func addressEntered() {
        // NSTextField also fires its action when it merely loses focus (for example when
        // the agent focuses a field in the page). Only a real Return key press navigates.
        guard let ev = NSApp.currentEvent, ev.type == .keyDown, ev.keyCode == 36 || ev.keyCode == 76 else { return }
        let text = addressLabel.stringValue.trimmingCharacters(in: .whitespaces)
        if text.isEmpty { return }
        var url: URL?
        if text.contains("://") {
            url = URL(string: text)
        } else if text.contains(".") && !text.contains(" ") {
            url = URL(string: "https://" + text)
        }
        if url == nil {
            var c = URLComponents(string: "https://duckduckgo.com/")!
            c.queryItems = [URLQueryItem(name: "q", value: text)]
            url = c.url
        }
        if let u = url { webView.load(URLRequest(url: u)); window.makeFirstResponder(webView) }
    }
    @objc func goBackAction() { webView.goBack() }
    @objc func goForwardAction() { webView.goForward() }

    func buildWindow() {
        let frame = NSRect(x: 0, y: 0, width: 1280, height: 860)
        window = NSWindow(contentRect: frame,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = title
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("OptimaMain")

        let content = NSView(frame: frame)
        content.autoresizingMask = [.width, .height]

        // Top bar: address + "controlled by an AI agent" badge.
        let topBar = NSView()
        topBar.wantsLayer = true
        topBar.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        topBar.translatesAutoresizingMaskIntoConstraints = false

        let badge = NSTextField(labelWithString: standalone ? "Optima" : "🤖 AI")
        badge.font = .boldSystemFont(ofSize: 12)
        badge.textColor = .secondaryLabelColor
        badge.translatesAutoresizingMaskIntoConstraints = false

        addressLabel = NSTextField(string: "")
        addressLabel.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        addressLabel.placeholderString = "Search or enter address"
        addressLabel.lineBreakMode = .byTruncatingMiddle
        addressLabel.bezelStyle = .roundedBezel
        addressLabel.target = self
        addressLabel.action = #selector(addressEntered)
        (addressLabel.cell as? NSTextFieldCell)?.sendsActionOnEndEditing = false
        addressLabel.translatesAutoresizingMaskIntoConstraints = false

        topBar.addSubview(badge)
        topBar.addSubview(addressLabel)

        // Hand-off banner: shown when the agent needs the human.
        banner = NSView()
        banner.wantsLayer = true
        banner.layer?.backgroundColor = NSColor.systemOrange.withAlphaComponent(0.18).cgColor
        banner.translatesAutoresizingMaskIntoConstraints = false
        banner.isHidden = true

        bannerLabel = NSTextField(wrappingLabelWithString: "")
        bannerLabel.font = .systemFont(ofSize: 13, weight: .medium)
        bannerLabel.translatesAutoresizingMaskIntoConstraints = false

        doneButton = NSButton(title: "Done", target: self, action: #selector(humanFinished))
        doneButton.bezelStyle = .rounded
        doneButton.keyEquivalent = "\r"
        doneButton.translatesAutoresizingMaskIntoConstraints = false

        banner.addSubview(bannerLabel)
        banner.addSubview(doneButton)

        // Web view with a persistent data store, so logins survive restarts.
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.applicationNameForUserAgent = uaSuffix
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.translatesAutoresizingMaskIntoConstraints = false

        content.addSubview(topBar)
        content.addSubview(banner)
        content.addSubview(webView)

        NSLayoutConstraint.activate([
            topBar.topAnchor.constraint(equalTo: content.topAnchor),
            topBar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            topBar.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            topBar.heightAnchor.constraint(equalToConstant: 36),

            badge.leadingAnchor.constraint(equalTo: topBar.leadingAnchor, constant: 10),
            badge.centerYAnchor.constraint(equalTo: topBar.centerYAnchor),
            addressLabel.leadingAnchor.constraint(equalTo: badge.trailingAnchor, constant: 10),
            addressLabel.trailingAnchor.constraint(equalTo: topBar.trailingAnchor, constant: -10),
            addressLabel.centerYAnchor.constraint(equalTo: topBar.centerYAnchor),

            banner.topAnchor.constraint(equalTo: topBar.bottomAnchor),
            banner.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            banner.trailingAnchor.constraint(equalTo: content.trailingAnchor),

            bannerLabel.leadingAnchor.constraint(equalTo: banner.leadingAnchor, constant: 14),
            bannerLabel.topAnchor.constraint(equalTo: banner.topAnchor, constant: 10),
            bannerLabel.bottomAnchor.constraint(equalTo: banner.bottomAnchor, constant: -10),
            bannerLabel.trailingAnchor.constraint(equalTo: doneButton.leadingAnchor, constant: -12),
            doneButton.trailingAnchor.constraint(equalTo: banner.trailingAnchor, constant: -14),
            doneButton.centerYAnchor.constraint(equalTo: banner.centerYAnchor),

            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])
        // The web view sits under the banner when visible, under the top bar otherwise.
        bannerTop = webView.topAnchor.constraint(equalTo: banner.bottomAnchor)
        barTop = webView.topAnchor.constraint(equalTo: topBar.bottomAnchor)
        barTop.isActive = true

        window.contentView = content
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    var bannerTop: NSLayoutConstraint!
    var barTop: NSLayoutConstraint!

    func setBanner(visible: Bool) {
        banner.isHidden = !visible
        barTop.isActive = !visible
        bannerTop.isActive = visible
    }

    @objc func humanFinished() {
        humanDone = true
        setBanner(visible: false)
    }

    func bringToFront() {
        NSApp.activate(ignoringOtherApps: true)
        window.deminiaturize(nil)
        window.makeKeyAndOrderFront(nil)
    }

    // MARK: Command loop

    func startReadingCommands() {
        Thread.detachNewThread { [weak self] in
            while let line = readLine(strippingNewline: true) {
                guard let data = line.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                DispatchQueue.main.async { self?.handle(obj) }
            }
            // stdin closed: the controller went away, so quit.
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }

    func handle(_ msg: [String: Any]) {
        let id = msg["id"] ?? NSNull()
        let cmd = msg["cmd"] as? String ?? ""
        let args = msg["args"] as? [String: Any] ?? [:]
        log("cmd \(cmd)")
        let timeout = (args["timeout"] as? Double) ?? 30

        switch cmd {
        case "navigate":
            guard let s = args["url"] as? String, let url = URL(string: s) else {
                wire.fail(id, "invalid url"); return
            }
            lastNavError = nil
            webView.load(URLRequest(url: url))
            waitForLoad(timeout: timeout) { [weak self] timedOut in self?.wire.ok(id, self?.pageInfo(timedOut: timedOut) ?? [:]) }

        case "set_content":
            let html = args["html"] as? String ?? ""
            webView.loadHTMLString(html, baseURL: nil)
            waitForLoad(timeout: timeout) { [weak self] timedOut in self?.wire.ok(id, self?.pageInfo(timedOut: timedOut) ?? [:]) }

        case "eval":
            let js = args["js"] as? String ?? ""
            webView.evaluateJavaScript(js) { [weak self] result, error in
                if let error = error as NSError? {
                    let detail = (error.userInfo["WKJavaScriptExceptionMessage"] as? String) ?? error.localizedDescription
                    self?.wire.fail(id, "javascript error: \(detail)")
                } else if let s = result as? String {
                    self?.wire.ok(id, s)
                } else {
                    self?.wire.ok(id, NSNull())
                }
            }

        case "wait_idle":
            // Give a click a moment to start a navigation, then wait for it to finish.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                guard let self = self else { return }
                if self.webView.isLoading {
                    self.waitForLoad(timeout: timeout) { timedOut in self.wire.ok(id, self.pageInfo(timedOut: timedOut)) }
                } else {
                    self.wire.ok(id, self.pageInfo(timedOut: false))
                }
            }

        case "back", "forward", "reload":
            if cmd == "back" { if webView.canGoBack { webView.goBack() } else { wire.ok(id, pageInfo(timedOut: false)); return } }
            if cmd == "forward" { if webView.canGoForward { webView.goForward() } else { wire.ok(id, pageInfo(timedOut: false)); return } }
            if cmd == "reload" { webView.reload() }
            waitForLoad(timeout: timeout) { [weak self] timedOut in self?.wire.ok(id, self?.pageInfo(timedOut: timedOut) ?? [:]) }

        case "info":
            wire.ok(id, pageInfo(timedOut: false))

        case "screenshot":
            webView.takeSnapshot(with: nil) { [weak self] image, error in
                guard let image = image,
                      let tiff = image.tiffRepresentation,
                      let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    self?.wire.fail(id, "screenshot failed: \(error?.localizedDescription ?? "unknown")"); return
                }
                self?.wire.ok(id, png.base64EncodedString())
            }

        case "focus":
            bringToFront()
            wire.ok(id)

        case "handoff_begin":
            humanDone = false
            bannerLabel.stringValue = args["message"] as? String ?? ""
            doneButton.title = args["button"] as? String ?? "Done"
            setBanner(visible: true)
            bringToFront()
            wire.ok(id)

        case "handoff_status":
            wire.ok(id, ["done": humanDone])

        case "handoff_end":
            setBanner(visible: false)
            wire.ok(id)

        case "dialogs":
            let d = lastDialogs
            lastDialogs.removeAll()
            wire.ok(id, d)

        case "quit":
            wire.ok(id)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { NSApp.terminate(nil) }

        default:
            wire.fail(id, "unknown command: \(cmd)")
        }
    }

    func pageInfo(timedOut: Bool) -> [String: Any] {
        var info: [String: Any] = [
            "url": webView.url?.absoluteString ?? "",
            "title": webView.title ?? "",
            "loading": webView.isLoading,
            "timed_out": timedOut,
        ]
        if let e = lastNavError { info["error"] = e }
        return info
    }

    func waitForLoad(timeout: Double, _ done: @escaping (Bool) -> Void) {
        let once = Once(done)
        loadWaiters.append(once)
        DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { once.fire(timedOut: true) }
    }

    func finishLoads() {
        let waiters = loadWaiters
        loadWaiters.removeAll()
        waiters.forEach { $0.fire(timedOut: false) }
    }

    // MARK: WKNavigationDelegate

    let debug = ProcessInfo.processInfo.environment["OPTIMA_DEBUG"] != nil

    func log(_ s: String) {
        guard debug else { return }
        FileHandle.standardError.write(("[engine] " + s + "\n").data(using: .utf8)!)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        log("navigate type=\(navigationAction.navigationType.rawValue) main=\(navigationAction.targetFrame?.isMainFrame ?? false) " +
            "method=\(navigationAction.request.httpMethod ?? "?") url=\(navigationAction.request.url?.absoluteString ?? "")")
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        addressLabel.stringValue = webView.url?.absoluteString ?? ""
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        log("finished \(webView.url?.absoluteString ?? "")")
        addressLabel.stringValue = webView.url?.absoluteString ?? ""
        finishLoads()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        let ns = error as NSError
        if ns.code != NSURLErrorCancelled { lastNavError = error.localizedDescription }
        finishLoads()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let ns = error as NSError
        if ns.code != NSURLErrorCancelled { lastNavError = error.localizedDescription }
        finishLoads()
    }

    // MARK: WKUIDelegate

    // Links that open a new window load in this one: the agent works in a single tab.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        log("new-window request type=\(navigationAction.navigationType.rawValue) url=\(navigationAction.request.url?.absoluteString ?? "")")
        if navigationAction.targetFrame == nil { webView.load(navigationAction.request) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        lastDialogs.append("alert: \(message)")
        completionHandler()
    }

    // Confirmation dialogs are answered "cancel": the agent never silently agrees to something.
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        lastDialogs.append("confirm (answered cancel): \(message)")
        completionHandler(false)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        lastDialogs.append("prompt (answered cancel): \(prompt)")
        completionHandler(nil)
    }
}

// MARK: - Entry point

var uaSuffix = "Version/18.0 Safari/605.1.15 Optima/0.1 (AI agent)"
var windowTitle = "Optima AI Browser"
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    if a == "--ua-suffix", let v = it.next() { uaSuffix = v }
    if a == "--title", let v = it.next() { windowTitle = v }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
var st = stat()
let stdinIsPipe = fstat(0, &st) == 0 && (st.st_mode & S_IFMT) == S_IFIFO
let engine = Engine(uaSuffix: uaSuffix, title: windowTitle, standalone: !stdinIsPipe)
app.delegate = engine
app.run()
