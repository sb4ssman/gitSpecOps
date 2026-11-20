/* Resolve here: the special operations, one click away, for this machine's own copy of a
 * repository (the user, 2026-11-17: "we need to make it EASY to RESOLVE issues"). Every button
 * calls an operation gitSpecOps already has (Special/_sync/resolve.py); commit and push show
 * their plan first and run only when you apply that plan.
 */
import {html} from './fleet_grid.js';

// What the box shows across the page's refreshes, per repository.
const memory = new Map();

function button(label, onClick, title = '') {
  const b = html('button', label); b.type = 'button';
  if (title) b.title = title;
  b.onclick = onClick;
  return b;
}

const remoteWork = new Map();

export function remoteResolveBox(row, machine, sent, act, redraw) {
  const key = `${row.id}/${machine.id}`;
  const session = remoteWork.get(key) || {selected: new Set(), message: ''};
  remoteWork.set(key, session);
  const box = html('section', undefined, 'resolve-box');
  box.append(html('h4', `Resolve on ${machine.label}`));
  const pending = session.pending && sent.find(request => request.id === session.pending.id);
  const request = (op, values = {}) => async () => {
    session.busy = true;
    session.note = '';
    redraw();
    try {
      const resolve = {op, ...(session.checkout ? {checkout: session.checkout} : {}), ...values};
      const answer = await act('remote-resolve', {machine_id: machine.id, machine_label: machine.label,
                                                repo_id: row.id, resolve});
      session.pending = {id: answer.sent.id, op, values};
      session.note = answer.message;
    } catch (error) { session.note = error.message; }
    session.busy = false;
    redraw();
  };
  const openResponse = async item => {
    session.busy = true;
    try {
      const result = await act('remote-result', {id: item.id});
      if (result.checkout) session.checkout = result.checkout;
      if (result.copies) {
        session.choices = {items: result.copies, op: item.op};
      } else if (['branches', 'stashes'].includes(item.op)) {
        session.inspection = result;
      } else if (item.op === 'changes') {
        session.changes = result;
        session.selected.clear();
        session.plan = session.file = null;
      } else if (item.op === 'untracked') {
        session.file = result;
      } else {
        session.plan = {op: item.op, values: result.draft || item.values || {}, result};
        if (['commit-apply', 'stash-apply'].includes(item.op) && result.applied) {
          session.changes = null;
          session.selected.clear();
          session.message = '';
        }
      }
      session.note = result.message || '';
    } catch (error) { session.note = error.message; }
    session.opened = item.id;
    session.pending = null;
    session.busy = false;
    redraw();
  };
  if (session.pending || session.busy) {
    const status = pending?.status;
    box.append(html('p', status ? `Request ${status}.` : session.note || 'Waiting for the receiving machine.', 'host-note'));
    if (session.pending && ['done', 'failed', 'partial'].includes(status)) {
      box.append(button('Open response from ' + machine.label, () => openResponse(session.pending)));
    }
    if (session.pending && (!status || status === 'dismissed')) {
      box.append(button('Return to Resolve controls', () => {
        session.pending = null;
        redraw();
      }, 'A queued request can be withdrawn from the Requests panel.'));
    }
    return box;
  }
  const previous = [...sent].reverse().find(item => item.kind === 'resolve' &&
    item.to === machine.id && item.items[0]?.repo_id === row.id && ['done', 'failed', 'partial'].includes(item.status));
  if (previous && previous.id !== session.opened) {
    box.append(button('Reopen latest Resolve response', () => openResponse({id: previous.id, op: previous.resolve?.op})));
  }
  box.append(button('Request diff…', request('changes')),
    button('Request branches…', request('branches')),
    button('Request stash list…', request('stashes')),
    button('Request fetch…', request('fetch')));
  if (session.inspection) box.append(checkoutInspection(session.inspection));
  if (session.checkout) {
    box.append(button('Check outgoing push…', request('push-plan')),
      button('Choose another checkout', () => {
        session.checkout = '';
        session.changes = session.plan = session.file = session.inspection = session.choices = null;
        session.selected.clear();
        redraw();
      }));
  }
  if (session.note) box.append(html('p', session.note, 'host-note'));
  for (const choice of session.choices?.items || []) {
    box.append(button(choice.label, async () => {
      const op = session.choices.op;
      session.choices = null;
      await request(op, {checkout: choice.checkout})();
    }));
  }
  if (session.checkout && session.changes?.files) {
    const stashMessage = html('input'); stashMessage.placeholder = 'Stash description';
    stashMessage.setAttribute('aria-label', 'Stash description');
    stashMessage.value = session.stashMessage || '';
    stashMessage.oninput = () => { session.stashMessage = stashMessage.value; };
    box.append(stashMessage, button('Preview stash of tracked work…', () => {
      if (!stashMessage.value.trim()) { session.note = 'Write a stash description first.'; redraw(); return; }
      request('stash-plan', {message: stashMessage.value.trim()})();
    }));
  }
  if (session.changes?.files) {
    const {files, label, summary, staged, unstaged, cut} = session.changes;
    box.append(html('p', `${label} · ${summary}`));
    if (cut) box.append(html('p', 'This preview is limited. Review the rest directly on the host.', 'host-note'));
    for (const [title, diff] of [['Staged diff', staged], ['Unstaged diff', unstaged]]) {
      if (!diff) continue;
      const details = html('details');
      details.append(html('summary', title), html('pre', diff, 'resolve-diff'));
      box.append(details);
    }
    const list = html('ul', undefined, 'resolve-files');
    for (const file of files) {
      const line = html('li');
      const tick = html('input'); tick.type = 'checkbox'; tick.checked = session.selected.has(file.name);
      tick.setAttribute('aria-label', `Include ${file.name}`);
      tick.onchange = () => { tick.checked ? session.selected.add(file.name) : session.selected.delete(file.name); };
      line.append(tick, html('code', ` ${file.status} ${file.name}`));
      if (file.status === 'untracked') line.append(button('Request preview…', request('untracked', {file: file.name})));
      list.append(line);
    }
    box.append(list);
    if (session.file) {
      box.append(html('strong', session.file.file || 'File preview'),
        html('pre', session.file.binary ? 'Binary file' : session.file.text || session.file.message || '', 'resolve-diff'));
      if (session.file.cut) box.append(html('p', 'Preview truncated.', 'host-note'));
    }
    if (files.length) {
      const stash = html('input'); stash.placeholder = 'Stash description';
      stash.setAttribute('aria-label', 'Stash description');
      stash.value = state.stashMessage || '';
      stash.oninput = () => { state.stashMessage = stash.value; };
      panel.append(stash, button('Preview stash of tracked work…', () => {
        const message = stash.value.trim();
        run('stash-plan', {message}, result => { state.stashPlan = {message, result}; })();
      }));
      if (state.stashPlan?.result.plan_id) {
        const {message, result} = state.stashPlan;
        panel.append(stashPreview(result, message),
          button('Create checked stash', run('stash-apply', {message, plan_id: result.plan_id}, answer => {
            state.stashPlan = null;
            if (answer.applied) state.changes = state.inspection = null;
          })));
      }
      const message = html('textarea'); message.rows = 3; message.placeholder = 'Commit message';
      message.setAttribute('aria-label', 'Remote commit message');
      message.value = session.message;
      message.oninput = () => { session.message = message.value; };
      box.append(message, button('Check selected commit…', () => {
        if (!session.selected.size || !session.message.trim()) {
          session.note = 'Select files and write a commit message first.';
          redraw();
          return;
        }
        request('commit-plan', {files: [...session.selected], message: session.message.trim()})();
      }));
    }
  }
  if (session.plan) {
    const {result, values, op} = session.plan;
    box.append(html('p', STATUS_WORDS[result.status] || result.message || result.status || '', 'host-note'));
    if (result.destination) box.append(html('p', `${result.branch} → ${result.remote} / ${result.destination}`, 'host-note'));
    if (result.security) {
      const {status, coverage, gaps, findings} = result.security;
      box.append(html('p', `Security ${status} · ${coverage} · ${gaps} gaps`, 'host-note'));
      for (const finding of findings) box.append(html('p', `${finding.check} · ${finding.where}`, 'host-note'));
    }
    if (op.endsWith('-plan') && result.ok && result.plan_id) {
      if (op === 'commit-plan') {
        box.append(html('pre', values.message + '\n\n' + values.files.join('\n'), 'host-note'));
      }
      if (op === 'stash-plan') box.append(stashPreview(result, values.message));
      const apply = op.replace('-plan', '-apply');
      const labels = {'commit-apply': 'Request checked commit…', 'push-apply': 'Request checked push…',
        'stash-apply': 'Request checked stash…'};
      box.append(button(labels[apply], request(apply, {...values, plan_id: result.plan_id})));
    }
  }
  return box;
}

