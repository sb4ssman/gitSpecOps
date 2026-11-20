/* The Security tab: choose repositories (or whole organizations), audit their working files and
 * every commit, and read the masked findings. Every decision is Python's: what counts as a
 * finding, its severity, whether a check is complete. Masked history can be reused from this
 * machine's private checkpoint. Only repositories with a copy on this machine appear.
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
            useEngines: new Set(), history: true, fresh: false, runners: 1, audit: null, polling: null, open: new Set(), signature: '',
            savedAudit: null, revealed: new Map(), settled: new Map(),
            visibility: {}, visibilityFilter: 'all', loadingPublic: false, visibilityLoaded: false};

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
  try {
    const capabilities = await act('security-engines');
    ui.engines = capabilities.engines || [];
    ui.maxRunners = Number(capabilities.max_runners) || 4;
    ui.auditCheckpoints = capabilities.audit_checkpoints === true;
    ui.boundAuditActions = capabilities.bound_audit_actions === true;
    renderRunBar();
  }
  catch (error) { box.replaceChildren(html('p', error.message, 'tone-warning')); return; }
  // An installed scanner is used unless the person unticks it (the user, 2026-11-17).
  if (!ui.enginesChosen) for (const engine of ui.engines) if (engine.installed) ui.useEngines.add(engine.engine);
  box.replaceChildren();
  const builtin = html('div', undefined, 'sec-engine');
  builtin.append(html('strong', '✓ Built-in checks'), html('span', 'Always on: credential shapes, personal details, ' +
    'your own identity values and leak descriptions, from your saved security policy.', 'host-note'));
  box.append(builtin);
  for (const engine of ui.engines) {
    const row = html('label', undefined, 'sec-engine');
    const tick = html('input'); tick.type = 'checkbox'; tick.disabled = !engine.installed;
    tick.checked = engine.installed && ui.useEngines.has(engine.engine);
    tick.onchange = () => { ui.enginesChosen = true; tick.checked ? ui.useEngines.add(engine.engine) : ui.useEngines.delete(engine.engine); };
    const text = html('span');
    text.append(html('strong', `${engine.label}: ${engine.installed ? 'installed' : 'not installed'}`),
                html('span', ` ${engine.about}`, 'host-note'));
    if (!engine.installed && engine.home_page) {
      const link = html('a', 'Where to get it'); link.href = engine.home_page; link.target = '_blank'; link.rel = 'noopener';
      text.append(html('span', ' '), link);
    }
    if (!engine.installed && engine.install) {
      const how = html('span', undefined, 'sec-install');
      how.append(html('span', 'To install it, run in a terminal: ', 'host-note'), html('code', engine.install));
      text.append(how);
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

// ---- protected values ---------------------------------------------------------------------------
const LISTS = {
  never_publish: ['Never publish', 'Your name, addresses, usernames: any of these anywhere is a high finding. ' +
    'Matching ignores case and finds the value inside longer text.'],
  never_publish_words: ['Never publish (whole words)', 'Matched only as a whole word: no letter, digit or ' +
    'underscore may touch it. For a short value, such as a first name, that also occurs inside other words ' +
    '(a time-zone id, a code name).'],
  safe_values: ['Allowed anyway', 'Exact values that look risky but are fine to publish, such as a ' +
    'well-known test value or someone else\'s public name.'],
};
const policy = {lists: null, show: false,
                pending: {never_publish: new Set(), never_publish_words: new Set(), safe_values: new Set()}};
const mask = value => (value.length <= 3 ? '•••' : `${value.slice(0, 2)}${'•'.repeat(Math.min(6, value.length - 3))}${value.slice(-1)}`);

async function loadPolicy() {
  try { policy.lists = (await act('security-policy')).lists; renderPolicy(); }
  catch (error) { document.getElementById('security-policy').replaceChildren(html('p', error.message, 'tone-warning')); }
}

async function changePolicy(list, change, note) {
  try {
    policy.lists = (await act('security-policy-change', {list, ...change})).lists;
    policy.pending[list].clear();
    renderPolicy(note);
  } catch (error) { renderPolicy(error.message, true); }
}

function renderPolicy(note = '', problem = false) {
  const box = document.getElementById('security-policy');
  box.replaceChildren();
  if (!policy.lists) return;
  const show = html('label', undefined, 'sec-option');
  const tick = html('input'); tick.type = 'checkbox'; tick.checked = policy.show;
  tick.onchange = () => { policy.show = tick.checked; renderPolicy(); };
  show.append(tick, html('span', ' Show the values on this screen'));
  box.append(show);
  for (const [list, [title, about]] of Object.entries(LISTS)) {
    const values = policy.lists[list] || [];
    const section = html('div', undefined, 'sec-list');
    section.append(html('h4', `${title} (${values.length})`), html('p', about, 'host-note'));
    const chips = html('div', undefined, 'sec-chips');
    for (const value of values) {
      const marked = policy.pending[list].has(value);
      const chip = html('button', `${policy.show ? value : mask(value)} ${marked ? '↺' : '✕'}`, `sec-value${marked ? ' sec-value-out' : ''}`);
      chip.type = 'button';
      chip.title = marked ? 'Keep this value' : 'Mark this value for removal';
      chip.onclick = () => { marked ? policy.pending[list].delete(value) : policy.pending[list].add(value); renderPolicy(); };
      chips.append(chip);
    }
    if (!values.length) chips.append(html('span', 'none yet', 'host-note'));
    section.append(chips);
    const loosensOnAdd = list === 'safe_values';
    const add = html('div', undefined, 'sec-add');
    const field = html('input'); field.type = 'text'; field.autocomplete = 'off'; field.spellcheck = false;
    field.placeholder = list === 'never_publish' ? 'Add a value to protect' : 'Add an allowed value';
    field.setAttribute('aria-label', field.placeholder);
    const word = html('input'); word.type = 'text'; word.autocomplete = 'off'; word.placeholder = 'Type LOOSEN';
    word.setAttribute('aria-label', 'Type LOOSEN to allow a change that weakens protection');
    const addButton = html('button', 'Add'); addButton.type = 'button';
    addButton.onclick = () => {
      const value = field.value.trim();
      if (!value) return;
      changePolicy(list, {add: [value], ...(loosensOnAdd ? {confirm: word.value} : {})}, `Added to "${title}". It applies to the next audit.`);
    };
    field.onkeydown = event => { if (event.key === 'Enter') addButton.click(); };
    add.append(field);
    if (loosensOnAdd) add.append(word);
    add.append(addButton);
    section.append(add);
    if (policy.pending[list].size) {
      const confirm = html('div', undefined, 'sec-add');
      const removeWord = html('input'); removeWord.type = 'text'; removeWord.autocomplete = 'off';
      removeWord.placeholder = 'Type LOOSEN';
      const blocking = list !== 'safe_values';
      const remove = html('button', `Remove ${policy.pending[list].size}`); remove.type = 'button';
      remove.onclick = () => changePolicy(list, {remove: [...policy.pending[list]], ...(blocking ? {confirm: removeWord.value} : {})},
                                           `Removed from "${title}". It applies to the next audit.`);
      if (blocking) confirm.append(html('span', 'Removing or narrowing protection: ', 'host-note'), removeWord);
      confirm.append(remove);
      if (list === 'never_publish') {
        const narrow = html('button', `Make ${policy.pending[list].size} whole-word only`); narrow.type = 'button';
        narrow.onclick = () => changePolicy(list, {move_to_words: [...policy.pending[list]], confirm: removeWord.value},
                                            'Moved to "Never publish (whole words)". It applies to the next audit.');
        confirm.append(narrow);
      }
      section.append(confirm);
    }
    box.append(section);
  }
  if (note) box.append(html('p', note, problem ? 'tone-warning' : 'tone-success'));
}

// ---- what to audit ------------------------------------------------------------------------------
async function loadVisibility() {
  if (ui.visibilityLoaded) return;
  try {
    const result = await act('repo-visibility');
    ui.visibility = result.visibility || {};
    ui.visibilityLoaded = true;
  } catch (error) {
    ui.visibilityLoaded = true; // keep going, filter shows Unknown for everything
  }
}

async function renderScope() {
  const box = document.getElementById('security-scope');
  await loadVisibility();
  let rows = localRows();
  if (ui.visibilityFilter !== 'all') {
    rows = rows.filter(row => {
      const vis = ui.visibility[row.id];
      if (ui.visibilityFilter === 'unknown') return vis !== 'public' && vis !== 'private' && vis !== 'internal';
      return vis === ui.visibilityFilter;
    });
  }
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.group_id)) groups.set(row.group_id, {label: row.namespace, host: row.group_host || (row.identity || {}).host, rows: []});
    groups.get(row.group_id).rows.push(row);
  }
  box.replaceChildren();
  if (!rows.length) { box.append(html('p', 'No repositories match this visibility filter.', 'empty')); return; }

  const filter = html('label', undefined, 'sec-option');
  filter.append(html('span', 'Visibility '));
  const select = html('select');
  select.disabled = !token();
  for (const [value, label] of [['all', 'All'], ['public', 'Public'], ['private', 'Private'], ['internal', 'Internal'], ['unknown', 'Unknown']]) {
    const option = html('option', label);
    option.value = value;
    if (value === ui.visibilityFilter) option.selected = true;
    select.append(option);
  }
  select.onchange = () => { ui.visibilityFilter = select.value; renderScope(); };
  filter.append(select);

  const refresh = html('button', 'Refresh visibility', 'quiet');
  refresh.type = 'button';
  refresh.disabled = !token();
  refresh.onclick = async () => {
    ui.visibilityLoaded = false;
    ui.visibility = {};
    await loadVisibility();
    renderScope();
  };

  const publicOnly = html('button', ui.loadingPublic ? 'Checking visibility…' : 'Select all public repos', 'quiet');
  publicOnly.type = 'button';
  publicOnly.disabled = ui.loadingPublic || !token();
  publicOnly.onclick = async () => {
    ui.loadingPublic = true;
    renderScope();
    try {
      const result = await act('repo-visibility');
      if (!result.namespaces_checked && result.namespaces_unavailable) {
        say('GitHub visibility could not be verified. The current selection was kept.');
        return;
      }
      const publicRows = localRows().filter(row => result.visibility[row.id] === 'public');
      ui.selected = new Set(publicRows.map(row => row.id));
      for (const row of publicRows) ui.open.add(row.group_id);
      const gaps = result.namespaces_unavailable ? ' Some GitHub namespaces were unavailable.' : '';
      say(`${publicRows.length} public repositories selected for the next audit.${gaps}`);
    } catch (error) { say(error.message); }
    finally { ui.loadingPublic = false; renderScope(); }
  };
  box.append(filter, refresh, publicOnly);
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
      const vis = ui.visibility[row.id] || 'unknown';
      const badge = html('span', vis, `badge sec-vis-${vis}`);
      badge.title = `GitHub visibility: ${vis}`;
      line.append(tick, html('span', ` ${row.identity ? row.identity.name : row.name}`), badge);
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
  tick.onchange = () => { ui.history = tick.checked; renderScope(); };
  history.append(tick, html('span', ' Every commit, not only the files as they are now (needed before publishing; slower)'));
  const go = html('button', running ? 'Auditing…' : `Audit ${ui.selected.size} ${ui.selected.size === 1 ? 'repository' : 'repositories'}`);
  go.type = 'button';
  go.disabled = running || !ui.selected.size || !token();
  go.onclick = start;
  const capacity = html('label', undefined, 'sec-option');
  const runners = html('select');
  runners.disabled = running;
  for (let count = 1; count <= (ui.maxRunners || 4); count++) {
    const option = html('option', String(count));
    option.value = String(count);
    runners.append(option);
  }
  runners.value = String(running ? ui.audit.runners || 1 : ui.runners);
  runners.onchange = () => { ui.runners = Number(runners.value); };
  capacity.append(html('span', 'Simultaneous runners '), runners);
  const fresh = html('label', undefined, 'sec-option');
  const rescan = html('input');
  rescan.type = 'checkbox'; rescan.checked = ui.fresh; rescan.disabled = running || !ui.history;
  rescan.onchange = () => { ui.fresh = rescan.checked; };
  fresh.append(rescan, html('span', ' Scan history from scratch'));
  bar.append(history);
  if (ui.auditCheckpoints) bar.append(fresh);
  bar.append(capacity, go);
  const picker = html('input'); picker.type = 'file'; picker.accept = '.json,application/json'; picker.hidden = true;
  const openReport = html('button', 'Open masked report', 'quiet'); openReport.type = 'button';
  openReport.onclick = () => picker.click();
  picker.onchange = async () => {
    const file = picker.files[0];
    if (!file) return;
    try {
      if (file.size > 64 * 1024 * 1024) throw new Error('Choose a masked report under 64 MiB.');
      ui.savedAudit = parseSavedAudit(await new Response(file).text());
      say('');
      setAudit(ui.audit);
    } catch (error) { say(error.message); }
  };
  bar.append(openReport, picker);
  if (ui.savedAudit) {
    const back = html('button', 'Back to local audit', 'quiet'); back.type = 'button';
    back.onclick = () => { ui.savedAudit = null; say(''); setAudit(ui.audit); };
    bar.append(back);
  }
  if (!ui.savedAudit && ui.audit?.results.length && token()) {
    const download = html('button', 'Export masked report', 'quiet');
    download.type = 'button';
    download.onclick = async () => {
      download.disabled = true;
      try {
        const report = await act('security-export', {id: ui.audit.id});
        const data = new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(data);
        const link = html('a');
        link.href = url;
        link.download = 'gitso-audit-' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      } catch (error) { say(error.message); }
      finally { download.disabled = false; }
    };
    bar.append(download);
    for (const [destination, label] of [['download', 'Download coverage'], ['folder', 'Share coverage to folder'],
                                       ['repo', 'Share coverage to state repo']]) {
      if (!ui.auditCheckpoints || (destination !== 'download' && !ui.audit.coverage_destinations?.includes(destination))) continue;
      const button = html('button', label, 'quiet');
      button.type = 'button';
      button.title = 'Coverage counts and opaque repository identifiers. Findings stay private.';
      button.onclick = async () => {
        button.disabled = true;
        try {
          const coverage = await act('security-export', {id: ui.audit.id, destination});
          if (destination === 'download') {
            if (coverage.kind !== 'gitso-audit-coverage') throw new Error('The app did not return a coverage-only file.');
            const url = URL.createObjectURL(new Blob([JSON.stringify(coverage, null, 2)], {type: 'application/json'}));
            const link = html('a');
            link.href = url; link.download = 'gitso-audit-coverage.json'; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
          } else {
            say(coverage.message);
          }
        } catch (error) { say(error.message); }
        finally { button.disabled = false; }
      };
      bar.append(button);
    }
  }
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
    const fresh = ui.auditCheckpoints && ui.history && ui.fresh ? {fresh: true} : {};
    const result = await act('security-start', {repo_ids: [...ui.selected], history: ui.history, ...fresh,
                                              engines: [...ui.useEngines], runners: ui.runners});
    ui.savedAudit = null;
    setAudit(result.audit);
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
/** Reveal values locally and leave the action controls in their own column. */
function findingCells(entry, material, finding, readOnly) {
  const values = html('td', undefined, 'sec-value');
  const actions = html('td', undefined, 'sec-actions');
  const value = html('code', finding.value);
  values.append(value);
  if (readOnly || entry.index === undefined || !finding.finding_id) return [values, actions];

  const key = `${ui.audit?.id}/${entry.index}/${material}/${finding.finding_id}`;
  const shown = ui.revealed.get(key);
  const payload = {index: entry.index, material, finding_id: finding.finding_id};
  if (ui.boundAuditActions) payload.audit_started_at = ui.audit.started_at;
  value.textContent = shown === undefined ? finding.value : shown;
  const updateCell = activeAction => {
    const [nextValue, nextActions] = findingCells(entry, material, finding, readOnly);
    values.replaceWith(nextValue);
    actions.replaceWith(nextActions);
    const selector = activeAction;
    (nextActions.querySelector(`[data-finding-action="${selector}"]`) ||
      nextActions.querySelector('button'))?.focus({preventScroll: true});
  };
  const addAction = button => {
    if (actions.childElementCount) {
      const pipe = html('span', '|', 'sec-action-divider');
      pipe.setAttribute('aria-hidden', 'true');
      actions.append(pipe);
    }
    actions.append(button);
  };
  const toggle = html('button', shown === undefined ? 'Show' : 'Hide', 'repo-link'); toggle.type = 'button';
  toggle.dataset.findingAction = 'toggle';
  toggle.onclick = async () => {
    if (ui.revealed.has(key)) ui.revealed.delete(key);
    else {
      try { ui.revealed.set(key, (await act('security-reveal', payload)).value); }
      catch (error) { say(error.message); return; }
    }
    updateCell('toggle');
  };
  addAction(toggle);
  // Acknowledge it (the user, 2026-11-17): a review accepts this exact finding (a binary file,
  // an uncertain example); "Not a secret" puts the value on the safe list, everywhere.
  const settled = ui.settled.get(key);
  if (settled) { actions.append(html('span', settled, 'host-note sec-action-status')); return [values, actions]; }
  const accept = html('button', 'Accept', 'repo-link'); accept.type = 'button';
  accept.title = 'Review: accept this exact finding at this place; it stops being flagged';
  accept.dataset.findingAction = 'accept';
  accept.onclick = async () => {
    try {
      const done = await act('security-accept', payload);
      ui.settled.set(key, done.status === 'accepted' || done.status === 'already-reviewed'
        ? 'Accepted: the next audit will not flag it.' : done.message);
    } catch (error) { say(error.message); return; }
    updateCell('accept');
  };
  addAction(accept);
  if (finding.check !== 'binary content') {
    const safe = html('button', 'Not a secret', 'repo-link'); safe.type = 'button';
    safe.title = 'Put this exact value on the safe list: no repository will flag it again';
    safe.dataset.findingAction = 'safe';
    safe.onclick = async () => {
      const word = window.prompt('This value will never be flagged again, in any repository. Type LOOSEN to allow it.');
      if (word === null) return;
      try {
        const value = ui.revealed.get(key) ?? (await act('security-reveal', payload)).value;
        await act('security-policy-change', {list: 'safe_values', add: [value], confirm: word});
        ui.settled.set(key, 'On the safe list: the next audit will not flag it.');
      } catch (error) { say(error.message); return; }
      updateCell('safe');
    };
    addAction(safe);
  }
  return [values, actions];
}

