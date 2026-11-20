/* Requests between machines (Elaborate/_fleet/requests.py), shown at the top of every tab:
 * what other machines ask of this one (Apply or Dismiss), what was done, and what this machine
 * has asked of others (Withdraw). Nothing here decides: the page sends the person's choice. */

const el = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const KIND = {pull: 'fast-forward', clone: 'clone', resolve: 'resolve repository'};
const RESOLVE_WORDS = {changes: 'share the staged and unstaged diff', untracked: 'share an untracked file preview',
  'commit-plan': 'check the proposed commit', 'commit-apply': 'apply the checked commit',
  'push-plan': 'check the outgoing commits', 'push-apply': 'apply the checked push',
  branches: 'share branch and divergence details', stashes: 'share the stash list', fetch: 'fetch remote refs',
  'stash-plan': 'preview a stash of tracked work', 'stash-apply': 'create the checked stash'};
const description = request => RESOLVE_WORDS[request.resolve?.op] || KIND[request.kind];
const working = new Set();
const openApprovals = new Set();
let message = '';

function names(request, rows = []) {
  const list = request.items.map(item => item.name || rows.find(row => row.id === item.repo_id)?.name || item.repo_id.slice(0, 8));
  return list.length > 6 ? `${list.slice(0, 6).join(', ')} and ${list.length - 6} more` : list.join(', ');
}

function approvalPhrase(request) {
  const [item] = request.items;
  if (request.items.length === 1 && item.owner && item.name) return `${item.owner}/${item.name}`;
  return `${KIND[request.kind].toUpperCase()} ${request.items.length}`;
}

function remoteApproval(request, act) {
  const challenge = request.challenge;
  const panel = el('details');
  panel.open = openApprovals.has(request.id);
  panel.ontoggle = () => {
    if (!panel.isConnected) return;
    if (panel.open) openApprovals.add(request.id);
    else openApprovals.delete(request.id);
  };
  panel.append(el('summary', 'Review and approve on this machine'));
  const list = el('ul');
  for (const item of request.items) {
    const name = [item.owner, item.name].filter(Boolean).join('/') || item.repo_id;
    const library = item.library || (request.kind === 'clone' ? 'receiver’s first library' : 'all receiver checkouts');
    list.append(el('li', `${name} · ${library}`));
  }
  panel.append(list);
  const button = el('button', challenge.mode === 'typed' ? 'Type to approve once' : 'Confirm once');
  button.type = 'button';
  button.onclick = async () => {
    const heading = `${KIND[request.kind]} ${request.items.length} on ${request.to_label}`;
    const text = challenge.mode === 'typed'
      ? window.prompt(`${heading}. Type ${approvalPhrase(request)} to acknowledge.`)
      : window.confirm(`${heading}?`) ? '' : null;
    if (text === null) return;
    button.disabled = true;
    try { message = (await act('request-confirm', {id: request.id, text})).message; }
    catch (error) { message = error.message; }
    finally { button.disabled = false; }
  };
  panel.append(button);
  return panel;
}

// How a request ended, in words: partly done and not done are never shown as done.
const ENDED = {done: 'Done', partial: 'Partly done', failed: 'Not done', dismissed: 'Dismissed'};
const ended = request => Object.prototype.hasOwnProperty.call(ENDED, request.status);

function requestedWhen(request) {
  const date = new Date(request.at);
  return Number.isFinite(date.getTime()) ? `Requested ${date.toLocaleString()}` : '';
}

