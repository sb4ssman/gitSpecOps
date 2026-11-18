/* The explorer: every copy in the fleet as a point, laid out by the dimensions you choose, in
 * depth (the user, 2026-11-16/17: "show EVERYTHING", "effectively 3D", "go straight to the issues
 * and see how these are different elsewhere").
 *
 *   point        one copy: a repository in one library on one machine (the fractal end result)
 *   columns/rows the dimensions you choose: machine, library, owner, provider, state, or none
 *   depth        issues come forward (closer, larger); in-sync copies recede
 *   hover        a lens magnifies what is under the cursor and fades the rest; every copy of the
 *                same repository lights up and is joined by lines, wherever it is
 *   wheel / drag zoom toward the cursor / move sideways across the plane
 *   issues       Next / Previous fly to each copy that needs a decision
 *   legend       your own colours and what to show, kept in this browser
 *
 * Every fact (tone, attention, words) comes from the display contract; this only lays it out.
 */
import {cellIn, columnsOf, copyText, html, orderedMachines, PROVIDER, shortCommit} from './fleet_grid.js';

const DIMENSIONS = [
  ['machine', 'Machine'], ['library', 'Library'], ['owner', 'Owner'], ['provider', 'Provider'],
  ['state', 'State'], ['none', 'Nothing'],
];
const DEPTHS = [['state', 'Issues come forward'], ['freshness', 'Stale machines recede'], ['none', 'Flat']];
const TONES = [
  ['danger', 'Needs a decision', '#e5534b'], ['warning', 'Behind, ahead or stashed', '#d4a017'],
  ['success', 'In sync with its provider', '#2ea043'], ['neutral', 'No upstream', '#8b929a'],
  ['muted', 'Same disk as a machine reporting now', '#5c6370'],
];
const SEVERITY = {danger: 1, warning: 0.7, neutral: 0.3, muted: 0.15, success: 0};

// Kept across the page's refreshes (every 3 seconds) and, for choices, across reloads.
const view = {x: 'machine', y: 'owner', z: 'state', camera: null, hover: null, pinned: null, issue: -1};
const legend = {colours: Object.fromEntries(TONES.map(([tone, , colour]) => [tone, colour])),
                hidden: new Set()};
try {
  const saved = JSON.parse(localStorage.getItem('gitso.explorer') || '{}');
  for (const key of ['x', 'y', 'z']) if (saved[key]) view[key] = saved[key];
  Object.assign(legend.colours, saved.colours || {});
  for (const tone of saved.hidden || []) legend.hidden.add(tone);
} catch { /* a remembered choice only */ }
function save() {
  try {
    localStorage.setItem('gitso.explorer', JSON.stringify({x: view.x, y: view.y, z: view.z,
      colours: legend.colours, hidden: [...legend.hidden]}));
  } catch { /* a remembered choice only */ }
}

/** Every copy: one point per repository per library per machine. */
function copiesOf(data) {
  const machines = orderedMachines(data, data.this_machine);
  const columns = columnsOf(machines, data.rows);
  const points = [];
  for (const row of data.rows) {
    for (const column of columns) {
      const cell = cellIn(row, column);
      if (!cell || !cell.present) continue;
      points.push({row, cell, machine: column.machine, library: column.library || (cell.place || {}).library || '',
                   tone: cell.tone || 'neutral', name: row.identity ? row.identity.name : row.name});
    }
  }
  return points;
}

const STATE_LABEL = Object.fromEntries(TONES.map(([tone, label]) => [tone, label]));
function keyOf(point, dimension) {
  switch (dimension) {
    case 'machine': return point.machine.label;
    case 'library': return `${point.machine.label} · ${point.library || 'library not reported'}`;
    case 'owner': return point.row.namespace || '(none)';
    case 'provider': {
      const host = (point.row.identity || {}).host;
      return host === 'local' || !host ? 'No remote' : (PROVIDER[host] || host);
    }
    case 'state': return STATE_LABEL[point.tone] || point.tone;
    default: return '';
  }
}
function depthOf(point) {
  if (view.z === 'state') return SEVERITY[point.tone] ?? 0.2;
  if (view.z === 'freshness') return point.cell.freshness === 'current' ? 0.8 : 0.1;
  return 0.4;
}

