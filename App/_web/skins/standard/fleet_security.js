/* The Security tab: choose repositories (or whole organizations), audit their working files and
 * every commit, and read the masked findings. Every decision is Python's: what counts as a
 * finding, its severity, whether a check is complete. Results stay in this browser tab; the
 * audit itself writes nothing anywhere. Only repositories with a copy on this machine appear.
 */
const html = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const STATUS = {
  passed: ['Passed', 'success', 'Nothing to review in what was checked.'],
  'review-required': ['Review', 'warning', 'Findings to look at before publishing.'],
  blocked: ['Blocked', 'danger', 'A high-severity finding: do not publish until it is resolved.'],
  incomplete: ['Incomplete', 'muted', 'Part of this could not be checked, so it proves nothing.'],
};

const ui = {built: false, container: null, data: null, connection: null, selected: new Set(), engines: [],
            useEngines: new Set(), history: true, audit: null, polling: null, open: new Set(), signature: ''};

function token() { return ui.data && ui.data.local_actions && ui.data.local_actions.token; }
async function act(action, payload = {}) {
  return ui.connection.desktopAction(action, payload, token(), {structured: true});
}
function localRows() {
  return ui.data.rows.filter(row => row.security_action && row.security_action.available);
}
function nameOf(repoId) {
  const row = ui.data.rows.find(item => item.id === repoId);
  return row ? row.name : repoId.slice(0, 12);
}

// ---- scanners ---------------------------------------------------------------------------------
async function loadEngines() {
  const box = document.getElementById('security-engines');
  box.replaceChildren(html('p', 'Looking for installed scanners…', 'host-note'));
  try { ui.engines = (await act('security-engines')).engines || []; }
  catch (error) { box.replaceChildren(html('p', error.message, 'tone-warning')); return; }
  box.replaceChildren();
  const builtin = html('div', undefined, 'sec-engine');
  builtin.append(html('strong', '✓ Built-in checks'), html('span', 'Always on: credential shapes, personal details, ' +
    'your own identity values and leak descriptions, from your saved security policy.', 'host-note'));
  box.append(builtin);
  for (const engine of ui.engines) {
    const row = html('label', undefined, 'sec-engine');
    const tick = html('input'); tick.type = 'checkbox'; tick.disabled = !engine.installed;
    tick.checked = engine.installed && ui.useEngines.has(engine.engine);
    tick.onchange = () => { tick.checked ? ui.useEngines.add(engine.engine) : ui.useEngines.delete(engine.engine); };
    const text = html('span');
    text.append(html('strong', `${engine.label}: ${engine.installed ? 'installed' : 'not installed'}`),
                html('span', ` ${engine.about}`, 'host-note'));
    if (!engine.installed && engine.home_page) {
      const link = html('a', 'Where to get it'); link.href = engine.home_page; link.target = '_blank'; link.rel = 'noopener';
      text.append(html('span', ' '), link);
    }
    row.append(tick, text);
    box.append(row);
  }
  const again = html('button', 'Check again', 'quiet');
  again.type = 'button';
  again.onclick = loadEngines;
  box.append(html('p', 'gitSpecOps never installs these. Install one yourself, then check again; ' +
    'a selected scanner that fails is reported as a gap, never as a pass.', 'host-note'), again);
}