/** How many open findings a part really has; the page receives the first few hundred. */
const openOf = (record, list) => (record && typeof record.findings_open === 'number' ? record.findings_open : list.length);

function findingsOf(record) {
  return record && Array.isArray(record.findings)
    ? record.findings.filter(item => item.classification !== 'quiet' && !item.review_id) : [];
}

// Import is a browser-only snapshot. It has no live indices, actions or fleet authority.
export function parseSavedAudit(text) {
  let saved;
  try { saved = JSON.parse(text); }
  catch { throw new Error('This file is not a valid JSON report.'); }
  const audit = saved?.audit;
  const bad = () => { throw new Error('Choose a gitSpecOps masked audit export.'); };
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if (saved?.disclosure !== 'masked' || !Array.isArray(audit?.results) ||
      !count(audit.total) || !count(audit.done) || audit.done > audit.total ||
      !Array.isArray(audit.engines) || !audit.engines.every(value => typeof value === 'string')) bad();
  function gapsOf(gaps) {
    if (!Array.isArray(gaps)) return [];
    return gaps.filter(gap => typeof gap?.where === 'string' && typeof gap.reason === 'string');
  }
  function part(record) {
    if (record == null) return null;
    if (!Array.isArray(record.findings) || !count(record.files) || !count(record.commits)) bad();
    const findings = record.findings.filter(item => item?.classification !== 'quiet' && !item?.review_id);
    if (!findings.every(item => ['severity', 'check', 'classification', 'where', 'value']
      .every(key => typeof item?.[key] === 'string'))) bad();
    const findingsOpen = count(record.findings_open) ? Math.max(findings.length, record.findings_open) : findings.length;
    const displayed = findings.slice(0, 300).map(({severity, check, classification, where, line, value, finding_id}) =>
      ({severity, check, classification, where, line: count(line) ? line : 0, value,
        finding_id: typeof finding_id === 'string' ? finding_id : ''}));
    return {files: record.files, commits: record.commits, findings_open: findingsOpen,
            findings: displayed, gaps: gapsOf(record.gaps)};
  }
  const results = audit.results.map(entry => {
    const result = entry?.security;
    if (typeof entry?.repo_id !== 'string' || !count(entry.checkout) ||
        !Object.prototype.hasOwnProperty.call(STATUS, result?.check_status)) bad();
    return {repo_id: entry.repo_id, checkout: entry.checkout,
            security: {check_status: result.check_status, gaps: gapsOf(result.gaps),
                       history: part(result.history), working_tree: part(result.working_tree)}};
  });
  return {id: 'saved', sourceId: audit.id, state: audit.state === 'finished' ? 'finished' : 'stopped',
          total: audit.total, done: audit.done, history: audit.history === true,
          engines: audit.engines, started_at: typeof audit.started_at === 'string' ? audit.started_at : '', results};
}