/** World layout: a grid of cells (columns × rows); in each cell its copies on a sunflower,
 *  issues at the centre. Cell size follows how many copies it holds. */
function layout(points) {
  const columns = [...new Set(points.map(p => keyOf(p, view.x)))].sort((a, b) => a.localeCompare(b));
  const rows = [...new Set(points.map(p => keyOf(p, view.y)))].sort((a, b) => a.localeCompare(b));
  const cells = new Map();
  for (const point of points) {
    const key = `${keyOf(point, view.x)}\u0000${keyOf(point, view.y)}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(point);
  }
  const SPACING = 13;
  const radiusOf = n => SPACING * Math.sqrt(n) * 0.62 + 18;
  const colWidth = columns.map(c => Math.max(110, ...rows.map(r => 2 * radiusOf((cells.get(`${c}\u0000${r}`) || []).length))));
  const rowHeight = rows.map(r => Math.max(90, ...columns.map(c => 2 * radiusOf((cells.get(`${c}\u0000${r}`) || []).length))));
  const xAt = [], yAt = [];
  colWidth.reduce((x, w, i) => { xAt[i] = x + w / 2; return x + w + 30; }, 160);
  rowHeight.reduce((y, h, i) => { yAt[i] = y + h / 2; return y + h + 30; }, 60);
  for (const [key, list] of cells) {
    const [c, r] = key.split('\u0000');
    const cx = xAt[columns.indexOf(c)], cy = yAt[rows.indexOf(r)];
    list.sort((a, b) => depthOf(b) - depthOf(a) || a.name.localeCompare(b.name));
    list.forEach((point, i) => {
      const angle = i * 2.39996, distance = SPACING * Math.sqrt(i) * 0.62;
      point.wx = cx + distance * Math.cos(angle);
      point.wy = cy + distance * Math.sin(angle);
      point.wz = depthOf(point);
    });
  }
  const width = xAt.length ? xAt[xAt.length - 1] + colWidth[colWidth.length - 1] / 2 + 40 : 400;
  const height = yAt.length ? yAt[yAt.length - 1] + rowHeight[rowHeight.length - 1] / 2 + 40 : 300;
  return {columns, rows, xAt, yAt, colWidth, rowHeight, width, height};
}

let state = null;  // {root, canvas, panel, data, points, world}

function project(point, camera, size) {
  // Perspective: nearer points sit further from the centre of view and are drawn larger.
  const s = camera.zoom * (1 + 0.35 * point.wz);
  return {x: size.w / 2 + (point.wx - camera.x) * s, y: size.h / 2 + (point.wy - camera.y) * s,
          r: Math.max(1.6, camera.zoom * (3.2 + 4.5 * point.wz))};
}

function draw() {
  const {canvas, points, world} = state;
  if (!view.fitted && canvas.clientWidth > 0) fit();
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const style = getComputedStyle(canvas);
  const ink = style.getPropertyValue('--ink').trim() || '#e6edf3';
  const muted = style.getPropertyValue('--muted').trim() || '#8b929a';
  const camera = view.camera, size = {w, h};
  const mouse = view.hover;
  const lensRadius = 90, lens = mouse ? 1.6 : 0;
  // Axis labels: columns along the top, rows down the left, moving with the plane.
  ctx.font = '12px system-ui, sans-serif';
  ctx.fillStyle = muted;
  ctx.textAlign = 'center';
  world.columns.forEach((label, i) => {
    const x = w / 2 + (world.xAt[i] - camera.x) * camera.zoom;
    ctx.fillText(label || '', x, Math.max(16, h / 2 + (30 - camera.y) * camera.zoom));
  });
  ctx.textAlign = 'right';
  world.rows.forEach((label, i) => {
    const y = h / 2 + (world.yAt[i] - camera.y) * camera.zoom;
    ctx.fillText(label || '', Math.max(110, w / 2 + (140 - camera.x) * camera.zoom), y + 4);
  });
  // Points, far first so near ones draw on top.
  const placed = [];
  for (const point of [...points].sort((a, b) => a.wz - b.wz)) {
    if (legend.hidden.has(point.tone)) continue;
    let p = project(point, camera, size);
    let alpha = 0.95;
    if (mouse) {
      const dx = p.x - mouse.x, dy = p.y - mouse.y, d = Math.hypot(dx, dy);
      const m = 1 + lens * Math.exp(-((d / lensRadius) ** 2));  // fisheye: near the cursor, space opens up
      p = {x: mouse.x + dx * m, y: mouse.y + dy * m, r: p.r * m};
      alpha = 0.25 + 0.75 * Math.exp(-((d / (lensRadius * 2.6)) ** 2));
    }
    placed.push({point, ...p, alpha});
  }
  const focus = view.pinned || (state.near && state.near.row.id);
  // Lines between every copy of the focused repository: how it differs elsewhere.
  if (focus) {
    const same = placed.filter(item => item.point.row.id === focus);
    ctx.strokeStyle = ink; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.2;
    for (let i = 1; i < same.length; i++) {
      ctx.beginPath(); ctx.moveTo(same[0].x, same[0].y); ctx.lineTo(same[i].x, same[i].y); ctx.stroke();
    }
  }
  for (const item of placed) {
    const highlighted = focus && item.point.row.id === focus;
    ctx.globalAlpha = highlighted ? 1 : (focus ? item.alpha * 0.6 : item.alpha);
    ctx.fillStyle = legend.colours[item.point.tone] || muted;
    ctx.beginPath(); ctx.arc(item.x, item.y, item.r, 0, Math.PI * 2); ctx.fill();
    if (highlighted) { ctx.strokeStyle = ink; ctx.lineWidth = 2; ctx.stroke(); }
    // Details appear as a copy gets close: its name, then how it compares and its commit.
    if (item.r >= 7 || highlighted) {
      ctx.fillStyle = ink; ctx.textAlign = 'left';
      ctx.font = `${Math.min(15, 9 + item.r * 0.35)}px system-ui, sans-serif`;
      ctx.fillText(item.point.name, item.x + item.r + 4, item.y - (item.r >= 11 ? 4 : -4));
      if (item.r >= 11 || highlighted) {
        ctx.fillStyle = muted;
        ctx.font = '11px system-ui, sans-serif';
        const commit = shortCommit((item.point.cell.facts || {}).head);
        ctx.fillText(`${item.point.machine.label}: ${copyText(item.point.cell, item.point.row)}${commit ? ` · ${commit}` : ''}`,
                     item.x + item.r + 4, item.y + 11);
      }
    }
  }
  ctx.globalAlpha = 1;
  state.placed = placed;
}

function nearest(x, y) {
  let best = null, bestD = Infinity;
  for (const item of state.placed || []) {
    const d = Math.hypot(item.x - x, item.y - y);
    if (d < Math.max(10, item.r + 4) && d < bestD) { best = item.point; bestD = d; }
  }
  return best;
}

function issues() {
  return state.points.filter(p => p.tone === 'danger' || p.tone === 'warning')
    .sort((a, b) => b.wz - a.wz || a.name.localeCompare(b.name));
}

function flyTo(point) {
  const target = {x: point.wx, y: point.wy, zoom: 2.6};
  const from = {...view.camera}, start = performance.now();
  const step = now => {
    const t = Math.min(1, (now - start) / 450), e = t * (2 - t);
    view.camera = {x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e,
                   zoom: from.zoom + (target.zoom - from.zoom) * e};
    draw();
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function fit() {
  const {world, canvas} = state;
  // Nearer points sit further out (depth): leave room for them.
  const zoom = Math.min(canvas.clientWidth / world.width, canvas.clientHeight / world.height, 1.4) / 1.4;
  view.camera = {x: world.width / 2, y: world.height / 2, zoom: Math.max(0.2, zoom || 1)};
  view.fitted = canvas.clientWidth > 0;  // drawn while its tab was hidden: fit again once seen
}

function showPanel(onRepository) {
  const {panel} = state;
  panel.replaceChildren();
  const focus = view.pinned;
  if (!focus) {
    panel.append(html('p', 'Hover to look closer; click a copy to pin its repository here. Wheel zooms, drag moves.', 'host-note'));
    return;
  }
  const copies = state.points.filter(p => p.row.id === focus);
  if (!copies.length) { view.pinned = null; showPanel(onRepository); return; }
  const row = copies[0].row;
  panel.append(html('h4', copies[0].name), html('p', row.advice, 'host-note'));
  const list = html('ul', undefined, 'explorer-copies');
  for (const copy of copies) {
    const item = html('li');
    const dot = html('span', '●'); dot.style.color = legend.colours[copy.tone] || '';
    item.append(dot, document.createTextNode(` ${copy.machine.label} · ${copy.library}: ${copyText(copy.cell, row)}`));
    const commit = shortCommit((copy.cell.facts || {}).head);
    if (commit) item.append(html('span', commit, 'host-note'));
    list.append(item);
  }
  panel.append(list);
  if (onRepository) {
    const open = html('button', 'Open in Repositories'); open.type = 'button';
    open.onclick = () => onRepository(row);
    panel.append(open);
  }
  const close = html('button', 'Unpin', 'quiet'); close.type = 'button';
  close.onclick = () => { view.pinned = null; showPanel(onRepository); draw(); };
  panel.append(close);
}

function legendBox(onChange) {
  const box = html('div', undefined, 'explorer-legend');
  box.append(html('strong', 'Legend'));
  for (const [tone, label] of TONES) {
    const line = html('label', undefined, 'explorer-legend-line');
    const show = html('input'); show.type = 'checkbox'; show.checked = !legend.hidden.has(tone);
    show.title = 'Show or hide these copies';
    show.onchange = () => { show.checked ? legend.hidden.delete(tone) : legend.hidden.add(tone); save(); onChange(); };
    const colour = html('input'); colour.type = 'color'; colour.value = legend.colours[tone];
    colour.title = 'Your colour for these copies';
    colour.oninput = () => { legend.colours[tone] = colour.value; save(); onChange(); };
    const count = state.points.filter(p => p.tone === tone).length;
    line.append(show, colour, document.createTextNode(` ${label} (${count})`));
    box.append(line);
  }
  box.append(html('p', 'Size and nearness: closer and larger needs you more. Lines join one repository\'s copies.', 'host-note'));
  const reset = html('button', 'Default colours', 'quiet'); reset.type = 'button';
  reset.onclick = () => { for (const [tone, , colour] of TONES) legend.colours[tone] = colour; legend.hidden.clear(); save(); rebuildLegend(); onChange(); };
  box.append(reset);
  return box;
}
let rebuildLegend = () => {};

function select(label, options, value, onChange) {
  const wrap = html('label', label);
  const select = html('select');
  for (const [id, name] of options) { const o = html('option', name); o.value = id; select.append(o); }
  select.value = value;
  select.oninput = () => onChange(select.value);
  wrap.append(select);
  return wrap;
}

/** Draw the explorer into `container`; on the page's refreshes, only its data changes. */
export function renderExplorer(container, data, options = {}) {
  const points = copiesOf(data);
  if (state && container.contains(state.root)) {
    // A refresh: keep the camera, hover and pins; take the new facts.
    const signature = points.map(p => `${p.row.id}/${p.machine.id}/${p.library}/${p.tone}`).join('|');
    state.data = data; state.onRepository = options.onRepository;
    if (signature !== state.signature) {
      state.points = points; state.signature = signature; state.world = layout(points);
      rebuildLegend(); showPanel(state.onRepository);
    }
    draw();
    return;
  }
  container.replaceChildren();
  const root = html('div', undefined, 'explorer');
  const controls = html('div', undefined, 'filter-bar explorer-controls');
  const canvas = html('canvas', undefined, 'explorer-canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Every copy of every repository, laid out by the chosen dimensions; issues come forward');
  const side = html('div', undefined, 'explorer-side');
  const panel = html('div', undefined, 'explorer-panel');
  const legendSlot = html('div');
  side.append(panel, legendSlot);
  const stage = html('div', undefined, 'explorer-stage');
  stage.append(canvas, side);
  root.append(controls, stage, html('p', 'Every point is one copy: a repository in one library on one machine. '
    + 'Choose what the columns and rows mean; issues come forward. Hover to look closer, click to pin, wheel to zoom, drag to move.', 'host-note'));
  container.append(root);
  state = {root, canvas, panel, data, points, signature: '', world: layout(points), onRepository: options.onRepository};
  const relayout = () => { state.world = layout(state.points); fit(); save(); draw(); };
  const issueCount = html('span', '', 'host-note');
  const go = step => () => {
    const list = issues();
    if (!list.length) { issueCount.textContent = 'No issues: every copy matches its provider.'; return; }
    view.issue = (view.issue + step + list.length) % list.length;
    const point = list[view.issue];
    view.pinned = point.row.id;
    issueCount.textContent = `Issue ${view.issue + 1} of ${list.length}: ${point.name} on ${point.machine.label}`;
    showPanel(state.onRepository); flyTo(point);
  };
  const prev = html('button', '◀ Previous issue'); prev.type = 'button'; prev.onclick = go(-1);
  const next = html('button', 'Next issue ▶'); next.type = 'button'; next.onclick = go(1);
  const whole = html('button', 'Whole fleet', 'quiet'); whole.type = 'button';
  whole.onclick = () => { fit(); draw(); };
  controls.append(
    select('Columns', DIMENSIONS, view.x, value => { view.x = value; relayout(); }),
    select('Rows', DIMENSIONS, view.y, value => { view.y = value; relayout(); }),
    select('Depth', DEPTHS, view.z, value => { view.z = value; relayout(); }),
    prev, next, whole, issueCount);
  rebuildLegend = () => { legendSlot.replaceChildren(legendBox(draw)); };
  rebuildLegend();
  showPanel(state.onRepository);
  // Interaction: hover lens, wheel zoom toward the cursor, drag to move, click to pin.
  let drag = null;
  canvas.addEventListener('mousemove', event => {
    const box = canvas.getBoundingClientRect();
    const x = event.clientX - box.left, y = event.clientY - box.top;
    if (drag) {
      view.camera.x = drag.cx - (x - drag.x) / view.camera.zoom;
      view.camera.y = drag.cy - (y - drag.y) / view.camera.zoom;
      drag.moved = drag.moved || Math.hypot(x - drag.x, y - drag.y) > 4;
      view.hover = null;
    } else view.hover = {x, y};
    state.near = view.hover ? nearest(x, y) : null;
    canvas.style.cursor = drag ? 'grabbing' : state.near ? 'pointer' : 'grab';
    draw();
  });
  canvas.addEventListener('mouseleave', () => { view.hover = null; state.near = null; draw(); });
  canvas.addEventListener('mousedown', event => {
    const box = canvas.getBoundingClientRect();
    drag = {x: event.clientX - box.left, y: event.clientY - box.top, cx: view.camera.x, cy: view.camera.y, moved: false};
  });
  window.addEventListener('mouseup', () => {
    if (drag && !drag.moved && state.near) { view.pinned = state.near.row.id; showPanel(state.onRepository); }
    drag = null;
    draw();
  });
  canvas.addEventListener('wheel', event => {
    event.preventDefault();
    const box = canvas.getBoundingClientRect();
    const x = event.clientX - box.left, y = event.clientY - box.top;
    const before = {x: view.camera.x + (x - canvas.clientWidth / 2) / view.camera.zoom,
                    y: view.camera.y + (y - canvas.clientHeight / 2) / view.camera.zoom};
    view.camera.zoom = Math.min(8, Math.max(0.15, view.camera.zoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
    view.camera.x = before.x - (x - canvas.clientWidth / 2) / view.camera.zoom;
    view.camera.y = before.y - (y - canvas.clientHeight / 2) / view.camera.zoom;
    draw();
  }, {passive: false});
  new ResizeObserver(() => draw()).observe(canvas);
  if (!view.camera) fit();
  requestAnimationFrame(() => { if (!view.camera || view.camera.zoom === 0) fit(); draw(); });
}
