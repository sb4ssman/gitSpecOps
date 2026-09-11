/* The standard skin. It renders display v1 and never decides what Git state means. */
import {FleetConnection} from './fleet_client.js';
import {ageLabel, GroupExpansion, groupRows, selectRows} from './fleet_view.js';

const byId = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const state = {data: null, selected: null, receivedAt: null, expansion: new GroupExpansion(savedCollapsedGroups())};
const controls = {
  query: byId('search'), status: byId('status-filter'), machine: byId('machine-filter'),
  sort: byId('sort'), refresh: byId('refresh'), warning: byId('connection-warning'),
};

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

function renderSummary() {
  const {summary} = state.data;
  const values = [
    [summary.attention, 'Need attention', `${summary.repositories} repositories observed`],
    [summary.machines, 'Reporting machines', `${summary.current_machines} current`],
    [summary.stale_machines, 'Stale machines', summary.stale_machines ? 'Review before acting' : 'All reports current'],
    [state.data.groups.length, 'Organizations observed', 'Baskets are planned'],
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
  for (const group of groups) {
    const details = node('details', undefined, 'repo-group');
    details.open = state.expansion.isOpen(group.id);
    details.addEventListener('toggle', () => {
      state.expansion.record(group.id, details.open);
      saveCollapsedGroups();
    });
    const summary = node('summary'); summary.append(document.createTextNode(group.label));
    summary.append(node('span', `${group.rows.length} shown · ${group.attention} need attention`, 'group-meta'));
    details.append(summary);
    const scroll = node('div', undefined, 'table-scroll'); const table = node('table');
    const header = node('tr');
    for (const title of ['Repository', ...data.machines.map(machine => machine.label), 'Advice']) header.append(node('th', title));
    const thead = node('thead'); thead.append(header); table.append(thead); const body = node('tbody');
    for (const row of group.rows) {
      const line = node('tr'); line.dataset.repoId = row.id;
      if (row.id === state.selected) line.classList.add('selected');
      const nameCell = node('td'); const link = node('button', row.identity.name, 'repo-link'); link.type = 'button';
      link.onclick = () => showDetail(row); nameCell.append(link, node('span', row.identity.host, 'host-note')); line.append(nameCell);
      for (const machine of data.machines) {
        const machineCell = node('td'); machineCell.append(cellBadge(row.cells[machine.id])); line.append(machineCell);
      }
      line.append(node('td', row.advice)); body.append(line);
    }
    table.append(body); scroll.append(table); details.append(scroll); list.append(details);
  }
  const selected = rows.find(row => row.id === state.selected);
  if (selected) showDetail(selected); else { state.selected = null; byId('detail').hidden = true; }
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
    ['Fleet ID', fleetId], ['Interface', 'Standard']]) facts.append(node('dt', term), node('dd', value));
  const block = byId('capabilities'); block.replaceChildren();
  for (const [id, capability] of Object.entries(capabilities)) {
    const item = node('div', undefined, 'capability');
    item.append(node('strong', `${capability.available ? 'Available' : 'Unavailable'} · ${id.replaceAll('_', ' ')}`),
      node('p', capability.reason)); block.append(item);
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

function renderAll() {
  renderSummary(); renderFilters(); renderRepositories(); renderMachines(); renderAbout(); renderNotices();
  byId('last-updated').textContent = `View received ${state.receivedAt.toLocaleTimeString()}`;
}

function selectTab(tab) {
  for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-pressed', String(button.dataset.tab === tab));
  for (const id of ['repositories', 'machines', 'about']) byId(`${id}-panel`).hidden = id !== tab;
}

for (const control of [controls.query, controls.status, controls.machine, controls.sort]) control.addEventListener('input', renderRepositories);
byId('clear-filters').onclick = () => { controls.query.value = ''; controls.status.value = 'attention'; controls.machine.value = 'all'; controls.sort.value = 'attention'; renderRepositories(); };
byId('expand').onclick = () => {
  state.expansion.expandAll();
  saveCollapsedGroups();
  document.querySelectorAll('.repo-group').forEach(item => { item.open = true; });
};
byId('collapse').onclick = () => {
  state.expansion.collapseAll(state.data.groups.map(group => group.id));
  saveCollapsedGroups();
  document.querySelectorAll('.repo-group').forEach(item => { item.open = false; });
};
byId('theme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => selectTab(button.dataset.tab);

setTheme(savedTheme());
const connection = new FleetConnection();
controls.refresh.onclick = () => connection.refresh();
connection.addEventListener('loading', () => { controls.refresh.disabled = true; });
connection.addEventListener('idle', () => { controls.refresh.disabled = false; });
connection.addEventListener('display', event => {
  state.data = event.detail.data; state.receivedAt = event.detail.receivedAt;
  controls.warning.hidden = true; byId('connection').textContent = 'Host connected'; renderAll();
});
connection.addEventListener('unavailable', event => {
  byId('connection').textContent = 'Host unavailable'; controls.warning.hidden = false;
  controls.warning.textContent = `Displayed data has been retained and may be stale. ${event.detail.message}`;
});
connection.start();