// ---- what to audit ------------------------------------------------------------------------------
function renderScope() {
  const box = document.getElementById('security-scope');
  const rows = localRows();
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.group_id)) groups.set(row.group_id, {label: row.namespace, host: (row.identity || {}).host, rows: []});
    groups.get(row.group_id).rows.push(row);
  }
  box.replaceChildren();
  if (!rows.length) { box.append(html('p', 'No repository has a copy on this machine yet.', 'empty')); return; }
  const ordered = [...groups.entries()].sort((a, b) => b[1].rows.length - a[1].rows.length || a[1].label.localeCompare(b[1].label));
  for (const [groupId, group] of ordered) {
    const details = html('details', undefined, 'sec-group');
    details.open = ui.open.has(groupId);
    details.ontoggle = () => { details.open ? ui.open.add(groupId) : ui.open.delete(groupId); };
    const summary = html('summary');
    const all = html('input'); all.type = 'checkbox';
    const chosen = group.rows.filter(row => ui.selected.has(row.id)).length;
    all.checked = chosen === group.rows.length;
    all.indeterminate = chosen > 0 && chosen < group.rows.length;
    all.setAttribute('aria-label', `Choose every repository in ${group.label}`);
    all.onclick = event => event.stopPropagation();
    all.onchange = () => { for (const row of group.rows) all.checked ? ui.selected.add(row.id) : ui.selected.delete(row.id); renderScope(); };
    summary.append(all, html('strong', ` ${group.label}`), html('span', ` · ${group.rows.length} here${group.host && group.host !== 'local' ? ` · ${group.host}` : ''}`, 'host-note'));
    details.append(summary);
    for (const row of group.rows.sort((a, b) => a.name.localeCompare(b.name))) {
      const line = html('label', undefined, 'sec-repo');
      const tick = html('input'); tick.type = 'checkbox'; tick.checked = ui.selected.has(row.id);
      tick.onchange = () => { tick.checked ? ui.selected.add(row.id) : ui.selected.delete(row.id); renderScope(); };
      line.append(tick, html('span', ` ${row.identity ? row.identity.name : row.name}`));
      details.append(line);
    }
    box.append(details);
  }
  renderRunBar();
}

function renderRunBar() {
  const bar = document.getElementById('security-run');
  bar.replaceChildren();
  const running = ui.audit && ui.audit.state === 'running';
  const history = html('label', undefined, 'sec-option');
  const tick = html('input'); tick.type = 'checkbox'; tick.checked = ui.history; tick.disabled = running;
  tick.onchange = () => { ui.history = tick.checked; };
  history.append(tick, html('span', ' Every commit, not only the files as they are now (needed before publishing; slower)'));
  const go = html('button', running ? 'Auditing…' : `Audit ${ui.selected.size} ${ui.selected.size === 1 ? 'repository' : 'repositories'}`);
  go.type = 'button';
  go.disabled = running || !ui.selected.size || !token();
  go.onclick = start;
  bar.append(history, go);
  if (running) {
    const stop = html('button', 'Stop', 'quiet'); stop.type = 'button';
    stop.onclick = async () => { try { setAudit((await act('security-stop')).audit); } catch (error) { say(error.message); } };
    bar.append(stop);
  }
  if (ui.selected.size) {
    const clear = html('button', 'Clear choice', 'quiet'); clear.type = 'button';
    clear.disabled = running;
    clear.onclick = () => { ui.selected.clear(); renderScope(); };
    bar.append(clear);
  }
}

function say(text) { document.getElementById('security-message').textContent = text; }

async function start() {
  say('');
  try {
    setAudit((await act('security-start', {repo_ids: [...ui.selected], history: ui.history, engines: [...ui.useEngines]})).audit);
    poll();
  } catch (error) { say(error.message); }
}

function poll() {
  clearTimeout(ui.polling);
  ui.polling = setTimeout(async () => {
    try { setAudit((await act('security-status')).audit); } catch (error) { say(error.message); }
    if (ui.audit && ui.audit.state === 'running') poll();
  }, 1500);
}

// ---- results ------------------------------------------------------------------------------------
function findingsOf(record) {
  return record && Array.isArray(record.findings)
    ? record.findings.filter(item => item.classification !== 'quiet' && !item.review_id) : [];
}

