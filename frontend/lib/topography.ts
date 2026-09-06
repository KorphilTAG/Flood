export type ElevationGrid = { bounds: number[]; width: number; height: number };
/** Bilinear sampling of archived USGS elevations, stored in decimeters. No fabricated fallback. */
export function sampleElevation(
  data: Uint16Array,
  grid: ElevationGrid,
  lon: number,
  lat: number,
): number | null {
  const [west, south, east, north] = grid.bounds;
  if (lon < west || lon > east || lat < south || lat > north) return null;
  const x = Math.max(
    0,
    Math.min(grid.width - 1, ((lon - west) / (east - west)) * grid.width - 0.5),
  );
  const y = Math.max(
    0,
    Math.min(
      grid.height - 1,
      ((north - lat) / (north - south)) * grid.height - 0.5,
    ),
  );
  const x0 = Math.floor(x),
    y0 = Math.floor(y),
    x1 = Math.min(x0 + 1, grid.width - 1),
    y1 = Math.min(y0 + 1, grid.height - 1);
  const a =
    data[y0 * grid.width + x0] * (1 - (x - x0)) +
    data[y0 * grid.width + x1] * (x - x0);
  const b =
    data[y1 * grid.width + x0] * (1 - (x - x0)) +
    data[y1 * grid.width + x1] * (x - x0);
  return (a * (1 - (y - y0)) + b * (y - y0)) / 10;
}
export function containsPoint(ring: number[][], lon: number, lat: number) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i],
      [xj, yj] = ring[j];
    if (
      yi > lat !== yj > lat &&
      lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi
    )
      inside = !inside;
  }
  return inside;
}
export function areaFootprint(lon: number, lat: number) {
  return [
    [lon - 0.006, lat - 0.003],
    [lon + 0.006, lat - 0.003],
    [lon + 0.007, lat + 0.004],
    [lon - 0.004, lat + 0.006],
    [lon - 0.006, lat - 0.003],
  ];
}

export function floodForecastProgress(target: number, initial: number) {
  const forecastStart = initial - 2.5 * 60 * 60 * 1000;
  const forecastWindow = 6 * 60 * 60 * 1000;
  return Math.max(0, Math.min(1, (target - forecastStart) / forecastWindow));
}

/**
 * Builds a planning-grade flood surface from the archived elevation grid.
 * Cross sections expand away from the river until higher ground exceeds the
 * modeled water surface. This is intentionally a terrain-constrained visual
 * estimate, not a replacement for a hydraulic model.
 */
export function terrainFloodFootprint(
  data: Uint16Array,
  grid: ElevationGrid,
  river: number[],
  depthMeters: number,
  progress: number,
) {
  const left: number[][] = [],
    right: number[][] = [];
  const maxDistance = 260 + progress * 900 + depthMeters * 120;
  for (let i = 0; i < river.length; i += 2) {
    const lon = river[i],
      lat = river[i + 1];
    const previous = Math.max(0, i - 2),
      next = Math.min(river.length - 2, i + 2);
    const meanLat =
      ((river[previous + 1] + river[next + 1]) / 2) * (Math.PI / 180);
    const dx = (river[next] - river[previous]) * 111_320 * Math.cos(meanLat),
      dy = (river[next + 1] - river[previous + 1]) * 110_540,
      length = Math.hypot(dx, dy) || 1,
      perpendicularX = -dy / length,
      perpendicularY = dx / length;
    const centerElevation = sampleElevation(data, grid, lon, lat) ?? 0;
    const waterElevation = centerElevation + 0.35 + depthMeters * 0.72;
    const edge = (side: number) => {
      let accepted = 70;
      for (let distance = 70; distance <= maxDistance; distance += 45) {
        const candidateLon =
            lon +
            (perpendicularX * distance * side) /
              (111_320 * Math.cos(lat * (Math.PI / 180))),
          candidateLat = lat + (perpendicularY * distance * side) / 110_540,
          elevation = sampleElevation(data, grid, candidateLon, candidateLat);
        if (
          elevation === null ||
          (distance > 115 && elevation > waterElevation + 0.3)
        )
          break;
        accepted = distance;
      }
      return [
        lon +
          (perpendicularX * accepted * side) /
            (111_320 * Math.cos(lat * (Math.PI / 180))),
        lat + (perpendicularY * accepted * side) / 110_540,
        waterElevation,
      ];
    };
    left.push(edge(1));
    right.push(edge(-1));
  }
  return [...left, ...right.reverse()];
}

export function projectedPeoplePosition(
  lon: number,
  lat: number,
  progress: number,
  index: number,
) {
  const distance = progress * (180 + index * 35),
    angle = (0.55 + index * 1.7) % (Math.PI * 2);
  return [
    lon +
      (Math.cos(angle) * distance) /
        (111_320 * Math.cos(lat * (Math.PI / 180))),
    lat + (Math.sin(angle) * distance) / 110_540,
  ];
}
