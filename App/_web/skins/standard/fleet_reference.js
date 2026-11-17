/* Reference: the catalog of operations by layer, and the documents (the user, 2026-11-17).
 * Everything comes from Python (App/_web/reference.py): gitso's own command table, each
 * script's manual, this project's documents. Reading only.
 */
import {html} from './fleet_grid.js';

const ui = {built: false, catalog: null, shown: null, query: '', error: ''};

function link(label, url) {
  const a = html('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener';
  return a;
}

async function open(call, what, draw) {
  ui.shown = {title: 'Reading…', text: ''}; draw();
  try { ui.shown = await call(what); } catch (error) { ui.shown = {title: 'Could not read it', text: error.message}; }
  draw();
}

function draw(container, call) {
  const redraw = () => draw(container, call);
  container.replaceChildren();
  if (ui.error) { container.append(html('p', ui.error, 'tone-text-warning')); return; }
  if (!ui.catalog) { container.append(html('p', 'Reading the catalog…', 'host-note')); return; }
  const grid = html('div', undefined, 'ref-grid');
  const side = html('div', undefined, 'ref-side');
  const search = html('input'); search.type = 'search'; search.placeholder = 'Find an operation or a document';
  search.value = ui.query; search.setAttribute('aria-label', 'Find in the reference');
  search.oninput = () => { ui.query = search.value; redraw(); container.querySelector('input[type=search]').focus(); };
  side.append(search);
  const wanted = ui.query.trim().toLocaleLowerCase();
  const matches = text => !wanted || text.toLocaleLowerCase().includes(wanted);
  for (const layer of ui.catalog.layers) {
    const entries = layer.commands.filter(c => matches(`${c.command} ${c.description}`));
    if (!entries.length) continue;
    const group = html('details', undefined, 'ref-group'); group.open = true;
    group.append(html('summary', `${layer.label} (${entries.length})`));
    for (const entry of entries) {
      const item = html('button', undefined, 'ref-item'); item.type = 'button';
      item.append(html('code', `gitso ${entry.command}`), html('span', entry.description, 'host-note'));
      item.onclick = () => open(call, {command: entry.command}, redraw);
      group.append(item);
      if (entry.git) { const more = html('p', '', 'ref-more'); more.append(link('Git\'s own manual for this', entry.git)); group.append(more); }
    }
    side.append(group);
  }
  const documents = ui.catalog.documents.filter(d => matches(`${d.id} ${d.title}`));
  if (documents.length) {
    const group = html('details', undefined, 'ref-group'); group.open = true;
    group.append(html('summary', `Documents (${documents.length})`));
    for (const doc of documents) {
      const item = html('button', undefined, 'ref-item'); item.type = 'button';
      item.append(html('code', doc.id), html('span', doc.title, 'host-note'));
      item.onclick = () => open(call, {document: doc.id}, redraw);
      group.append(item);
    }
    side.append(group);
  }
  const online = html('details', undefined, 'ref-group'); online.open = true;
  online.append(html('summary', 'Online manuals'));
  for (const item of ui.catalog.links) { const line = html('p', '', 'ref-more'); line.append(link(item.label, item.url)); online.append(line); }
  side.append(online);
  const page = html('article', undefined, 'card ref-page');
  if (ui.shown) {
    page.append(html('h3', ui.shown.title));
    if (ui.shown.script) page.append(html('p', ui.shown.script, 'host-note'));
    page.append(html('pre', ui.shown.text, 'ref-text'));
  } else {
    page.append(html('h3', 'Reference'), html('p', 'Choose an operation to read its manual, or a document. ' +
      'Every operation here is one you can run in a terminal as written.', 'host-note'));
  }
  grid.append(side, page);
  container.append(grid);
}

/** The Reference tile's number and line. */
export function referenceSummary() {
  if (!ui.catalog) return ['Reference', 'operations and documents'];
  const count = ui.catalog.layers.reduce((sum, layer) => sum + layer.commands.length, 0);
  return [String(count), `operations · ${ui.catalog.documents.length} documents`];
}

/** Built once; `call(payload)` asks this computer's app. Without it (the view on another
 *  device) the page says where the reference is. */
export function renderReference(container, call, onLoaded) {
  if (ui.built) return;
  ui.built = true;
  if (!call) { container.replaceChildren(html('p', 'The reference opens on the computer that runs gitSpecOps.', 'host-note')); return; }
  draw(container, call);
  call({}).then(answer => { ui.catalog = answer; draw(container, call); if (onLoaded) onLoaded(); })
    .catch(error => { ui.error = error.message; draw(container, call); });
}
