/* Orgs/Archives: organizations (the folders that hold repositories) across every machine's
 * libraries. All organizations: one line each, counted per library under each machine. One
 * organization: the copy grid, with what needs a decision said in words first. Tables only;
 * the visual is the Network map. Every fact comes from the display contract.
 */
import {cellIn, columnsOf, copyGrid, GRID_FOOTNOTE, gridNotes, html, orderedMachines, toneOfFreshness} from './fleet_grid.js';

/** Rows of one organization, attention first; "all" is every row. By name, so one organization's
 *  folders in several libraries are one organization. */
export function rowsOf(data, groupId) {
  const name = groupId.startsWith('org:') ? groupId.slice(4) : null;
  return data.rows.filter(row => groupId === 'all' || (name ? row.namespace === name : row.group_id === groupId))
    .sort((a, b) => (b.needs_attention - a.needs_attention) || a.name.localeCompare(b.name));
}

/** The organization menu: each organization once, by name. */
export function organizationChoices(data) {
  return [...new Set(data.rows.map(row => row.namespace))].sort((a, b) => a.localeCompare(b))
    .map(label => [`org:${label}`, label]);
}

function needsDecision(row) {
  return row.needs_attention || row.copies?.heads_agree === false;
}

function reviewButton(rows, onReview) {
  const button = html('button', `Walk through ${rows.length} ${rows.length === 1 ? 'issue' : 'issues'}`, 'quiet');
  button.type = 'button';
  button.onclick = () => onReview(rows);
  return button;
}

function overview(container, data, perspective, onPick, onReview) {
  const machines = orderedMachines(data, perspective);
  const columns = columnsOf(machines, data.rows);
  const names = organizationChoices(data).map(([, name]) => name);
  container.append(html('p', `${names.length} organizations, each counted in every library that holds a copy. ` +
    'Choose one to line up its repositories.', 'map-note'));
  const table = html('table', undefined, 'map-grid map-org');
  const widths = html('colgroup');
  widths.append(html('col', undefined, 'map-col-repo'), html('col', undefined, 'map-col-online'));
  for (const column of columns) widths.append(html('col'));
  table.append(widths);
  const head = html('tr'), under = html('tr');
  const first = html('th', 'Organization'), online = html('th', 'Repositories'); first.rowSpan = 2; online.rowSpan = 2;
  head.append(first, online);
  for (const column of columns) {
    const starts = columns.find(item => item.machine.id === column.machine.id) === column;
    if (starts) {
      const th = html('th', column.machine.label, `tone-${toneOfFreshness(column.machine.freshness)} map-group-start`);
      th.colSpan = columns.filter(item => item.machine.id === column.machine.id).length;
      head.append(th);
    }
    under.append(html('th', column.library || '', `map-library${starts ? ' map-group-start' : ''}`));
  }
  const thead = html('thead'); thead.append(head, under); table.append(thead);
  const body = html('tbody');
  for (const name of names) {
    const rows = rowsOf(data, `org:${name}`);
    const issues = rows.filter(needsDecision);
    const attention = issues.length;
    const line = html('tr', undefined, attention ? 'map-attention' : '');
    const cell = html('td');
    const open = html('button', `${attention ? '⚑ ' : ''}${name}`, 'repo-link'); open.type = 'button';
    open.onclick = () => onPick({group: `org:${name}`});
    cell.append(open);
    if (attention) cell.append(reviewButton(issues, onReview));
    line.append(cell, html('td', `${rows.length}${attention ? ` · ${attention} need attention` : ''}`));
    for (const column of columns) {
      const here = rows.map(row => cellIn(row, column)).filter(Boolean);
      const flagged = here.filter(copy => copy.needs_attention).length;
      const starts = columns.find(item => item.machine.id === column.machine.id) === column;
      const tone = !here.length ? 'tone-muted' : flagged ? 'tone-warning' : 'tone-success';
      line.append(html('td', here.length ? `${here.length} of ${rows.length}${flagged ? ` · ${flagged} need attention` : ''}` : '—',
                       `${tone}${starts ? ' map-group-start' : ''}`));
    }
    body.append(line);
  }
  table.append(body);
  const scroll = html('div', undefined, 'table-scroll'); scroll.append(table);
  container.append(scroll);
}

function oneOrganization(container, data, perspective, group, handlers, showUnavailable) {
  const {onPick, onReview, onRepository, actions} = handlers;
  const rows = rowsOf(data, group);
  const label = group.slice(4);
  // In words first: what is the same everywhere, and what needs a decision, from Python's advice.
  const open = rows.filter(needsDecision);
  const verdict = html('div', undefined, open.length ? 'map-verdict map-verdict-open' : 'map-verdict');
  verdict.append(html('strong', open.length
    ? `${label}: ${rows.length - open.length} of ${rows.length} are the same on every machine that has them. ${open.length} need${open.length === 1 ? 's' : ''} a decision:`
    : `${label}: all ${rows.length} are the same on every machine that has them.`));
  if (open.length) {
    verdict.append(reviewButton(open, onReview));
    const list = html('ul');
    for (const row of open) {
      const item = html('li');
      const inspect = html('button', row.identity ? row.identity.name : row.name, 'repo-link');
      inspect.type = 'button';
      inspect.title = 'Open checkout details and available actions';
      inspect.onclick = () => onRepository(row);
      item.append(inspect, document.createTextNode(` ${row.advice}`));
      list.append(item);
    }
    verdict.append(list);
  }
  container.append(verdict);
  container.append(copyGrid(data, rows, {perspective, actions, asks: true, showUnavailable,
    onName: onRepository, onChange: () => onPick({})}));
  container.append(html('p', GRID_FOOTNOTE, 'host-note'));
  gridNotes(container);
}

/** Draw the panel's body. `options`: group ("all" or "org:<name>"), perspective; handlers:
 *  onPick(change), onReview(rows), onRepository(row), actions. */
export function renderOrgs(container, data, options, handlers) {
  container.replaceChildren();
  if (!data.rows.length) { container.append(html('p', 'No repositories observed yet.', 'empty')); return; }
  if (options.group && options.group !== 'all' && rowsOf(data, options.group).length) {
    oneOrganization(container, data, options.perspective, options.group, handlers, options.showUnavailable);
  } else overview(container, data, options.perspective, handlers.onPick, handlers.onReview);
}
