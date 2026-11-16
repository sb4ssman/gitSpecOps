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
  const state = {settings: null, message: '', plan: null, key: ''};

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
    if (s.fleet_id) {
      box.append(el('strong', `In the fleet ${s.fleet_name || '(unnamed)'}`),
        el('p', 'Your other machines join it by this name: in setup, or on this tab, "Look for your fleets on Tailscale".'));
      const name = el('input'); name.type = 'text'; name.value = s.fleet_name || ''; name.maxLength = 60;
      box.append(el('label', 'Name '), name, button('Rename', async () => {
        try { const done = await call('name-fleet', {name: name.value}); state.settings = done.settings; state.message = done.notice; }
        catch (error) { state.message = error.message; }
        draw();
      }));
      // The key belongs in a box of its own state: redrawing the tab must not lose it.
      const advanced = el('details'); advanced.append(el('summary', 'For a machine without Tailscale'));
      advanced.append(el('p', 'It joins with the fleet key instead. The key is 64 characters; the 16-character Fleet ID is not the key.', 'host-note'));
      if (state.key) advanced.append(el('pre', state.key, 'host-note'));
      advanced.append(button(state.key ? 'Hide the fleet key' : 'Show the fleet key', () => {
        if (state.key) { state.key = ''; draw(); return; }
        planned('show-key', {}, done => { state.key = done.key; state.message = done.notice || ''; draw(); });
      }));
      advanced.open = Boolean(state.key);
      box.append(advanced, button('Leave the fleet', () => planned('leave', {}, () => load('Left the fleet. This machine keeps its libraries.'))));
      return box;
    }
    box.append(el('strong', 'Not in a fleet'),
      el('p', 'Join the fleet your other machines are in, found by its name on Tailscale. Or start one: name it under Connections and turn a connection on.'));
    const found = el('div');
    box.append(button('Look for your fleets on Tailscale', async () => {
      found.replaceChildren(el('p', 'Looking…', 'host-note'));
      try {
        const fleets = (await call('fleets')).fleets;
        found.replaceChildren();
        if (!fleets.length) found.append(el('p', 'No fleet is answering on your tailnet. On a machine in the fleet, the app must be running with Tailscale as one of its connections.', 'host-note'));
        for (const fleet of fleets) {
          const item = el('div');
          item.append(button(`Join ${fleet.name}`, () => planned('join',
            {fleet_id: fleet.fleet_id, fleet_label: fleet.name, tailnet: true, tailnet_seconds: 300},
            () => load(`Joined ${fleet.name}.`))), el('span', ` on ${fleet.machines.join(', ')}`, 'host-note'));
          found.append(item);
        }
      } catch (error) { found.replaceChildren(el('p', error.message, 'tone-text-warning')); }
    }), found);
    const advanced = el('details'); advanced.append(el('summary', 'Without Tailscale: join with a fleet key'));
    const key = el('input'); key.type = 'password'; key.placeholder = 'Fleet key: 64 characters (not the 16-character Fleet ID)'; key.autocomplete = 'off';
    advanced.append(key, button('Join with this key', () => {
      const value = key.value.replace(/[\s-]/g, '').toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(value)) { state.message = `A fleet key is 64 characters long; this is ${value.length}. The 16-character Fleet ID is not the key.`; draw(); return; }
      planned('join', {key: value, tailnet: true, tailnet_seconds: 300}, () => load('Joined the fleet.'));
    }));
    box.append(advanced);
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
    const fleetName = el('input'); fleetName.type = 'text'; fleetName.placeholder = 'My fleet'; fleetName.maxLength = 60;
    if (!s.fleet_id) box.append(el('p', 'Name for the new fleet (when you turn a connection on):', 'host-note'), fleetName);
    box.append(row1, row1b, el('p', 'Synced folder', 'host-note'), folder, row2b,
      el('p', 'State repository', 'host-note'), repo, row3b, row3c,
      button('Review the change', () => planned('connections', {
        tailnet: tailnet.checked, tailnet_seconds: Number(seconds.value), folder: folder.value.trim(),
        repo: repo.value.trim(), create_repo: create.checked, fleet_name: fleetName.value.trim(),
        names: {tailnet: tailnetNames.checked, folder: folderNames.checked, repo: repoNames.checked},
      }, done => load(done.notice || 'Saved.'))));
    return box;
  }

  function sharedSection(s) {
    const shared = s.shared;
    const box = el('div', undefined, 'capability');
    box.append(el('strong', 'Shared protected values'),
      el('p', s.fleet_id
        ? 'Shared with your other machines over Tailscale. A value added on any machine is added here; a removal, or a newly allowed value, waits for your answer below.'
        : 'Shared once this machine is in a fleet.'));
    const WORDS = {never_publish: 'never-publish value', never_publish_words: 'whole-word never-publish value', safe_values: 'allowed value'};
    for (const q of shared.questions) {
      const item = el('div', undefined, 'host-note');
      const what = q.kind === 'remove' ? `${q.from} removed the ${WORDS[q.list]} ` : `${q.from} added the ${WORDS[q.list]} `;
      item.append(el('p', `${what}“${q.value}”.`));
      const answer = accept => async () => {
        try { const done = await call('shared-answer', {id: q.id, accept}); state.settings = done.settings; state.message = done.notice; }
        catch (error) { state.message = error.message; }
        draw();
      };
      item.append(button(q.kind === 'remove' ? 'Remove it here too' : 'Allow it here too', answer(true)),
        button('Keep this machine as it is', answer(false)));
      box.append(item);
    }
    if (shared.has_folder) {
      const seal = el('input'); seal.type = 'checkbox'; seal.checked = shared.sealed;
      const label = el('label'); label.append(seal, ' Also through the synced folder, sealed with a key from the fleet key');
      box.append(label);
      if (!shared.encryption_installed) box.append(el('p', 'Turning this on installs the cryptography package into this folder\'s .venv.', 'host-note'));
      box.append(button('Review the change', () => planned('seal', {enabled: seal.checked}, done => load(done.notice || 'Saved.'))));
    }
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
    block.append(fleetSection(s), connectionsSection(s), sharedSection(s), fetchSection(s), signInSection(s));
  }

  draw();
  load();
}
