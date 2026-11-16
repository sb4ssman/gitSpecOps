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
let message = '';

function names(request) {
  const list = request.items.map(item => item.name || item.repo_id.slice(0, 8));
  return list.length > 6 ? `${list.slice(0, 6).join(', ')} and ${list.length - 6} more` : list.join(', ');
}

export function renderRequests(block, data, act) {
  const requests = data.requests || {waiting: [], answered: [], sent: []};
  block.replaceChildren();
  if (!data.local_actions || (!requests.waiting.length && !requests.answered.length && !requests.sent.length && !message)) {
    block.hidden = true; return;
  }
  block.hidden = false;
  if (message) block.append(el('p', message, 'host-note'));
  const finished = requests.answered.length + requests.sent.filter(r => r.status === 'done' || r.status === 'dismissed').length;
  if (finished) {
    const clear = el('button', `Clear ${finished} finished`); clear.type = 'button';
    clear.onclick = async () => {
      try { await act('request-clear', {}); message = 'Cleared; the task log (App & setup) keeps the record.'; } catch (error) { message = error.message; }
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
    item.append(el('summary', `${request.status === 'done' ? 'Done' : 'Dismissed'}: ${KIND[request.kind]} for ${request.from_label} (${request.items.length})`),
      el('pre', request.result || '', 'host-note'));
    block.append(item);
  }
  for (const request of requests.sent) {
    // Answered over there: say so, with what happened; otherwise it is still waiting.
    const answered = request.status === 'done' || request.status === 'dismissed';
    const item = el(answered ? 'details' : 'div', undefined, 'request');
    const words = answered
      ? `${request.status === 'done' ? 'Done' : 'Dismissed'} on ${request.to_label}: ${KIND[request.kind]} ${names(request)}`
      : `Waiting on ${request.to_label} (apply it there): ${KIND[request.kind]} ${names(request)}. `;
    item.append(el(answered ? 'summary' : 'span', words, answered ? undefined : 'host-note'));
    if (answered) item.append(el('pre', request.result || '', 'host-note'));
    const button = el('button', answered ? 'Clear' : 'Withdraw'); button.type = 'button';
    button.onclick = async () => {
      try { await act('request-withdraw', {id: request.id}); message = answered ? '' : 'Withdrawn.'; } catch (error) { message = error.message; }
    };
    item.append(button);
    block.append(item);
  }
}
