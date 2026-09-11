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
export class FleetConnection extends EventTarget {
  constructor({fetcher = globalThis.fetch.bind(globalThis), interval = 3000} = {}) {
    super(); this.fetcher = fetcher; this.interval = interval; this.busy = false; this.timer = null;
  }
  async refresh() {
    if (this.busy) return;
    this.busy = true; this.dispatchEvent(new CustomEvent('loading'));
    try {
      const response = await this.fetcher('/v1/dashboard', {cache: 'no-store', signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(`Host returned ${response.status}.`);
      const data = acceptDisplay(await response.json());
      this.dispatchEvent(new CustomEvent('display', {detail: {data, receivedAt: new Date()}}));
    } catch (error) {
      this.dispatchEvent(new CustomEvent('unavailable', {detail: {message: error.message}}));
    } finally { this.busy = false; this.dispatchEvent(new CustomEvent('idle')); }
  }
  start() { this.stop(); this.refresh(); this.timer = setInterval(() => this.refresh(), this.interval); }
  stop() { if (this.timer !== null) clearInterval(this.timer); this.timer = null; }
}
