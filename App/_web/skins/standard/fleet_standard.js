/* The standard skin. It renders display v1 and never decides what Git state means. */
import {FleetConnection} from './fleet_client.js';
import {ageLabel, GroupExpansion, groupRows, regroup, selectRows} from './fleet_view.js';
import {renderMap, VIEWS} from './fleet_map.js';
import {auditThese, renderSecurity, securitySummary} from './fleet_security.js';
import {columnsOf, copyGrid, GRID_FOOTNOTE, gridNotes, orderedMachines, perspectiveOf, placeTree} from './fleet_grid.js';
import {organizationChoices, renderOrgs} from './fleet_orgs.js';
import {MENU, renderClouds, renderMachines as drawMachines, renderMenu} from './fleet_pages.js';
import {notCountedSection, resolveBox} from './fleet_resolve.js';
import {referenceSummary, renderReference} from './fleet_reference.js';
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
  byId('away').hidden = !state.data.local_actions;  // offered at this computer only
  const mark = state.data.mark;
  if (!mark || !mark.machine || !mark.fleet) return;
  const m = mark.machine.state, f = mark.fleet.state;
  const words = `This machine: ${mark.machine.text} · Fleet: ${mark.fleet.text}`;
  // One short line: this machine, and the fleet in a few words; the full line on hover.
  byId('mark-text').textContent = `This machine: ${mark.machine.text} · Fleet: ${mark.fleet.short || mark.fleet.text}`;
  byId('mark-text').title = words;
  const activity = state.data.activity || {phase: 'idle', text: ''};
  const working = m === 'starting' || (activity.phase && activity.phase !== 'idle');
  renderActivity(activity.text ? activity.text[0].toUpperCase() + activity.text.slice(1) : '');
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

/** The live line; "N folders are second copies" opens the list of them (the user, 2026-11-17:
 *  "how do i use my tool to identify the offending duplicates, and see where they live?"). */
function renderActivity(text) {
  const line = byId('activity-text');
  const found = text.match(/\d+ folders? (?:is a|are) second cop(?:y|ies)/);
  if (!found) { line.textContent = text; return; }
  const link = node('a', found[0]); link.href = '#repositories';
  link.title = 'List the repositories with more than one folder on this machine';
  link.onclick = event => { event.preventDefault(); showSecondCopies(); };
  line.replaceChildren(text.slice(0, found.index), link, text.slice(found.index + found[0].length));
}

function showSecondCopies() {
  controls.query.value = '';
  controls.status.value = 'copies';
  controls.machine.value = state.data.this_machine;
  selectTab('repositories');
  renderRepositories();
}

/** The menu: each item carries its tile's number and line (the user, 2026-11-16). */
let activeTab = 'map';
function renderSummary() {
  renderMenu(byId('menu'), state.data, activeTab, securitySummary(), selectTab, referenceSummary());
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
  const panel = byId('detail');
  // Typing a commit message or using a control here: the 3-second refresh waits for you.
  if (state.selected === row.id && !panel.hidden && panel.contains(document.activeElement)
      && document.activeElement !== document.body) return;
  state.selected = row.id;
  panel.hidden = false; panel.replaceChildren();
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
  // Resolve here: the special operations for this machine's own copy (fleet_resolve.js).
  const here = row.cells[state.data.this_machine];
  if (state.data.local_actions && here && here.present) {
    const act = (op, extra = {}) => connection.desktopAction('repo-action', {op, repo_id: row.id, ...extra},
      state.data.local_actions.token, {structured: true});
    panel.append(resolveBox(row, here, act, () => { panel.replaceChildren(); state.selected = null; showDetail(row); }));
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
      const dirty = (cell.facts.staged || 0) + (cell.facts.unstaged || 0) + (cell.facts.untracked || 0);
      if (dirty && fleetActions()) section.append(uncommittedThere(row, machine, dirty));
    }
    panel.append(section);
  }
  for (const current of document.querySelectorAll('tbody tr')) current.classList.toggle('selected', current.dataset.repoId === row.id);
}

/** "What is uncommitted there?": that machine answers with file names and line counts (never
 *  contents). A machine that is off cannot answer; its counts are its last report. */
