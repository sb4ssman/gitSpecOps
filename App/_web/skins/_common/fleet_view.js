/* Presentation selectors. Status meanings and attention decisions come from Python. */
export function selectRows(data, {query = '', status = 'attention', machine = 'all', sort = 'attention'} = {}) {
  const search = query.trim().toLocaleLowerCase();
  const rows = data.rows.filter(row => {
    if (!`${row.name} ${row.identity.host}`.toLocaleLowerCase().includes(search)) return false;
    const cell = machine === 'all' ? null : row.cells[machine];
    if (machine !== 'all' && !cell) return false;
    const tags = cell ? cell.tags : row.tags;
    if (status !== 'all' && !tags.includes(status)) return false;
    return !cell || cell.present || status === 'missing';
  });
  return rows.sort((a, b) => (sort === 'attention' ? b.severity - a.severity : 0)
    || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}
/** Group by where repositories live (library, then folder) or by GitHub owner: every view reads
 *  `groups` and each row's `group_id`, so regrouping here regroups them all (2026-11-15). */
export function regroup(data, mode) {
  if (mode !== 'place' || !data.place_groups) {
    return {...data, rows: data.rows.map(row => ({...row, group_host: (row.identity || {}).host}))};
  }
  const byId = new Map(data.place_groups.map(group => [group.id, group]));
  return {...data, owner_groups: data.groups, groups: data.place_groups,
          rows: data.rows.map(row => {
            const group = byId.get(row.place_id) || {label: 'Folder not shared', host: 'Other machines'};
            return {...row, group_id: row.place_id, namespace: group.label, group_host: group.host,
                    owner_group_id: row.group_id, owner_namespace: row.namespace};
          })};
}

/** The GitHub-owner grouping whatever the page is set to: the zoom map goes provider, owner,
 *  repository, and a library folder is not an owner (an empty GitHub cloud, 2026-11-16). */
export function byOwner(data) {
  if (!data.owner_groups) return data;
  return {...data, groups: data.owner_groups,
          rows: data.rows.map(row => ({...row, group_id: row.owner_group_id ?? row.group_id,
                                       namespace: row.owner_namespace ?? row.namespace}))};
}

export function groupRows(data, rows) {
  return data.groups.map(group => ({...group, rows: rows.filter(row => row.group_id === group.id)}))
    .filter(group => group.rows.length);
}
export function ageLabel(seconds) {
  if (seconds === null) return 'Unknown';
  if (seconds < 60) return `${Math.floor(seconds)} seconds ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

export class GroupExpansion {
  constructor(closed = []) { this.closed = new Set(closed); }
  isOpen(id) { return !this.closed.has(id); }
  record(id, open) { if (open) this.closed.delete(id); else this.closed.add(id); }
  expandAll() { this.closed.clear(); }
  collapseAll(ids) { for (const id of ids) this.closed.add(id); }
}
