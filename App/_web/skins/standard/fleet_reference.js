/* Reference: the catalog of operations by layer, each with its manual, its source, and a way to
 * use it; and the documents (the user, 2026-11-17: "the info box needs a button").
 * Everything comes from Python (App/_web/reference.py): gitso's own command table, each
 * script's manual, this project's documents.
 *
 * Using an operation: on this machine it opens a terminal in the folder you chose with the
 * command typed and running, so its own screen, plan and questions are in front of you. On
 * another machine only the two operations that cannot lose work can be sent (fast-forward and
 * clone); they run there when it next checks in.
 */
import {html} from './fleet_grid.js';
import {machineActions} from './fleet_actions.js';

const ui = {built: false, catalog: null, shown: null, query: '', error: '', chosen: null,
            use: {machine: '', kind: 'none', target: '', extra: '', note: ''}};
// Operations another machine can be asked to do, and the request each becomes.
const REMOTE = {pull: 'pull', 'machine catch-up': 'pull', 'archive update': 'pull', clone: 'clone', 'machine materialize': 'clone'};

function link(label, url) {
  const a = html('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener';
  return a;
}
function option(value, label) { const o = html('option', label); o.value = value; return o; }

// ---- the list: rebuilt only when the catalog or the search changes, so a click keeps your place
function drawList(box, context, drawPage) {
  box.replaceChildren();
  const wanted = ui.query.trim().toLocaleLowerCase();
  const matches = text => !wanted || text.toLocaleLowerCase().includes(wanted);
  const item = (key, code, words, open) => {
    const b = html('button', undefined, `ref-item${ui.chosen === key ? ' ref-chosen' : ''}`); b.type = 'button';
    b.dataset.key = key;
    b.append(html('code', code), html('span', words, 'host-note'));
    b.onclick = () => {
      ui.chosen = key;
      for (const other of box.querySelectorAll('.ref-item')) other.classList.toggle('ref-chosen', other.dataset.key === key);
      open();
    };
    return b;
  };
  const read = async what => {
    ui.shown = {title: 'Reading…', text: ''}; drawPage();
    try { ui.shown = {...await context.call(what), ...what}; } catch (error) { ui.shown = {title: 'Could not read it', text: error.message}; }
    ui.use.note = ''; drawPage();
  };
  for (const layer of ui.catalog.layers) {
    const entries = layer.commands.filter(c => matches(`${c.command} ${c.description}`));
    if (!entries.length) continue;
    const group = html('details', undefined, 'ref-group'); group.open = true;
    group.append(html('summary', `${layer.label} (${entries.length})`));
    for (const entry of entries) {
      group.append(item(`c/${entry.command}`, `gitso ${entry.command}`, entry.description, () => read({command: entry.command})));
      if (entry.git) { const more = html('p', '', 'ref-more'); more.append(link('Git\'s own manual for this', entry.git)); group.append(more); }
    }
    box.append(group);
  }
  const documents = ui.catalog.documents.filter(d => matches(`${d.id} ${d.title}`));
  if (documents.length) {
    const group = html('details', undefined, 'ref-group'); group.open = true;
    group.append(html('summary', `Documents (${documents.length})`));
    for (const doc of documents) group.append(item(`d/${doc.id}`, doc.id, doc.title, () => read({document: doc.id})));
    box.append(group);
  }
  const online = html('details', undefined, 'ref-group'); online.open = true;
  online.append(html('summary', 'Online manuals'));
  for (const entry of ui.catalog.links) { const line = html('p', '', 'ref-more'); line.append(link(entry.label, entry.url)); online.append(line); }
  box.append(online);
}

// ---- using an operation
function rowsFor(data, kind, target) {
  if (kind === 'repository') return data.rows.filter(row => row.id === target);
  if (kind === 'organization') return data.rows.filter(row => row.group_id === target);
  return data.rows;
}

function useForm(context, drawPage) {
  const data = context.data(), command = ui.shown.command, use = ui.use;
  const box = html('section', undefined, 'ref-use');
  box.append(html('h4', 'Use it'));
  if (!data || !data.local_actions) { box.append(html('p', 'Operations are run from the computer that runs gitSpecOps.', 'host-note')); return box; }
  const me = data.this_machine;
  if (!data.machines.some(m => m.id === use.machine)) use.machine = me;
  const here = use.machine === me;
  const machine = data.machines.find(m => m.id === use.machine) || {id: me, label: 'this machine'};
  const line = html('div', undefined, 'ref-fields');
  const where = html('select');
  for (const m of data.machines) where.append(option(m.id, m.id === me ? `${m.label} (this machine)` : m.label));
  where.value = use.machine;
  where.onchange = () => { use.machine = where.value; use.note = ''; drawPage(); };
  const kinds = [['none', 'No particular folder'], ['repository', 'One repository'], ['organization', 'An organization'],
                 ...(here ? [['library', 'A library folder']] : [])];
  if (!kinds.some(([id]) => id === use.kind)) use.kind = 'none';
  const kind = html('select');
  for (const [id, label] of kinds) kind.append(option(id, label));
  kind.value = use.kind;
  kind.onchange = () => { use.kind = kind.value; use.target = ''; use.note = ''; drawPage(); };
  const label = (text, control) => { const l = html('label', text); l.append(control); return l; };
  line.append(label('On', where), label('Pointed at', kind));
  if (use.kind !== 'none') {
    const target = html('select');
    let choices = [];
    if (use.kind === 'repository') {
      choices = data.rows.filter(row => !here || (row.cells[me] && row.cells[me].present))
        .map(row => [row.id, row.name]).sort((a, b) => a[1].localeCompare(b[1]));
    } else if (use.kind === 'organization') {
      choices = (data.groups || []).map(group => [group.id, `${group.label} (${group.count})`]).sort((a, b) => a[1].localeCompare(b[1]));
    } else {
      choices = (data.libraries || []).filter(entry => entry.machine_id === me && entry.library).map(entry => [entry.library, entry.library]);
    }
    for (const [id, text] of choices) target.append(option(id, text));
    if (!choices.some(([id]) => id === use.target)) use.target = choices.length ? choices[0][0] : '';
    target.value = use.target;
    target.onchange = () => { use.target = target.value; use.note = ''; drawPage(); };
    line.append(label('Which', target));
  }
  box.append(line);
  const request = REMOTE[command];
  if (here) {
    const extra = html('input'); extra.type = 'text'; extra.spellcheck = false; extra.value = use.extra;
    extra.placeholder = 'More arguments, as you would type them (optional)';
    extra.setAttribute('aria-label', 'More arguments');
    extra.oninput = () => { use.extra = extra.value; };
    const go = html('button', 'Open it in a terminal'); go.type = 'button';
    go.title = 'A terminal opens in that folder with this command running: its own screen, plan and questions';
    go.disabled = use.kind === 'organization';
    go.onclick = async () => {
      use.note = 'Opening…'; drawPage();
      try {
        const payload = {op: 'run-command', command, arguments: use.extra};
        if (use.kind === 'repository') payload.repo_id = use.target;
        if (use.kind === 'library') payload.library = use.target;
        use.note = (await context.repoAction(payload)).message;
      } catch (error) { use.note = error.message; }
      drawPage();
    };
    const row = html('div', undefined, 'ref-fields'); row.append(extra, go); box.append(row);
    if (use.kind === 'organization') box.append(html('p', 'A terminal opens in one folder: choose a repository or a library. ' +
      'For a whole organization, the buttons below act on every repository in it.', 'host-note'));
  } else if (!request) {
    box.append(html('p', `Only a fast-forward or a clone can be sent to another machine: they cannot lose work. To run "gitso ${command}" ` +
      `on ${machine.label}, open this page there.`, 'host-note'));
  }
  // The two operations that can run without a terminal, here or there, on what was chosen.
  if (request || use.kind !== 'none') {
    const rows = rowsFor(data, use.kind === 'library' ? 'none' : use.kind, use.target);
    const scope = use.kind === 'organization' ? ((data.groups || []).find(g => g.id === use.target) || {}).label || ''
      : use.kind === 'repository' ? (rows[0] || {}).name || '' : 'everything it has';
    const bar = machineActions({data, rows, machine, scope, actions: context.actions(), redraw: drawPage, clone: use.kind !== 'none' && use.kind !== 'library'});
    if (bar) box.append(bar);
    else if (request) box.append(html('p', `Nothing to fast-forward or clone on ${machine.label} for that choice.`, 'host-note'));
  }
  if (use.note) box.append(html('p', use.note, 'host-note'));
  return box;
}

function drawPageInto(page, context) {
  const drawPage = () => drawPageInto(page, context);
  const top = page.scrollTop;
  page.replaceChildren();
  if (!ui.shown) {
    page.append(html('h3', 'Reference'), html('p', 'Choose an operation to read its manual, see its source and use it; or a document.', 'host-note'));
    return;
  }
  page.append(html('h3', ui.shown.title));
  if (ui.shown.script) page.append(html('p', ui.shown.script, 'host-note'));
  if (ui.shown.command) page.append(useForm(context, drawPage));
  page.append(html('pre', ui.shown.text, 'ref-text'));
  if (ui.shown.source) {
    const code = html('details', undefined, 'ref-source'); code.open = true;
    code.append(html('summary', `The code: ${ui.shown.script}`), html('pre', ui.shown.source, 'ref-code'));
    page.append(code);
  }
  page.scrollTop = top;
}

/** The Reference tile's number and line. */
export function referenceSummary() {
  if (!ui.catalog) return ['Reference', 'operations and documents'];
  const count = ui.catalog.layers.reduce((sum, layer) => sum + layer.commands.length, 0);
  return [String(count), `operations · ${ui.catalog.documents.length} documents`];
}

/** Built once. `context`: call(payload) reads the reference; data() is the current page data;
 *  actions() the fleet actions; repoAction(payload) a local repository action. Without `call`
 *  (the view on another device) the page says where the reference is. */
export function renderReference(container, context, onLoaded) {
  if (ui.built) return;
  ui.built = true;
  if (!context || !context.call) { container.replaceChildren(html('p', 'The reference opens on the computer that runs gitSpecOps.', 'host-note')); return; }
  const grid = html('div', undefined, 'ref-grid');
  const side = html('div', undefined, 'ref-side');
  const search = html('input'); search.type = 'search'; search.placeholder = 'Find an operation or a document';
  search.setAttribute('aria-label', 'Find in the reference');
  const list = html('div', 'Reading the catalog…', 'ref-list');
  const page = html('article', undefined, 'card ref-page');
  const drawPage = () => drawPageInto(page, context);
  search.oninput = () => { ui.query = search.value; if (ui.catalog) drawList(list, context, drawPage); };
  side.append(search, list);
  grid.append(side, page);
  container.replaceChildren(grid);
  drawPage();
  context.call({}).then(answer => { ui.catalog = answer; drawList(list, context, drawPage); if (onLoaded) onLoaded(); })
    .catch(error => { list.textContent = error.message; });
}