const asked = new Map();
function uncommittedThere(row, machine, dirty) {
  const key = `${row.id}/${machine.id}`, box = node('div', undefined, 'detail-changes');
  const view = asked.get(key);
  const ask = node('button', view ? 'Ask again' : `Show the ${dirty} uncommitted item${dirty === 1 ? '' : 's'}`, 'quiet'); ask.type = 'button';
  const redraw = () => { state.selected = null; showDetail(row); };
  ask.onclick = async () => {
    asked.set(key, {loading: true}); redraw();
    try { asked.set(key, {result: await fleetActions().changes(row.id, machine.id)}); }
    catch (error) {
      asked.set(key, {error: machine.freshness === 'current' ? error.message
        : `${machine.label} is not running gitSpecOps right now, so it cannot answer. These counts are its last report; ` +
          'the file names never leave a machine until it is asked. Open this page there, or ask again when it is on.'});
    }
    redraw();
  };
  box.append(ask);
  if (!view) return box;
  if (view.loading) box.append(node('p', `Asking ${machine.label}…`, 'host-note'));
  else if (view.error) box.append(node('p', view.error, 'tone-text-warning'));
  else for (const [index, copy] of (view.result.copies || []).entries()) {
    box.append(node('p', `${view.result.copies.length > 1 ? `Copy ${index + 1}: ` : ''}${copy.summary}`));
    const list = node('ul');
    for (const file of copy.files || []) {
      const lines = file.added >= 0 && (file.added || file.deleted) ? ` +${file.added} −${file.deleted}` : '';
      list.append(node('li', `${file.name} · ${file.status}${lines}${file.line_endings_only ? ' · line endings only' : ''}`));
    }
    box.append(list);
  }
  return box;
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
  const perspective = perspectiveOf(data, null);
  const grid = {perspective, columns: columnsOf(orderedMachines(data, perspective), rows, data.libraries)};
  if (state.grouping === 'place') renderPlaceTree(list, data, rows, grid);
  else for (const group of groups) renderGroup(list, group, data, grid);
  list.append(node('p', GRID_FOOTNOTE, 'host-note'));
  gridNotes(list);
  const selected = rows.find(row => row.id === state.selected);
  if (selected) showDetail(selected); else { state.selected = null; byId('detail').hidden = true; }
}

// Other machines start collapsed; the ones the person opened stay open across reloads.
const openedMachines = (() => {
  try { return new Set(JSON.parse(localStorage.getItem('gitso.openMachines') || '[]')); } catch { return new Set(); }
})();
function saveOpenedMachines() {
  try { localStorage.setItem('gitso.openMachines', JSON.stringify([...openedMachines])); } catch { /* a remembered choice only */ }
}

/** Machine > Library > Folder > Repositories, labelled at every level; this machine first and
 *  open, issues first at every level, every control still on the page (the user, 2026-11-16). */
function renderPlaceTree(list, data, rows, grid) {
  const here = perspectiveOf(data, null);
  const chosen = controls.machine.value;
  for (const branch of placeTree(data, rows, here)) {
    if (chosen !== 'all' && branch.machine.id !== chosen) continue;
    if (!branch.repositories) continue;
    const mine = branch.machine.id === here;
    const machineId = `m/${branch.machine.id}`;
    const outer = node('details', undefined, 'repo-machine');
    outer.open = mine || chosen !== 'all' ? state.expansion.isOpen(machineId) : openedMachines.has(machineId);
    outer.addEventListener('toggle', () => {
      if (mine || chosen !== 'all') state.expansion.record(machineId, outer.open);
      else if (outer.open) openedMachines.add(machineId); else openedMachines.delete(machineId);
      saveCollapsedGroups(); saveOpenedMachines();
    });
    const head = node('summary');
    head.append(node('span', 'Machine', 'level-label'), document.createTextNode(`${branch.machine.label}${mine ? ' (this machine)' : ''}`));
    head.append(node('span', `${branch.libraries.length} librar${branch.libraries.length === 1 ? 'y' : 'ies'} · ` +
      `${branch.repositories} repositories · ${branch.attention} need attention · ${branch.machine.freshness}`, 'group-meta'));
    outer.append(head); list.append(outer);
    for (const library of branch.libraries) {
      const libraryId = `${machineId}/${library.name}`;
      const inner = node('details', undefined, 'repo-library');
      inner.open = state.expansion.isOpen(libraryId);
      inner.addEventListener('toggle', () => { state.expansion.record(libraryId, inner.open); saveCollapsedGroups(); });
      const libHead = node('summary');
      libHead.append(node('span', 'Library', 'level-label'), document.createTextNode(library.name));
      libHead.append(node('span', `${library.folders.length} folder${library.folders.length === 1 ? '' : 's'} · ` +
        `${library.repositories} repositories · ${library.attention} need attention`, 'group-meta'));
      inner.append(libHead); outer.append(inner);
      for (const folder of library.folders) {
        renderGroup(inner, {id: `${libraryId}/${folder.name}`, label: folder.name, rows: folder.rows,
                            count: folder.rows.length, attention: folder.attention, level: 'Folder'}, data, grid);
      }
    }
  }
}

