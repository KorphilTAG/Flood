/** Procedural exercise relief, not measured terrain or a hydraulic model. */
export function riverSample(lon: number, river: number[]) {
  let i = 0;
  while (i < river.length - 4 && lon > river[i + 2]) i += 2;
  const u = Math.max(
    0,
    Math.min(1, (lon - river[i]) / (river[i + 2] - river[i])),
  );
  return {
    lat: river[i + 1] + u * (river[i + 3] - river[i + 1]),
    bed: 470 - (lon + 99.4) * 180,
  };
}
export function terrainElevation(lon: number, lat: number, river: number[]) {
  const { lat: center, bed } = riverSample(lon, river);
  const distance = Math.abs(lat - center) * 111000;
  const relief = Math.min(
    210,
    Math.max(0, Math.min(distance, 500) - 180) * 0.006 +
      Math.max(0, distance - 500) * 0.075,
  );
  const hills =
    Math.max(0, Math.sin(lon * 240) * Math.cos(lat * 190)) *
    Math.min(85, Math.max(0, distance - 600) * 0.03);
  return bed + relief + hills;
}
