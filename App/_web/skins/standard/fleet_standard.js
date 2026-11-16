/* The standard skin. It renders display v1 and never decides what Git state means. */
import {FleetConnection} from './fleet_client.js';
import {ageLabel, GroupExpansion, groupRows, regroup, selectRows} from './fleet_view.js';
import {renderMap, VIEWS} from './fleet_map.js';
import {renderSecurity} from './fleet_security.js';
import {renderSettings} from './fleet_settings.js';
import {renderRequests} from './fleet_requests.js';

const byId = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const state = {data: null, raw: null, selected: null, receivedAt: null,
               expansion: new GroupExpansion(savedCollapsedGroups()), grouping: savedGrouping()};
const desktopMessages = new Map();
const desktopPending = new Set();
// Session memory only: no report, browser storage, notification or fleet publication.
const securityResults = new Map();
const securityPending = new Set();
let desktopDraft = null;
const controls = {
  query: byId('search'), status: byId('status-filter'), machine: byId('machine-filter'),
  sort: byId('sort'), warning: byId('connection-warning'),
};

// Group by where repositories live (library, then folder) or by GitHub owner. Every view reads
// `groups` and each row's `group_id`, so one regrouping here regroups them all (2026-11-15).
function savedGrouping() {
  try { return localStorage.getItem('gitso.grouping') === 'owner' ? 'owner' : 'place'; } catch { return 'place'; }
}
function option(value, label) {
  const item = node('option', label); item.value = value; return item;
}

function savedTheme() {
  try { return localStorage.getItem('gitspecops-theme') || 'dark'; } catch { return 'dark'; }
}

