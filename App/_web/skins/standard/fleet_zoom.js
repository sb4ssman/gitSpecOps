/* The zoomable map: zoomed out, the clouds and the machines; click any of them to go deeper.
 *
 *   fleet         clouds (GitHub, GitLab, "no remote") above, machines below, a line for every
 *                 machine-cloud pair that shares repositories (thicker = more, amber = trouble)
 *   cloud         that host's organizations, sized by how many repositories they hold
 *   machine       that machine's library as a tree: host, then organization
 *   organization  its repositories, coloured by their worst copy
 *   repository    the remote and every machine's copy, with pull and push arrows
 *
 * It draws the display contract and decides nothing: trouble is a copy whose reported state is
 * not "synced"; attention, tones and advice come from Python. Library paths stay private, so a
 * machine's tree is its hosts and organizations. Every mark has text; colour is never alone.
 */
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
const clip = (text, size) => (text.length > size ? `${text.slice(0, size - 1)}…` : text);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const HOST_NAMES = {'github.com': 'GitHub', 'gitlab.com': 'GitLab', 'bitbucket.org': 'Bitbucket', local: 'No remote'};
const hostOf = row => (row.identity && row.identity.host && row.identity.host !== 'local' ? row.identity.host : 'local');
const hostName = host => HOST_NAMES[host] || host;
// The copy's own attention, decided in Python (the display contract); never recomputed here.
const trouble = cell => Boolean(cell && cell.present && cell.needs_attention);
const toneClass = tone => (tone === 'danger' ? 'z-danger' : tone === 'warning' ? 'z-warn' : tone === 'muted' ? 'z-muted' : 'z-ok');
// A cloud outline on a 32-unit box, centred near (16, 9), about 25 units wide.
const CLOUD = 'M7.5 16.3 A3.8 3.8 0 0 1 6.8 8.8 A6.2 6.2 0 0 1 18.6 6.4 A4.8 4.8 0 0 1 25.6 10.8 A2.9 2.9 0 0 1 25 16.3 Z';

/** Where the map is zoomed to: a path of levels, kept across refreshes of the data. */
const trail = [];
let motion = null;

export function zoomTo(step) { trail.push(step); motion = 'in'; }
function zoomOut(depth) { trail.length = depth; motion = 'out'; }

// ---- counting (from the contract; no new meaning) ---------------------------------------------
function hosts(data) {
  const found = new Map();
  for (const row of data.rows) {
    const host = hostOf(row);
    const entry = found.get(host) || {host, count: 0, attention: 0};
    entry.count += 1;
    entry.attention += row.needs_attention ? 1 : 0;
    found.set(host, entry);
  }
  return [...found.values()].sort((a, b) => (a.host === 'local') - (b.host === 'local') || b.count - a.count);
}
function onMachine(data, machineId, filter = () => true) {
  let count = 0, bad = 0;
  for (const row of data.rows) {
    const cell = row.cells[machineId];
    if (!cell || !cell.present || !filter(row)) continue;
    count += 1;
    bad += trouble(cell) ? 1 : 0;
  }
  return {count, bad};
}
function worstTone(row, machineId) {
  const cells = machineId ? [row.cells[machineId]] : Object.values(row.cells);
  const tones = cells.filter(c => c && c.present).map(c => c.tone);
  if (!tones.length) return 'muted';
  return tones.includes('danger') ? 'danger' : tones.includes('warning') || row.needs_attention ? 'warning' : 'success';
}