/** One group of the inventory: the shared copy grid, so a copy reads the same as on
 *  Orgs/Archives, with every group's columns lined up (`grid.columns`). */
function renderGroup(list, group, data, grid) {
  const details = node('details', undefined, 'repo-group');
  details.open = state.expansion.isOpen(group.id);
  details.addEventListener('toggle', () => {
    state.expansion.record(group.id, details.open);
    saveCollapsedGroups();
  });
  const summary = node('summary');
  if (group.level) summary.append(node('span', group.level, 'level-label'));
  summary.append(document.createTextNode(group.label));
  summary.append(node('span', `${shownOf(group.rows.length, group.count ?? group.rows.length)} · ${group.attention} need attention`, 'group-meta'));
  if (state.data.local_actions) {
    const audit = node('button', 'Audit these', 'quiet group-action'); audit.type = 'button';
    audit.title = 'Choose them on the Security tab; the audit starts when you press Audit there';
    audit.onclick = event => { event.preventDefault(); event.stopPropagation(); openAudit(group.rows.map(row => row.id)); };
    summary.append(audit);
  }
  details.append(summary);
  details.append(copyGrid(data, group.rows, {perspective: grid.perspective, columns: grid.columns, advice: true,
    actions: fleetActions(), onName: row => showDetail(row), onChange: renderRepositories}));
  list.append(details);
}

function renderMachines() {
  drawMachines(byId('machine-list'), state.data, ageLabel, null, fleetActions(), renderMachines);
}

function renderCloudsPanel() {
  renderClouds(byId('clouds'), state.data);
}

/** "Audit these": choose them on the Security tab and go there; the audit waits for Audit. */
function openAudit(repoIds) {
  auditThese(repoIds);
  selectTab('security');
}

/** A repository named on another page: open it in Repositories, its details shown. */
function openRepository(row) {
  controls.query.value = row.identity ? row.identity.name : row.name;
  controls.status.value = 'all';
  selectTab('repositories');
  renderRepositories();
  showDetail(row);
}

// Orgs/Archives: the organization and perspective survive a reload.
const orgOptions = (() => {
  try { return {group: 'all', ...JSON.parse(localStorage.getItem('gitso.orgs') || '{}'), perspective: null}; } catch { return {group: 'all', perspective: null}; }
})();
const unavailableActionsKey = 'gitso.showUnavailableActions';
let showUnavailableActions = (() => {
  try { return localStorage.getItem(unavailableActionsKey) !== 'false'; } catch { return true; }
})();

function unavailableActionsChoice() {
  const label = node('label', undefined, 'unavailable-actions-choice');
  const input = node('input');
  input.type = 'checkbox';
  input.checked = showUnavailableActions;
  input.onchange = () => {
    showUnavailableActions = input.checked;
    try { localStorage.setItem(unavailableActionsKey, String(input.checked)); } catch { /* private storage may refuse */ }
    for (const choice of document.querySelectorAll('.unavailable-actions-choice input')) choice.checked = input.checked;
    if (state.data) renderOrgsPanel();
  };
  label.append(input, document.createTextNode(' Show unavailable actions'));
  return label;
}

byId('orgs-perspective').closest('label').after(unavailableActionsChoice());

