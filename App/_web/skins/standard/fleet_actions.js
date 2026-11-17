/* The operations as buttons, wherever a view shows something that needs one (the user,
 * 2026-11-17: "the app needs to be the conduit to the special operations"). Every view is a
 * slice of the same rows, so they share these: given some repositories and a machine, offer
 * what can be done there. On this machine it runs now; on another it is sent, and runs when
 * that machine next checks in. Both are the two operations that cannot lose work.
 */
import {html} from './fleet_grid.js';

const notes = new Map();  // what the last press said, per machine and scope

const hasProvider = row => Boolean(row.identity && row.identity.owner && row.identity.host && row.identity.host !== 'local');
const facts = (row, machineId) => { const cell = row.cells[machineId]; return cell && cell.present ? (cell.facts || {}) : null; };

/** What `rows` need on `machine`: {behind: rows a fast-forward would move, missing: rows it lacks}. */
export function needsOn(rows, machine) {
  return {
    behind: rows.filter(row => { const f = facts(row, machine.id); return f && f.behind > 0 && !(f.ahead > 0); }),
    missing: rows.filter(row => !facts(row, machine.id) && hasProvider(row)),
  };
}

/** Buttons for `rows` on `machine`. `scope` names the slice ("Sb4ssport-Alpha", "everything") for
 *  the words; `actions` is the page's fleet actions (absent on a read-only view); `redraw`
 *  repaints the view. Returns null when there is nothing to offer. */
export function machineActions({data, rows, machine, scope, actions, redraw, library = '', clone = true}) {
  if (!actions) return null;
  const {behind} = needsOn(rows, machine);
  // Clone only for a slice someone chose (an organization, a repository): never "everything the
  // fleet has that this machine lacks" in one click.
  const missing = clone ? needsOn(rows, machine).missing : [];
  const key = `${machine.id}/${scope}`;
  const note = notes.get(key);
  if (!behind.length && !missing.length && !note) return null;
  const here = machine.id === data.this_machine;
  const bar = html('div', undefined, 'act-bar');
  bar.append(html('strong', `${machine.label}${scope ? `, ${scope}` : ''}: `));
  const send = (kind, list) => async () => {
    const what = kind === 'pull' ? 'Fast-forward' : 'Clone';
    if (here && !window.confirm(`${what} ${list.length} here now? Each is fetched first and moved only if clean and simply behind; a clone replaces nothing.`)) return;
    notes.set(key, here ? 'Working…' : 'Sending…'); redraw();
    try {
      const done = await actions.send({to: machine.id, to_label: machine.label, kind, items: list.map(row => ({
        repo_id: row.id, name: (row.identity || {}).name || row.name, host: (row.identity || {}).host,
        owner: (row.identity || {}).owner, folder: (row.place || {}).folder || '', ...(library ? {library} : {})}))});
      notes.set(key, done.message);
    } catch (error) { notes.set(key, error.message); }
    redraw();
  };
  const where = here ? ' here' : '';
  if (behind.length) {
    const b = html('button', `Fast-forward ${behind.length} behind${where}`); b.type = 'button';
    b.title = here ? 'Fetch, then move each clean copy that is simply behind' : `Runs on ${machine.label} when it next checks in; the result appears under Requests`;
    b.onclick = send('pull', behind); bar.append(b);
  }
  if (missing.length) {
    const b = html('button', `Clone ${missing.length} missing${where}`, 'quiet'); b.type = 'button';
    b.title = 'A clone replaces nothing that exists';
    b.onclick = send('clone', missing); bar.append(b);
  }
  if (machine.freshness !== 'current' && !here && (behind.length || missing.length)) {
    bar.append(html('span', ' This machine is not reporting; a request waits until it is on.', 'host-note'));
  }
  if (note) {
    const said = html(note.includes('\n') ? 'pre' : 'span', note, 'host-note act-note');
    const clear = html('button', '×', 'quiet act-clear'); clear.type = 'button'; clear.title = 'Dismiss';
    clear.onclick = () => { notes.delete(key); redraw(); };
    bar.append(said, clear);
  }
  return bar;
}

/** One bar per machine that has something to do for `rows` (or the one machine given). */
export function actionBars(container, {data, rows, scope, actions, redraw, only = null, clone = true}) {
  if (!actions) return;
  const machines = only ? data.machines.filter(m => m.id === only) : data.machines;
  const box = html('div', undefined, 'act-bars');
  for (const machine of machines) {
    const bar = machineActions({data, rows, machine, scope, actions, redraw, clone});
    if (bar) box.append(bar);
  }
  if (box.childElementCount) container.append(box);
  else if (only) container.append(html('p', 'Nothing to fast-forward or clone here: every copy on this machine is current, ahead, or has work of its own.', 'host-note'));
}