function checkoutInspection(result) {
  const box = html('div');
  if (!result.branches && !result.stashes) {
    box.append(html('p', 'The host could not read this checkout.', 'host-note'));
    return box;
  }
  const entries = result.branches || result.stashes;
  box.append(html('strong', result.branches ? 'Branches and upstreams' : 'Stashes'));
  if (!entries.length) box.append(html('p', 'None on this checkout.', 'host-note'));
  const list = html('ul');
  for (const entry of entries) {
    const text = result.branches
      ? `${entry.current ? '* ' : ''}${entry.branch} · ${entry.tip.slice(0, 10)} · ${entry.upstream || 'No upstream'} ${entry.divergence}`
      : `${entry.ref} · ${entry.oid.slice(0, 10)} · ${entry.subject}`;
    list.append(html('li', text));
  }
  box.append(list);
  if (result.cut) box.append(html('p', 'Showing the first 50 entries.', 'host-note'));
  return box;
}

function stashPreview(result, message) {
  const box = html('div');
  box.append(html('p', `Stash ${result.count} tracked files · ${result.untracked} untracked entries stay here.`, 'host-note'),
    html('pre', message + '\n\n' + result.files.join('\n'), 'host-note'));
  if (result.count > result.files.length) box.append(html('p', 'Only the first 50 paths are shown.', 'host-note'));
  return box;
}