function renderOrgsPanel() {
  const data = state.data;
  fillSelect(byId('orgs-group'), [['all', 'All organizations'], ...organizationChoices(data)], orgOptions.group);
  fillSelect(byId('orgs-perspective'), data.machines.map(m => [m.id, m.label]), perspectiveOf(data, orgOptions.perspective));
  byId('orgs-perspective').closest('label').hidden = !byId('orgs-group').value || byId('orgs-group').value === 'all';
  renderOrgs(byId('orgs'), data, {group: byId('orgs-group').value, perspective: perspectiveOf(data, orgOptions.perspective),
    showUnavailable: showUnavailableActions}, {
    onPick: change => {
      Object.assign(orgOptions, change);
      try { localStorage.setItem('gitso.orgs', JSON.stringify({group: orgOptions.group})); } catch { /* a remembered choice only */ }
      renderOrgsPanel();
    },
    onAudit: data.local_actions ? openAudit : null, onRepository: openRepository, actions: fleetActions(),
  });
}
for (const [id, key] of [['orgs-group', 'group'], ['orgs-perspective', 'perspective']]) {
  byId(id).addEventListener('input', event => {
    orgOptions[key] = event.target.value;
    try { localStorage.setItem('gitso.orgs', JSON.stringify({group: orgOptions.group})); } catch { /* a remembered choice only */ }
    if (state.data) renderOrgsPanel();
  });
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
  if (state.data.local_actions && !byId('not-counted')) {
    // What this machine does not count, each with "Count again" (fleet_resolve.js).
    const section = node('div', undefined, 'capability'); section.id = 'not-counted';
    byId('capabilities').before(section);
    notCountedSection(section, (op, extra = {}) => connection.desktopAction('repo-action', {op, ...extra},
      state.data.local_actions.token, {structured: true}));
  }
  renderSettingCards(byId('integrations'), integrations);
  renderSettingCards(byId('features'), features);
  if (!byId('unavailable-actions-settings')) {
    const choice = unavailableActionsChoice();
    choice.id = 'unavailable-actions-settings';
    byId('integrations').before(choice);
  }
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
const MAP_DEFAULTS = {view: 'overview', perspective: null};
const mapOptions = (() => {
  try { return {...MAP_DEFAULTS, ...JSON.parse(localStorage.getItem('gitso.map') || '{}'), perspective: null}; } catch { return {...MAP_DEFAULTS}; }
})();
function saveMapOptions() {
  try { localStorage.setItem('gitso.map', JSON.stringify({...mapOptions, perspective: null})); } catch { /* a remembered choice only */ }
}

function fillSelect(select, entries, chosen) {
  select.replaceChildren(...entries.map(([value, label]) => option(value, label)));
  if (entries.some(([value]) => value === chosen)) select.value = chosen;
}

function renderMapPanel() {
  const data = state.data;
  fillSelect(byId('map-view'), VIEWS, mapOptions.view);
  mapOptions.view = byId('map-view').value;
  fillSelect(byId('map-perspective'), data.machines.map(m => [m.id, m.label]), perspectiveOf(data, mapOptions.perspective));
  mapOptions.perspective = byId('map-perspective').value || null;
  byId('map-perspective').closest('label').hidden = mapOptions.view !== 'machines';
  // Never a blank map: while the library is still being read, say so; if drawing fails, say why
  // and what to do (the user, 2026-11-16).
  const box = byId('map');
  if (!data.rows.length) {
    const activity = data.activity || {};
    box.replaceChildren(node('p', activity.phase && activity.phase !== 'idle'
      ? `Building the map: ${activity.text}.` : 'No repositories observed yet: add a library folder in Settings.', 'empty'));
    return;
  }
  try {
    renderMap(box, data, {...mapOptions, actions: fleetActions(), onRepository: openRepository}, change => { Object.assign(mapOptions, change); saveMapOptions(); renderMapPanel(); });
  } catch (error) {
    box.replaceChildren(node('p', `The map could not be drawn (${error.message}). Switch to another map view above; `
      + 'if this one keeps failing, tell us the message.', 'tone-text-warning'));
  }
}

for (const [id, key] of [['map-view', 'view'], ['map-perspective', 'perspective']]) {
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
  renderRequests(byId('requests'), state.data, async (action, payload) => {
    const done = await fleetActions().act(action, payload); await connection.refresh(); return done;
  });
  renderFilters(); renderRepositories(); renderMapPanel(); renderOrgsPanel(); renderSecurity(byId('security'), state.data, connection);
  renderMachines(); renderCloudsPanel(); renderAbout(); renderNotices();
  renderReference(byId('reference'), state.data.local_actions ? {
    call: payload => connection.desktopAction('reference', payload, state.data.local_actions.token, {structured: true}),
    data: () => state.data, actions: fleetActions,
    repoAction: payload => connection.desktopAction('repo-action', payload, state.data.local_actions.token, {structured: true}),
  } : null, renderSummary);
  renderSummary();  // after Security, so its tile shows the latest audit
  byId('last-updated').textContent = `View received ${state.receivedAt.toLocaleTimeString()}`;
}

function selectTab(tab) {
  activeTab = tab;
  for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-pressed', String(button.dataset.tab === tab));
  for (const {id} of MENU) byId(`${id}-panel`).hidden = id !== tab;
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
  for (const machine of state.data.machines) openedMachines.add(`m/${machine.id}`);
  saveCollapsedGroups(); saveOpenedMachines();
  document.querySelectorAll('.repo-group, .repo-library, .repo-machine').forEach(item => { item.open = true; });
};
byId('collapse').onclick = () => {
  const ids = [...state.data.groups.map(group => group.id)];
  for (const branch of placeTree(state.data, state.data.rows, perspectiveOf(state.data, null))) {
    ids.push(`m/${branch.machine.id}`);
    for (const library of branch.libraries) {
      ids.push(`m/${branch.machine.id}/${library.name}`);
      for (const folder of library.folders) ids.push(`m/${branch.machine.id}/${library.name}/${folder.name}`);
    }
  }
  state.expansion.collapseAll(ids);
  openedMachines.clear(); saveOpenedMachines();
  saveCollapsedGroups();
  document.querySelectorAll('.repo-group, .repo-library, .repo-machine').forEach(item => { item.open = false; });
};
// "On my other devices": where your phone or another computer opens this page (2026-11-17).
byId('away').onclick = async () => {
  const note = byId('away-note');
  if (!note.hidden) { note.hidden = true; return; }
  note.hidden = false; note.textContent = 'Looking…';
  try {
    const s = (await connection.desktopAction('setup/settings', {}, state.data.local_actions.token, {structured: true})).settings;
    if (s.remote_view) {
      const link = node('a', s.remote_view); link.href = s.remote_view; link.target = '_blank'; link.rel = 'noopener';
      const copy = node('button', 'Copy', 'quiet'); copy.type = 'button';
      copy.onclick = async () => { try { await navigator.clipboard.writeText(s.remote_view); copy.textContent = 'Copied'; } catch { copy.textContent = 'Select it and copy'; } };
      note.replaceChildren('The view from this machine, for your phone or another computer with Tailscale on the same account: ', link, ' ', copy,
        ' It is read-only and shows the fleet as this machine sees it.');
    } else {
      const open = node('a', 'Settings'); open.href = '#settings'; open.onclick = event => { event.preventDefault(); note.hidden = true; selectTab('settings'); };
      note.replaceChildren('Not shared with your other devices yet. In ', open,
        ', under "How the app shows itself", choose "Also on my Tailscale devices", save, and restart the app. Install Tailscale on the other device with the same account.');
    }
  } catch (error) { note.textContent = error.message; }
};
byId('theme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
// The menu is on screen from the start; its numbers arrive with the first report.
renderMenu(byId('menu'), {summary: {}, machines: [], rows: [], mark: {}}, activeTab, ['', ''], selectTab);
// An address ending in #map (gitso tray --open) or another tab's name opens at that tab, on load
// and when a link on the page (the header's home and Settings links) changes it.
const TABS = MENU.map(item => item.id);
// Older addresses keep working: #about was "App & setup", now Settings. #orgs/<name> opens one
// organization, so a link can point straight at it.
const ALIASES = {about: 'settings'};
function tabFromAddress() {
  const [asked, detail] = location.hash.slice(1).split('/');
  const tab = ALIASES[asked] || asked;
  if (tab === 'orgs' && detail) {
    orgOptions.group = `org:${decodeURIComponent(detail)}`;
    if (state.data) renderOrgsPanel();
  }
  selectTab(TABS.includes(tab) ? tab : 'map');
}
tabFromAddress();
window.addEventListener('hashchange', tabFromAddress);

setTheme(savedTheme());
const connection = new FleetConnection();
// What the page does, said plainly (the user, 2026-11-16): every 3 seconds it asks the app on this
// computer what it already knows. That reads no repository and fetches nothing: the app itself
// checks a repository when its files change, and fetches on the schedule set in Settings.
const LIVE = 'Live: updated every 3 seconds from this computer\'s gitSpecOps';
const LIVE_DETAIL = 'The page asks the app on this computer for what it already knows. That reads no repository and fetches nothing. The app checks a repository when its files change, and fetches from GitHub on the schedule set in Settings.';
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
