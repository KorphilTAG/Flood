import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

test('a forecast completing during forward playback publishes without clearing the chart', async () => {
  const messages: { type: string; water: unknown }[] = [];
  const context = vm.createContext({
    window: {
      parent: { postMessage: (message: typeof messages[number]) => messages.push(message) },
      location: { origin: 'http://localhost:3000' }, addEventListener: () => {},
    },
    AbortController, URLSearchParams,
    setTimeout: () => 1, clearTimeout: () => {},
  });
  const source = readFileSync(new URL('../public/terrain/terrain.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/^export /gm, ''), context);
  await vm.runInContext(`
    state.runId = 'reference'; state.t = '2025-07-04T07:30:00Z';
    userMoved = true;
    updateReadout = setBusy = applyOverlay = applyReaches = updateGaugeChips = hideError = () => {};
    fetchOverlay = async () => ({});
    fetchJson = async (url) => {
      if (url.includes('/state?')) {
        // The timeline crosses into the next bucket while the engine computes.
        state.t = '2025-07-04T07:35:00Z';
        return { p: '2025-07-04T07:30:00Z', t: '2025-07-04T09:30:00Z' };
      }
      if (url.includes('/reaches?')) return [{ feature_id: 3586192, t: '2025-07-04T09:30:00Z', stage_mid_m: 1, q_mid_cms: 10, rate_of_rise_m_per_h: 0.2 }];
      return [{ site: '08165500', t: '2025-07-04T09:30:00Z', predicted_wse_mid_m: 500 }];
    };
    refresh();
  `, context);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'hunt-water');
  assert.ok(messages[0].water);
});

test('embedded terrain follows the page timeline and ignores the engine clock', () => {
  let receive: (event: unknown) => void = () => {};
  let refreshes = 0;
  const parent = {};
  const context = vm.createContext({
    window: {
      parent, location: { origin: 'http://localhost:3000' },
      addEventListener: (_: string, callback: typeof receive) => { receive = callback; },
    },
    setTimeout: () => { refreshes++; return 1; },
    clearTimeout: () => {},
  });
  const source = readFileSync(new URL('../public/terrain/terrain.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/^export /gm, ''), context);
  vm.runInContext("state.runId = 'reference'; handleClock({ t: '2025-07-03T12:00:00Z' });", context);
  assert.equal(vm.runInContext('state.t', context), null);
  const send = (at: number) => receive({
    origin: 'http://localhost:3000', source: parent,
    data: { type: 'incident-data', at, features: [] },
  });
  send(Date.parse('2025-07-04T07:30:00Z'));
  assert.equal(vm.runInContext('state.t', context), '2025-07-04T07:30:00Z');
  assert.equal(vm.runInContext('deriveCutoffAndValid(state.t, state.mode, state.horizonMin, state.lagMin).t', context), '2025-07-04T09:30:00Z');
  send(Date.parse('2025-07-04T08:00:00Z'));
  assert.equal(refreshes, 2);
  vm.runInContext("handleClock({ t: '2025-07-03T12:00:00Z' });", context);
  assert.equal(vm.runInContext('state.t', context), '2025-07-04T08:00:00Z');
  send(NaN);
  assert.equal(refreshes, 2);
});