function setAudit(audit) {
  ui.audit = audit;
  renderRunBar();
  const box = document.getElementById('security-results');
  box.replaceChildren();
  if (!audit) { box.append(html('p', 'No audit has run since gitSpecOps started. Results are kept only here, until it restarts.', 'host-note')); return; }
  const progress = html('div', undefined, 'sec-progress');
  const bar = html('progress'); bar.max = audit.total; bar.value = audit.done;
  const words = audit.state === 'running'
    ? `${audit.done} of ${audit.total} checked${audit.current ? ` · now ${nameOf(audit.current)}` : ''}`
    : `${audit.state === 'stopped' ? 'Stopped' : 'Finished'}: ${audit.done} of ${audit.total} checked${audit.history ? ', every commit included' : ', current files only'}` +
      `${audit.engines.length ? ` · with ${audit.engines.join(', ')}` : ''}`;
  progress.append(bar, html('span', words));
  box.append(progress);
  const counts = {passed: 0, 'review-required': 0, blocked: 0, incomplete: 0};
  for (const entry of audit.results) counts[entry.security.check_status] = (counts[entry.security.check_status] || 0) + 1;
  const chips = html('div', undefined, 'sec-chips');
  for (const [status, [label, tone]] of Object.entries(STATUS)) chips.append(html('span', `${counts[status] || 0} ${label.toLowerCase()}`, `pill tone-${tone}`));
  box.append(chips);
  const order = {blocked: 0, 'review-required': 1, incomplete: 2, passed: 3};
  for (const entry of [...audit.results].sort((a, b) => order[a.security.check_status] - order[b.security.check_status])) {
    const result = entry.security;
    const [label, tone, meaning] = STATUS[result.check_status] || STATUS.incomplete;
    const tree = findingsOf(result.working_tree), past = findingsOf(result.history);
    const gaps = [...(result.gaps || []), ...((result.working_tree || {}).gaps || []), ...((result.history || {}).gaps || [])];
    const item = html('details', undefined, `sec-result tone-border-${tone}`);
    const summary = html('summary');
    summary.append(html('span', label, `pill tone-${tone}`), html('strong', ` ${nameOf(entry.repo_id)}`),
                   html('span', ` · files: ${tree.length} · history: ${result.history ? past.length : 'not checked'}` +
                                `${gaps.length ? ` · ${gaps.length} not inspected` : ''}${entry.checkout > 1 ? ` · copy ${entry.checkout}` : ''}`, 'host-note'));
    item.append(summary, html('p', meaning, 'host-note'));
    for (const [title, list, record] of [['In the files as they are now', tree, result.working_tree],
                                         ['In history (every commit)', past, result.history]]) {
      if (!record) continue;
      item.append(html('h4', `${title}: ${list.length ? `${list.length} to review` : 'nothing to review'}` +
                             ` (${record.files} file version${record.files === 1 ? '' : 's'}${record.commits ? `, ${record.commits} commits` : ''})`));
      if (!list.length) continue;
      const table = html('table', undefined, 'sec-findings');
      const head = html('tr');
      for (const name of ['Severity', 'What', 'Where', 'Masked value']) head.append(html('th', name));
      table.append(head);
      for (const finding of list.slice(0, 200)) {
        const line = html('tr', undefined, finding.severity === 'high' ? 'sec-high' : '');
        line.append(html('td', finding.severity), html('td', `${finding.check} (${finding.classification})`),
                    html('td', `${finding.where}${finding.line ? `:${finding.line}` : ''}`), html('td', finding.value));
        table.append(line);
      }
      item.append(table);
      if (list.length > 200) item.append(html('p', `${list.length - 200} more not shown; the terminal scan with --json lists all.`, 'host-note'));
    }
    for (const gap of gaps) item.append(html('p', `Not inspected: ${gap.where}: ${gap.reason}`, 'tone-warning'));
    box.append(item);
  }
}

// ---- entry ------------------------------------------------------------------------------------
/** Called on every refresh of the dashboard data; builds once, then keeps the person's choices. */
export function renderSecurity(container, data, connection) {
  ui.data = data;
  ui.connection = connection;
  if (!ui.built) {
    ui.built = true;
    ui.container = container;
    container.replaceChildren();
    const grid = html('div', undefined, 'sec-grid');
    const left = html('article', undefined, 'card');
    left.append(html('h3', 'What to audit'), html('p', 'Choose whole organizations or single repositories. Only ' +
      'repositories with a copy on this machine are listed.', 'host-note'));
    const scope = html('div'); scope.id = 'security-scope'; left.append(scope);
    const right = html('article', undefined, 'card');
    right.append(html('h3', 'Scanners'));
    const engines = html('div'); engines.id = 'security-engines'; right.append(engines);
    grid.append(left, right);
    const run = html('div', undefined, 'sec-run'); run.id = 'security-run';
    const message = html('p', '', 'tone-warning'); message.id = 'security-message'; message.setAttribute('role', 'status');
    const results = html('div', undefined, 'sec-results'); results.id = 'security-results';
    container.append(grid, run, message, results);
    loadEngines();
    act('security-status').then(result => { setAudit(result.audit); if (result.audit && result.audit.state === 'running') poll(); })
      .catch(() => setAudit(null));
  }
  const signature = localRows().map(row => row.id).join(',');
  if (signature !== ui.signature) { ui.signature = signature; renderScope(); }
}