// ---- drawing pieces -------------------------------------------------------------------------
function node(svg, {label, onOpen}) {
  const group = el('g', {class: 'z-node', tabindex: 0, role: 'button', 'aria-label': label});
  group.addEventListener('click', onOpen);
  group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(); } });
  svg.append(group);
  return group;
}
function cloud(svg, x, y, width, host, detail, tone, onOpen) {
  const s = width / 25;
  const group = node(svg, {label: `${hostName(host)}: ${detail}. Open.`, onOpen});
  group.append(el('path', {d: CLOUD, transform: `translate(${x - 16 * s} ${y - 11 * s}) scale(${s})`,
                           class: `z-cloud ${toneClass(tone)}${host === 'local' ? ' z-dashed' : ''}`,
                           'vector-effect': 'non-scaling-stroke'}));
  group.append(el('text', {x, y: y - 2, class: 'z-label'}, hostName(host)));
  group.append(el('text', {x, y: y + 16, class: 'z-detail'}, detail));
  return group;
}
function machineBox(svg, x, y, machine, detail, tone, onOpen) {
  const group = node(svg, {label: `${machine.label}: ${detail}. Open.`, onOpen});
  group.append(el('rect', {x: x - 88, y: y - 38, width: 176, height: 76, rx: 10, class: `z-machine ${toneClass(tone)}`}));
  group.append(el('text', {x, y: y - 10, class: 'z-label'}, clip(machine.label, 20)));
  group.append(el('text', {x, y: y + 9, class: 'z-detail'}, detail));
  group.append(el('text', {x, y: y + 25, class: 'z-detail'}, machine.freshness === 'current' ? 'reporting' : machine.freshness));
  return group;
}
/** `at` places the label along the line (0 at the start, 1 at the end): links that fan out from
 *  several clouds would otherwise put every label at the same height, on top of each other. */
function link(svg, x1, y1, x2, y2, width, tone, label, curve = 0, at = 0.5) {
  const mx = (x1 + x2) / 2 + curve, my = (y1 + y2) / 2, u = 1 - at;
  svg.append(el('path', {d: `M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`, class: `z-link ${toneClass(tone)}`, 'stroke-width': width}));
  if (label) svg.append(el('text', {x: u * u * x1 + 2 * u * at * mx + at * at * x2,
                                    y: u * u * y1 + 2 * u * at * my + at * at * y2 - 6, class: 'z-link-label'}, label));
}
function frame(container, height, title) {
  const svg = el('svg', {viewBox: `0 0 1000 ${height}`, class: 'zoom-svg', role: 'group', 'aria-label': title});
  if (motion && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    svg.classList.add(motion === 'in' ? 'z-enter-in' : 'z-enter-out');
    requestAnimationFrame(() => requestAnimationFrame(() => svg.classList.add('z-settled')));
  }
  motion = null;
  container.append(svg);
  return svg;
}

// ---- levels ---------------------------------------------------------------------------------
/** Each machine's library for the fleet level: host and organization headings, then each
 *  repository it holds (its own unfinished work first), at most `limit` lines. */
function libraryLines(data, machineId, limit) {
  const byOrg = new Map();
  for (const row of data.rows) {
    const cell = row.cells[machineId];
    if (!cell || !cell.present) continue;
    const key = `${hostOf(row)}\u0000${row.group_id}`;
    if (!byOrg.has(key)) byOrg.set(key, {host: hostOf(row), id: row.group_id, label: row.namespace, repos: []});
    byOrg.get(key).repos.push({row, cell});
  }
  const lines = [];
  const orgs = [...byOrg.values()].sort((a, b) => a.host.localeCompare(b.host) || a.label.localeCompare(b.label));
  const total = orgs.reduce((sum, org) => sum + 1 + org.repos.length, 0);
  for (const org of orgs) {
    if (lines.length >= limit - 1) break;
    lines.push({kind: 'org', org});
    org.repos.sort((a, b) => trouble(b.cell) - trouble(a.cell) || a.row.name.localeCompare(b.row.name));
    for (const repo of org.repos) {
      if (lines.length >= limit - 1) break;
      lines.push({kind: 'repo', ...repo});
    }
  }
  const shown = lines.filter(line => line.kind === 'repo').length;
  const all = orgs.reduce((sum, org) => sum + org.repos.length, 0);
  if (lines.length < total && all > shown) lines.push({kind: 'more', count: all - shown});
  return lines;
}

const LIBRARY_TOP = 640, LIBRARY_LINE = 19, LIBRARY_LIMIT = 16;

