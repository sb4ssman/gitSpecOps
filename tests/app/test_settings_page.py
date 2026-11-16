"""The App & setup tab's controls (fleet_settings.js), run in Node against a minimal page stand-in
when Node is installed: it draws the sections, a change shows its plan, Apply sends the plan's id."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "App" / "_web" / "skins" / "standard" / "fleet_settings.js"
SCRIPT = r"""
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ''; this.attrs = {}; this.value = ''; this.style = {}; }
  append(...items) { for (const item of items) this.children.push(typeof item === 'string' ? Object.assign(new Node('#text'), {textContent: item}) : item); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  setAttribute(k, v) { this.attrs[k] = v; }
  all() { return [this, ...this.children.flatMap(child => child.all ? child.all() : [])]; }
  text() { return this.all().map(n => n.textContent).join(' '); }
}
globalThis.document = {createElement: tag => new Node(tag)};
const settings = {enrolled: true, fleet_id: null,
  connections: {tailnet: {on: false, seconds: 300, names: true, choices: [60, 300, 1800]},
                folder: {on: false, path: '', names: false}, repo: {on: false, name: '', names: false}},
  shared: {questions: [{id: 'q1', kind: 'remove', list: 'never_publish', value: 'old-name', from: 'desk'}], sealed: false, encryption_installed: false, has_folder: true},
  fetch_minutes: 1440, fetch_choices: [0, 60, 360, 1440], sign_in: {supported: true, enabled: false}};
const calls = [];
const connection = {desktopAction: async (action, payload) => {
  calls.push([action, payload]);
  if (action === 'setup/settings') return {settings, applied: true};
  if (action === 'setup/connections' && !payload.apply) return {applied: false, plan_id: 'p1', question: 'Connect this way?', plan: {changes: ['start a fleet', 'Tailscale: on']}};
  return {applied: true, notice: 'Saved.'};
}};
const {renderSettings} = await import(MODULE);
const block = new Node('div');
renderSettings(block, connection, () => 'token');
await new Promise(r => setTimeout(r, 10));
const out = {sections: block.text()};
const review = block.all().find(n => n.tag === 'button' && n.textContent === 'Review the change');
block.all().find(n => n.tag === 'input' && n.attrs.type !== 'x' && n.type === 'checkbox').checked = true;  // Tailscale on
await review.onclick(); await new Promise(r => setTimeout(r, 10));
out.plan = block.text();
const apply = block.all().find(n => n.tag === 'button' && n.textContent === 'Apply');
await apply.onclick(); await new Promise(r => setTimeout(r, 10));
out.calls = calls.map(([a, p]) => [a, p.apply || null, p.tailnet ?? null]);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class SettingsPageTests(unittest.TestCase):
    def test_draws_shows_the_plan_and_applies_it(self):
        done = subprocess.run(["node", "--input-type=module", "-e", SCRIPT.replace("MODULE", json.dumps(MODULE.as_uri()))],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        for words in ("Not in a fleet", "Look for your fleets on Tailscale", "Connections", "Fetch from GitHub",
                      "Shared protected values", "desk removed the never-publish value", "Remove it here too",
                      "Start at sign-in"):
            self.assertIn(words, out["sections"])
        self.assertIn("Connect this way?", out["plan"])
        self.assertIn("start a fleet", out["plan"])
        self.assertIn(["setup/connections", None, True], out["calls"])
        self.assertIn(["setup/connections", "p1", True], out["calls"])


if __name__ == "__main__":
    unittest.main()
