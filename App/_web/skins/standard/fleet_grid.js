/* The copy grid: one row per repository, one column per library under each machine, the provider
 * beside them. Repositories and Orgs/Archives both draw this one table, so a copy reads the same
 * wherever it appears (the user, 2026-11-16: "CONSISTENT choices").
 *
 * Every word and colour comes from the display contract: a cell's facts, tone and attention are
 * Python's. The grid only lines them up and says each copy against its provider.
 */
export const html = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
export const toneOfFreshness = freshness => (freshness === 'current' ? 'success' : freshness === 'absent' ? 'muted' : 'warning');

export const PROVIDER = {'github.com': 'GitHub', 'gitlab.com': 'GitLab', 'bitbucket.org': 'Bitbucket'};

/** Machines in reading order: the perspective first, then by label. */
export function orderedMachines(data, perspective) {
  return [...data.machines].sort((a, b) => (b.id === perspective) - (a.id === perspective)
    || a.label.localeCompare(b.label));
}

/** This machine's view unless another was chosen, so every page starts from where you are. */
export function perspectiveOf(data, chosen) {
  if (chosen && data.machines.some(m => m.id === chosen)) return chosen;
  return data.machines.some(m => m.id === data.this_machine) ? data.this_machine : (data.machines[0] || {}).id;
}

/** A copy, said against its one source of truth, the provider it comes from: "matches GitHub",
 *  "3 behind GitHub", "2 ahead of GitHub (not pushed)", with uncommitted files and extra copies
 *  named plainly (the user, 2026-11-16: "same commit as WHAT?"). As of that machine's last fetch. */
export function copyText(cell, row) {
  if (!cell || !cell.present) return 'not here';
  // One box, two systems: this quiet copy is on a disk another machine reports live (Python's words).
  if (cell.same_disk_as) return cell.description;
  const facts = cell.facts || {};
  const host = (row.identity || {}).host;
  const remote = PROVIDER[host] || (host && host !== 'local' ? host : null);
  const parts = [];
  const changed = (facts.staged || 0) + (facts.unstaged || 0) + (facts.untracked || 0);
  if (changed) parts.push(`${changed} uncommitted item${changed === 1 ? '' : 's'}`);
  if (!remote) parts.push('no remote: the only copy is on machines');
  else if (!facts.has_upstream) parts.push(`not linked to a branch on ${remote}`);
  else if (facts.ahead && facts.behind) parts.push(`${facts.ahead} ahead and ${facts.behind} behind ${remote}`);
  else if (facts.ahead) parts.push(`${facts.ahead} ahead of ${remote} (not pushed)`);
  else if (facts.behind) parts.push(`${facts.behind} behind ${remote}`);
  else parts.push(`matches ${remote}`);
  if (facts.stashes) parts.push(`${facts.stashes} stash${facts.stashes === 1 ? '' : 'es'}`);
  if (cell.freshness && cell.freshness !== 'current') parts.push(`last known (${cell.freshness})`);
  if ((facts.checkouts || 1) > 1) parts.push(`${facts.checkouts} copies on this machine`);
  return parts.join(' · ');
}

export const dirtyOf = cell => {
  const facts = (cell && cell.facts) || {};
  return (facts.staged || 0) + (facts.unstaged || 0) + (facts.untracked || 0);
};
export const providerUrl = row => {
  const id = row.identity || {};
  return id.host && id.host !== 'local' && id.owner && id.name ? `https://${id.host}/${id.owner}/${id.name}` : null;
};

/** Each folder a machine keeps a repository in: its `copies` when it has several, else itself. */
export const copiesOf = cell => (cell.copies && cell.copies.length ? cell.copies : [{...(cell.facts || {}), place: cell.place}]);

/** Libraries under machines: one column per library a machine keeps these repositories in (two
 *  libraries, two columns), one column when it keeps them in one or none. */