function savedCollapsedGroups() {
  try {
    const value = JSON.parse(localStorage.getItem('gitspecops-collapsed-groups') || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  } catch { return []; }
}

function saveCollapsedGroups() {
  try { localStorage.setItem('gitspecops-collapsed-groups', JSON.stringify([...state.expansion.closed])); }
  catch { /* private storage may refuse */ }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  byId('theme').textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
  byId('theme').setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
  try { localStorage.setItem('gitspecops-theme', theme); } catch { /* private storage may refuse */ }
}

/** The mark: drawn by the server from the two signals the display document names. */
let markShown = '';
function renderMark() {
  byId('first-observation').hidden = Boolean(state.data.machines && state.data.machines.length);
  const mark = state.data.mark;
  if (!mark || !mark.machine || !mark.fleet) return;
  const m = mark.machine.state, f = mark.fleet.state;
  const words = `This machine: ${mark.machine.text} · Fleet: ${mark.fleet.text}`;
  byId('mark-text').textContent = words;
  const activity = state.data.activity || {phase: 'idle', text: ''};
  const working = m === 'starting' || (activity.phase && activity.phase !== 'idle');
  byId('activity-text').textContent = activity.text ? activity.text[0].toUpperCase() + activity.text.slice(1) : '';
  byId('activity').classList.toggle('working', Boolean(working));
  const banner = byId('first-observation');
  if (!banner.hidden && activity.text) banner.textContent = `${activity.text[0].toUpperCase() + activity.text.slice(1)}. ` +
    'Nothing is forgotten: your repositories appear here as soon as this machine has read them.';
  byId('mark').alt = `gitSpecOps. ${words}`;
  if (markShown === `${m}/${f}/${working}`) return;
  markShown = `${m}/${f}/${working}`;
  const url = (size, animate) => `/v1/mark.svg?machine=${encodeURIComponent(m)}&fleet=${encodeURIComponent(f)}&size=${size}${animate ? '&working=1' : ''}`;
  byId('mark').src = url(64, working);
  byId('favicon').href = url(32, false);
}

function renderSummary() {
  const {summary} = state.data;
  const values = [
    [summary.attention, 'Need attention', `${summary.repositories} repositories observed`],
    [summary.machines, 'Reporting machines', `${summary.current_machines} current`],
    [summary.stale_machines, 'Stale machines', summary.stale_machines ? 'Review before acting' : 'All reports current'],
    [state.data.groups.length, state.grouping === 'place' ? 'Folders observed' : 'Organizations observed',
     state.grouping === 'place' ? 'Grouped by library and folder' : 'Grouped by owner'],
  ];
  byId('summary').replaceChildren(...values.map(([value, label, detail]) => {
    const card = node('article', undefined, 'metric');
    card.append(node('strong', String(value)), node('span', label), node('small', detail));
    return card;
  }));
}

function renderFilters() {
  const chosenStatus = controls.status.value;
  controls.status.replaceChildren(...state.data.filters.map(item => option(item.id, item.label)));
  controls.status.value = state.data.filters.some(item => item.id === chosenStatus) ? chosenStatus : 'attention';
  const chosenMachine = controls.machine.value;
  controls.machine.replaceChildren(option('all', 'All machines'),
    ...state.data.machines.map(machine => option(machine.id, machine.label)));
  controls.machine.value = state.data.machines.some(item => item.id === chosenMachine) ? chosenMachine : 'all';
}

function cellBadge(cell) {
  const badge = node('span', cell.description, `badge tone-${cell.tone}`);
  badge.title = cell.description;
  return badge;
}

function showDetail(row) {
  state.selected = row.id;
  const panel = byId('detail'); panel.hidden = false; panel.replaceChildren();
  const head = node('div', undefined, 'detail-header');
  const identity = node('div'); identity.append(node('span', row.identity.host, 'host-note'), node('h3', row.name));
  const close = node('button', 'Close', 'quiet'); close.type = 'button';
  close.onclick = () => { state.selected = null; panel.hidden = true; renderRepositories(); };
  head.append(identity, close); panel.append(head);
  panel.append(node('p', row.advice, 'detail-advice'));
  if (row.publication && !row.publication.published) {
    panel.append(node('p', row.publication.reason, 'tone-text-warning'));
  }
  if (row.desktop_action) {
    const action = row.desktop_action;
    const button = node('button', action.label);
    button.type = 'button';
    button.disabled = !action.available || desktopPending.has(row.id) || !state.data.local_actions;
    button.title = action.reason;
    const message = node('p', desktopMessages.get(row.id) || action.reason, 'host-note');
    message.setAttribute('role', 'status');
    button.onclick = async () => {
      desktopPending.add(row.id); button.disabled = true;
      try {
        desktopMessages.set(row.id, await connection.desktopAction('open-git-client',
          {repo_id: row.id}, state.data.local_actions.token));
      } catch (error) { desktopMessages.set(row.id, error.message); }
      finally {
        desktopPending.delete(row.id);
        if (state.selected === row.id) showDetail(row);
      }
    };
    panel.append(button, message);
  }
  if (row.security_action) {
    const action = row.security_action;
    const button = node('button', action.label);
    button.type = 'button';
    button.disabled = !action.available || securityPending.has(row.id) || !state.data.local_actions;
    button.title = action.reason;
    button.onclick = async () => {
      securityPending.add(row.id); button.disabled = true;
      try {
        const result = await connection.desktopAction('security-preview', {repo_id: row.id},
          state.data.local_actions.token, {structured: true});
        securityResults.set(row.id, result);
      } catch (error) { securityResults.set(row.id, {message: error.message}); }
      finally {
        securityPending.delete(row.id);
        if (state.selected === row.id) showDetail(row);
      }
    };
    panel.append(button, node('p', securityPending.has(row.id) ? 'Checking local security…' : action.reason, 'host-note'));
    const result = securityResults.get(row.id);
    if (result) {
      panel.append(node('p', result.message, 'host-note'));
      for (const entry of result.local_security || []) {
        panel.append(node('p', `Checkout ${entry.checkout}: ${entry.security.check_status}; observed ${entry.security.observed_at}. Advisory snapshot; recheck before acting.`));
        const details = node('details');
        details.append(node('summary', 'Masked findings and coverage'), node('pre', JSON.stringify(entry.security, null, 2)));
        panel.append(details);
      }
    }
  }
  for (const machine of state.data.machines) {
    const cell = row.cells[machine.id];
    const section = node('section', undefined, 'detail-machine'); section.append(node('h4', machine.label), cellBadge(cell));
    if (cell.facts) {
      const facts = node('dl');
      const entries = [
        ['Staged', cell.facts.staged], ['Unstaged', cell.facts.unstaged],
        ['Untracked', cell.facts.untracked], ['Stashes', cell.facts.stashes],
        ['Ahead', cell.facts.ahead ?? 'Unknown'], ['Behind', cell.facts.behind ?? 'Unknown'],
        ['Upstream', cell.facts.has_upstream ? 'Configured' : 'Unknown'],
        ['Operation', cell.facts.operation ?? 'None'],
        ['Branch', cell.facts.branch ?? 'Not shared'],
        ['Commit', cell.facts.head ? cell.facts.head.slice(0, 10) : 'Not shared'],
      ];
      for (const [term, value] of entries) facts.append(node('dt', term), node('dd', String(value)));
      section.append(facts);
    }
    panel.append(section);
  }
  for (const current of document.querySelectorAll('tbody tr')) current.classList.toggle('selected', current.dataset.repoId === row.id);
}

function renderRepositories() {
  const data = state.data;
  const rows = selectRows(data, {query: controls.query.value, status: controls.status.value,
    machine: controls.machine.value, sort: controls.sort.value});
  const groups = groupRows(data, rows);
  byId('result-count').textContent = `${rows.length} of ${data.summary.repositories} repositories shown`;
  const list = byId('repository-list'); list.replaceChildren();
  if (!rows.length) {
    list.append(node('p', 'No repositories match these filters.', 'empty'));
    byId('detail').hidden = true; return;
  }
  // By library and folder: each library is a section, its folders inside it (the user,
  // 2026-11-16). By owner: one level, as before.
  const libraries = new Map();
  for (const group of groups) {
    const key = state.grouping === 'place' ? (group.host || 'Other machines') : '';
    if (!libraries.has(key)) libraries.set(key, []);
    libraries.get(key).push(group);
  }
  for (const [library, folders] of libraries) {
    let target = list;
    if (library) {
      const outer = node('details', undefined, 'repo-library');
      const outerId = `library/${library}`;
      outer.open = state.expansion.isOpen(outerId);
      outer.addEventListener('toggle', () => { state.expansion.record(outerId, outer.open); saveCollapsedGroups(); });
      const count = folders.reduce((sum, group) => sum + group.rows.length, 0);
      const total = folders.reduce((sum, group) => sum + (group.count ?? group.rows.length), 0);
      const attention = folders.reduce((sum, group) => sum + group.attention, 0);
      const head = node('summary'); head.append(document.createTextNode(library));
      head.append(node('span', `${folders.length} folder${folders.length === 1 ? '' : 's'} · ${shownOf(count, total)} · ${attention} need attention`, 'group-meta'));
      outer.append(head); list.append(outer); target = outer;
    }
    for (const group of folders) renderGroup(target, group, data);
  }
  const selected = rows.find(row => row.id === state.selected);
  if (selected) showDetail(selected); else { state.selected = null; byId('detail').hidden = true; }
}

function renderGroup(list, group, data) {
  {
    const details = node('details', undefined, 'repo-group');
    details.open = state.expansion.isOpen(group.id);
    details.addEventListener('toggle', () => {
      state.expansion.record(group.id, details.open);
      saveCollapsedGroups();
    });
    const summary = node('summary'); summary.append(document.createTextNode(group.label));
    summary.append(node('span', `${shownOf(group.rows.length, group.count ?? group.rows.length)} · ${group.attention} need attention`, 'group-meta'));
    details.append(summary);
    const scroll = node('div', undefined, 'table-scroll'); const table = node('table', undefined, 'repo-table');
    // The same column widths in every group, so the columns line up down the page.
    const columns = node('colgroup');
    const share = data.machines.length ? Math.floor(36 / data.machines.length) : 0;
    for (const width of [28, ...data.machines.map(() => share), 72 - share * data.machines.length]) {
      const col = node('col'); col.style.width = `${width}%`; columns.append(col);
    }
    table.append(columns);
    const header = node('tr');
    for (const title of ['Repository', ...data.machines.map(machine => machine.label), 'Advice']) header.append(node('th', title));
    const thead = node('thead'); thead.append(header); table.append(thead); const body = node('tbody');
    for (const row of group.rows) {
      const line = node('tr'); line.dataset.repoId = row.id;
      if (row.id === state.selected) line.classList.add('selected');
      const nameCell = node('td'); const link = node('button', row.identity.name, 'repo-link'); link.type = 'button';
      link.onclick = () => showDetail(row); nameCell.append(link, node('span', row.identity.host, 'host-note'));
      if (row.publication && !row.publication.published) {
        const held = node('span', 'not published', 'badge tone-warning');
        held.title = row.publication.reason; nameCell.append(held);
      }
      line.append(nameCell);
      for (const machine of data.machines) {
        const machineCell = node('td'); machineCell.append(cellBadge(row.cells[machine.id])); line.append(machineCell);
      }
      line.append(node('td', row.advice)); body.append(line);
    }
    table.append(body); scroll.append(table); details.append(scroll); list.append(details);
  }
}

function renderMachines() {
  const list = byId('machine-list'); list.replaceChildren();
  for (const machine of state.data.machines) {
    const card = node('article', undefined, 'card'); card.append(node('h3', machine.label),
      node('span', machine.freshness, `badge tone-${machine.tone}`));
    const facts = node('dl');
    for (const [term, value] of [['Last report', ageLabel(machine.age_seconds)],
      ['Repositories', machine.repository_count], ['Device ID', machine.id]]) facts.append(node('dt', term), node('dd', String(value)));
    card.append(facts); list.append(card);
  }
  const issues = byId('issues'); issues.replaceChildren();
  if (state.data.issues.length) {
    const block = node('section', undefined, 'issue-list'); block.append(node('h3', 'Observation issues'));
    const entries = node('ul');
    for (const issue of state.data.issues) for (const item of issue.items) entries.append(node('li', `${issue.machine}: ${item}`));
    block.append(entries); issues.append(block);
  }
}

function renderAbout() {
  const {product, fleet_id: fleetId, capabilities, integrations, features} = state.data;
  byId('product-version').textContent = `${product.name} ${product.version} · ${product.channel} channel`;
  const facts = byId('app-facts'); facts.replaceChildren();
  for (const [term, value] of [['Display contract', `${state.data.contract.name} v${state.data.contract.version}`],
    ['Fleet', state.data.mark?.fleet?.state === 'none' ? 'not in a fleet' : (state.data.fleet_name || 'in a fleet, not named yet')],
    ['Fleet ID (identifies it; not the key)', fleetId], ['Interface', 'Standard']]) facts.append(node('dt', term), node('dd', value));
  // On this computer the setup card holds every setting; the read-only summaries are for the
  // Tailscale view, where nothing can be changed.
  byId('integrations-card').hidden = Boolean(state.data.local_actions);
  byId('features-card').hidden = Boolean(state.data.local_actions);
  if (state.data.local_actions) {  // this computer only: never on the Tailscale view
    const open = node('button', 'Open settings folder');
    open.type = 'button';
    open.addEventListener('click', async () => {
      try { await connection.desktopAction('setup/open-folder', {}, state.data.local_actions.token, {structured: true}); }
      catch (error) { open.textContent = error.message; }
    });
    const value = node('dd'); value.append(open);
    facts.append(node('dt', 'Settings'), value);
  }
  const block = byId('capabilities'); block.replaceChildren();
  for (const [id, capability] of Object.entries(capabilities)) {
    const item = node('div', undefined, 'capability');
    item.append(node('strong', `${capability.available ? 'Available' : 'Unavailable'} · ${id.replaceAll('_', ' ')}`),
      node('p', capability.reason)); block.append(item);
  }
  if (state.data.baskets && state.data.baskets.configured) {
    const {scopes, withheld, unobserved} = state.data.baskets;
    const section = node('div', undefined, 'capability');
    section.append(node('strong', 'Baskets on this machine'),
      node('p', 'Observing, publishing and capture are separate. Change them with "fleet baskets".'));
    const facts = node('dl');
    for (const scope of ['observe', 'publish', 'capture']) {
      const selection = scopes[scope] || {};
      const listed = (selection.namespaces || []).join(', ');
      facts.append(node('dt', scope), node('dd', listed ? `${selection.mode} ${listed}` : selection.mode || 'unknown'));
    }
    section.append(facts);
    if (withheld) section.append(node('p', `${withheld} repository(ies) here are published to nothing.`, 'tone-text-warning'));
    if (unobserved) section.append(node('p', `${unobserved} repository(ies) under your roots are not observed.`, 'host-note'));
    block.append(section);
  }
  if (state.data.desktop_client && state.data.local_actions) {
    const client = state.data.desktop_client;
    const section = node('div', undefined, 'capability');
    section.append(node('strong', 'Primary desktop Git client'),
      node('p', 'Open a local checkout in your preferred app for commits, merges, rebases, and conflict resolution.'));
    const label = node('label', 'Use on this machine ');
    const select = node('select');
    select.append(option('', 'Disabled'), ...client.choices.map(item => option(item.id, item.label)));
    if (client.id && !client.choices.some(item => item.id === client.id)) {
      select.append(option(client.id, `${client.label} (unavailable)`));
    }
    select.value = desktopDraft ?? client.id;
    select.onchange = () => { desktopDraft = select.value; };
    label.append(select);
    const save = node('button', 'Save preference'); save.type = 'button';
    const result = node('p', desktopMessages.get('settings') || '', 'host-note');
    result.setAttribute('role', 'status');
    save.onclick = async () => {
      save.disabled = true;
      try {
        desktopMessages.set('settings', await connection.desktopAction('git-client',
          {client_id: select.value}, state.data.local_actions.token));
        desktopDraft = null;
        await connection.refresh();
      } catch (error) {
        desktopMessages.set('settings', error.message); result.textContent = error.message;
      } finally { save.disabled = false; }
    };
    section.append(label, save, result); block.append(section);
  }
  if (state.data.local_actions) {
    const section = node('div', undefined, 'capability');
    section.append(node('strong', 'Fleet catch-up'), node('p',
      'Fresh-fetch every locally observed checkout and show the same safe fast-forward plan as the terminal command. Applying pulls remains an explicit terminal confirmation.'));
    const preview = node('button', 'Preview catch-up'); preview.type = 'button';
    const result = node('pre', desktopMessages.get('catchup-preview') || '', 'host-note');
    preview.onclick = async () => {
      preview.disabled = true;
      try { desktopMessages.set('catchup-preview', await connection.desktopAction('catchup-preview', {}, state.data.local_actions.token)); }
      catch (error) { desktopMessages.set('catchup-preview', error.message); }
      finally { preview.disabled = false; renderAbout(); }
    };
    section.append(preview, result); block.append(section);
  }
  if (state.data.local_actions) {  // this computer only: never on the Tailscale view
    byId('setup-card').hidden = false;
    renderSettings(byId('setup-controls'), connection, () => state.data.local_actions.token);
  }
  renderSettingCards(byId('integrations'), integrations);
  renderSettingCards(byId('features'), features);
}

function renderSettingCards(block, settings) {
  block.replaceChildren();
  for (const setting of settings) {
    const item = node('div', undefined, 'capability');
    const title = node('strong', `${setting.enabled ? 'Enabled' : setting.available ? 'Available' : 'Planned'} · ${setting.label}`);
    item.append(title, node('p', setting.description));
    if (setting.detail) item.append(node('p', setting.detail, 'host-note'));
    block.append(item);
  }
}

function renderNotices() {
  const block = byId('notices'); block.replaceChildren();
  for (const notice of state.data.notices) block.append(node('p', notice.text, `tone-text-${notice.tone}`));
}

/** "10 of 11 shown" when the filters hide some: a folder never looks smaller than it is. */
function shownOf(shown, total) {
  return shown === total ? `${shown} shown` : `${shown} of ${total} shown (filters hide ${total - shown})`;
}

// The map's choices survive a reload (the user, 2026-11-16: reloading went back to the zoom map).
const MAP_DEFAULTS = {view: 'zoom', perspective: null, group: 'all', repo: null};
const mapOptions = (() => {
  try { return {...MAP_DEFAULTS, ...JSON.parse(localStorage.getItem('gitso.map') || '{}')}; } catch { return {...MAP_DEFAULTS}; }
})();
function saveMapOptions() {
  try { localStorage.setItem('gitso.map', JSON.stringify(mapOptions)); } catch { /* a remembered choice only */ }
}

function fillSelect(select, entries, chosen) {
  select.replaceChildren(...entries.map(([value, label]) => option(value, label)));
  if (entries.some(([value]) => value === chosen)) select.value = chosen;
}

function renderMapPanel() {
  const data = state.data;
  fillSelect(byId('map-view'), VIEWS, mapOptions.view);
  fillSelect(byId('map-perspective'), data.machines.map(m => [m.id, m.label]), mapOptions.perspective);
  fillSelect(byId('map-group'), [['all', 'All organizations'], ...data.groups.map(g => [g.id, g.label])], mapOptions.group);
  fillSelect(byId('map-repo'), data.rows.map(r => [r.id, r.name]), mapOptions.repo);
  mapOptions.perspective = byId('map-perspective').value || null;
  mapOptions.repo = byId('map-repo').value || null;
  byId('map-perspective').closest('label').hidden = mapOptions.view === 'zoom';
  byId('map-group').closest('label').hidden = mapOptions.view !== 'organization';
  byId('map-repo').closest('label').hidden = mapOptions.view !== 'repository';
  // Never a blank map: while the library is still being read, say so; if drawing fails, say why
  // and what to do (the user, 2026-11-16).
  const box = byId('map');
  if (!data.rows.length) {
    const activity = data.activity || {};
    box.replaceChildren(node('p', activity.phase && activity.phase !== 'idle'
      ? `Building the map: ${activity.text}.` : 'No repositories observed yet: add a library folder in App & setup.', 'empty'));
    return;
  }
  try {
    renderMap(box, data, {...mapOptions, actions: fleetActions()}, change => { Object.assign(mapOptions, change); saveMapOptions(); renderMapPanel(); });
  } catch (error) {
    box.replaceChildren(node('p', `The map could not be drawn (${error.message}). Switch to another map view above; `
      + 'if this one keeps failing, tell us the message.', 'tone-text-warning'));
  }
}

for (const [id, key] of [['map-view', 'view'], ['map-perspective', 'perspective'], ['map-group', 'group'], ['map-repo', 'repo']]) {
  byId(id).addEventListener('input', event => { mapOptions[key] = event.target.value; saveMapOptions(); if (state.data) renderMapPanel(); });
}

/** Requests to other machines and their uncommitted-work summaries: this computer only. */
function fleetActions() {
  if (!state.data.local_actions) return null;
  const act = (action, payload) => connection.desktopAction(action, payload, state.data.local_actions.token, {structured: true});
  return {act, send: payload => act('request-send', payload),
          changes: (repo_id, machine_id) => act('changes', {repo_id, machine_id})};
}

function renderAll() {
  renderSummary();
  renderRequests(byId('requests'), state.data, async (action, payload) => {
    const done = await fleetActions().act(action, payload); await connection.refresh(); return done;
  });
  renderFilters(); renderRepositories(); renderMapPanel(); renderSecurity(byId('security'), state.data, connection); renderMachines(); renderAbout(); renderNotices();
  byId('last-updated').textContent = `View received ${state.receivedAt.toLocaleTimeString()}`;
}

function selectTab(tab) {
  for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-pressed', String(button.dataset.tab === tab));
  for (const id of ['repositories', 'map', 'security', 'machines', 'about']) byId(`${id}-panel`).hidden = id !== tab;
  // The address always names the tab on screen, so reloading stays on it (the user, 2026-11-16).
  if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
}

for (const control of [controls.query, controls.status, controls.machine, controls.sort]) control.addEventListener('input', renderRepositories);
byId('grouping').value = state.grouping;
byId('grouping').onchange = () => {
  state.grouping = byId('grouping').value;
  try { localStorage.setItem('gitso.grouping', state.grouping); } catch { /* a remembered choice only */ }
  if (state.raw) { state.data = regroup(state.raw, state.grouping); renderAll(); }
};
byId('clear-filters').onclick = () => { controls.query.value = ''; controls.status.value = 'attention'; controls.machine.value = 'all'; controls.sort.value = 'attention'; renderRepositories(); };
byId('expand').onclick = () => {
  state.expansion.expandAll();
  saveCollapsedGroups();
  document.querySelectorAll('.repo-group, .repo-library').forEach(item => { item.open = true; });
};
byId('collapse').onclick = () => {
  state.expansion.collapseAll([...state.data.groups.map(group => group.id),
    ...new Set(state.data.groups.map(group => `library/${group.host || 'Other machines'}`))]);
  saveCollapsedGroups();
  document.querySelectorAll('.repo-group, .repo-library').forEach(item => { item.open = false; });
};
byId('theme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => selectTab(button.dataset.tab);
// An address ending in #map (gitso tray --open) or another tab's name opens at that tab, on load
// and when a link on the page (the header's home and App & setup links) changes it.
const TABS = ['repositories', 'map', 'security', 'machines', 'about'];
function tabFromAddress() { const tab = location.hash.slice(1); if (TABS.includes(tab)) selectTab(tab); }
tabFromAddress();
window.addEventListener('hashchange', tabFromAddress);

setTheme(savedTheme());
const connection = new FleetConnection();
// What the page does, said plainly (the user, 2026-11-16): every 3 seconds it asks the app on this
// computer what it already knows. That reads no repository and fetches nothing: the app itself
// checks a repository when its files change, and fetches on the schedule set in App & setup.
const LIVE = 'Live: updated every 3 seconds from this computer\'s gitSpecOps';
const LIVE_DETAIL = 'The page asks the app on this computer for what it already knows. That reads no repository and fetches nothing. The app checks a repository when its files change, and fetches from GitHub on the schedule set in App & setup.';
connection.addEventListener('display', event => {
  if (event.detail.data.setup_required) { window.location.href = '/setup'; return; }
  state.raw = event.detail.data; state.data = regroup(state.raw, state.grouping);
  state.receivedAt = event.detail.receivedAt;
  controls.warning.hidden = true;
  byId('connection').textContent = LIVE; byId('connection').title = LIVE_DETAIL;
  renderMark(); renderAll();
});
connection.addEventListener('unavailable', event => {
  byId('connection').textContent = 'Dashboard unavailable'; controls.warning.hidden = false;
  controls.warning.textContent = `Displayed data has been retained and may be stale. ${event.detail.message}`;
});
connection.start();
