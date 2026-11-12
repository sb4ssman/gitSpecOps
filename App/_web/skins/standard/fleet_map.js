/* The network map. Draws what the display contract says; decides nothing.
 *
 * Views: machines together (nodes and links), libraries (organizations per machine), one
 * organization across machines, one repository across machines. A chosen machine sets the
 * perspective: it comes first, sits at the centre, and the other copies are read against it.
 * Attention, freshness and whether copies agree all come from Python (`needs_attention`,
 * `freshness`, `map.links`, `row.copies`). Colour is never the only signal: every mark has text.
 */
import {renderZoom} from './fleet_zoom.js';

const SVG = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, text) => {
  const item = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
  if (text !== undefined) item.textContent = text;
  return item;
};
const html = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const toneOfFreshness = freshness => (freshness === 'current' ? 'success' : freshness === 'absent' ? 'muted' : 'warning');

export const VIEWS = [
  ['zoom', 'Zoomable map: clouds and machines'],
  ['machines', 'Machines together'],
  ['libraries', 'Libraries: host, organization, repository'],
  ['organization', 'One organization across machines'],
  ['repository', 'One repository across machines'],
];

/** Machines in reading order: the perspective first, then by label. */
export function orderedMachines(data, perspective) {
  return [...data.machines].sort((a, b) => (b.id === perspective) - (a.id === perspective)
    || a.label.localeCompare(b.label));
}

/** Rows of one organization (group), attention first; the same order every machine sees. */
export function rowsOf(data, groupId) {
  return data.rows.filter(row => groupId === 'all' || row.group_id === groupId)
    .sort((a, b) => (b.needs_attention - a.needs_attention) || a.name.localeCompare(b.name));
}

/** Per organization per machine: copies present and how many need attention. */
export function libraryCounts(data) {
  const counts = {};
  for (const row of data.rows) {
    for (const [machine, cell] of Object.entries(row.cells)) {
      if (!cell.present) continue;
      const key = `${row.group_id}\u0000${machine}`;
      counts[key] = counts[key] || {present: 0, attention: 0};
      counts[key].present += 1;
      counts[key].attention += row.needs_attention ? 1 : 0;
    }
  }
  return counts;
}

function machinesView(container, data, perspective, onPick) {
  const machines = orderedMachines(data, perspective);
  const size = 520, centre = size / 2, radius = machines.length > 1 ? 190 : 0;
  const place = {};
  machines.forEach((machine, index) => {
    if (index === 0 && machine.id === perspective) { place[machine.id] = [centre, centre]; return; }
    const ring = machines.length - (machines[0].id === perspective ? 1 : 0);
    const slot = index - (machines[0].id === perspective ? 1 : 0);
    const angle = (2 * Math.PI * slot) / Math.max(ring, 1) - Math.PI / 2;
    place[machine.id] = [centre + radius * Math.cos(angle), centre + radius * Math.sin(angle)];
  });
  const svg = el('svg', {viewBox: `0 0 ${size} ${size}`, class: 'map-svg', role: 'img',
                         'aria-label': 'Machines and the repositories they share'});
  for (const link of (data.map && data.map.links) || []) {
    if (!place[link.a] || !place[link.b]) continue;
    const [x1, y1] = place[link.a], [x2, y2] = place[link.b];
    const tone = link.differ ? 'warning' : 'success';
    const line = el('line', {x1, y1, x2, y2, class: `map-link tone-line-${tone}`,
                             'stroke-width': Math.min(2 + link.shared / 4, 12)});
    line.append(el('title', {}, `${link.shared} shared repositories; ${link.differ} on different commits; ${link.attention} need attention`));
    svg.append(line);
    svg.append(el('text', {x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 6, class: 'map-link-label'},
                  `${link.shared} shared${link.differ ? `, ${link.differ} differ` : ''}`));
  }
  for (const machine of machines) {
    const [x, y] = place[machine.id];
    const attention = data.rows.filter(row => row.cells[machine.id]?.present && row.needs_attention).length;
    const group = el('g', {class: 'map-node', tabindex: 0, role: 'button',
                           'aria-label': `${machine.label}: ${machine.freshness}, ${machine.repository_count} repositories, ${attention} need attention`});
    group.append(el('circle', {cx: x, cy: y, r: machine.id === perspective ? 46 : 38,
                               class: `map-machine tone-fill-${toneOfFreshness(machine.freshness)}`}));
    group.append(el('text', {x, y: y - 4, class: 'map-node-label'}, machine.label));
    group.append(el('text', {x, y: y + 13, class: 'map-node-detail'},
                    `${machine.repository_count} repos · ${attention} ⚑`));
    group.append(el('text', {x, y: y + 28, class: 'map-node-detail'}, machine.freshness));
    group.addEventListener('click', () => onPick({perspective: machine.id}));
    group.addEventListener('keydown', event => { if (event.key === 'Enter') onPick({perspective: machine.id}); });
    svg.append(group);
  }
  container.append(svg);
  container.append(html('p', 'Lines join machines that hold copies of the same repositories; ' +
    'thicker means more shared. Choose a machine to see the fleet from it.', 'map-note'));
}

