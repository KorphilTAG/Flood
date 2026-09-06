import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import {
  sampleElevation,
  containsPoint,
  areaFootprint,
  floodForecastProgress,
  projectedPeoplePosition,
  terrainFloodFootprint,
} from '../lib/topography.ts';
const metadata = JSON.parse(
  readFileSync(new URL('../data/terrain.json', import.meta.url), 'utf8'),
);
const bytes = readFileSync(
  new URL('../public/terrain/guadalupe-2021.u16', import.meta.url),
);
const grid = new Uint16Array(
  bytes.buffer,
  bytes.byteOffset,
  bytes.byteLength / 2,
);
void test('Historical terrain is pinned to validated 2021 USGS source pixels', () => {
  assert.equal(bytes.byteLength, metadata.width * metadata.height * 2);
  assert.equal(
    createHash('sha256').update(bytes).digest('hex'),
    metadata.sha256,
  );
  assert.equal(metadata.publicationDate, '2021-11-03');
  assert.equal(metadata.sources.length, 2);
  assert.ok(
    metadata.sources.every(
      (s: { downloadURL: string }) =>
        s.downloadURL.includes('/historical/') &&
        s.downloadURL.endsWith('_20211103.tif'),
    ),
  );
  const sites = JSON.parse(
    readFileSync(new URL('../data/mock.json', import.meta.url), 'utf8'),
  ).sectors;
  for (const site of sites) {
    const h = sampleElevation(grid, metadata, site.lon, site.lat);
    assert.ok(h !== null && h > 450 && h < 710);
  }
});
void test('DEM sampling interpolates pixel centers correctly and never invents outside coverage', () => {
  const pixels = new Uint16Array([1000, 2000, 3000, 4000]);
  const geometry = { width: 2, height: 2, bounds: [0, 0, 2, 2] };
  assert.equal(sampleElevation(pixels, geometry, 0.5, 1.5), 100);
  assert.equal(sampleElevation(pixels, geometry, 1, 1), 250);
  assert.equal(sampleElevation(pixels, geometry, 1.5, 0.5), 400);
  assert.equal(sampleElevation(pixels, geometry, 3, 1), null);
  assert.equal(sampleElevation(grid, metadata, -100, 31), null);
});
void test('Census mask includes Texas locations and excludes neighboring states', () => {
  const ring = JSON.parse(
    readFileSync(
      new URL('../data/texas-boundary.json', import.meta.url),
      'utf8',
    ),
  ).geometry.coordinates[0];
  for (const [lon, lat] of [
    [-99.265, 30.015],
    [-97.743, 30.267],
    [-95.369, 29.76],
    [-96.797, 32.777],
  ])
    assert.equal(containsPoint(ring, lon, lat), true);
  for (const [lon, lat] of [
    [-106.65, 35.08],
    [-97.52, 35.47],
    [-90.07, 29.95],
  ])
    assert.equal(containsPoint(ring, lon, lat), false);
  assert.equal(containsPoint(areaFootprint(-99.3, 30), -99.3, 30), true);
});
void test('forecast progression and terrain flood footprint change with time', () => {
  const initial = Date.UTC(2026, 0, 1, 12);
  assert.equal(
    floodForecastProgress(initial - 2.5 * 60 * 60 * 1000, initial),
    0,
  );
  assert.equal(
    floodForecastProgress(initial + 3.5 * 60 * 60 * 1000, initial),
    1,
  );
  const river = [-99.3, 30, -99.29, 30.01, -99.28, 30.02];
  const early = terrainFloodFootprint(grid, metadata, river, 1, 0);
  const late = terrainFloodFootprint(grid, metadata, river, 2, 1);
  assert.equal(early.length, river.length);
  assert.equal(late.length, river.length);
  assert.ok(late.every((point) => point.length === 3));
  assert.notDeepEqual(early, late);
  const stationary = projectedPeoplePosition(-99.3, 30, 0, 0);
  const projected = projectedPeoplePosition(-99.3, 30, 1, 0);
  assert.deepEqual(stationary, [-99.3, 30]);
  assert.notDeepEqual(projected, stationary);
});
