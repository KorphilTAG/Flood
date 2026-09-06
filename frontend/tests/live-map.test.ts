import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveLiveMap,
  reportPresets,
  tacticsPresets,
} from '../lib/live-map.ts';
import {
  operationsReducer,
  type Operations,
  type Report,
  type MapObservation,
} from '../lib/operations.ts';
const now = 100000000;
const sectors = [
  { id: 'a', code: 'A', lon: -99.3, lat: 30, people: [5, 9] },
  { id: 'b', code: 'B', lon: -99.2, lat: 30, people: [2, 4] },
];
const empty = (): Operations => ({
  assignments: [],
  reports: [],
  queued: [],
  offline: false,
  log: [],
});
const observation = (
  action: MapObservation['action'],
  targetId: string,
  count?: number,
): MapObservation => ({ action, targetId, lon: -99.302, lat: 30.002, count });
const report = (id: string, o: MapObservation, createdAt = now): Report => ({
  id,
  teamId: 'team',
  sectorId: 'a',
  kind: 'Hazard',
  text: 'Observed at the marked location',
  confidence: 'High',
  createdAt,
  observation: o,
});
const derive = (reports: Report[], cutoff = now) =>
  deriveLiveMap(sectors, reports, cutoff, cutoff, now);

void test('The map starts entirely predicted, and incoming hazard checks update geometry before verification', () => {
  assert.equal(derive([]).coverage.modeled, 100);
  assert.equal(derive([]).coverage.verified, 0);
  const r = report('clear', observation('hazard_absent', 'hazard:a'));
  const updated = derive([r]);
  const hazard = updated.features.find((f) => f.id === 'hazard:a')!;
  assert.equal(hazard.active, false);
  assert.equal(hazard.state, 'reported');
  assert.equal(hazard.lon, r.observation!.lon);
  assert.ok(updated.coverage.reported > 0);
  assert.equal(updated.coverage.verified, 0);
  const verified = derive([{ ...r, verifiedAt: now + 1000 }], now + 1000);
  assert.equal(
    verified.features.find((f) => f.id === hazard.id)!.state,
    'verified',
  );
  assert.equal(verified.coverage.total, updated.coverage.total);
  assert.ok(verified.coverage.verified > 0);
  const reopened = derive(
    [
      report('present', observation('hazard_present', 'hazard:a'), now + 2000),
      r,
    ],
    now + 2000,
  );
  assert.equal(reopened.features.find((f) => f.id === hazard.id)!.active, true);
});

void test('New groups have independent pins; relocation and evacuation affect only the chosen group', () => {
  const a = report('found1', observation('people_found', 'group:1', 4));
  const b = report('found2', observation('people_found', 'group:2', 7));
  const moved = report(
    'moved',
    { ...observation('people_relocated', 'group:1', 4), lon: -99.31 },
    now + 1000,
  );
  const state = derive([moved, b, a], now + 1000);
  assert.equal(state.features.find((f) => f.id === 'group:1')!.lon, -99.31);
  assert.equal(state.features.find((f) => f.id === 'group:2')!.count[0], 7);
  assert.ok(
    state.features.some((f) => f.id === 'people:a' && f.state === 'predicted'),
  );
  const evacuated = derive(
    [
      report(
        'evacuated',
        observation('people_evacuated', 'group:1'),
        now + 2000,
      ),
      moved,
      b,
      a,
    ],
    now + 2000,
  );
  assert.equal(
    evacuated.features.find((f) => f.id === 'group:1')!.active,
    false,
  );
  assert.equal(
    evacuated.features.find((f) => f.id === 'group:2')!.active,
    true,
  );
});

void test('No people visible never removes a predicted population, and unrelated area targets are rejected', () => {
  const r = report('checked', observation('people_not_seen', 'people:a'));
  const feature = derive([r]).features.find((f) => f.id === 'people:a')!;
  assert.equal(feature.active, true);
  assert.deepEqual(feature.count, [5, 9]);
  const wrongArea = report('wrong', observation('hazard_absent', 'hazard:b'));
  assert.equal(
    derive([wrongArea]).features.find((f) => f.id === 'hazard:b')!.state,
    'predicted',
  );
});

void test('Offline observations stay off the shared map until received, including replay after delivery', () => {
  let state = operationsReducer(
    { ...empty(), offline: true },
    {
      type: 'report',
      report: report('offline', observation('hazard_present', 'hazard:a')),
    },
  );
  assert.equal(derive(state.reports).coverage.modeled, 100);
  state = operationsReducer(state, {
    type: 'connectivity',
    offline: false,
    time: now + 5000,
    id: 'connect',
  });
  assert.equal(derive(state.reports, now + 4999).coverage.modeled, 100);
  assert.ok(derive(state.reports, now + 5000).coverage.reported > 0);
});

void test('Latest observation wins, and verifying an older observation does not undo a newer location', () => {
  const old = {
    ...report('old', observation('people_found', 'group:1', 3)),
    verifiedAt: now + 9000,
  };
  const newer = report(
    'new',
    { ...observation('people_relocated', 'group:1', 5), lat: 30.01 },
    now + 3000,
  );
  assert.equal(
    derive([newer, old], now + 9000).features.find((f) => f.id === 'group:1')!
      .lat,
    30.01,
  );
  assert.equal(
    derive([newer, old], now + 2000).features.find((f) => f.id === 'group:1')!
      .state,
    'reported',
  );
  assert.equal(
    derive([newer, old], now - 1).features.some((f) => f.id === 'group:1'),
    false,
  );
});

void test('Outcome presets include negative findings, and tactics adapt to incoming group reports', () => {
  assert.ok(reportPresets.some((p) => p.action === 'hazard_absent'));
  assert.match(
    reportPresets.find((p) => p.action === 'people_not_seen')!.text,
    /does not establish/,
  );
  const initial = tacticsPresets('Riverside', derive([]).features);
  const updated = tacticsPresets(
    'Riverside',
    derive([report('group', observation('people_found', 'group:1', 2))])
      .features,
  );
  assert.ok(initial.some((p) => p.label === 'Locate potential occupants'));
  assert.ok(updated.some((p) => p.label === 'Assess located group'));
  assert.ok(updated.some((p) => p.label === 'Reconcile new reports'));
});
