/* The menu (each item carries its tile: a number and a line) and the Machines and Clouds pages.
 * Tables only; every number is a display-contract fact (summary, machines, libraries, providers,
 * integrations) or a count of them. Nothing here decides what a state means.
 */
import {html, PROVIDER} from './fleet_grid.js';
import {machineActions} from './fleet_actions.js';

/** The menu, in the user's order (2026-11-16). `id` is the panel and the address (#map). */
export const MENU = [
  {id: 'map', label: 'Network map'},
  {id: 'repositories', label: 'Repositories'},
  {id: 'orgs', label: 'Orgs/Archives'},
  {id: 'machines', label: 'Machines'},
  {id: 'clouds', label: 'Clouds'},
  {id: 'security', label: 'Security'},
  {id: 'reference', label: 'Reference'},
  {id: 'settings', label: 'Settings'},
];

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Each menu item's number and line. `security` is the Security tab's own summary. */
export function menuTiles(data, security, reference) {
  const s = data.summary || {};
  const libraries = data.libraries || [];
  const talking = (data.integrations || []).filter(item => item.enabled).map(item => TRANSPORT_NAMES[item.id] || item.label);
  const providers = (data.providers || []).filter(item => item.host !== 'local').map(item => item.label);
  const machine = data.machines.find(item => item.id === data.this_machine);
  return {
    map: [String(s.machines ?? data.machines.length), `${plural(s.copies ?? s.repositories ?? 0, 'copy', 'copies')} · zoom in`],
    repositories: [String(s.repositories ?? data.rows.length), `${s.attention ?? 0} need attention`],
    orgs: [String(s.organizations ?? '—'), `in ${plural(s.libraries ?? libraries.length, 'library', 'libraries')}`],
    machines: [String(s.machines ?? data.machines.length), s.stale_machines ? `${s.stale_machines} stale` : 'all reports current'],
    clouds: [String(s.providers ?? providers.length), [...providers, ...talking].join(' · ') || 'none yet'],
    security: security,
    reference: reference || ['Reference', 'operations and documents'],
    settings: [data.fleet_name || (data.mark?.fleet?.state === 'none' ? 'No fleet' : 'Fleet'), machine ? machine.label : 'this machine'],
  };
}

export function renderMenu(nav, data, active, security, onSelect, reference) {
  const tiles = data.generated_at ? menuTiles(data, security, reference) : {};
  if (!nav.childElementCount) {
    for (const item of MENU) {
      const button = html('button', undefined, 'menu-tile'); button.type = 'button';
      button.dataset.tab = item.id;
      button.append(html('span', item.label, 'menu-label'), html('strong', '', 'menu-value'), html('small', '', 'menu-detail'));
      button.onclick = () => onSelect(item.id);
      nav.append(button);
    }
  }
  for (const button of nav.querySelectorAll('[data-tab]')) {
    const [value, detail] = tiles[button.dataset.tab] || ['', ''];
    button.querySelector('.menu-value').textContent = value;
    button.querySelector('.menu-detail').textContent = detail;
    button.setAttribute('aria-pressed', String(button.dataset.tab === active));
  }
}

const TRANSPORT_NAMES = {tailscale: 'Tailscale', synced_folder: 'Shared folder', github: 'gitso-managed repository'};

function table(headings, rows) {
  const t = html('table', undefined, 'data-table');
  const head = html('tr');
  for (const heading of headings) head.append(html('th', heading));
  const thead = html('thead'); thead.append(head); t.append(thead);
  const body = html('tbody');
  for (const cells of rows) {
    const line = html('tr');
    for (const cell of cells) line.append(cell instanceof Node ? (() => { const td = html('td'); td.append(cell); return td; })() : html('td', String(cell)));
    body.append(line);
  }
  t.append(body);
  const scroll = html('div', undefined, 'table-scroll'); scroll.append(t);
  return scroll;
}