function fleetLevel(container, data) {
  const clouds = hosts(data), machines = [...data.machines].sort((a, b) => a.label.localeCompare(b.label));
  const libraries = new Map(machines.map(m => [m.id, libraryLines(data, m.id, LIBRARY_LIMIT)]));
  const deepest = Math.max(0, ...[...libraries.values()].map(lines => lines.length));
  const svg = frame(container, deepest ? LIBRARY_TOP + deepest * LIBRARY_LINE + 20 : 600,
                    'The fleet: clouds, machines and their libraries');
  const xs = (n, i) => (1000 / (n + 1)) * (i + 1);
  const cloudAt = new Map(clouds.map((c, i) => [c.host, [xs(clouds.length, i), 120]]));
  const machineAt = new Map(machines.map((m, i) => [m.id, [xs(machines.length, i), 470]]));
  for (const [i, a] of machines.entries()) {               // machine to machine, below
    for (const b of machines.slice(i + 1)) {
      const shared = (data.map && data.map.links || []).find(l => (l.a === a.id && l.b === b.id) || (l.a === b.id && l.b === a.id));
      if (!shared) continue;
      const [x1, y1] = machineAt.get(a.id), [x2, y2] = machineAt.get(b.id);
      svg.append(el('path', {d: `M${x1} ${y1 + 38} Q${(x1 + x2) / 2} ${y1 + 130} ${x2} ${y2 + 38}`,
                             class: `z-link ${toneClass(shared.differ ? 'warning' : 'success')}`, 'stroke-width': 3}));
      svg.append(el('text', {x: (x1 + x2) / 2, y: y1 + 100, class: 'z-link-label'},
                    `${shared.shared} shared${shared.differ ? `, ${shared.differ} on different commits` : ''}`));
    }
  }
  for (const [m, machine] of machines.entries()) {          // machine to cloud
    for (const [c, host] of clouds.entries()) {
      const {count, bad} = onMachine(data, machine.id, row => hostOf(row) === host.host);
      if (!count) continue;
      const [x1, y1] = cloudAt.get(host.host), [x2, y2] = machineAt.get(machine.id);
      // Each machine's labels at their own height, each cloud's a little apart: never stacked.
      const at = Math.min(0.8, 0.25 + 0.45 * (m / Math.max(1, machines.length - 1)) + 0.06 * c);
      link(svg, x1, y1 + 34, x2, y2 - 38, Math.min(2 + Math.sqrt(count) * 1.2, 16), bad ? 'warning' : 'success',
           `${count}${bad ? ` · ${bad} need attention` : ''}`, 0, at);
    }
  }
  for (const host of clouds) {
    const [x, y] = cloudAt.get(host.host);
    cloud(svg, x, y, 190, host.host, `${host.count} repos${host.attention ? ` · ${host.attention} ⚑` : ''}`,
          host.host === 'local' ? 'muted' : host.attention ? 'warning' : 'success',
          () => { zoomTo({kind: 'cloud', id: host.host}); rerender(); });
  }
  for (const machine of machines) {
    const [x, y] = machineAt.get(machine.id);
    const {count, bad} = onMachine(data, machine.id);
    machineBox(svg, x, y, machine, `${count} repos${bad ? ` · ${bad} ⚑` : ''}`,
               machine.freshness !== 'current' ? 'warning' : bad ? 'warning' : 'success',
               () => { zoomTo({kind: 'machine', id: machine.id}); rerender(); });
  }
  const column = 1000 / (machines.length + 1), width = Math.floor((column - 24) / 7.2);
  for (const machine of machines) {                         // each machine's library, below
    const [x] = machineAt.get(machine.id), left = x - column / 2 + 14;
    libraries.get(machine.id).forEach((line, i) => {
      const y = LIBRARY_TOP + i * LIBRARY_LINE;
      if (line.kind === 'org') {
        const item = node(svg, {label: `${line.org.label} on ${hostName(line.org.host)}. Open the organization.`,
                                onOpen: () => { zoomTo({kind: 'organization', id: line.org.id}); rerender(); }});
        item.append(el('text', {x: left, y, class: 'z-row z-strong z-muted-text'},
                            clip(`${hostName(line.org.host)} · ${line.org.label}`, width)));
      } else if (line.kind === 'repo') {
        const name = line.row.identity ? line.row.identity.name : line.row.name;
        const tone = trouble(line.cell) ? 'warning' : line.cell.state === 'unknown' ? 'muted' : 'success';
        const item = node(svg, {label: `${name} on ${machine.label}: ${line.cell.description}. Open.`,
                                onOpen: () => { zoomTo({kind: 'repository', id: line.row.id}); rerender(); }});
        item.append(el('circle', {cx: left + 12, cy: y - 4, r: 4.5, class: `z-dot ${toneClass(tone)}`}));
        item.append(el('text', {x: left + 24, y, class: 'z-row'}, clip(name, width - 3)));
      } else {
        const item = node(svg, {label: `${line.count} more on ${machine.label}. Open the machine.`,
                                onOpen: () => { zoomTo({kind: 'machine', id: machine.id}); rerender(); }});
        item.append(el('text', {x: left + 24, y, class: 'z-row z-muted-text'}, `+ ${line.count} more`));
      }
    });
  }
  if (!machines.length) svg.append(el('text', {x: 500, y: 470, class: 'z-detail'}, 'No machine has reported yet.'));
}

