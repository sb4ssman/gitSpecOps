/* App & setup: change this machine's setup from the page (the user, 2026-11-16).
 * Every control calls a setup route (App/_web/setup.py), which calls the same functions as
 * setup and the commands. Changes to the fleet show their plan first and apply only on "Apply".
 * Built once and redrawn only after an action, so the page's refresh never wipes what is typed. */

const el = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const button = (text, onClick) => { const b = el('button', text); b.type = 'button'; b.onclick = onClick; return b; };
const choice = (value, label) => { const o = el('option', label); o.value = String(value); return o; };
const every = seconds => seconds % 3600 === 0 && seconds >= 3600
  ? `every ${seconds / 3600} hour${seconds === 3600 ? '' : 's'}` : `every ${seconds / 60} minute${seconds === 60 ? '' : 's'}`;
const FETCH_LABELS = {0: 'Never (behind counts use the last fetch you made)', 60: 'Every hour', 360: 'Every 6 hours', 1440: 'Once a day'};

export function renderSettings(block, connection, token) {
  if (block.dataset.built === '1') return;
  block.dataset.built = '1';
  const state = {settings: null, message: '', plan: null};

  async function call(action, payload = {}) {
    return connection.desktopAction(`setup/${action}`, payload, token(), {structured: true});
  }

  async function load(message = '') {
    state.message = message;
    try { state.settings = (await call('settings')).settings; }
    catch (error) { state.message = error.message; }
    draw();
  }

  // A planned action: show its plan and question; "Apply" sends it back with the plan's id.
  async function planned(action, payload, onDone) {
    try {
      const first = await call(action, payload);
      if (first.applied) { onDone(first); return; }
      state.plan = {action, payload, result: first, onDone};
    } catch (error) { state.message = error.message; }
    draw();
  }

  function planBox() {
    const {action, payload, result, onDone} = state.plan;
    const box = el('div', undefined, 'capability');
    box.append(el('strong', result.question || 'Apply this?'));
    if (result.notice) box.append(el('p', result.notice, 'tone-text-warning'));
    const list = el('ul');
    const plan = result.plan || {};
    for (const line of plan.changes || Object.entries(plan).filter(([k]) => k !== 'action')
      .map(([k, v]) => `${k.replaceAll('_', ' ')}: ${Array.isArray(v) ? v.join(', ') : v}`)) list.append(el('li', line));
    box.append(list,
      button('Apply', async () => {
        try {
          const done = await call(action, {...payload, apply: result.plan_id});
          state.plan = null;
          if (done.applied) onDone(done); else { state.plan = {action, payload, result: done, onDone}; draw(); }
        } catch (error) { state.plan = null; state.message = error.message; draw(); }
      }),
      button('Cancel', () => { state.plan = null; state.message = 'Nothing was changed.'; draw(); }));
    return box;
  }

  function fleetSection(s) {
    const box = el('div', undefined, 'capability');
    box.append(el('strong', s.fleet_id ? `In fleet ${s.fleet_id}` : 'Not in a fleet'));
    if (s.fleet_id) {
      box.append(el('p', 'To add another machine: on it, join through this machine on Tailscale, or paste this machine\'s key.'));
      const shown = el('pre', '', 'host-note');
      box.append(button('Show the fleet key', () => planned('show-key', {}, done => {
        shown.textContent = done.key; state.message = done.notice || ''; draw(); box.append(shown);
      })), button('Leave the fleet', () => planned('leave', {}, () => load('Left the fleet. This machine keeps its libraries.'))));
      return box;
    }
    box.append(el('p', 'Join the fleet your other machines are in, or start one: turn on a connection below.'));
    const peers = el('div');
    box.append(button('Look for machines on Tailscale', async () => {
      peers.replaceChildren(el('p', 'Looking…', 'host-note'));
      try {
        const found = (await call('peers')).peers;
        peers.replaceChildren();
        if (!found.length) peers.append(el('p', 'No machine on your tailnet is sharing a fleet right now. On a machine in the fleet, the app must be running with Tailscale on.', 'host-note'));
        for (const peer of found) {
          peers.append(button(`Join through ${peer.label}`, () => planned('join',
            {via: peer.label, tailnet: true, tailnet_seconds: 300}, () => load(`Joined the fleet ${peer.label} is in.`))));
        }
      } catch (error) { peers.replaceChildren(el('p', error.message, 'tone-text-warning')); }
    }), peers);
    const key = el('input'); key.type = 'password'; key.placeholder = 'Fleet key (64 characters)'; key.autocomplete = 'off';
    box.append(el('p', 'Or paste the key shown on a machine already in the fleet:'), key,
      button('Join with this key', () => {
        const value = key.value.replace(/[\s-]/g, '').toLowerCase();
        if (!/^[0-9a-f]{64}$/.test(value)) { state.message = `A fleet key has 64 letters a-f and digits; this has ${value.length} characters.`; draw(); return; }
        planned('join', {key: value, tailnet: true, tailnet_seconds: 300}, () => load('Joined the fleet.'));
      }));
    return box;
  }

  function connectionsSection(s) {
    const c = s.connections;
    const box = el('div', undefined, 'capability');
    box.append(el('strong', 'Connections'), el('p', 'How this machine shares its report with the others. Any combination; each is another way a report arrives.'));
    const tailnet = el('input'); tailnet.type = 'checkbox'; tailnet.checked = c.tailnet.on;
    const seconds = el('select'); for (const value of c.tailnet.choices) seconds.append(choice(value, every(value)));
    seconds.value = String(c.tailnet.seconds);
    const tailnetNames = el('input'); tailnetNames.type = 'checkbox'; tailnetNames.checked = c.tailnet.names;
    const row1 = el('label'); row1.append(tailnet, ' Tailscale (live; only your own devices) — ask the others ', seconds);
    const row1b = el('label'); row1b.append(tailnetNames, ' with repository names');
    const folder = el('input'); folder.type = 'text'; folder.placeholder = 'A folder your sync client replicates (empty: off)';
    folder.value = c.folder.on ? c.folder.path : '';
    const folderNames = el('input'); folderNames.type = 'checkbox'; folderNames.checked = c.folder.names;
    const row2b = el('label'); row2b.append(folderNames, ' with repository names');
    const repo = el('input'); repo.type = 'text'; repo.placeholder = 'owner/name of a private state repository (experimental; empty: off)';
    repo.value = c.repo.on ? c.repo.name : '';
    const create = el('input'); create.type = 'checkbox';
    const row3b = el('label'); row3b.append(create, ' create it (private) if it does not exist');
    const repoNames = el('input'); repoNames.type = 'checkbox'; repoNames.checked = c.repo.names;
    const row3c = el('label'); row3c.append(repoNames, ' with repository names');
    box.append(row1, row1b, el('p', 'Synced folder', 'host-note'), folder, row2b,
      el('p', 'State repository', 'host-note'), repo, row3b, row3c,
      button('Review the change', () => planned('connections', {
        tailnet: tailnet.checked, tailnet_seconds: Number(seconds.value), folder: folder.value.trim(),
        repo: repo.value.trim(), create_repo: create.checked,
        names: {tailnet: tailnetNames.checked, folder: folderNames.checked, repo: repoNames.checked},
      }, done => load(done.notice || 'Saved.'))));
    return box;
  }

  function fetchSection(s) {
    const box = el('div', undefined, 'capability');
    box.append(el('strong', 'Fetch from GitHub'), el('p', 'Read-only git fetch of every repository, so "behind" means behind the remote now. Moves no branch and no file.'));
    const select = el('select'); for (const value of s.fetch_choices) select.append(choice(value, FETCH_LABELS[value] || `${value} minutes`));
    select.value = String(s.fetch_minutes);
    box.append(select, button('Save', async () => {
      try { await call('fetch', {minutes: Number(select.value)}); await load('Saved. The app uses the new schedule now.'); }
      catch (error) { state.message = error.message; draw(); }
    }));
    return box;
  }

  function signInSection(s) {
    const box = el('div', undefined, 'capability');
    box.append(el('strong', 'Start at sign-in'));
    if (!s.sign_in.supported) { box.append(el('p', s.sign_in.reason || 'Not available on this system.', 'host-note')); return box; }
    const toggle = el('input'); toggle.type = 'checkbox'; toggle.checked = s.sign_in.enabled;
    const label = el('label'); label.append(toggle, ' Start gitSpecOps when I sign in to this computer');
    toggle.onchange = async () => {
      try { const done = await call('sign-in', {enabled: toggle.checked}); state.settings = done.settings; state.message = done.notice; }
      catch (error) { state.message = error.message; }
      draw();
    };
    box.append(label);
    if (s.sign_in.elsewhere) box.append(el('p', `Turned off in ${s.sign_in.elsewhere}; turning it on here turns it back on.`, 'host-note'));
    return box;
  }

  function draw() {
    block.replaceChildren();
    const status = el('p', state.message, 'host-note'); status.setAttribute('role', 'status');
    if (state.message) block.append(status);
    if (state.plan) { block.append(planBox()); return; }
    const s = state.settings;
    if (!s) { block.append(el('p', 'Reading this machine\'s setup…', 'host-note')); return; }
    if (!s.enrolled) { block.append(el('p', 'This machine has no library yet: run setup first.', 'host-note')); return; }
    block.append(fleetSection(s), connectionsSection(s), fetchSection(s), signInSection(s));
  }

  draw();
  load();
}