export function renderRequests(block, data, act) {
  const requests = data.requests || {waiting: [], answered: [], sent: []};
  block.replaceChildren();
  if (!data.local_actions || (!requests.waiting.length && !requests.answered.length && !requests.sent.length && !message)) {
    block.hidden = true; return;
  }
  block.hidden = false;
  if (message) block.append(el('p', message, 'host-note'));
  const outgoing = requests.sent.filter(request => !ended(request));
  const replies = requests.sent.filter(ended);
  const finished = requests.answered.length + replies.length;
  const incomingSection = el('section');
  const outgoingSection = el('section');
  const finishedSection = el('section');
  if (requests.waiting.length) {
    incomingSection.append(el('h3', `Incoming requests (${requests.waiting.length})`));
    block.append(incomingSection);
  }
  if (outgoing.length) {
    outgoingSection.append(el('h3', `Outgoing requests (${outgoing.length})`));
    block.append(outgoingSection);
  }
  if (finished) {
    finishedSection.append(el('h3', `Finished receipts (${finished})`));
    block.append(finishedSection);
    const clear = el('button', `Clear ${finished} finished`); clear.type = 'button';
    clear.onclick = async () => {
      try { await act('request-clear', {}); message = 'Cleared; the task log (Settings) keeps the record.'; } catch (error) { message = error.message; }
    };
    finishedSection.append(clear);
  }
  for (const request of requests.waiting) {
    const item = el('div', undefined, 'request request-waiting');
    item.append(el('strong', `${request.from_label} asks this machine to ${description(request)}`),
      el('p', names(request, data.rows), 'host-note'));
    if (request.kind === 'resolve') {
      const details = request.resolve;
      for (const text of request.resolve_details || []) item.append(el('p', text, 'host-note'));
      if (details.op === 'changes' || details.op === 'untracked') {
        item.append(el('p', 'Apply shares the requested content with the requesting device.', 'host-note'));
      }
      if (details.file) item.append(el('code', details.file));
      if (details.files) item.append(el('pre', details.files.join('\n'), 'host-note'));
      if (details.message) item.append(el('pre', details.message, 'host-note'));
    } else {
      item.append(el('p', request.kind === 'pull'
        ? 'Each is fetched first and moved forward only if it is clean and simply behind.'
        : 'Each is cloned into its organization folder in this machine’s first library.', 'host-note'));
    }
    const busy = working.has(request.id);
    if (request.status === 'running') { item.append(el('p', 'Running now…', 'host-note')); incomingSection.append(item); continue; }
    for (const [label, accept] of [['Apply', true], ['Dismiss', false]]) {
      const button = el('button', busy && accept ? 'Working…' : label); button.type = 'button'; button.disabled = busy;
      button.onclick = async () => {
        working.add(request.id); renderRequests(block, data, act);
        try {
          const reply = await act('request-answer', {id: request.id, accept});
          message = ENDED[reply.status] ? `${ENDED[reply.status]}. See the finished receipt for details.` :
            'Reply recorded. See Requests for the current status.';
        }
        catch (error) { message = error.message; }
        working.delete(request.id);
      };
      item.append(button);
    }
    incomingSection.append(item);
  }
  for (const request of requests.answered) {
    const item = el('details', undefined, 'request');
    item.append(el('summary', `${ENDED[request.status] || request.status}: ${KIND[request.kind]} for ${request.from_label} (${request.items.length})`),
      el('pre', request.result || '', 'host-note'));
    finishedSection.append(item);
  }
  for (const request of [...outgoing, ...replies]) {
    // Answered over there: say so, with what happened; otherwise it is still waiting.
    const answered = ended(request);
    const item = el(answered ? 'details' : 'div', undefined, `request${request.status === 'partial' || request.status === 'failed' ? ' request-trouble' : ''}`);
    if (answered && request.status !== 'done') item.open = true;
    const challengeActive = request.status === 'waiting' && request.challenge
      && Date.parse(request.challenge.expires) > Date.now();
    const canApprove = challengeActive && !request.confirmation;
    const waiting = challengeActive && request.confirmation ? 'Approval sent'
      : canApprove ? 'Ready for your confirmation here'
        : request.approval_mode === 'paused' ? 'Incoming operations paused'
        : request.approval_mode === 'automatic' ? 'Accepted for automatic execution'
          : 'Waiting for approval on the receiving machine';
    const words = answered
      ? `${ENDED[request.status]} on ${request.to_label}: ${description(request)} ${names(request, data.rows)}`
      : request.status === 'running' ? `Running on ${request.to_label}: ${description(request)} ${names(request, data.rows)}. `
      : request.status === 'waiting' ? `${waiting} · ${request.to_label}: ${description(request)} ${names(request, data.rows)}. `
        : `Queued for ${request.to_label}; awaiting receipt: ${description(request)} ${names(request, data.rows)}. `;
    item.append(el(answered ? 'summary' : 'span', words, answered ? undefined : 'host-note'));
    const when = requestedWhen(request);
    const machine = data.machines?.find(candidate => candidate.id === request.to);
    if (when) item.append(el('p', when + (!answered && machine?.freshness === 'stale' ? ' · receiver has not reported recently' : ''), 'host-note'));
    if (canApprove) item.append(remoteApproval(request, act));
    if (answered) item.append(el('pre', request.result || '', 'host-note'));
    const button = el('button', answered ? 'Clear' : 'Withdraw'); button.type = 'button';
    if (!answered) button.title = 'Stops it only if that machine has not picked it up yet';
    button.onclick = async () => {
      try { await act('request-withdraw', {id: request.id}); message = answered ? '' : 'Withdrawn.'; } catch (error) { message = error.message; }
    };
    if (answered || !request.status) item.append(button);
    (answered ? finishedSection : outgoingSection).append(item);
  }
}