export function sameAuditRun(saved, live) {
  const started = Date.parse(saved?.started_at);
  return !!(live && saved?.sourceId === live.id && Number.isFinite(started) && started === Date.parse(live.started_at));
}

function setAudit(liveAudit) {
  const box = document.getElementById('security-results');
  const audit = ui.savedAudit || liveAudit;
  const expanded = new Set(box.dataset.auditKey === String(audit?.id)
    ? [...box.querySelectorAll('details.sec-result[open]')].map(item => item.dataset.resultKey)
    : []);
  box.dataset.auditKey = String(audit?.id);
  ui.audit = liveAudit;
  renderRunBar();
  box.replaceChildren();
  if (!audit) { box.append(html('p', 'No audit has run since gitSpecOps started. A new audit can reuse saved history.', 'host-note')); return; }
  const progress = html('div', undefined, 'sec-progress');
  const bar = html('progress'); bar.max = audit.total; bar.value = audit.done;
  const words = audit.state === 'running'
    ? `${audit.done} of ${audit.total} checked${audit.current ? ` · now ${nameOf(audit.current)}` : ''}`
    : `${audit.state === 'stopped' ? 'Stopped' : audit.state === 'failed' ? 'Incomplete' : 'Finished'}: ${audit.done} of ${audit.total} checked${audit.history ? ', reachable history selected' : ', current files only'}` +
      `${audit.engines.length ? ` · with ${audit.engines.join(', ')}` : ''}`;
  progress.append(bar, html('span', words));
  box.append(progress);
  const matchedRun = ui.boundAuditActions && sameAuditRun(ui.savedAudit, liveAudit);
  if (ui.savedAudit) {
    const date = Date.parse(audit.started_at);
    const label = Number.isFinite(date) ? ` · ${new Date(date).toLocaleString()}` : '';
    box.append(html('p', `Saved masked report${label} · ${matchedRun ? 'matching live findings can be reviewed' :
      'read-only. Run an audit on the source checkout to review these findings.'}`, 'host-note'));
    if (!matchedRun) {
      const select = html('button', 'Select these local repos for a fresh audit', 'quiet');
      select.type = 'button';
      select.onclick = () => {
        ui.fresh = true;
        auditThese([...new Set(audit.results.map(entry => entry.repo_id))]);
      };
      box.append(select);
    }
  }
  if (audit.error) box.append(html('p', audit.error, 'tone-text-warning'));
  for (const runner of audit.active || []) {
    const s = runner.step_seconds;
    const time = s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
    const copy = runner.copy ? ` (copy ${runner.copy})` : '';
    box.append(html('div', `${nameOf(runner.repo_id)}${copy}: ${runner.step} · ${time}`, 'sec-status'));
  }
  const counts = {passed: 0, 'review-required': 0, blocked: 0, incomplete: 0};
  for (const entry of audit.results) counts[entry.security.check_status] = (counts[entry.security.check_status] || 0) + 1;
  const chips = html('div', undefined, 'sec-chips');
  for (const [status, [label, tone]] of Object.entries(STATUS)) chips.append(html('span', `${counts[status] || 0} ${label.toLowerCase()}`, `pill tone-${tone}`));
  box.append(chips);
  const order = {blocked: 0, 'review-required': 1, incomplete: 2, passed: 3};
  const copies = new Map();
  for (const entry of audit.results) copies.set(entry.repo_id, Math.max(entry.checkout, copies.get(entry.repo_id) || 0));
  for (const entry of [...audit.results].sort((a, b) => order[a.security.check_status] - order[b.security.check_status])) {
    const result = entry.security;
    const [label, tone, meaning] = STATUS[result.check_status] || STATUS.incomplete;
    const tree = findingsOf(result.working_tree), past = findingsOf(result.history);
    const gaps = [...(result.gaps || []), ...((result.working_tree || {}).gaps || []), ...((result.history || {}).gaps || [])];
    const item = html('details', undefined, `sec-result tone-border-${tone}`);
    item.dataset.resultKey = `${entry.repo_id}/${entry.checkout}`;
    item.open = expanded.has(item.dataset.resultKey);
    const summary = html('summary');
    summary.append(html('span', label, `pill tone-${tone}`), html('strong', ` ${nameOf(entry.repo_id)}`),
                   html('span', ` · files: ${openOf(result.working_tree, tree)} · history: ${result.history ? openOf(result.history, past) : 'not checked'}` +
                                `${gaps.length ? ` · ${gaps.length} not inspected` : ''}` +
                                `${copies.get(entry.repo_id) > 1 ? ` · checkout ${entry.checkout} of ${copies.get(entry.repo_id)}` : ''}` +
                                `${entry.checkout_name ? ` · ${entry.checkout_name}` : ''}`, 'host-note'));
    item.append(summary, html('p', meaning, 'host-note'));
    for (const [title, list, record, material] of [['In the files as they are now', tree, result.working_tree, 'working_tree'],
                                                   ['In reachable history', past, result.history, 'history']]) {
      if (!record) continue;
      const checkpoint = record.checkpoint;
      const fileCountLabel = checkpoint?.reused_commits ? 'file version inspections' : 'file versions';
      item.append(html('h4', `${title}: ${list.length ? `${openOf(record, list)} to review` : 'nothing to review'}` +
                             ` (${record.files} ${fileCountLabel}${record.commits ? `, ${record.commits} commits` : ''})`));
      if (checkpoint?.reused_commits) {
        item.append(html('p', `${checkpoint.reused_commits} commits reused · ${checkpoint.new_commits} scanned this audit`, 'host-note'));
      }
      if (record.reused_batches && checkpoint?.mode !== 'reused') {
        item.append(html('p', `${record.reused_batches} clean blob batches reused`, 'host-note'));
      }
      const cached = checkpoint?.mode === 'reused';
      if (cached && list.length) item.append(html('p', 'Scan history from scratch to reveal or review these findings.', 'host-note'));
      if (!list.length) continue;
      const table = html('table', undefined, 'sec-findings');
      const head = html('tr');
      for (const name of ['Severity', 'What', 'Where', 'Value', 'Actions']) {
        const heading = html('th', name); heading.scope = 'col'; head.append(heading);
      }
      table.append(head);
      const liveEntry = matchedRun ? liveAudit.results.find(item =>
        item.repo_id === entry.repo_id && item.checkout === entry.checkout) : null;
      const liveRecord = liveEntry?.security[material];
      const liveFindings = new Map((liveRecord?.checkpoint?.mode === 'reused' ? [] : findingsOf(liveRecord))
        .map(finding => [finding.finding_id, finding]));
      for (const finding of list) {
        const line = html('tr', undefined, finding.severity === 'high' ? 'sec-high' : '');
        const liveFinding = liveFindings.get(finding.finding_id);
        const sameFinding = liveFinding && ['check', 'severity', 'classification', 'where', 'line', 'value']
          .every(key => liveFinding[key] === finding[key]);
        const actionEntry = sameFinding ? liveEntry : entry;
        line.append(html('td', finding.severity), html('td', `${finding.check} (${finding.classification})`),
                    html('td', `${finding.where}${finding.line ? `:${finding.line}` : ''}`, 'sec-location'),
                    ...findingCells(actionEntry, material, finding, cached || (Boolean(ui.savedAudit) && !sameFinding)));
        table.append(line);
      }
      item.append(table);
      const open = openOf(record, list);
      if (open > list.length) {
        const source = ui.savedAudit ? 'Use the exported JSON to inspect the complete saved results.' :
          'Export the masked report to inspect all findings.';
        item.append(html('p', `${open - list.length} more findings. ${source}`, 'host-note'));
      }
    }
    for (const gap of gaps) item.append(html('p', `Not inspected: ${gap.where}: ${gap.reason}`, 'tone-warning'));
    box.append(item);
  }
}

