/* The network map: the visual of the fleet. Tables live on the other pages (Repositories,
 * Orgs/Archives, Machines, Clouds); this page draws, zooms and links into them.
 *
 * Views: the zoomable map (clouds and machines, click to go deeper) and machines together (nodes
 * and links). A chosen machine sets the perspective: it comes first and sits at the centre.
 * Attention, freshness and whether copies agree all come from Python (`needs_attention`,
 * `freshness`, `map.links`). Colour is never the only signal: every mark has text.
 */
import {renderZoom} from './fleet_zoom.js';
import {renderExplorer} from './fleet_explorer.js';
import {html, orderedMachines, perspectiveOf, toneOfFreshness} from './fleet_grid.js';

const SVG = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, text) => {
  const item = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
  if (text !== undefined) item.textContent = text;
  return item;
};

export const VIEWS = [
  ['overview', 'Clouds and machines (overview)'],
  ['explorer', 'Explorer: every copy, by the dimensions you choose'],
  ['machines', 'Machines together'],
];

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

/** Render one view into `container`. `onPick` receives partial option changes. */
export function renderMap(container, data, options, onPick) {
  // The explorer keeps its own canvas across the page's refreshes (its camera, hover and pins).
  if (options.view === 'explorer') { renderExplorer(container, data, options); return; }
  container.replaceChildren();
  if (!options.view || options.view === 'overview') { renderZoom(container, data); return; }
  if (!data.machines.length) { container.append(html('p', 'No machine has reported yet.', 'empty')); return; }
  machinesView(container, data, perspectiveOf(data, options.perspective), onPick);
}