/** Machines, each with its libraries under it. */
export function renderMachines(container, data, ageLabel, onOrg, actions = null, redraw = () => {}) {
  container.replaceChildren();
  if (!data.machines.length) { container.append(html('p', 'No machine has reported yet.', 'empty')); return; }
  const libraries = data.libraries || [];
  for (const machine of data.machines) {
    const card = html('article', undefined, 'card machine-card');
    const head = html('div', undefined, 'machine-head');
    head.append(html('h3', machine.id === data.this_machine ? `${machine.label} (this machine)` : machine.label),
                html('span', machine.freshness, `badge tone-${machine.tone}`));
    card.append(head);
    card.append(html('p', `Last report ${ageLabel(machine.age_seconds)} · ${plural(machine.repository_count, 'repository', 'repositories')} · device ID ${machine.id}`, 'host-note'));
    const mine = libraries.filter(entry => entry.machine_id === machine.id);
    if (mine.length) {
      // Libraries across, their numbers down (the user, 2026-11-17: no sideways scrolling).
      const label = id => (data.machines.find(m => m.id === id) || {label: id}).label;
      const t = html('table', undefined, 'data-table machine-libraries');
      const head = html('tr'); head.append(html('th', 'Library'));
      for (const entry of mine) {
        const th = html('th', entry.library || 'not named (an older report)');
        // The same disk from another system on the same box (a dual boot), named.
        for (const other of entry.same_disk_as || []) th.append(html('span', `same disk as ${label(other.machine_id)}: ${other.library}`, 'host-note'));
        head.append(th);
      }
      const thead = html('thead'); thead.append(head); t.append(thead);
      const body = html('tbody');
      for (const [name, value] of [['Repositories', e => e.repositories], ['Organizations', e => e.organizations],
                                   ['Need attention', e => (e.attention ? `⚑ ${e.attention}` : '0')]]) {
        const line = html('tr'); line.append(html('th', name));
        for (const entry of mine) line.append(html('td', String(value(entry))));
        body.append(line);
      }
      t.append(body);
      card.append(t);
    } else card.append(html('p', 'No library reported.', 'host-note'));
    // What this machine can be brought up to date with, as buttons (fleet_actions.js).
    const bar = machineActions({data, rows: data.rows, machine, scope: 'everything it has', actions, redraw, clone: false});
    if (bar) card.append(bar);
    container.append(card);
  }
  const issues = data.issues || [];
  if (issues.length) {
    const block = html('section', undefined, 'issue-list'); block.append(html('h3', 'Observation issues'));
    const entries = html('ul');
    for (const issue of issues) for (const item of issue.items) entries.append(html('li', `${issue.machine}: ${item}`));
    block.append(entries); container.append(block);
  }
}

/** Clouds: where repositories live online, and how the machines talk to each other. */
export function renderClouds(container, data) {
  container.replaceChildren();
  container.append(html('h3', 'Providers'));
  container.append(html('p', 'Where the repositories come from. Every copy on every machine is compared with its provider.', 'host-note'));
  const providers = data.providers || [];
  container.append(providers.length ? table(['Provider', 'Owners', 'Repositories', 'Need attention'], providers.map(entry => {
    const name = entry.host !== 'local' ? (() => { const a = html('a', `${PROVIDER[entry.host] || entry.label} ↗`); a.href = `https://${entry.host}`; a.target = '_blank'; a.rel = 'noopener'; return a; })() : entry.label;
    return [name, entry.owners, entry.repositories, entry.attention ? `⚑ ${entry.attention}` : '0'];
  })) : html('p', 'No repositories observed yet.', 'empty'));
  container.append(html('h3', 'How the machines talk'));
  container.append(html('p', 'Each machine reports what it holds by one or more of these. Change them in Settings.', 'host-note'));
  container.append(table(['Way', 'State', 'Detail'], (data.integrations || []).map(item => [
    TRANSPORT_NAMES[item.id] || item.label, item.enabled ? 'on' : item.available ? 'off' : 'not available',
    item.detail || item.description || ''])));
}
