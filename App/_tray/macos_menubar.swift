// gitSpecOps' menu-bar icon on a Mac without Qt (macOS 10.15 and older): the same mark as
// everywhere (App/_mark/geometry.py: a hub for this machine inside a ring of five for the fleet),
// in the live colours the page shows. The app itself runs in Python; this only shows it.
//
// Built and started by App/_tray/macos_bar.py when the app runs without Qt on macOS. It reads
// the local page's /v1/dashboard every 5 seconds, quits when the app's process is gone, and its
// Quit asks the app to stop (gitso tray --stop), which then ends this too.
import Cocoa

let COLOURS: [String: NSColor] = [
    "starting": NSColor(calibratedRed: 0x8b / 255, green: 0x92 / 255, blue: 0x9a / 255, alpha: 1),
    "ok": NSColor(calibratedRed: 0x2e / 255, green: 0xa0 / 255, blue: 0x43 / 255, alpha: 1),
    "attention": NSColor(calibratedRed: 0xd4 / 255, green: 0xa0 / 255, blue: 0x17 / 255, alpha: 1),
    "error": NSColor(calibratedRed: 0xe5 / 255, green: 0x53 / 255, blue: 0x4b / 255, alpha: 1),
    "none": NSColor(calibratedRed: 0x8b / 255, green: 0x92 / 255, blue: 0x9a / 255, alpha: 1),
]
let HOLLOW: Set<String> = ["starting", "none"]

final class Bar: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    let info = Bundle.main.infoDictionary ?? [:]
    var machine = "starting", fleet = "none", words = "gitSpecOps: starting"
    var appPid: pid_t = 0
    var page = "http://127.0.0.1:8760/"
    var gitso = NSHomeDirectory() + "/.gitspecops/bin/gitso"

    func applicationDidFinishLaunching(_ note: Notification) {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--pid"), i + 1 < args.count { appPid = pid_t(args[i + 1]) ?? 0 }
        if let i = args.firstIndex(of: "--page"), i + 1 < args.count { page = args[i + 1] }
        if let i = args.firstIndex(of: "--gitso"), i + 1 < args.count { gitso = args[i + 1] }
        let menu = NSMenu()
        menu.addItem(withTitle: "Open gitSpecOps", action: #selector(openPage), keyEquivalent: "o").target = self
        menu.addItem(withTitle: "Update gitSpecOps", action: #selector(update), keyEquivalent: "").target = self
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "Quit gitSpecOps", action: #selector(quitApp), keyEquivalent: "q").target = self
        item.menu = menu
        draw()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }

    /// The app's process is gone: so is its icon. Then the page's two states.
    func refresh() {
        if appPid > 0 && kill(appPid, 0) != 0 { NSApp.terminate(nil); return }
        guard let url = URL(string: page + "v1/dashboard") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let self = self, let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let mark = json["mark"] as? [String: Any],
                  let m = mark["machine"] as? [String: Any], let f = mark["fleet"] as? [String: Any] else { return }
            DispatchQueue.main.async {
                self.machine = m["state"] as? String ?? "starting"
                self.fleet = f["state"] as? String ?? "none"
                self.words = "This machine: \(m["text"] as? String ?? "") · Fleet: \(f["text"] as? String ?? "")"
                self.draw()
            }
        }.resume()
    }

    func run(_ arguments: [String]) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: gitso)
        task.arguments = arguments
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = NSHomeDirectory() + "/.local/bin:/usr/local/bin:/usr/bin:/bin:" + (env["PATH"] ?? "")
        task.environment = env
        try? task.run()
    }

    @objc func openPage() { NSWorkspace.shared.open(URL(string: page)!) }
    @objc func update() { run(["update", "--terminal"]) }
    @objc func quitApp() { run(["tray", "--stop"]) }

    func draw() {
        item.button?.image = mark(machine: machine, fleet: fleet)
        item.button?.toolTip = words
    }

    /// geometry.py's small mark: nodes at radius 11.8 on a 32-unit square, line 1.9, node 2.7, hub 5.0.
    func mark(machine: String, fleet: String) -> NSImage {
        let size: CGFloat = 18
        let image = NSImage(size: NSSize(width: size, height: size), flipped: true) { _ in
            let s = size / 32
            let c = CGPoint(x: 16 * s, y: 16 * s), radius = 11.8 * s
            let nodeR = 2.7 * s, hubR = 5.0 * s, width = max(1.0, 1.9 * s)
            let nodes = (0..<5).map { k -> CGPoint in
                let a = (-90.0 + 72.0 * Double(k)) * Double.pi / 180
                return CGPoint(x: c.x + radius * CGFloat(cos(a)), y: c.y + radius * CGFloat(sin(a)))
            }
            let fleetColour = COLOURS[fleet] ?? COLOURS["none"]!
            let machineColour = COLOURS[machine] ?? COLOURS["starting"]!
            func segment(_ a: CGPoint, _ ra: CGFloat, _ b: CGPoint, _ rb: CGFloat) {
                let dx = b.x - a.x, dy = b.y - a.y, d = max(0.001, hypot(dx, dy))
                let path = NSBezierPath()
                path.move(to: CGPoint(x: a.x + dx / d * ra, y: a.y + dy / d * ra))
                path.line(to: CGPoint(x: b.x - dx / d * rb, y: b.y - dy / d * rb))
                path.lineWidth = width
                path.lineCapStyle = .round
                fleetColour.setStroke()
                path.stroke()
            }
            for k in 0..<5 { segment(nodes[k], nodeR, nodes[(k + 1) % 5], nodeR) }
            for p in nodes { segment(c, hubR, p, nodeR) }
            func dot(_ p: CGPoint, _ r: CGFloat, _ colour: NSColor, _ hollow: Bool) {
                let oval = NSBezierPath(ovalIn: NSRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r))
                if hollow { oval.lineWidth = max(1.0, 1.3 * s); colour.setStroke(); oval.stroke() }
                else { colour.setFill(); oval.fill() }
            }
            for p in nodes { dot(p, nodeR, fleetColour, HOLLOW.contains(fleet)) }
            dot(c, hubR, machineColour, HOLLOW.contains(machine))
            return true
        }
        image.isTemplate = false
        return image
    }
}

let app = NSApplication.shared
let delegate = Bar()
app.delegate = delegate
app.setActivationPolicy(.accessory)  // the menu bar only, no Dock icon
app.run()