/** The Security menu tile: the last audit's outcome since the app started, or how to start one. */
export function securitySummary() {
  const audit = ui.audit;
  if (!audit) return ['Audit', 'files and every commit'];
  if (audit.state === 'running') return [`${audit.done}/${audit.total}`, 'auditing now'];
  const blocked = audit.results.filter(entry => entry.security.check_status === 'blocked').length;
  const review = audit.results.filter(entry => entry.security.check_status === 'review-required').length;
  return [String(audit.done), blocked ? `checked · ${blocked} blocked` : review ? `checked · ${review} to review` : 'checked · all passed'];
}

/** "Audit these" from a repository group elsewhere on the page: choose exactly those that have a
 *  copy here, open their groups, and say how many were chosen. The audit itself still waits for
 *  the person's Audit button. Returns how many could be chosen. */
export function auditThese(repoIds) {
  if (!ui.data) return 0;
  const here = new Set(localRows().map(row => row.id));
  const chosen = repoIds.filter(id => here.has(id));
  ui.selected = new Set(chosen);
  for (const row of localRows()) if (ui.selected.has(row.id)) ui.open.add(row.group_id);
  if (ui.built) {
    renderScope();
    const skipped = repoIds.length - chosen.length;
    say(`${chosen.length} chosen${skipped ? `; ${skipped} have no copy on this machine, so they cannot be audited here` : ''}. Press Audit to start.`);
  }
  return chosen.length;
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
    const values = html('article', undefined, 'card');
    values.append(html('h3', 'Protected values'), html('p', 'Saved in your gitSpecOps settings on this machine; ' +
      'changes apply to the next audit, no restart needed.', 'host-note'));
    const list = html('div'); list.id = 'security-policy'; values.append(list);
    // Scanners and protected values first, then what to audit (the user, 2026-11-17).
    grid.append(right, values);
    const run = html('div', undefined, 'sec-run'); run.id = 'security-run';
    const message = html('p', '', 'tone-warning'); message.id = 'security-message'; message.setAttribute('role', 'status');
    const results = html('div', undefined, 'sec-results'); results.id = 'security-results';
    container.append(grid, left, run, message, results);
    loadEngines();
    loadPolicy();
    act('security-status').then(result => { setAudit(result.audit); if (result.audit && result.audit.state === 'running') poll(); })
      .catch(() => setAudit(null));
  }
  const signature = localRows().map(row => row.id).join(',');
  if (signature !== ui.signature) { ui.signature = signature; renderScope(); }
}