export function columnsOf(machines, rows, reportedLibraries = []) {
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
    if (!libraries.length) {
      for (const entry of reportedLibraries) {
        if (entry.machine_id === machine.id && entry.library && !libraries.includes(entry.library)) libraries.push(entry.library);
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
export function cellIn(row, column) {
  const cell = row.cells[column.machine.id];
  if (!cell || !cell.present) return null;
  if (!column.split) return cell;
  const copy = copiesOf(cell).find(item => (item.place || {}).library === column.library);
  if (!copy) return null;
  const facts = {...copy, checkouts: 1, has_remote: (cell.facts || {}).has_remote, identity: (cell.facts || {}).identity};
  const tone = copyTone(facts);
  // This folder's own attention, not the machine's combined one (Python's `libraries` counts each
  // library the same way).
  return {...cell, copies: null, place: copy.place, facts, tone: cell.freshness === 'current' ? tone : 'warning',
          needs_attention: tone === 'danger' || tone === 'warning'};
}

/** Machine > Library > Folder > Repositories: the same tree on every machine (the user,
 *  2026-11-16: "it needs to be fractal"). The machine showing the page comes first, then the
 *  others by name; at every level, what needs attention first. A repository a machine keeps in
 *  two libraries is under both: they are two copies. `rows` are already filtered and sorted. */
export function placeTree(data, rows, thisMachine) {
  const machines = orderedMachines(data, thisMachine);
  const byAttention = (a, b) => (b.attention - a.attention) || a.name.localeCompare(b.name);
  const tree = [];
  for (const machine of machines) {
    const libraries = new Map();
    for (const row of rows) {
      const cell = row.cells[machine.id];
      if (!cell || !cell.present) continue;
      for (const copy of copiesOf(cell)) {
        const library = (copy.place || {}).library || 'Library not reported';
        const folder = (copy.place || {}).folder || '(directly in the library)';
        const column = {machine, library: (copy.place || {}).library, split: Boolean(cell.copies && cell.copies.length)};
        const here = column.split ? cellIn(row, column) : cell;
        if (!libraries.has(library)) libraries.set(library, new Map());
        const folders = libraries.get(library);
        if (!folders.has(folder)) folders.set(folder, []);
        if (!folders.get(folder).some(item => item.row.id === row.id)) folders.get(folder).push({row, attention: Boolean(here && here.needs_attention)});
      }
    }
    const libraryList = [...libraries.entries()].map(([name, folders]) => {
      const folderList = [...folders.entries()].map(([folder, items]) => ({
        name: folder, rows: items.map(item => item.row), attention: items.filter(item => item.attention).length,
      })).sort(byAttention);
      return {name, folders: folderList, repositories: folderList.reduce((n, f) => n + f.rows.length, 0),
              attention: folderList.reduce((n, f) => n + f.attention, 0)};
    }).sort(byAttention);
    tree.push({machine, libraries: libraryList,
               repositories: libraryList.reduce((n, l) => n + l.repositories, 0),
               attention: libraryList.reduce((n, l) => n + l.attention, 0)});
  }
  return tree;
}

/** The provider's commit, from the machine that fetched most recently. */
export function providerHead(row) {
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
export const shortCommit = head => (head ? head.slice(0, 7) : '');

/** What the grids keep across refreshes: the last request's answer, the work summary shown. */
export const gridState = {message: '', changes: null};
const gridOffsets = new Map();

/** The grid. `options`: perspective, columns (shared across several grids so they line up),
 *  actions (this computer only: requests and work summaries), onName(row), onChange() to redraw,
 *  asks (the "Ask a machine" row), advice (an Advice column). */
export function copyGrid(data, rows, options) {
  const {perspective, actions, onName, onChange = () => {}, asks = false, advice = false,
    showUnavailable = true} = options;
  const machines = orderedMachines(data, perspective);
  const columns = options.columns || columnsOf(machines, rows, data.libraries);
  // Alternate shades by machine, so a machine's libraries read as one block.
  const shades = new Map(machines.map((machine, index) => [machine.id, index % 2 ? 'map-shade-b' : 'map-shade-a']));
  const shadeOf = column => shades.get(column.machine.id);
  const startsGroup = column => columns.find(item => item.machine.id === column.machine.id) === column;
  const cellClass = (column, tone) => `${tone} ${shadeOf(column)}${startsGroup(column) ? ' map-group-start' : ''}`;
  const table = html('table', undefined, 'map-grid map-org copy-grid');
  const inspector = html('aside', undefined, 'copy-inspector');
  inspector.hidden = true;
  const send = async (kind, list, column) => {
    const machine = column.machine;
    const target = `${machine.label}${column.library ? ` · ${column.library}` : ''}`;
    const action = kind === 'pull' ? 'Fast-forward' : 'Clone';
    const subject = list.length === 1 ? list[0].name : `${list.length} repositories`;
    const timing = machine.id === data.this_machine ? 'Runs here now.' : 'The receiving machine decides whether to run or ask for approval.';
    if (!window.confirm(`${action} ${subject} on ${target}? ${timing}`)) return;
    try {
      const done = await actions.send({to: machine.id, to_label: machine.label, kind, items: list.map(row => ({
        repo_id: row.id, name: (row.identity || {}).name || row.name, host: (row.identity || {}).host,
        owner: (row.identity || {}).owner, folder: (row.place || {}).folder || '',
        ...(column.library ? {library: column.library} : {})}))});
      gridState.message = done.message;
    } catch (error) { gridState.message = error.message; }
    onChange();
  };
  // Equal widths for every library column, whatever its words.
  const widths = html('colgroup');
  widths.append(html('col', undefined, 'map-col-repo'), html('col', undefined, 'map-col-online'));
  for (const column of columns) widths.append(html('col'));
  if (advice) widths.append(html('col', undefined, 'map-col-advice'));
  table.append(widths);
  // Machines on the first header row, each spanning its libraries on the second.
  const head = html('tr'), under = html('tr');
  const repo = html('th', 'Repository'), online = html('th', 'Online');
  repo.rowSpan = 2; online.rowSpan = 2;
  head.append(repo, online);
  for (const column of columns) {
    const first = startsGroup(column);
    if (first) {
      const th = html('th', column.machine.id === perspective ? `${column.machine.label} (perspective)` : column.machine.label);
      th.className = `tone-${toneOfFreshness(column.machine.freshness)} ${shadeOf(column)} map-group-start`;
      th.colSpan = columns.filter(item => item.machine.id === column.machine.id).length;
      head.append(th);
    }
    under.append(html('th', column.library || '', `map-library ${shadeOf(column)}${first ? ' map-group-start' : ''}`));
  }
  if (advice) { const th = html('th', 'Advice'); th.rowSpan = 2; head.append(th); }
  const thead = html('thead'); thead.append(head, under); table.append(thead);
  const body = html('tbody');
  if (actions && asks) {
    // Have a machine bring these copies forward, or clone the ones it lacks. The machine doing
    // the work checks each one again and runs it on arrival (both operations cannot lose work).
    const line = html('tr', undefined, 'map-asks');
    const label = html('td'); label.append(html('span', 'Do it on a machine:', 'host-note'));
    line.append(label, html('td'));
    for (const column of columns) {
      const machine = column.machine;
      const cell = html('td', undefined, cellClass(column, ''));
      // A fast-forward is all the button can do: only copies simply behind their provider.
      const held = rows.filter(row => canFastForward(cellIn(row, column)));
      const missing = rows.filter(row => column.library && !cellIn(row, column) && providerUrl(row));
      const here = machine.id === data.this_machine;
      const suffix = here ? ' here' : '';
      const choices = [
        ['pull', held, `Fast-forward ${held.length}${suffix}`, 'No existing checkout is clean and behind-only.'],
        ['clone', missing, `Clone ${missing.length} missing${suffix}`, column.library
          ? 'No missing repository with a known clone source.' : 'No destination library is selected.'],
      ];
      for (const [kind, items, label, reason] of choices) {
        if (!items.length && !showUnavailable) continue;
        const button = html('button', label);
        button.type = 'button';
        button.disabled = !items.length;
        if (items.length) {
          button.onclick = () => send(kind, items, column);
          cell.append(button);
        } else {
          const explanation = html('span', undefined, 'unavailable-action');
          explanation.tabIndex = 0;
          explanation.title = reason;
          explanation.setAttribute('aria-label', `${label}. ${reason}`);
          explanation.append(button);
          cell.append(explanation);
        }
      }
      line.append(cell);
    }
    if (advice) line.append(html('td'));
    body.append(line);
  }
  for (const row of rows) {
    const line = html('tr', undefined, row.needs_attention ? 'map-attention' : '');
    line.dataset.repoId = row.id;
    const name = html('button', `${row.needs_attention ? '⚑ ' : ''}${row.identity ? row.identity.name : row.name}`, 'repo-link');
    name.type = 'button';
    if (onName) name.onclick = () => onName(row);
    const first = html('td'); first.append(name);
    if (row.identity && row.identity.owner) first.append(html('span', row.identity.owner, 'host-note'));
    if (row.publication && !row.publication.published) {
      const held = html('span', 'not published', 'badge tone-warning'); held.title = row.publication.reason; first.append(held);
    }
    line.append(first);
    const online = html('td'); const url = providerUrl(row);
    if (url) { const link = html('a', `${PROVIDER[row.identity.host] || row.identity.host} ↗`); link.href = url; link.target = '_blank'; link.rel = 'noopener'; online.append(link); }
    else online.append(html('span', 'no remote', 'host-note'));
    const upstream = providerHead(row);
    if (upstream) online.append(html('span', shortCommit(upstream), 'host-note'));
    line.append(online);
    for (const column of columns) {
      const machine = column.machine;
      const cell = cellIn(row, column);
      const td = html('td', undefined, cellClass(column, cell && cell.present ? `tone-${cell.tone}` : 'tone-muted'));
      const status = html('span', !cell && column.split && (row.cells[machine.id] || {}).present
        ? `not in ${column.library}` : copyText(cell, row));
      td.append(status);
      if (actions && dirtyOf(cell) && !cell.same_disk_as) {
        // Uncommitted work: ask that machine what it is (names and line counts, never contents).
        const show = html('button', 'Review changes', 'quiet copy-action'); show.type = 'button';
        const key = JSON.stringify([row.id, machine.id, column.library]);
        show.setAttribute('aria-label', `Review changes: ${row.name} on ${machine.label}${column.library ? ` (${column.library})` : ''}`);
        const summarize = view => {
          const [copy, ...others] = inspectorCopies(view);
          if (!copy || others.length || !Number.isInteger(copy.untracked_folders)) return;
          const facts = cell.facts || {};
          const summary = copyText({...cell, facts: {...facts, staged: 0, unstaged: 0, untracked: 0}}, row);
          status.textContent = `${copy.summary} · ${summary}`;
        };
        if (gridState.changes?.key === key) {
          summarize(gridState.changes);
          gridState.changes.trigger = show;
          td.classList.add('copy-selected');
        }
        show.onclick = async () => {
          const view = {title: [row.name, machine.label, column.library].filter(Boolean).join(' · '),
            key, library: column.library, loading: true, trigger: show,
            requestDetail: offset => actions.changes(row.id, machine.id, offset)};
          gridState.changes = view;
          drawInspector(inspector, show);
          try { view.result = await actions.changes(row.id, machine.id); }
          catch (error) { view.error = error.message; }
          view.loading = false;
          if (gridState.changes === view) {
            summarize(view);
            drawInspector(activeInspector);
          }
        };
        td.append(show);
      } else if (actions && ((!cell && column.library && providerUrl(row)) || canFastForward(cell))) {
        const clone = !cell;
        const button = html('button', clone ? 'Clone here' : 'Fast-forward', 'quiet copy-action');
        button.type = 'button';
        button.setAttribute('aria-label', `${button.textContent}: ${row.name} on ${machine.label}${column.library ? ` (${column.library})` : ''}`);
        button.onclick = () => send(clone ? 'clone' : 'pull', [row], column);
        td.append(button);
      }
      const commit = cell && cell.present && shortCommit((cell.facts || {}).head);
      if (commit) td.append(html('span', commit, 'host-note'));
      line.append(td);
    }
    if (advice) line.append(html('td', row.advice));
    body.append(line);
  }
  table.append(body);
  const scroll = html('div', undefined, 'table-scroll copy-grid-scroll'); scroll.append(table);
  const scrollKey = JSON.stringify([location.hash, perspective, rows[0]?.id, rows.length]);
  const offset = gridOffsets.get(scrollKey);
  if (offset) requestAnimationFrame(() => { scroll.scrollLeft = offset.left; scroll.scrollTop = offset.top; });
  scroll.addEventListener('scroll', () => gridOffsets.set(scrollKey, {left: scroll.scrollLeft, top: scroll.scrollTop}), {passive: true});
  const wrapper = html('div', undefined, 'copy-grid-wrap'); wrapper.append(scroll, inspector);
  return wrapper;
}

function canFastForward(cell) {
  const facts = (cell && cell.facts) || {};
  return cell && !cell.same_disk_as && !dirtyOf(cell) && !facts.operation && facts.behind > 0 && !(facts.ahead > 0);
}

/** The last request's answer and the inspector for the selected checkout. */
export function gridNotes(container) {
  if (gridState.message) container.append(html(gridState.message.includes('\n') ? 'pre' : 'p', gridState.message, 'host-note'));
  if (!gridState.changes || activeInspector?.isConnected) return;
  const inspector = gridState.changes.trigger?.closest('.copy-grid-wrap')?.querySelector('.copy-inspector');
  if (inspector && container.contains(inspector)) drawInspector(inspector);
}

let activeInspector;
let selectedCopy;
function inspectorCopies(view) {
  const copies = view.result?.copies || [];
  return view.library && copies.every(copy => Object.hasOwn(copy, 'library'))
    ? copies.filter(copy => copy.library === view.library) : copies;
}

function drawInspector(box, trigger) {
  if (activeInspector && activeInspector !== box) activeInspector.hidden = true;
  activeInspector = box;
  const view = gridState.changes;
  selectedCopy?.classList.remove('copy-selected');
  selectedCopy = view.trigger?.closest('td');
  selectedCopy?.classList.add('copy-selected');
  box.hidden = false;
  box.setAttribute('aria-label', view.title);
  const keepFocus = box.contains(document.activeElement);
  box.replaceChildren();
  const close = html('button', 'Close'); close.type = 'button';
  const dismiss = () => {
    gridState.changes = null;
    box.hidden = true;
    selectedCopy?.classList.remove('copy-selected');
    view.trigger?.focus({preventScroll: true});
  };
  close.onclick = dismiss;
  box.onkeydown = event => { if (event.key === 'Escape') dismiss(); };
  const header = html('div', undefined, 'detail-header');
  header.append(html('h3', view.title), close);
  box.append(header);
  if (view.loading) box.append(html('p', 'Asking…', 'host-note'));
  else if (view.error) box.append(html('p', view.error, 'tone-text-warning'));
  else {
    const copies = view.result.copies || [];
    const scoped = view.library && copies.every(copy => Object.hasOwn(copy, 'library'));
    const shown = inspectorCopies(view);
    if (!shown.length) box.append(html('p', 'No checkout details were returned for this library.'));
    if (!scoped && view.library && copies.length > 1) box.append(html('p', 'This peer reported changes across its libraries.'));
    if (shown.length && view.requestDetail) {
      const page = Number.isInteger(view.offset) ? view.offset : null;
      const request = (label, offset) => {
        const button = html('button', label, 'quiet');
        button.type = 'button';
        button.onclick = async () => {
          button.disabled = true;
          try {
            const result = await view.requestDetail(offset);
            if (gridState.changes !== view) return;
            view.result = result;
            view.offset = offset;
            view.detailError = '';
          } catch (error) {
            view.detailError = error.message;
          }
          if (gridState.changes === view) drawInspector(activeInspector);
        };
        box.append(button);
      };
      if (page === null) request('Request complete file list', 0);
      else {
        if (page > 0) request('Previous files', Math.max(0, page - 200));
        const next = shown.find(copy => Number.isInteger(copy.next_offset))?.next_offset;
        if (next !== undefined) request('More files', next);
        request('Show summary', undefined);
      }
      if (view.detailError) box.append(html('p', view.detailError, 'tone-text-warning'));
    }
    for (const [index, copy] of shown.entries()) {
      box.append(html('p', `${shown.length > 1 ? `Copy ${index + 1}: ` : ''}${copy.summary}`));
      const list = html('ul');
      for (const file of copy.files || []) {
        const lines = file.added >= 0 && (file.added || file.deleted) ? ` +${file.added} −${file.deleted}` : '';
        const status = file.kind === 'folder' ? 'new folder' : file.status;
        list.append(html('li', `${file.name} · ${status}${lines}${file.line_endings_only ? ' · line endings only' : ''}`));
      }
      box.append(list);
    }
  }
  if (trigger || keepFocus) close.focus({preventScroll: true});
}

/** The words under every grid: what "matches" is measured against, and when. */
export const GRID_FOOTNOTE = 'Each copy is compared with its provider as of that machine\'s last fetch, and the faded '
  + 'code under it is the commit it is on. To fetch now: gitso fetch <organization folder>, or set a schedule in Settings.';