function words(record) {
  if (!record) return '';
  if (record.error) return record.error;
  if (record.message) return record.message;
  return record.ok === false ? 'It did not complete.' : 'Done.';
}

/** The box, for `row` on this machine. `act(op, extra)` calls the local repo-action. */
export function resolveBox(row, cell, act, redraw) {
  const state = memory.get(row.id) || {};
  memory.set(row.id, state);
  const box = html('section', undefined, 'resolve-box');
  box.append(html('h4', 'Resolve here, on this machine'));
  const run = (op, extra = {}, then) => async () => {
    state.busy = op; state.note = 'Working…'; redraw();
    try {
      const answer = await act(op, {checkout: state.checkout || 0, ...extra});
      state.note = words(answer);
      if (then) then(answer);
    } catch (error) { state.note = error.message; }
    state.busy = null; redraw();
  };
  const facts = (cell && cell.facts) || {};
  // Several folders of this repository here: choose which one every button acts on.
  if (cell && cell.copies && cell.copies.length > 1) {
    if (!state.copies && !state.loadingCopies) {
      state.loadingCopies = true;
      act('copies', {}).then(answer => { state.copies = answer.copies; redraw(); })
        .catch(error => { state.loadingCopies = false; state.note = error.message; redraw(); });
    }
    box.append(copyChooser(state, redraw));
  }
  const tools = html('div', undefined, 'resolve-tools');
  tools.append(
    button('Open folder', run('open-folder'), 'Open this copy in the file browser'),
    button('Open in VS Code', run('open-editor')),
    button('Inspect branches', run('branches', {}, answer => { state.inspection = answer; })),
    button('Inspect stashes', run('stashes', {}, answer => { state.inspection = answer; })),
    button(state.changes ? 'Refresh changes' : 'Show changes', run('changes', {}, answer => {
      state.changes = answer;
      const available = new Set((answer.files || []).map(file => file.path));
      state.picked = new Set([...(state.picked || [])].filter(path => available.has(path)));
      state.commit = null;
    }), 'Each changed file, a summary and the diff, from this machine only'),
    button('Fetch', run('fetch'), 'Bring the provider\'s news; moves nothing of yours'));
  if ((facts.behind || 0) > 0 && !(facts.ahead || 0)) {
    tools.append(button(`Fast-forward ${facts.behind}`, run('pull'), 'Only when clean and simply behind'));
  }
  if ((facts.ahead || 0) > 0 || (facts.unpushed || 0) > 0) {
    tools.append(button('Check push…', run('push-plan', {}, answer => { state.push = answer; }),
      'secure-push: plans the push and checks what would leave'));
  }
  tools.append(button('Safe to delete this copy?', run('retire-check', {}, answer => { state.retire = answer; }),
    'Fetches, then proves every commit is on GitHub and every uncommitted file is the same in another copy. Deletes nothing.'));
  tools.append(button('Don\'t count here', async () => {
    if (!window.confirm('Stop counting this repository on this machine? Settings lists it, to count it again.')) return;
    await run('not-counted')();
  }, 'For a dependency checkout inside a build folder, say'));
  box.append(tools);
  if (state.note) box.append(html('p', state.note, 'host-note'));
  if (state.inspection) box.append(checkoutInspection(state.inspection));

  if (state.retire) box.append(retirePanel(state, run, redraw));

  if (state.push) {
    const push = html('div', undefined, 'resolve-plan');
    push.append(html('strong', 'Push'), planView(state.push));
    if (state.push.plan_id && !state.push.applied) {
      push.append(button('Push', run('push-apply', {plan_id: state.push.plan_id}, answer => { state.push = answer.applied ? null : answer; })));
    }
    push.append(button('Close', () => { state.push = null; redraw(); }));
    box.append(push);
  }

  if (state.changes) {
    const files = state.changes.files || [];
    const panel = html('div', undefined, 'resolve-changes');
    panel.append(html('strong', files.length ? `${files.length} changed file${files.length === 1 ? '' : 's'} here` : 'Nothing uncommitted here.'));
    const list = html('ul', undefined, 'resolve-files');
    for (const file of files) {
      const line = html('li');
      const tick = html('input'); tick.type = 'checkbox'; tick.checked = state.picked.has(file.path);
      tick.onchange = () => { tick.checked ? state.picked.add(file.path) : state.picked.delete(file.path); };
      line.append(tick, html('code', ` ${file.status} `), document.createTextNode(file.path));
      list.append(line);
    }
    panel.append(list);
    if (state.changes.summary) panel.append(html('pre', state.changes.summary, 'resolve-summary'));
    if (state.changes.diff) {
      const more = html('details');
      more.append(html('summary', `The diff${state.changes.cut ? ' (the first part)' : ''}`), html('pre', state.changes.diff, 'resolve-diff'));
      panel.append(more);
    }
    if (files.length) {
      const message = html('textarea'); message.rows = 3; message.placeholder = 'Commit message';
      message.setAttribute('aria-label', 'Commit message');
      message.value = state.message || '';
      message.oninput = () => { state.message = message.value; };
      panel.append(html('p', 'Select the files to commit and enter a message.', 'host-note'), message);
      panel.append(button('Check this commit…', () => run('commit-plan', {message: state.message || '', files: [...state.picked]},
        answer => { state.commit = answer; })(), 'secure-commit: checks the files, message and identity first'));
      if (state.commit) {
        panel.append(planView(state.commit));
        if (state.commit.plan_id && !state.commit.applied) {
          panel.append(button('Commit', run('commit-apply', {message: state.message || '', files: [...state.picked], plan_id: state.commit.plan_id},
            answer => { if (answer.applied) { state.commit = null; state.changes = null; state.message = ''; } else state.commit = answer; })));
        }
      }
    }
    panel.append(button('Close', () => { state.changes = null; state.commit = null; redraw(); }));
    box.append(panel);
  }
  return box;
}

