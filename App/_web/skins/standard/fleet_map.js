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
  // "org:<name>" is every folder of that name, in every library on every machine: one machine's
  // two Sb4ssport-Alpha folders (a working library and a backup) showed one repository (2026-11-16).
  const name = groupId.startsWith('org:') ? groupId.slice(4) : null;
  return data.rows.filter(row => groupId === 'all' || (name ? row.namespace === name : row.group_id === groupId))
    .sort((a, b) => (b.needs_attention - a.needs_attention) || a.name.localeCompare(b.name));
}

/** The organization menu: each organization once, by name. */
export function organizationChoices(data) {
  return [...new Set(data.groups.map(group => group.label))].sort((a, b) => a.localeCompare(b))
    .map(label => [`org:${label}`, label]);
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
      counts[key].attention += cell.needs_attention ? 1 : 0;   // this machine's copy, not the row
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
    const attention = data.rows.filter(row => row.cells[machine.id]?.needs_attention).length;
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
      across.onclick = () => onPick({view: 'organization', group: `org:${group.label}`});
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

const PROVIDER = {'github.com': 'GitHub', 'gitlab.com': 'GitLab', 'bitbucket.org': 'Bitbucket'};

/** A copy, said against its one source of truth, the provider it comes from: "matches GitHub",
 *  "3 behind GitHub", "2 ahead of GitHub (not pushed)", with uncommitted files and extra copies
 *  named plainly (the user, 2026-11-16: "same commit as WHAT?"). As of that machine's last fetch. */
function copyText(cell, row) {
  if (!cell || !cell.present) return 'not here';
  const facts = cell.facts || {};
  const host = (row.identity || {}).host;
  const remote = PROVIDER[host] || (host && host !== 'local' ? host : null);
  const parts = [];
  const changed = (facts.staged || 0) + (facts.unstaged || 0) + (facts.untracked || 0);
  if (changed) parts.push(`${changed} uncommitted file${changed === 1 ? '' : 's'}`);
  if (!remote) parts.push('no remote: the only copy is on machines');
  else if (!facts.has_upstream) parts.push(`not linked to a branch on ${remote}`);
  else if (facts.ahead && facts.behind) parts.push(`${facts.ahead} ahead and ${facts.behind} behind ${remote}`);
  else if (facts.ahead) parts.push(`${facts.ahead} ahead of ${remote} (not pushed)`);
  else if (facts.behind) parts.push(`${facts.behind} behind ${remote}`);
  else parts.push(`matches ${remote}`);
  if (facts.stashes) parts.push(`${facts.stashes} stash${facts.stashes === 1 ? '' : 'es'}`);
  if ((facts.checkouts || 1) > 1) parts.push(`${facts.checkouts} copies on this machine`);
  return parts.join(' · ');
}

// What the organization view keeps across the page's refreshes: the last request's answer, and
// the uncommitted-work summary being shown.
const orgState = {message: '', changes: null};
const dirtyOf = cell => {
  const facts = (cell && cell.facts) || {};
  return (facts.staged || 0) + (facts.unstaged || 0) + (facts.untracked || 0);
};
const providerUrl = row => {
  const id = row.identity || {};
  return id.host && id.host !== 'local' && id.owner && id.name ? `https://${id.host}/${id.owner}/${id.name}` : null;
};

/** Each folder a machine keeps a repository in: its `copies` when it has several, else itself. */
const copiesOf = cell => (cell.copies && cell.copies.length ? cell.copies : [{...(cell.facts || {}), place: cell.place}]);

/** Libraries under machines: one column per library a machine keeps this organization in (two
 *  libraries, two columns; the user, 2026-11-16), one column when it keeps it in one or none. */
function columnsOf(machines, rows) {
  const columns = [];
  for (const machine of machines) {
    const libraries = [];
    for (const row of rows) {
      const cell = row.cells[machine.id];
      if (!cell || !cell.present) continue;
      for (const copy of copiesOf(cell)) {
        const library = (copy.place || {}).library;
        if (library && !libraries.includes(library)) libraries.push(library);
      }
    }
    libraries.sort((a, b) => a.localeCompare(b));
    if (libraries.length <= 1) columns.push({machine, library: libraries[0] || null, split: false});
    else for (const library of libraries) columns.push({machine, library, split: true});
  }
  return columns;
}

/** A copy's own colour, by the same rule Python uses for a whole cell. */
function copyTone(facts) {
  if (dirtyOf({facts}) || (facts.ahead && facts.behind)) return 'danger';
  if (facts.ahead || facts.behind || facts.stashes) return 'warning';
  return facts.has_upstream ? 'success' : 'neutral';
}

/** The repository's copy in one column: the machine's cell, or its copy in that column's library. */
function cellIn(row, column) {
  const cell = row.cells[column.machine.id];
  if (!cell || !cell.present) return null;
  if (!column.split) return cell;
  const copy = copiesOf(cell).find(item => (item.place || {}).library === column.library);
  if (!copy) return null;
  const facts = {...copy, checkouts: 1, has_remote: (cell.facts || {}).has_remote, identity: (cell.facts || {}).identity};
  return {...cell, copies: null, place: copy.place, facts, tone: cell.freshness === 'current' ? copyTone(facts) : 'warning'};
}

/** The provider's commit, from the machine that fetched most recently. */
function providerHead(row) {
  let best = null;
  for (const cell of Object.values(row.cells)) {
    if (!cell || !cell.present) continue;
    const stamp = (cell.facts || {}).upstream_observed_at || '';
    for (const copy of copiesOf(cell)) {
      if (copy.upstream_head && (!best || stamp > best.stamp)) best = {head: copy.upstream_head, stamp};
    }
  }
  return best && best.head;
}
const shortCommit = head => (head ? head.slice(0, 7) : '');

function organizationView(container, data, perspective, group, onPick, actions) {
  const machines = orderedMachines(data, perspective);
  const rows = rowsOf(data, group);
  const columns = columnsOf(machines, rows);
  // Alternate shades by machine, so a machine's libraries read as one block.
  const shades = new Map(machines.map((machine, index) => [machine.id, index % 2 ? 'map-shade-b' : 'map-shade-a']));
  const shadeOf = column => shades.get(column.machine.id);
  const startsGroup = column => columns.find(item => item.machine.id === column.machine.id) === column;
  const cellClass = (column, tone) => `${tone} ${shadeOf(column)}${startsGroup(column) ? ' map-group-start' : ''}`;
  const label = group.startsWith('org:') ? group.slice(4) : (data.groups.find(item => item.id === group) || {label: 'All organizations'}).label;
  container.append(html('p', `${label}: every repository, its copy on each machine lined up in one row, and where it lives online.`, 'map-note'));
  // In words first: what is in sync everywhere, and what needs a decision, from the advice Python
  // writes for each repository (the user, 2026-11-16: "I can't decipher this").
  const settled = rows.filter(row => !row.needs_attention && (row.copies || {}).heads_agree !== false);
  const open = rows.filter(row => !settled.includes(row));
  const verdict = html('div', undefined, open.length ? 'map-verdict map-verdict-open' : 'map-verdict');
  verdict.append(html('strong', open.length
    ? `${settled.length} of ${rows.length} are the same on every machine that has them. ${open.length} need${open.length === 1 ? 's' : ''} a decision:`
    : `All ${rows.length} are the same on every machine that has them.`));
  if (open.length) {
    const list = html('ul');
    for (const row of open) list.append(html('li', `${row.name}: ${row.advice}`));
    verdict.append(list);
  }
  container.append(verdict);
  const table = html('table', undefined, 'map-grid');
  table.classList.add('map-org');
  // Equal widths for every library column, whatever its words (the user, 2026-11-16).
  const widths = html('colgroup');
  widths.append(html('col', undefined, 'map-col-repo'), html('col', undefined, 'map-col-online'));
  for (const column of columns) widths.append(html('col'));
  table.append(widths);
  // Machines on the first header row, each spanning its libraries on the second: one machine with
  // two libraries under it, one shade per machine.
  const head = html('tr'), under = html('tr');
  const repo = html('th', 'Repository'), online = html('th', 'Online');
  repo.rowSpan = 2; online.rowSpan = 2;
  head.append(repo, online);
  for (const column of columns) {
    const first = columns.find(item => item.machine.id === column.machine.id) === column;
    if (first) {
      const span = columns.filter(item => item.machine.id === column.machine.id).length;
      const th = html('th', column.machine.id === perspective ? `${column.machine.label} (perspective)` : column.machine.label);
      th.className = `tone-${toneOfFreshness(column.machine.freshness)} ${shadeOf(column)} map-group-start`;
      th.colSpan = span;
      head.append(th);
    }
    under.append(html('th', column.library || '', `map-library ${shadeOf(column)}${first ? ' map-group-start' : ''}`));
  }
  table.append(head, under);
  if (actions) {
    // Ask a machine to bring this organization's copies forward, or to clone the ones it lacks.
    // The machine doing the work checks each one again and shows the request for approval.
    const asks = html('tr', undefined, 'map-asks');
    // The note's style on the text, not the cell: a block-level cell broke the header row's borders.
    const askLabel = html('td'); askLabel.append(html('span', 'Ask a machine:', 'host-note'));
    asks.append(askLabel, html('td'));
    for (const column of columns) {
      const machine = column.machine;
      const cell = html('td', undefined, cellClass(column, ''));
      // Only copies that are behind GitHub: a fast-forward is all this button can do. A copy on a
      // different commit that is not behind (ahead, diverged) needs a decision, not this button.
      const held = rows.filter(row => ((cellIn(row, column) || {}).facts || {}).behind > 0);
      // Missing from this column: from this library when the machine has several.
      const missing = rows.filter(row => !cellIn(row, column) && providerUrl(row));
      // This machine's own column runs here and now (you are at it); another machine's is a request
      // it shows on its own page (the user, 2026-11-16).
      const here = machine.id === data.this_machine;
      const ask = (kind, list) => async () => {
        if (here && !window.confirm(`${kind === 'pull' ? 'Fast-forward' : 'Clone'} ${list.length} here now? Each is fetched first and moved only if clean and simply behind; a clone replaces nothing.`)) return;
        orgState.message = here ? 'Working…' : orgState.message; onPick({});
        try {
          const done = await actions.send({to: machine.id, to_label: machine.label, kind, items: list.map(row => ({
            repo_id: row.id, name: (row.identity || {}).name || row.name, host: (row.identity || {}).host,
            owner: (row.identity || {}).owner, folder: (row.place || {}).folder || '',
            ...(column.library ? {library: column.library} : {})}))});
          orgState.message = done.message;
        } catch (error) { orgState.message = error.message; }
        onPick({});
      };
      const suffix = here ? ' here' : '';
      if (held.length) { const b = html('button', `Fast-forward ${held.length}${suffix}`); b.type = 'button'; b.onclick = ask('pull', held); cell.append(b); }
      if (missing.length) { const b = html('button', `Clone ${missing.length} missing${suffix}`); b.type = 'button'; b.onclick = ask('clone', missing); cell.append(b); }
      asks.append(cell);
    }
    table.append(asks);
  }
  for (const row of rows) {
    const line = html('tr', undefined, row.needs_attention ? 'map-attention' : '');
    const name = html('button', `${row.needs_attention ? '⚑ ' : ''}${row.name}`, 'repo-link');
    name.onclick = () => onPick({view: 'repository', repo: row.id});
    const first = html('td'); first.append(name); line.append(first);
    const online = html('td'); const url = providerUrl(row);
    if (url) { const link = html('a', `${(row.identity || {}).host} ↗`); link.href = url; link.target = '_blank'; link.rel = 'noopener'; online.append(link); }
    else online.append(html('span', 'no remote', 'host-note'));
    const upstream = providerHead(row);
    if (upstream) online.append(html('span', shortCommit(upstream), 'host-note'));
    line.append(online);
    for (const column of columns) {
      const machine = column.machine;
      const cell = cellIn(row, column);
      const td = html('td', undefined, cellClass(column, cell && cell.present ? `tone-${cell.tone}` : 'tone-muted'));
      if (actions && dirtyOf(cell)) {
        // Uncommitted work: ask that machine what it is (names and line counts, never contents).
        const show = html('button', copyText(cell, row, row.cells[perspective]), 'repo-link'); show.type = 'button';
        show.title = 'Show what the uncommitted work is';
        show.onclick = async () => {
          orgState.changes = {title: `${row.name} on ${machine.label}`, loading: true};
          onPick({});
          try { orgState.changes = {title: `${row.name} on ${machine.label}`, result: await actions.changes(row.id, machine.id)}; }
          catch (error) { orgState.changes = {title: `${row.name} on ${machine.label}`, error: error.message}; }
          onPick({});
        };
        td.append(show);
      } else td.textContent = !cell && column.split && (row.cells[machine.id] || {}).present
        ? `not in ${column.library}` : copyText(cell, row, row.cells[perspective]);
      // This copy's commit, faded, under its words; "not here" has none.
      const commit = cell && cell.present && shortCommit((cell.facts || {}).head);
      if (commit) td.append(html('span', commit, 'host-note'));
      line.append(td);
    }
    table.append(line);
  }
  if (orgState.message) container.append(html(orgState.message.includes('\n') ? 'pre' : 'p', orgState.message, 'host-note'));
  container.append(table);
  container.append(html('p', 'Each copy is compared with its provider as of that machine\'s last fetch. To fetch now on this '
    + 'machine: gitso fetch <organization folder>; or set a schedule in App & setup.', 'host-note'));
  if (orgState.changes) container.append(changesBox(orgState.changes));
}

function changesBox(view) {
  const box = html('div', undefined, 'map-changes');
  const close = html('button', 'Close'); close.type = 'button';
  close.onclick = () => { orgState.changes = null; box.remove(); };
  box.append(html('strong', `Uncommitted work: ${view.title}`), close);
  if (view.loading) { box.append(html('p', 'Asking…', 'host-note')); return box; }
  if (view.error) { box.append(html('p', view.error, 'tone-text-warning')); return box; }
  for (const [index, copy] of (view.result.copies || []).entries()) {
    box.append(html('p', `${view.result.copies.length > 1 ? `Copy ${index + 1}: ` : ''}${copy.summary}`));
    const list = html('ul');
    for (const file of copy.files || []) {
      const lines = file.added >= 0 && (file.added || file.deleted) ? ` +${file.added} −${file.deleted}` : '';
      list.append(html('li', `${file.name} · ${file.status}${lines}${file.line_endings_only ? ' · line endings only' : ''}`));
    }
    box.append(list);
  }
  return box;
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
    ? options.perspective : (data.machines.some(m => m.id === data.this_machine) ? data.this_machine : (data.machines[0] || {}).id);
  if (!data.machines.length) { container.append(html('p', 'No machine has reported yet.', 'empty')); return; }
  if (options.view === 'libraries') librariesView(container, data, perspective, onPick);
  else if (options.view === 'organization') organizationView(container, data, perspective, options.group || 'all', onPick, options.actions);
  else if (options.view === 'repository') repositoryView(container, data, perspective, options.repo);
  else machinesView(container, data, perspective, onPick);
}
