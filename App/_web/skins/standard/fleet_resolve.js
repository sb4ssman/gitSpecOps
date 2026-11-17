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
      const answer = await act(op, extra);
      state.note = words(answer);
      if (then) then(answer);
    } catch (error) { state.note = error.message; }
    state.busy = null; redraw();
  };
  const facts = (cell && cell.facts) || {};
  const tools = html('div', undefined, 'resolve-tools');
  tools.append(
    button('Open folder', run('open-folder'), 'Open this copy in the file browser'),
    button('Open in VS Code', run('open-editor')),
    button(state.changes ? 'Refresh changes' : 'Show changes', run('changes', {}, answer => {
      state.changes = answer; state.picked = new Set((answer.files || []).map(f => f.path));
    }), 'Each changed file, a summary and the diff, from this machine only'),
    button('Fetch', run('fetch'), 'Bring the provider\'s news; moves nothing of yours'));
  if ((facts.behind || 0) > 0 && !(facts.ahead || 0)) {
    tools.append(button(`Fast-forward ${facts.behind}`, run('pull'), 'Only when clean and simply behind'));
  }
  if ((facts.ahead || 0) > 0 || (facts.unpushed || 0) > 0) {
    tools.append(button('Check push…', run('push-plan', {}, answer => { state.push = answer; }),
      'secure-push: plans the push and checks what would leave'));
  }
  tools.append(button('Don\'t count here', async () => {
    if (!window.confirm('Stop counting this repository on this machine? Settings lists it, to count it again.')) return;
    await run('not-counted')();
  }, 'For a dependency checkout inside a build folder, say'));
  box.append(tools);
  if (state.note) box.append(html('p', state.note, 'host-note'));

  if (state.push) {
    const push = html('div', undefined, 'resolve-plan');
    push.append(html('strong', 'Push plan'), html('pre', JSON.stringify(state.push.plan || state.push, null, 2)));
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
      message.value = state.message || '';
      message.oninput = () => { state.message = message.value; };
      panel.append(message);
      panel.append(button('Check this commit…', () => run('commit-plan', {message: state.message || '', files: [...state.picked]},
        answer => { state.commit = answer; })(), 'secure-commit: checks the files, message and identity first'));
      if (state.commit) {
        panel.append(html('pre', JSON.stringify(state.commit.plan || state.commit, null, 2)));
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

/** Settings: what this machine does not count, each with "Count again". */
export async function notCountedSection(container, act) {
  container.replaceChildren(html('h4', 'Not counted on this machine'));
  try {
    const {not_counted: list} = await act('not-counted-list', {});
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
