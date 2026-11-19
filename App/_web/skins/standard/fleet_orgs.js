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

function auditButton(rows, onAudit) {
  const button = html('button', `Audit these ${rows.length}`, 'quiet'); button.type = 'button';
  button.title = 'Choose them on the Security tab; the audit starts when you press Audit there';
  button.onclick = event => { event.stopPropagation(); onAudit(rows.map(row => row.id)); };
  return button;
}

function overview(container, data, perspective, onPick, onAudit) {
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
    const attention = rows.filter(row => row.needs_attention).length;
    const line = html('tr', undefined, attention ? 'map-attention' : '');
    const cell = html('td');
    const open = html('button', `${attention ? '⚑ ' : ''}${name}`, 'repo-link'); open.type = 'button';
    open.onclick = () => onPick({group: `org:${name}`});
    cell.append(open);
    if (onAudit) cell.append(auditButton(rows, onAudit));
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
  const {onPick, onAudit, onRepository, actions} = handlers;
  const rows = rowsOf(data, group);
  const label = group.slice(4);
  // In words first: what is the same everywhere, and what needs a decision, from Python's advice.
  const settled = rows.filter(row => !row.needs_attention && (row.copies || {}).heads_agree !== false);
  const open = rows.filter(row => !settled.includes(row));
  const verdict = html('div', undefined, open.length ? 'map-verdict map-verdict-open' : 'map-verdict');
  verdict.append(html('strong', open.length
    ? `${label}: ${settled.length} of ${rows.length} are the same on every machine that has them. ${open.length} need${open.length === 1 ? 's' : ''} a decision:`
    : `${label}: all ${rows.length} are the same on every machine that has them.`));
  if (onAudit) verdict.append(auditButton(rows, onAudit));
  if (open.length) {
    const list = html('ul');
    for (const row of open) list.append(html('li', `${row.identity ? row.identity.name : row.name}: ${row.advice}`));
    verdict.append(list);
  }
  container.append(verdict);
  container.append(copyGrid(data, rows, {perspective, actions, asks: true, showUnavailable,
    onName: onRepository, onChange: () => onPick({})}));
  container.append(html('p', GRID_FOOTNOTE, 'host-note'));
  gridNotes(container);
}

/** Draw the panel's body. `options`: group ("all" or "org:<name>"), perspective; handlers:
 *  onPick(change), onAudit(repoIds), onRepository(row), actions. */
export function renderOrgs(container, data, options, handlers) {
  container.replaceChildren();
  if (!data.rows.length) { container.append(html('p', 'No repositories observed yet.', 'empty')); return; }
  if (options.group && options.group !== 'all' && rowsOf(data, options.group).length) {
    oneOrganization(container, data, options.perspective, options.group, handlers, options.showUnavailable);
  } else overview(container, data, options.perspective, handlers.onPick, handlers.onAudit);
}
