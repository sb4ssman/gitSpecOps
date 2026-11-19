/* Requests between machines (Elaborate/_fleet/requests.py), shown at the top of every tab:
 * what other machines ask of this one (Apply or Dismiss), what was done, and what this machine
 * has asked of others (Withdraw). Nothing here decides: the page sends the person's choice. */

const el = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const KIND = {pull: 'fast-forward', clone: 'clone'};
const working = new Set();
const openApprovals = new Set();
let message = '';

function names(request) {
  const list = request.items.map(item => item.name || item.repo_id.slice(0, 8));
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
const ended = request => Object.hasOwn(ENDED, request.status);

export function renderRequests(block, data, act) {
  const requests = data.requests || {waiting: [], answered: [], sent: []};
  block.replaceChildren();
  if (!data.local_actions || (!requests.waiting.length && !requests.answered.length && !requests.sent.length && !message)) {
    block.hidden = true; return;
  }
  block.hidden = false;
  if (message) block.append(el('p', message, 'host-note'));
  const finished = requests.answered.length + requests.sent.filter(ended).length;
  if (finished) {
    const clear = el('button', `Clear ${finished} finished`); clear.type = 'button';
    clear.onclick = async () => {
      try { await act('request-clear', {}); message = 'Cleared; the task log (Settings) keeps the record.'; } catch (error) { message = error.message; }
    };
    block.append(clear);
  }
  for (const request of requests.waiting) {
    const item = el('div', undefined, 'request request-waiting');
    item.append(el('strong', `${request.from_label} asks this machine to ${KIND[request.kind]} ${request.items.length} repositor${request.items.length === 1 ? 'y' : 'ies'}`),
      el('p', names(request), 'host-note'),
      el('p', request.kind === 'pull'
        ? 'Each is fetched first and moved forward only if it is clean and simply behind; anything else is reported, not touched.'
        : 'Each is cloned into its organization folder in this machine\'s first library; nothing that exists is replaced.', 'host-note'));
    const busy = working.has(request.id);
    if (request.status === 'running') { item.append(el('p', 'Running now…', 'host-note')); block.append(item); continue; }
    for (const [label, accept] of [['Apply', true], ['Dismiss', false]]) {
      const button = el('button', busy && accept ? 'Working…' : label); button.type = 'button'; button.disabled = busy;
      button.onclick = async () => {
        working.add(request.id); renderRequests(block, data, act);
        try { await act('request-answer', {id: request.id, accept}); message = accept ? 'Done; the result is below.' : 'Dismissed.'; }
        catch (error) { message = error.message; }
        working.delete(request.id);
      };
      item.append(button);
    }
    block.append(item);
  }
  for (const request of requests.answered.slice(0, 3)) {
    const item = el('details', undefined, 'request');
    item.append(el('summary', `${ENDED[request.status] || request.status}: ${KIND[request.kind]} for ${request.from_label} (${request.items.length})`),
      el('pre', request.result || '', 'host-note'));
    block.append(item);
  }
  for (const request of requests.sent) {
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
      ? `${ENDED[request.status]} on ${request.to_label}: ${KIND[request.kind]} ${names(request)}`
      : request.status === 'running' ? `Running on ${request.to_label}: ${KIND[request.kind]} ${names(request)}. `
      : request.status === 'waiting' ? `${waiting} · ${request.to_label}: ${KIND[request.kind]} ${names(request)}. `
        : `Queued for ${request.to_label}; awaiting receipt: ${KIND[request.kind]} ${names(request)}. `;
    item.append(el(answered ? 'summary' : 'span', words, answered ? undefined : 'host-note'));
    if (canApprove) item.append(remoteApproval(request, act));
    if (answered) item.append(el('pre', request.result || '', 'host-note'));
    const button = el('button', answered ? 'Clear' : 'Withdraw'); button.type = 'button';
    if (!answered) button.title = 'Stops it only if that machine has not picked it up yet';
    button.onclick = async () => {
      try { await act('request-withdraw', {id: request.id}); message = answered ? '' : 'Withdrawn.'; } catch (error) { message = error.message; }
    };
    if (answered || !request.status) item.append(button);
    block.append(item);
  }
}