/** A commit or push check, in words: what it found and what happens next; the full record is
 *  one click away (an outside review, 2026-11-17: no raw JSON as the main display). */
const STATUS_WORDS = {
  ready: 'Checked: ready to commit.', planned: 'Checked: ready to push.', committed: 'Committed.', pushed: 'Pushed.',
  fetched: 'Fetched remote refs.', 'stash-ready': 'Checked stash ready for approval.', stashed: 'Stash created.',
  'nothing-to-stash': 'No tracked work to stash.', 'stash-needs-review': 'A stash was created. Review the host checkout.',
  'already-current': 'Nothing to push: the provider already has it.', 'nothing-to-commit': 'Nothing to commit.',
  blocked: 'Blocked: a high-severity finding. Resolve it first.', 'review-required': 'Findings need a look before this can go ahead.',
  'hook-rejected': 'A Git hook in this repository refused the commit.',
};
function planView(record) {
  const view = html('div', undefined, 'resolve-check');
  const good = record.ok !== false;
  view.append(html('p', STATUS_WORDS[record.status] || record.status || '', good ? 'tone-text-success' : 'tone-text-warning'));
  if (record.message) view.append(html('p', record.message, 'host-note'));
  if (record.failed_hook) view.append(html('p', `Hook: ${record.failed_hook}`, 'host-note'));
  const findings = ((record.security || {}).findings || []).filter(f => f.classification !== 'quiet' && !f.review_id);
  if (findings.length) {
    const list = html('ul', undefined, 'resolve-files');
    for (const f of findings.slice(0, 40)) list.append(html('li', `${f.severity} · ${f.check} · ${f.where}${f.line ? `:${f.line}` : ''} · ${f.value || ''}`));
    view.append(html('strong', `${findings.length} finding${findings.length === 1 ? '' : 's'} (values masked)`), list);
    if (findings.length > 40) view.append(html('p', `${findings.length - 40} more; the Security page lists them.`, 'host-note'));
  }
  const more = html('details');
  more.append(html('summary', 'The full record'), html('pre', JSON.stringify(record, null, 2)));
  view.append(more);
  return view;
}