function cloudLevel(container, data, host) {
  const groups = data.groups.filter(g => (g.host || 'local') === host || (host === 'local' && !g.host))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  const columns = Math.max(4, Math.ceil(Math.sqrt(groups.length * 1.8)));
  const cell = 1000 / columns, rows = Math.ceil(groups.length / columns);
  const max = Math.max(1, ...groups.map(g => g.count));
  const svg = frame(container, 170 + rows * (cell + 10), `${hostName(host)}: its organizations`);
  cloud(svg, 500, 70, 220, host, `${plural(groups.length, 'organization', 'organizations')} · ${groups.reduce((s, g) => s + g.count, 0)} repos`,
        host === 'local' ? 'muted' : 'success', () => { zoomOut(trail.length - 1); rerender(); });
  groups.forEach((group, i) => {
    const x = cell * (i % columns) + cell / 2, y = 190 + Math.floor(i / columns) * (cell + 10) + cell / 2 - 10;
    const r = Math.max(14, (cell / 2 - 14) * Math.sqrt(group.count / max));
    const item = node(svg, {label: `${group.label}: ${group.count} repositories, ${group.attention} need attention. Open.`,
                            onOpen: () => { zoomTo({kind: 'organization', id: group.id}); rerender(); }});
    item.append(el('circle', {cx: x, cy: y, r, class: `z-bubble ${toneClass(group.attention ? 'warning' : 'success')}`}));
    item.append(el('text', {x, y: y + 4, class: 'z-count'}, String(group.count)));
    item.append(el('text', {x, y: y + r + 16, class: 'z-detail'}, clip(group.label, Math.floor(cell / 7.5))));
    if (group.attention) item.append(el('text', {x, y: y + r + 30, class: 'z-detail z-warn-text'}, `${group.attention} ⚑`));
  });
}

function machineLevel(container, data, machineId) {
  const machine = data.machines.find(m => m.id === machineId);
  const byHost = new Map();
  for (const row of data.rows) {
    const cell = row.cells[machineId];
    if (!cell || !cell.present) continue;
    const host = hostOf(row);
    if (!byHost.has(host)) byHost.set(host, new Map());
    const orgs = byHost.get(host);
    const entry = orgs.get(row.group_id) || {id: row.group_id, label: row.namespace, count: 0, bad: 0};
    entry.count += 1;
    entry.bad += trouble(cell) ? 1 : 0;
    orgs.set(row.group_id, entry);
  }
  const lines = [...byHost.entries()].map(([host, orgs]) => [host, [...orgs.values()].sort((a, b) => b.bad - a.bad || b.count - a.count || a.label.localeCompare(b.label))]);
  const rowsNeeded = lines.reduce((s, [, orgs]) => s + orgs.length + 1, 0);
  const svg = frame(container, Math.max(420, 60 + rowsNeeded * 24), `${machine.label}: its library`);
  const total = onMachine(data, machineId);
  machineBox(svg, 110, 90, machine, `${total.count} repos${total.bad ? ` · ${total.bad} ⚑` : ''}`,
             total.bad ? 'warning' : 'success', () => { zoomOut(trail.length - 1); rerender(); });
  let y = 50;
  for (const [host, orgs] of lines) {
    const hostY = y + 12;
    const bad = orgs.reduce((s, o) => s + o.bad, 0), count = orgs.reduce((s, o) => s + o.count, 0);
    link(svg, 198, 90, 330, hostY, 2.5, bad ? 'warning' : 'success');
    const hostNode = node(svg, {label: `${hostName(host)} on ${machine.label}: ${count} repositories. Open the cloud.`,
                                onOpen: () => { zoomTo({kind: 'cloud', id: host}); rerender(); }});
    hostNode.append(el('rect', {x: 330, y: hostY - 13, width: 190, height: 26, rx: 13, class: `z-pill ${toneClass(host === 'local' ? 'muted' : bad ? 'warning' : 'success')}`}));
    hostNode.append(el('text', {x: 425, y: hostY + 5, class: 'z-detail z-strong'}, `${hostName(host)} · ${count}${bad ? ` · ${bad} ⚑` : ''}`));
    y += 24;
    for (const org of orgs) {
      const orgY = y + 12;
      svg.append(el('path', {d: `M520 ${hostY} C560 ${hostY} 560 ${orgY} 600 ${orgY}`, class: `z-link z-thin ${toneClass(org.bad ? 'warning' : 'success')}`}));
      const item = node(svg, {label: `${org.label}: ${org.count} here, ${org.bad} need attention. Open.`,
                              onOpen: () => { zoomTo({kind: 'organization', id: org.id}); rerender(); }});
      item.append(el('circle', {cx: 610, cy: orgY, r: 7, class: `z-dot ${toneClass(org.bad ? 'warning' : 'success')}`}));
      item.append(el('text', {x: 626, y: orgY + 4, class: 'z-row'}, `${clip(org.label, 34)}  ${org.count}${org.bad ? ` · ${org.bad} ⚑` : ''}`));
      y += 24;
    }
  }
}