function gridHead(machines, perspective, first) {
  const head = html('tr');
  head.append(html('th', first));
  for (const machine of machines) {
    const cell = html('th', machine.id === perspective ? `${machine.label} (perspective)` : machine.label);
    cell.className = `tone-${toneOfFreshness(machine.freshness)}`;
    head.append(cell);
  }
  return head;
}

const HOST_NAMES = {'github.com': 'GitHub', 'gitlab.com': 'GitLab', 'bitbucket.org': 'Bitbucket',
                    'local': 'No remote: only on a machine'};
// What is open in the tree, kept across refreshes (hosts start open, organizations closed).
const closedHosts = new Set();
const openGroups = new Set();

/** Where each library's repositories live: host, then organization, then repository. */
export function libraryTree(data) {
  const hosts = new Map();
  for (const group of data.groups) {
    if (!hosts.has(group.host)) hosts.set(group.host, []);
    hosts.get(group.host).push(group);
  }
  return [...hosts.entries()]
    .sort(([a], [b]) => (a === 'local') - (b === 'local') || a.localeCompare(b))
    .map(([host, groups]) => ({host, label: HOST_NAMES[host] || host, groups,
                               count: groups.reduce((sum, g) => sum + g.count, 0),
                               attention: groups.reduce((sum, g) => sum + g.attention, 0)}));
}

function countText(value) {
  return value && value.present ? `${value.present} here${value.attention ? ` · ${value.attention} need attention` : ''}` : '—';
}
function countTone(value) {
  return value && value.present ? (value.attention ? 'tone-warning' : '') : 'tone-muted';
}

function librariesView(container, data, perspective, onPick) {
  const machines = orderedMachines(data, perspective);
  const counts = libraryCounts(data);
  const redraw = () => { container.replaceChildren(); librariesView(container, data, perspective, onPick); };
  container.append(html('p', 'Every library as a tree: where repositories are hosted, then each ' +
    'organization, then each repository, with each machine’s copies lined up in the columns. ' +
    'Library folder paths stay private on each machine.', 'map-note'));
  const table = html('table', undefined, 'map-grid map-tree');
  table.append(gridHead(machines, perspective, 'Host · organization · repository'));
  const toggle = (label, open, onClick, level) => {
    const button = html('button', `${open ? '▾' : '▸'} ${label}`, `tree-toggle tree-${level}`);
    button.setAttribute('aria-expanded', String(open));
    button.onclick = onClick;
    return button;
  };
  for (const host of libraryTree(data)) {
    const hostOpen = !closedHosts.has(host.host);
    const line = html('tr', undefined, 'tree-host-row');
    const first = html('td');
    first.append(toggle(`${host.label} · ${host.groups.length} organization${host.groups.length === 1 ? '' : 's'}, ` +
                        `${host.count} repositories${host.attention ? `, ${host.attention} need attention` : ''}`,
                        hostOpen, () => { hostOpen ? closedHosts.add(host.host) : closedHosts.delete(host.host); redraw(); }, 'host'));
    line.append(first);
    for (const machine of machines) {
      const total = {present: 0, attention: 0};
      for (const group of host.groups) {
        const value = counts[`${group.id}\u0000${machine.id}`];
        if (value) { total.present += value.present; total.attention += value.attention; }
      }
      line.append(html('td', countText(total), countTone(total)));
    }
    table.append(line);
    if (!hostOpen) continue;
    for (const group of host.groups) {
      const groupOpen = openGroups.has(group.id);
      const row = html('tr', undefined, group.attention ? 'tree-group-row map-attention' : 'tree-group-row');
      const cell = html('td');
      cell.append(toggle(`${group.label} (${group.count})`, groupOpen,
                         () => { groupOpen ? openGroups.delete(group.id) : openGroups.add(group.id); redraw(); }, 'group'));
      const across = html('button', 'across machines', 'repo-link tree-open');
      across.onclick = () => onPick({view: 'organization', group: group.id});
      cell.append(across);
      row.append(cell);
      for (const machine of machines) {
        const value = counts[`${group.id}\u0000${machine.id}`];
        row.append(html('td', countText(value), countTone(value)));
      }
      table.append(row);
      if (!groupOpen) continue;
      for (const repo of rowsOf(data, group.id)) {
        const leaf = html('tr', undefined, repo.needs_attention ? 'tree-repo-row map-attention' : 'tree-repo-row');
        const name = html('button', `${repo.needs_attention ? '⚑ ' : ''}${repo.identity ? repo.identity.name : repo.name}`, 'repo-link tree-repo');
        name.onclick = () => onPick({view: 'repository', repo: repo.id});
        const lead = html('td'); lead.append(name); leaf.append(lead);
        for (const machine of machines) {
          const copy = repo.cells[machine.id];
          leaf.append(html('td', copyText(copy, repo, repo.cells[perspective]),
                           copy && copy.present ? `tone-${copy.tone}` : 'tone-muted'));
        }
        table.append(leaf);
      }
    }
  }
  container.append(table);
}

