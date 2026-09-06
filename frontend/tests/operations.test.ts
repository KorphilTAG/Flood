import test from 'node:test';
import assert from 'node:assert/strict';
import {
  operationsReducer,
  deriveTimes,
  visibleReports,
  fixtureDepth,
  evidenceCoverage,
  objectivePresets,
  observationPresets,
  type Operations,
} from '../lib/operations.ts';
const time = Date.parse('2025-01-01T12:00:00Z');
const empty = (): Operations => ({
  assignments: [],
  reports: [],
  queued: [],
  offline: false,
  log: [],
});
void test('Command assignment is shared with Field and preserves objective and status updates', () => {
  let state = operationsReducer(empty(), {
    type: 'assign',
    id: 'a1',
    assignment: {
      teamId: 'team:1',
      sectorId: 'site:1',
      objective: 'Verify the approach',
      status: 'Assigned',
      updatedAt: time,
    },
  });
  assert.equal(state.assignments[0].objective, 'Verify the approach');
  state = operationsReducer(state, {
    type: 'status',
    teamId: 'team:1',
    status: 'On scene',
    time: time + 60000,
    id: 's1',
  });
  assert.equal(state.assignments[0].status, 'On scene');
  assert.equal(state.log[0].sectorId, 'site:1');
  const unchanged = operationsReducer(state, {
    type: 'assign',
    id: 'a2',
    assignment: {
      teamId: 'team:1',
      sectorId: 'site:2',
      objective: 'Conflicting assignment',
      status: 'Assigned',
      updatedAt: time,
    },
  });
  assert.deepEqual(unchanged, state);
});
void test('Offline reports are queued, then delivered exactly once to Command', () => {
  let state = operationsReducer(empty(), {
    type: 'connectivity',
    offline: true,
    time,
    id: 'c1',
  });
  const report = {
    id: 'r1',
    teamId: 'team:1',
    sectorId: 'site:1',
    kind: 'Access',
    text: 'Water across the road',
    confidence: 'Medium',
    createdAt: time,
  };
  state = operationsReducer(state, { type: 'report', report });
  assert.equal(state.queued.length, 1);
  assert.equal(visibleReports(state, 'site:1', time).length, 0);
  state = operationsReducer(state, {
    type: 'connectivity',
    offline: false,
    time,
    id: 'c2',
  });
  assert.equal(state.queued.length, 0);
  assert.equal(visibleReports(state, 'site:1', time).length, 1);
  state = operationsReducer(state, {
    type: 'connectivity',
    offline: false,
    time,
    id: 'c3',
  });
  state = operationsReducer(state, { type: 'report', report });
  assert.equal(state.reports.length, 1);
});
void test('A report never leaks into an earlier knowledge cutoff', () => {
  const state = operationsReducer(empty(), {
    type: 'report',
    report: {
      id: 'r1',
      teamId: 'team:1',
      sectorId: 'site:1',
      kind: 'Hazard',
      text: 'Bridge approach blocked',
      confidence: 'High',
      createdAt: time,
    },
  });
  assert.equal(visibleReports(state, 'site:1', time - 1).length, 0);
  assert.equal(visibleReports(state, 'site:1', time).length, 1);
});
void test('Forecast and stale modes preserve p <= t and clamp record boundaries', () => {
  assert.deepEqual(
    deriveTimes(time, 'forecast', 60, time - 3600000, time + 7200000),
    { p: time, t: time + 3600000, horizon: 60 },
  );
  assert.deepEqual(
    deriveTimes(time, 'stale', 120, time - 3600000, time + 7200000),
    { p: time - 3600000, t: time, horizon: 60 },
  );
  assert.equal(
    deriveTimes(time, 'forecast', 240, time - 3600000, time + 7200000).t,
    time + 7200000,
  );
});
void test('Illustrative depth visibly changes with timeline and ensemble selection', () => {
  assert.ok(
    fixtureDepth(1, time + 3600000, time, 'mid') >
      fixtureDepth(1, time, time, 'mid'),
  );
  assert.ok(
    fixtureDepth(1, time, time, 'high') > fixtureDepth(1, time, time, 'low'),
  );
  assert.equal(fixtureDepth(0, time - 3600000, time, 'low'), 0);
});

void test('Verification changes coverage only after review, respecting cutoff and offline delivery', () => {
  const seed = [{ state: 'Inferred' }, { state: 'Confirmed' }];
  const report = {
    id: 'r1',
    teamId: 't1',
    sectorId: 's1',
    kind: 'Hazard',
    text: 'Crossing blocked',
    confidence: 'High',
    createdAt: time,
  };
  let state = operationsReducer(
    { ...empty(), offline: true },
    { type: 'report', report },
  );
  assert.equal(evidenceCoverage(state, 's1', time, seed).verified, 50);
  assert.equal(
    operationsReducer(state, {
      type: 'verify',
      reportId: 'r1',
      time,
      id: 'v0',
    }),
    state,
  );
  state = operationsReducer(state, {
    type: 'connectivity',
    offline: false,
    time,
    id: 'c1',
  });
  assert.equal(evidenceCoverage(state, 's1', time, seed).verified, 33);
  state = operationsReducer(state, {
    type: 'verify',
    reportId: 'r1',
    time: time + 60000,
    id: 'v1',
  });
  assert.equal(evidenceCoverage(state, 's1', time, seed).verified, 33);
  assert.equal(evidenceCoverage(state, 's1', time + 60000, seed).verified, 67);
  assert.equal(evidenceCoverage(state, 's1', time + 60000, seed).pending, 0);
  assert.equal(evidenceCoverage(state, 's2', time + 60000, seed).verified, 50);
  assert.equal(
    operationsReducer(state, {
      type: 'verify',
      reportId: 'r1',
      time: time + 120000,
      id: 'v2',
    }),
    state,
  );
});
void test('Objective presets follow specialty and selected area', () => {
  const boat = objectivePresets('Boat team', 'Riverside');
  const medical = objectivePresets('Medical', 'East bank');
  assert.ok(boat.some((p) => /boat approach/i.test(p.text)));
  assert.ok(medical.some((p) => /medical/i.test(p.text)));
  assert.ok(boat.every((p) => p.text.startsWith('Riverside:')));
  assert.notDeepEqual(boat, medical);
});

void test('Field quick responses remain unverified and preserve uncertainty until reviewed', () => {
  const option = observationPresets('Assistance needs', 'B–12').find(
    (o) => o.label === 'No people visible',
  )!;
  assert.match(option.text, /does not establish/);
  assert.match(option.text, /B–12/);
  const state = operationsReducer(empty(), {
    type: 'report',
    report: {
      id: 'quick1',
      teamId: 'team1',
      sectorId: 'b12',
      kind: 'Assistance needs',
      text: option.text,
      confidence: 'Medium',
      createdAt: time,
    },
  });
  assert.equal(state.reports[0].verifiedAt, undefined);
  assert.equal(evidenceCoverage(state, 'b12', time, []).verified, 0);
  assert.ok(
    observationPresets('Hazard', 'A–22').some((o) => /crossing/i.test(o.text)),
  );
});
