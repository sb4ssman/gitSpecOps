# macOS menu-bar prototype (tested 2026-11-16)

Why: on macOS 10.15 there is no Qt (PySide6) wheel, so the app runs without an icon
(`_run_without_icon`). A native menu-bar icon needs no Qt: Swift and AppKit ship with the
Command Line Tools.

Tested on an iMac on macOS 10.15.8 with Swift 5.3.2 (Command Line Tools only): `swiftc -O
GitsoBar.swift -o GitsoBar` took about a minute and made an 80 KB binary. Wrapped as
`GitsoBar.app/Contents/{MacOS/GitsoBar, Info.plist}` with `LSUIElement` true (menu bar only, no
Dock icon) and started with `open GitsoBar.app`, it showed "◐ gso" in the menu bar. Its menu
items ran `gitso tray --open` and `gitso update --yes`. `gitso tray --stop` does not stop it:
it is a separate process. Nothing was installed; it lived in /tmp.

Not done: a real icon (the shared mark), starting at sign-in, stopping with the app, packaging.
Newer Macs have Qt wheels, so the normal tray is the first thing to try there.

```swift
// Proof of concept: a menu-bar icon for gitSpecOps on older Macs (no Qt needed).
// The Python app keeps running without an icon; this only shows an icon and calls `gitso`.
import Cocoa

final class Bar: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let gitso = NSHomeDirectory() + "/.gitspecops/bin/gitso"

    func applicationDidFinishLaunching(_ note: Notification) {
        item.button?.title = "◐ gso"
        item.button?.toolTip = "gitSpecOps"
        let menu = NSMenu()
        menu.addItem(withTitle: "Open the fleet page", action: #selector(openPage), keyEquivalent: "o").target = self
        menu.addItem(withTitle: "Update gitSpecOps", action: #selector(update), keyEquivalent: "").target = self
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "Quit this icon", action: #selector(quit), keyEquivalent: "q").target = self
        item.menu = menu
    }

    func run(_ args: [String]) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: gitso)
        task.arguments = args
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = NSHomeDirectory() + "/.local/bin:/usr/local/bin:/usr/bin:/bin:" + (env["PATH"] ?? "")
        task.environment = env
        try? task.run()
    }

    @objc func openPage() { run(["tray", "--open"]) }
    @objc func update() { run(["update", "--yes"]) }
    @objc func quit() { NSApp.terminate(nil) }
}

let app = NSApplication.shared
let delegate = Bar()
app.delegate = delegate
app.setActivationPolicy(.accessory)  // menu bar only, no Dock icon
app.run()
```