function copyText(cell, row, perspectiveCell) {
  if (!cell || !cell.present) return 'not here';
  const head = cell.facts && cell.facts.head;
  const mine = perspectiveCell && perspectiveCell.present && perspectiveCell.facts && perspectiveCell.facts.head;
  const relation = head && mine && cell !== perspectiveCell ? (head === mine ? ' · same commit' : ' · different commit') : '';
  return `${cell.description || cell.state}${relation}`;
}

function organizationView(container, data, perspective, group, onPick) {
  const machines = orderedMachines(data, perspective);
  const rows = rowsOf(data, group);
  const label = (data.groups.find(item => item.id === group) || {label: 'All organizations'}).label;
  container.append(html('p', `${label}: every repository, its copy on each machine lined up in one row.`, 'map-note'));
  const table = html('table', undefined, 'map-grid');
  table.append(gridHead(machines, perspective, 'Repository'));
  for (const row of rows) {
    const line = html('tr', undefined, row.needs_attention ? 'map-attention' : '');
    const name = html('button', `${row.needs_attention ? '⚑ ' : ''}${row.name}`, 'repo-link');
    name.onclick = () => onPick({view: 'repository', repo: row.id});
    const first = html('td'); first.append(name); line.append(first);
    for (const machine of machines) {
      const cell = row.cells[machine.id];
      line.append(html('td', copyText(cell, row, row.cells[perspective]),
                       cell && cell.present ? `tone-${cell.tone}` : 'tone-muted'));
    }
    table.append(line);
  }
  container.append(table);
}

function repositoryView(container, data, perspective, repo) {
  const row = data.rows.find(item => item.id === repo) || data.rows[0];
  if (!row) { container.append(html('p', 'No repositories reported yet.', 'empty')); return; }
  const machines = orderedMachines(data, perspective);
  const agree = row.copies ? row.copies.heads_agree : null;
  container.append(html('h3', row.name));
  container.append(html('p', `${row.advice} · ${row.copies ? row.copies.present : 0} copies · ` +
    (agree === null ? 'commits not shared' : agree ? 'every copy on the same commit' : 'copies on different commits'),
    row.needs_attention ? 'map-note tone-warning' : 'map-note'));
  const list = html('div', undefined, 'map-copies');
  for (const machine of machines) {
    const cell = row.cells[machine.id];
    const card = html('article', undefined, `card map-copy${machine.id === perspective ? ' map-perspective' : ''}`);
    card.append(html('h4', machine.id === perspective ? `${machine.label} (perspective)` : machine.label));
    card.append(html('p', copyText(cell, row, row.cells[perspective]), cell && cell.present ? `tone-${cell.tone}` : 'tone-muted'));
    if (cell && cell.present && cell.facts) {
      const facts = html('dl');
      for (const [key, value] of [['Branch', cell.facts.branch || 'not shared'],
                                  ['Commit', cell.facts.head ? cell.facts.head.slice(0, 12) : 'not shared'],
                                  ['Ahead', cell.facts.ahead], ['Behind', cell.facts.behind],
                                  ['Uncommitted', (cell.facts.unstaged || 0) + (cell.facts.staged || 0) + (cell.facts.untracked || 0)]]) {
        if (value === undefined || value === null) continue;
        facts.append(html('dt', key)); facts.append(html('dd', String(value)));
      }
      card.append(facts);
    }
    list.append(card);
  }
  container.append(list);
}

/** Render one view into `container`. `onPick` receives partial option changes. */
export function renderMap(container, data, options, onPick) {
  container.replaceChildren();
  if (options.view === 'zoom') { renderZoom(container, data); return; }
  const perspective = options.perspective && data.machines.some(m => m.id === options.perspective)
    ? options.perspective : (data.machines[0] || {}).id;
  if (!data.machines.length) { container.append(html('p', 'No machine has reported yet.', 'empty')); return; }
  if (options.view === 'libraries') librariesView(container, data, perspective, onPick);
  else if (options.view === 'organization') organizationView(container, data, perspective, options.group || 'all', onPick);
  else if (options.view === 'repository') repositoryView(container, data, perspective, options.repo);
  else machinesView(container, data, perspective, onPick);
}
