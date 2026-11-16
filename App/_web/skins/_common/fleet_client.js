/* Shared by all presentations. Owns transport and compatibility, never the DOM. */
export const CONTRACT = Object.freeze({name: 'gitspecops.fleet.display', version: 1});
export function acceptDisplay(value) {
  if (value?.contract?.name !== CONTRACT.name || value.contract.version !== CONTRACT.version) {
    throw new Error('This interface and host use different display versions. Update them together.');
  }
  if (!Array.isArray(value.rows) || !Array.isArray(value.machines) || !Array.isArray(value.groups)
      || !Array.isArray(value.filters) || !Array.isArray(value.notices)
      || !Array.isArray(value.integrations) || !Array.isArray(value.features)
      || !value.summary || !value.capabilities || !value.product) {
    throw new Error('The host returned an incomplete display. Previous data has been retained.');
  }
  return value;
}
/* AbortSignal.timeout is missing from older browsers (Safari on macOS 10.15); every request
   failed there. A controller and a timer do the same job everywhere. */
export function timeoutSignal(ms) {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') return AbortSignal.timeout(ms);
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}
export class FleetConnection extends EventTarget {
  constructor({fetcher = globalThis.fetch.bind(globalThis), interval = 3000} = {}) {
    super(); this.fetcher = fetcher; this.interval = interval; this.busy = false; this.timer = null;
  }
  async refresh() {
    if (this.busy) return;
    this.busy = true; this.dispatchEvent(new CustomEvent('loading'));
    try {
      const response = await this.fetcher('/v1/dashboard', {cache: 'no-store', signal: timeoutSignal(15000)});
      if (!response.ok) throw new Error(`Host returned ${response.status}.`);
      const data = acceptDisplay(await response.json());
      this.dispatchEvent(new CustomEvent('display', {detail: {data, receivedAt: new Date()}}));
    } catch (error) {
      this.dispatchEvent(new CustomEvent('unavailable', {detail: {message: error.message}}));
    } finally { this.busy = false; this.dispatchEvent(new CustomEvent('idle')); }
  }
  async desktopAction(action, payload, token, {structured = false} = {}) {
    if (!['git-client', 'open-git-client', 'catchup-preview', 'security-preview', 'security-engines',
         'security-start', 'security-status', 'security-stop', 'security-reveal', 'security-policy',
         'security-policy-change', 'setup/open-folder', 'setup/settings', 'setup/connections', 'setup/fetch',
         'setup/sign-in', 'setup/fleets', 'setup/name-fleet', 'setup/add', 'setup/remove', 'setup/presentation', 'setup/baskets', 'setup/show-key', 'setup/join', 'setup/leave', 'setup/shared-answer', 'request-send', 'request-withdraw', 'request-answer', 'request-clear', 'changes', 'setup/tasks',
         'setup/seal'].includes(action) || !token) {
      throw new Error('Desktop actions are unavailable in this dashboard.');
    }
    const response = await this.fetcher(`/v1/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-GitSpecOps-Token': token},
      body: JSON.stringify(payload), signal: timeoutSignal(action === 'security-preview' ? 120000 : action.startsWith('setup/') ? 60000 : 15000),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The desktop action failed.');
    return structured ? result : result.message;
  }
  start() { this.stop(); this.refresh(); this.timer = setInterval(() => this.refresh(), this.interval); }
  stop() { if (this.timer !== null) clearInterval(this.timer); this.timer = null; }
}
