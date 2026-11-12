/* The setup page. It shows what the app reports and sends what the person typed; every decision
 * (what is reached, what is allowed) is made by the same headless setup steps the commands use. */
const byId = id => document.getElementById(id);
const html = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const lines = id => byId(id).value.split('\n').map(line => line.trim()).filter(Boolean);
let token = null;
let wasEnrolled = null;

function say(text, tone = 'neutral') {
  const message = byId('message');
  message.textContent = text;
  message.className = `tone-${tone}`;
}

async function load(readiness = false) {
  const response = await fetch('/v1/setup' + (readiness ? '?readiness=1' : ''), {cache: 'no-store'});
  const state = await response.json();
  token = state.local_actions && state.local_actions.token;
  render(state);
  return state;
}

async function act(action, payload) {
  const response = await fetch('/v1/setup/' + action, {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-GitSpecOps-Token': token || ''},
    body: JSON.stringify(payload)});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || 'The app refused this step.');
  return body;
}

function renderTiers(state) {
  const block = byId('tiers');
  block.replaceChildren();
  for (const tier of state.tiers) {
    const card = html('article', undefined, 'card setup-tier' + (tier.reached ? ' reached' : '') +
                      (tier.id === state.next ? ' next' : ''));
    card.append(html('h3', (tier.reached ? '✓ ' : tier.id === state.next ? '→ ' : '') + tier.title));
    card.append(html('p', tier.reached ? 'Set up.' : 'Adds: ' + tier.needs));
    const list = html('ul');
    for (const item of tier.unlocks) list.append(html('li', item.text + (item.built ? '' : ' (planned)'),
                                                      item.built ? '' : 'tone-muted'));
    card.append(list);
    block.append(card);
  }
}

function renderMachine(state) {
  const machine = state.machine;
  const list = byId('libraries');
  list.replaceChildren();
  byId('presentation-card').hidden = !machine;
  byId('fleet-section').hidden = !machine;
  if (!machine) {
    byId('machine-summary').textContent = 'Not enrolled yet. Tell gitSpecOps which folders hold your repositories; nothing is looked at until you say so.';
    return;
  }
  byId('machine-summary').textContent = `${machine.label}: ${machine.libraries.length} librar${machine.libraries.length === 1 ? 'y' : 'ies'}.`;
  const items = html('ul', undefined, 'setup-list');
  for (const library of machine.libraries) {
    const row = html('li', library);
    if (machine.libraries.length > 1) {
      const remove = html('button', 'Remove', 'quiet');
      remove.type = 'button';
      remove.onclick = () => run('remove', {path: library});
      row.append(' ', remove);
    }
    items.append(row);
  }
  list.append(items);
  for (const input of document.querySelectorAll('input[name=face]')) input.checked = input.value === machine.presentation.face;
  for (const input of document.querySelectorAll('input[name=web]')) input.checked = input.value === machine.presentation.web;
}

function renderFleet(state) {
  const fleet = state.fleet;
  byId('leave-card').hidden = !fleet;
  byId('join-card').querySelector('h3').textContent = fleet ? 'Change how this machine shares' : 'Join or start a fleet';
  byId('fleet-summary').textContent = fleet
    ? `In fleet ${fleet.fleet_id}, sharing through: ${Object.keys(fleet.transports).join(', ')}.`
    : 'Join this machine to your others: a key from a machine already in your fleet, or a new fleet; then any ways to share.';
  if (state.readiness) {
    const ready = state.readiness;
    const report = byId('readiness-report');
    report.replaceChildren(
      html('p', `Git: ${ready.git ? 'ready' : 'missing (required)'}.`),
      html('p', `GitHub (for a managed repository): ${ready.github ? 'logged in' : 'no gh login'}.`),
      html('p', `Tailscale: ${ready.tailnet ? 'connected' : 'not connected'}.`),
      html('p', `Likely sync folders: ${ready.folders.length ? ready.folders.join(', ') : 'none found; you can still name one'}.`));
    byId('sync-folders').replaceChildren(...ready.folders.map(folder => Object.assign(document.createElement('option'), {value: folder})));
    byId('join-repo').disabled = !ready.github;
    byId('join-create').disabled = !ready.github;
    byId('join-tailnet').disabled = !ready.tailnet;
  }
}

function render(state) {
  if (state.error) say(state.error, 'danger');
  renderTiers(state);
  renderMachine(state);
  renderFleet(state);
  byId('to-map').hidden = !state.machine;
  if (wasEnrolled === false && state.machine) say('This machine is enrolled. The app is starting its map…', 'success');
  wasEnrolled = Boolean(state.machine);
}

async function run(action, payload) {
  say('Working…');
  try {
    const result = await act(action, payload);
    render(result.state);
    if (action === 'find') {
      const found = byId('found');
      found.replaceChildren();
      for (const item of result.found) {
        const row = html('li', `${item.repositories} repositories  ${item.path} `);
        const use = html('button', 'Use', 'quiet');
        use.type = 'button';
        use.onclick = () => { byId('add-paths').value = (byId('add-paths').value + '\n' + item.path).trim(); };
        row.append(use);
        found.append(row);
      }
      say(result.found.length ? 'Found folders that hold repositories. Choose the libraries, then Add.' : 'No repositories found there.');
    } else {
      say(result.notice || 'Saved.', 'success');
    }
  } catch (error) {
    say(error.message, 'danger');
  }
}

byId('find').onclick = () => run('find', {paths: lines('find-paths'), whole_machine: byId('find-whole').checked,
                                         confirm: byId('find-confirm').value.trim()});
byId('add').onclick = () => run('add', {paths: lines('add-paths'), confirm: byId('add-confirm').value.trim()});
byId('presentation').onclick = () => run('presentation', {
  face: (document.querySelector('input[name=face]:checked') || {}).value,
  web: (document.querySelector('input[name=web]:checked') || {}).value});
byId('join').onclick = () => run('join', {key: byId('join-key').value.trim(), folder: byId('join-folder').value.trim(),
                                         repo: byId('join-repo').value.trim(), create_repo: byId('join-create').checked,
                                         tailnet: byId('join-tailnet').checked, share_names: byId('join-names').checked,
                                         confirm: byId('join-confirm').value.trim()});
byId('leave').onclick = () => run('leave', {confirm: byId('leave-confirm').value.trim()});
byId('readiness').onclick = async () => { say('Checking Git, GitHub, Tailscale and sync folders…'); await load(true); say('Checked.'); };

load().catch(() => say('The app is not answering. Is it running?', 'danger'));
