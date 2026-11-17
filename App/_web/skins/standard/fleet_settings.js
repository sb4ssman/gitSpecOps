/* Settings: change this machine's setup from the page (the user, 2026-11-16).
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
// Form pieces that read as controls: a checkbox beside its words, a field under its label, a row.
const section = (title, text) => {
  const box = el('div', undefined, 'capability setup-section-box');
  box.append(el('h4', title));
  if (text) box.append(el('p', text, 'host-note'));
  return box;
};
const row = (...items) => { const line = el('div', undefined, 'setting-row'); line.append(...items); return line; };
const check = (text, checked) => {
  const input = el('input'); input.type = 'checkbox'; input.checked = Boolean(checked);
  const label = el('label', undefined, 'setting-check'); label.append(input, el('span', text));
  return {label, input};
};
const field = (text, control) => {
  const label = el('label', undefined, 'setting-field'); label.append(el('span', text), control); return label;
};
const textInput = (value, placeholder) => {
  const input = el('input'); input.type = 'text'; input.value = value || ''; input.placeholder = placeholder || ''; return input;
};

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

  // A setting made at once: say what happened, then read the settings back.
  async function act(action, payload, message) {
    try { const done = await call(action, payload); await load(done.notice || message); }
    catch (error) { state.message = error.message; draw(); }
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
    const box = el('div', undefined, 'capability setup-section-box');
    if (s.fleet_id) {
      box.append(el('h4', `In the fleet ${s.fleet_name || '(not named yet: name it below)'}`),
        el('p', 'Your other machines join it by this name: in setup, or on this tab, "Look for your fleets on Tailscale".', 'host-note'));
      const name = textInput(s.fleet_name || '', 'For example: Home-Fleet'); name.maxLength = 60;
      box.append(row(field('Fleet name', name), button(s.fleet_name ? 'Rename' : 'Name it', async () => {
        try { const done = await call('name-fleet', {name: name.value}); state.settings = done.settings; state.message = done.notice; }
        catch (error) { state.message = error.message; }
        draw();
      })));
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
    box.append(el('h4', 'Not in a fleet'),
      el('p', 'Join the fleet your other machines are in, found by its name on Tailscale. Or start one: name it under Connections and turn a connection on.', 'host-note'));
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
    const box = section('Connections', 'How this machine and the others reach each other. Any combination; each is one more way a report arrives.');
    const fleetName = textInput('', 'My fleet'); fleetName.maxLength = 60;
    if (!s.fleet_id) box.append(field('Name for the new fleet (used when you turn a connection on)', fleetName));
    const tailnet = check('Tailscale: live, between your own devices only', c.tailnet.on);
    const seconds = el('select'); for (const value of c.tailnet.choices) seconds.append(choice(value, every(value)));
    seconds.value = String(c.tailnet.seconds);
    const tailnetNames = check('Show repository names to the other machines', c.tailnet.names);
    box.append(tailnet.label, row(field('Ask the other machines', seconds)), tailnetNames.label);
    const folder = textInput(c.folder.on ? c.folder.path : '', 'Empty: off');
    const folderNames = check('Carry repository names (the sync service can read them)', c.folder.names);
    box.append(el('h5', 'Synced folder'), field('A folder your sync client (OneDrive, Dropbox, Syncthing…) replicates', folder), folderNames.label);
    const repo = textInput(c.repo.on ? c.repo.name : '', 'owner/name; empty: off');
    const create = check('Create it, private, if it does not exist', false);
    const repoNames = check('Carry repository names', c.repo.names);
    box.append(el('h5', 'State repository (experimental)'), field('A private GitHub repository gitSpecOps keeps status in', repo),
      create.label, repoNames.label);
    box.append(row(button('Review the change', () => planned('connections', {
      tailnet: tailnet.input.checked, tailnet_seconds: Number(seconds.value), folder: folder.value.trim(),
      repo: repo.value.trim(), create_repo: create.input.checked, fleet_name: fleetName.value.trim(),
      names: {tailnet: tailnetNames.input.checked, folder: folderNames.input.checked, repo: repoNames.input.checked},
    }, done => load(done.notice || 'Saved.')))));
    return box;
  }

  function librariesSection(s) {
    const box = section('Library folders', 'The folders gitSpecOps watches for repositories. A repository\'s parent folder is its group on the Repositories tab.');
    for (const path of s.libraries) {
      box.append(row(el('code', path), button('Remove', () => {
        if (window.confirm(`Stop watching ${path}? Nothing in it is changed.`)) act('remove', {path}, 'Removed. The app reads its libraries again now.');
      })));
    }
    const add = textInput('', 'Full path of a folder that holds repositories');
    box.append(row(field('Add a library folder', add), button('Add', () => planned('add', {paths: [add.value.trim()]}, done => load(done.notice || 'Added.')))));
    return box;
  }

  function displaySection(s) {
    const box = section('How the app shows itself');
    const shown = s.presentation || {face: 'web', web: 'loopback'};
    const face = el('select'); face.append(choice('web', 'This web view'), choice('window', 'The app window'));
    face.value = shown.face;
    const web = el('select');
    web.append(choice('loopback', 'On this computer only'), choice('tailnet', 'Also on my Tailscale devices'), choice('off', 'Off'));
    web.value = shown.web;
    box.append(field('Double-clicking the tray icon opens', face), field('The web view is served', web),
      row(button('Save', () => act('presentation', {face: face.value, web: web.value}, 'Saved. Takes effect when the app restarts.'))));
    return box;
  }

  function basketsSection(s) {
    const box = section('What this machine watches and shares', 'By GitHub owner, written host/owner (github.com/your-org), separated by commas.');
    const MODES = [['all', 'Everything'], ['none', 'Nothing'], ['only', 'Only these owners'], ['except', 'Everything except these owners']];
    for (const [scope, title] of [['observe', 'Watch on this machine'], ['publish', 'Share with the other machines']]) {
      const current = (s.baskets || {})[scope] || {mode: 'all'};
      const mode = el('select'); for (const [value, label] of MODES) mode.append(choice(value, label));
      mode.value = current.mode;
      const names = textInput((current.namespaces || []).join(', '), 'github.com/owner, …');
      box.append(el('h5', title), row(mode, names, button('Save', () => act('baskets',
        {scope, mode: mode.value, namespaces: names.value}, 'Saved.'))));
    }
    const capture = ((s.baskets || {}).capture || {}).mode || 'none';
    box.append(el('p', `Recovery snapshots of unfinished work: ${capture === 'none' ? 'off' : capture}. They need a recovery location first (gitso recovery).`, 'host-note'));
    return box;
  }

  function sharedSection(s) {
    const shared = s.shared;
    const box = el('div', undefined, 'capability setup-section-box');
    box.append(el('h4', 'Shared protected values'),
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
      const seal = check('Also through the synced folder, sealed with a key from the fleet key', shared.sealed);
      box.append(seal.label);
      if (!shared.encryption_installed) box.append(el('p', 'Turning this on installs the cryptography package into this folder\'s .venv.', 'host-note'));
      box.append(row(button('Review the change', () => planned('seal', {enabled: seal.input.checked}, done => load(done.notice || 'Saved.')))));
    }
    return box;
  }

  function fetchSection(s) {
    const box = section('Fetch from GitHub', 'How often the app runs a read-only git fetch on every repository, so "behind" means behind GitHub now. It moves no branch and no file.');
    const select = el('select'); for (const value of s.fetch_choices) select.append(choice(value, FETCH_LABELS[value] || `${value} minutes`));
    select.value = String(s.fetch_minutes);
    box.append(row(field('Fetch every repository', select), button('Save', () => act('fetch', {minutes: Number(select.value)}, 'Saved. The app uses the new schedule now.'))));
    return box;
  }

  function signInSection(s) {
    const box = section('Start at sign-in');
    if (!s.sign_in.supported) { box.append(el('p', s.sign_in.reason || 'Not available on this system.', 'host-note')); return box; }
    const {label, input: toggle} = check('Start gitSpecOps when I sign in to this computer', s.sign_in.enabled);
    toggle.onchange = async () => {
      try { const done = await call('sign-in', {enabled: toggle.checked}); state.settings = done.settings; state.message = done.notice; }
      catch (error) { state.message = error.message; }
      draw();
    };
    box.append(label);
    if (s.sign_in.elsewhere) box.append(el('p', `Turned off in ${s.sign_in.elsewhere}; turning it on here turns it back on.`, 'host-note'));
    return box;
  }

  function tasksSection() {
    // The task log: what was asked of other machines, what was applied or dismissed here, and what
    // ran here; plus clearing finished or stale requests (the user, 2026-11-16).
    const box = section('Requests and the task log', 'Every request this machine sent, applied or dismissed, and every fleet action run here, newest first. Kept in tasks.log in the settings folder.');
    const list = el('div');
    const clear = async payload => {
      try {
        const done = await connection.desktopAction('request-clear', payload, token(), {structured: true});
        state.message = done.message; await connection.refresh();
      } catch (error) { state.message = error.message; }
      draw();
    };
    box.append(row(
      button('Show the task log', async () => {
        try {
          const tasks = (await call('tasks')).tasks;
          if (!tasks.length) { list.replaceChildren(el('p', 'Nothing yet.', 'host-note')); return; }
          const items = el('ul');
          for (const task of tasks.slice(0, 100)) {
            const item = el('li', `${new Date(task.at).toLocaleString()} · ${task.event} · ${task.kind || ''} · `
              + `${task.from || ''} → ${task.to || ''} · ${(task.repositories || []).join(', ')}`);
            if ((task.result || []).length) item.title = task.result.join('\n');  // the result, on hover
            items.append(item);
          }
          list.replaceChildren(items);
        } catch (error) { list.replaceChildren(el('p', error.message, 'tone-text-warning')); }
      }),
      button('Clear finished requests', () => clear({})),
      button('Clear every request this machine sent', () => {
        if (window.confirm('Withdraw every request this machine has sent, waiting or not? The task log keeps the record.')) clear({everything_sent: true});
      })), list);
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
    const grid = el('div', undefined, 'setup-sections');
    grid.append(fleetSection(s), connectionsSection(s), librariesSection(s), sharedSection(s), fetchSection(s),
      basketsSection(s), displaySection(s), signInSection(s), tasksSection());
    block.append(grid);
  }

  draw();
  load();
}
