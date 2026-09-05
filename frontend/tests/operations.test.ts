import test from 'node:test';
import assert from 'node:assert/strict';
import {
  operationsReducer,
  deriveTimes,
  visibleReports,
  fixtureDepth,
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