function copyChooser(state, redraw) {
  const choose = html('fieldset', undefined, 'resolve-copies');
  choose.append(html('legend', 'Which copy on this machine'));
  if (!state.copies) { choose.append(html('p', 'Finding the copies…', 'host-note')); return choose; }
  for (const copy of state.copies) {
    const line = html('label');
    const pick = html('input'); pick.type = 'radio'; pick.name = 'resolve-copy';
    pick.checked = (state.checkout || 0) === copy.checkout;
    pick.onchange = () => {
      state.checkout = copy.checkout;
      state.changes = state.commit = state.push = state.retire = state.inspection = state.stashPlan = null; state.note = '';
      redraw();
    };
    line.append(pick, html('strong', ` ${copy.library}${copy.inside ? ` / ${copy.inside}` : ''}`),
                html('span', ` · ${copy.branch || 'no branch'} · ${copy.head || 'no commits'}`, 'host-note'));
    choose.append(line);
  }
  return choose;
}

/** "Safe to delete?": the proof, file by file; the person opens the folder and deletes it. */
function retirePanel(state, run, redraw) {
  const answer = state.retire;
  const panel = html('div', undefined, `resolve-plan ${answer.safe ? 'tone-border-success' : 'tone-border-warning'}`);
  panel.append(html('strong', answer.verdict, answer.safe ? 'tone-text-success' : 'tone-text-warning'),
               html('p', answer.path, 'host-note'));
  const list = (title, rows) => {
    if (!rows || !rows.length) return;
    panel.append(html('h5', title));
    const items = html('ul', undefined, 'resolve-files');
    for (const row of rows) {
      const item = html('li');
      item.append(html('code', ` ${row.status} `), document.createTextNode(`${row.path} — ${row.elsewhere}`));
      items.append(item);
    }
    panel.append(items);
  };
  list('Uncommitted and untracked here', answer.files);
  list('Ignored here (not judged: look before deleting)', answer.ignored);
  panel.append(html('p', answer.note, 'host-note'),
               button('Open this copy\'s folder', run('open-folder')),
               button('Close', () => { state.retire = null; redraw(); }));
  return panel;
}

/** Settings: what this machine does not count, each with "Count again". */
export async function notCountedSection(container, act) {
  container.replaceChildren(html('h4', 'Not counted on this machine'));
  try {
    const {not_counted: list} = await act('not-counted-list', {});
    const add = html('div', undefined, 'sec-add');
    const field = html('input'); field.type = 'text'; field.spellcheck = false;
    field.placeholder = 'A folder inside a library, by its full path';
    field.setAttribute('aria-label', 'A folder not to count');
    const note = html('p', '', 'host-note');
    add.append(field, button('Don\'t count anything in it', async () => {
      try { note.textContent = (await act('not-counted-folder', {path: field.value.trim()})).message; notCountedSection(container, act); }
      catch (error) { note.textContent = error.message; }
    }));
    container.append(html('p', 'A folder here leaves out every repository inside it, such as an agent\'s run folders ' +
      'or a build\'s dependencies. Nothing is skipped on its own.', 'host-note'), add, note);
    if (!list.length) { container.append(html('p', 'Every repository in your libraries is counted.', 'host-note')); return; }
    const ul = html('ul');
    for (const path of list) {
      const li = html('li'); li.append(html('code', path), document.createTextNode(' '));
      li.append(button('Count again', async () => { await act('count-again', {path}); notCountedSection(container, act); }));
      ul.append(li);
    }
    container.append(ul);
  } catch (error) { container.append(html('p', error.message, 'tone-text-warning')); }
}
