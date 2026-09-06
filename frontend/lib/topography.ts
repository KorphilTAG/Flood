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