function organizationLevel(container, data, groupId, machineId) {
  const group = data.groups.find(g => g.id === groupId);
  const rows = data.rows.filter(r => r.group_id === groupId)
    .sort((a, b) => (b.needs_attention - a.needs_attention) || a.name.localeCompare(b.name));
  const svg = frame(container, Math.max(300, 70 + rows.length * 28), `${group ? group.label : groupId}: its repositories`);
  const top = 40, mid = top + (rows.length * 28) / 2;
  const head = node(svg, {label: `${group ? group.label : groupId}. Zoom out.`, onOpen: () => { zoomOut(trail.length - 1); rerender(); }});
  head.append(el('circle', {cx: 120, cy: mid, r: 46, class: `z-bubble ${toneClass(group && group.attention ? 'warning' : 'success')}`}));
  head.append(el('text', {x: 120, y: mid - 2, class: 'z-label'}, clip(group ? group.label : groupId, 14)));
  head.append(el('text', {x: 120, y: mid + 16, class: 'z-detail'}, `${rows.length} repos`));
  rows.forEach((row, i) => {
    const y = top + i * 28 + 14, tone = worstTone(row, machineId);
    svg.append(el('path', {d: `M166 ${mid} C260 ${mid} 260 ${y} 330 ${y}`, class: `z-link z-thin ${toneClass(tone)}`}));
    const item = node(svg, {label: `${row.name}: ${row.advice}. Open.`,
                            onOpen: () => { zoomTo({kind: 'repository', id: row.id}); rerender(); }});
    item.append(el('circle', {cx: 340, cy: y, r: 7, class: `z-dot ${toneClass(tone)}`}));
    item.append(el('text', {x: 356, y: y + 4, class: 'z-row'}, `${clip(row.identity ? row.identity.name : row.name, 32)}`));
    item.append(el('text', {x: 620, y: y + 4, class: 'z-row z-muted-text'}, clip(row.advice, 52)));
  });
}

function repositoryLevel(container, data, repoId) {
  const row = data.rows.find(r => r.id === repoId);
  if (!row) { container.append(html('p', 'This repository is no longer reported.', 'empty')); return; }
  const machines = [...data.machines].sort((a, b) => a.label.localeCompare(b.label));
  const svg = frame(container, 520, `${row.name}: every copy`);
  const host = hostOf(row);
  cloud(svg, 500, 90, 230, host, clip(row.name, 34), host === 'local' ? 'muted' : row.needs_attention ? 'warning' : 'success',
        () => { zoomOut(trail.length - 1); rerender(); });
  svg.append(el('text', {x: 500, y: 175, class: 'z-detail z-strong'}, clip(row.advice, 90)));
  machines.forEach((machine, i) => {
    const x = (1000 / (machines.length + 1)) * (i + 1), y = 410, cell = row.cells[machine.id];
    const here = cell && cell.present;
    const facts = (here && cell.facts) || {};
    const tone = here ? cell.tone : 'muted';
    if (here && host !== 'local') {
      const behind = facts.behind || 0, ahead = facts.ahead || 0;
      link(svg, 500, 124, x, y - 38, 3, tone, [behind ? `↓ ${behind} to pull` : '', ahead ? `↑ ${ahead} to push` : '']
        .filter(Boolean).join(' · ') || 'in step', (x - 500) * 0.15);
    }
    const group = node(svg, {label: `${machine.label}: ${here ? cell.description || cell.state : 'no copy'}`, onOpen: () => {}});
    group.append(el('rect', {x: x - 110, y: y - 38, width: 220, height: 96, rx: 10, class: `z-machine ${toneClass(tone)}${here ? '' : ' z-dashed'}`}));
    group.append(el('text', {x, y: y - 12, class: 'z-label'}, clip(machine.label, 22)));
    group.append(el('text', {x, y: y + 8, class: 'z-detail'}, here ? clip(cell.description || cell.state, 30) : 'no copy here'));
    if (here) {
      const dirty = (facts.staged || 0) + (facts.unstaged || 0) + (facts.untracked || 0);
      group.append(el('text', {x, y: y + 26, class: 'z-detail'}, [facts.branch ? `on ${clip(facts.branch, 16)}` : '',
        dirty ? plural(dirty, 'uncommitted file', 'uncommitted files') : '', facts.stashes ? plural(facts.stashes, 'stash', 'stashes') : '']
        .filter(Boolean).join(' · ') || 'clean'));
      group.append(el('text', {x, y: y + 44, class: 'z-detail'}, facts.head ? `commit ${facts.head.slice(0, 10)}` : ''));
    }
  });
}

// ---- the frame around the levels ------------------------------------------------------------
let current = null;
function rerender() { if (current) renderZoom(...current); }

function label(step, data) {
  if (step.kind === 'cloud') return hostName(step.id);
  if (step.kind === 'machine') return (data.machines.find(m => m.id === step.id) || {label: step.id}).label;
  if (step.kind === 'organization') return (data.groups.find(g => g.id === step.id) || {label: step.id}).label;
  return (data.rows.find(r => r.id === step.id) || {name: step.id}).name;
}
function exists(step, data) {
  if (step.kind === 'cloud') return data.rows.some(r => hostOf(r) === step.id);
  if (step.kind === 'machine') return data.machines.some(m => m.id === step.id);
  if (step.kind === 'organization') return data.groups.some(g => g.id === step.id);
  return data.rows.some(r => r.id === step.id);
}

/** Draw the map at its current zoom into `container`. */
export function renderZoom(container, data) {
  current = [container, data];
  while (trail.length && !exists(trail[trail.length - 1], data)) trail.pop();
  container.replaceChildren();
  const bar = html('nav', undefined, 'zoom-trail');
  bar.setAttribute('aria-label', 'Where the map is zoomed to');
  const crumbs = [{label: 'Fleet', depth: 0}, ...trail.map((step, i) => ({label: label(step, data), depth: i + 1}))];
  crumbs.forEach((crumb, i) => {
    if (i) bar.append(html('span', '›', 'zoom-sep'));
    if (i === crumbs.length - 1) { bar.append(html('strong', crumb.label)); return; }
    const button = html('button', crumb.label, 'repo-link');
    button.onclick = () => { zoomOut(crumb.depth); rerender(); };
    bar.append(button);
  });
  if (trail.length) {
    const back = html('button', 'Zoom out', 'quiet zoom-back');
    back.onclick = () => { zoomOut(trail.length - 1); rerender(); };
    bar.append(back);
  }
  container.append(bar);
  const step = trail[trail.length - 1];
  const machineContext = (trail.find(s => s.kind === 'machine') || {}).id;
  if (!step) fleetLevel(container, data);
  else if (step.kind === 'cloud') cloudLevel(container, data, step.id);
  else if (step.kind === 'machine') machineLevel(container, data, step.id);
  else if (step.kind === 'organization') organizationLevel(container, data, step.id, machineContext);
  else repositoryLevel(container, data, step.id);
  container.append(html('p', 'Click anything to zoom in; the trail above (or Escape) zooms out. ' +
    'Amber means something there needs attention; the words say what.', 'map-note'));
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !trail.length || !current || !current[0].isConnected || current[0].closest('[hidden]')) return;
  zoomOut(trail.length - 1);
  rerender();
});
