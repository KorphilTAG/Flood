'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type * as Cesium from 'cesium';
import { Minus, Plus, LocateFixed, TriangleAlert } from 'lucide-react';
import mock from '@/data/mock.json';
import terrain from '@/data/terrain.json';
import texas from '@/data/texas-boundary.json';
import {
  areaFootprint,
  containsPoint,
  floodForecastProgress,
  sampleElevation,
  terrainFloodFootprint,
} from '@/lib/topography';
import { fixtureDepth } from '@/lib/operations';
import type { MapFeature } from '@/lib/live-map';
import { Checkbox } from '@/components/ui/checkbox';
import 'cesium/Build/Cesium/Widgets/widgets.css';

type Props = {
  selected: string;
  features: MapFeature[];
  onSelect: (id: string) => void;
  target: number;
  initial: number;
  member: string;
  focus: number;
  fieldCopy?: boolean;
  onHover?: (id: string | null) => void;
};
const texasRing = texas.geometry.coordinates[0];
const txBounds = [-106.65, 25.83, -93.5, 36.51];
let elevationPromise: Promise<Uint16Array> | undefined;
function loadElevation() {
  elevationPromise ??= fetch('/terrain/guadalupe-2021.u16')
    .then(async (response) => {
      if (!response.ok) throw new Error('Elevation unavailable');
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength !== terrain.width * terrain.height * 2)
        throw new Error('Incomplete elevation grid');
      return new Uint16Array(buffer);
    })
    .catch((error) => {
      elevationPromise = undefined;
      throw error;
    });
  return elevationPromise;
}
export default function OperationalMap({
  selected,
  features,
  onSelect,
  target,
  initial,
  member,
  focus,
  fieldCopy = false,
  onHover,
}: Props) {
  const mode3d = true;
  const container = useRef<HTMLDivElement>(null),
    viewer = useRef<Cesium.Viewer | null>(null),
    api = useRef<typeof Cesium | null>(null);
  const events = useRef({ onSelect, onHover }),
    boundsRef = useRef(txBounds),
    modeRef = useRef(false);
  const [ready, setReady] = useState(false),
    [error, setError] = useState(''),
    [basemapIssue, setBasemapIssue] = useState(false),
    [elevationError, setElevationError] = useState('');
  const [dem, setDem] = useState<Uint16Array | null>(null),
    [hovered, setHovered] = useState<string | null>(null);
  const [layers, setLayers] = useState({
    flood: true,
    sectors: true,
    teams: !fieldCopy,
    hazards: true,
    people: true,
    landmarks: true,
    flow: true,
  });
  const projectedHazards = features.filter(
    (f) => f.category === 'hazard' && f.active,
  );
  useEffect(() => {
    events.current = { onSelect, onHover };
  }, [onSelect, onHover]);
  useEffect(() => {
    if (!mode3d || dem) return;
    let active = true;
    void loadElevation()
      .then((data) => {
        if (active) setDem(data);
      })
      .catch(() => {
        if (active)
          setElevationError(
            'Historical terrain could not load. Reload to retry; observations remain available in the area panel.',
          );
      });
    return () => {
      active = false;
    };
  }, [mode3d, dem]);
  const resetView = useCallback(() => {
    const v = viewer.current,
      C = api.current;
    if (!v || !C) return;
    v.camera.setView({
      destination: mode3d
        ? C.Cartesian3.fromDegrees(-99.265, 29.94, 18500)
        : C.Rectangle.fromDegrees(-99.425, 29.925, -99.115, 30.125),
      orientation: { heading: 0, pitch: C.Math.toRadians(-65), roll: 0 },
    });
    v.scene.requestRender();
  }, [mode3d]);
  useEffect(() => {
    let cancelled = false,
      resize: ResizeObserver | undefined,
      handler: Cesium.ScreenSpaceEventHandler | undefined,
      removeMove: (() => void) | undefined;
    (window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL =
      '/cesium/';
    void import('cesium')
      .then((C) => {
        if (cancelled || !container.current) return;
        api.current = C;
        const v = new C.Viewer(container.current, {
          animation: false,
          timeline: false,
          baseLayerPicker: false,
          baseLayer: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          fullscreenButton: false,
          selectionIndicator: false,
          infoBox: false,
          sceneMode: C.SceneMode.SCENE3D,
          terrainProvider: new C.EllipsoidTerrainProvider(),
          requestRenderMode: true,
          maximumRenderTimeChange: Infinity,
          skyBox: false,
          skyAtmosphere: false,
        });
        viewer.current = v;
        v.useBrowserRecommendedResolution = false;
        v.scene.backgroundColor = C.Color.fromCssColorString('#182329');
        v.scene.globe.baseColor = C.Color.fromCssColorString('#c9d0bd');
        v.scene.globe.cartographicLimitRectangle = C.Rectangle.fromDegrees(
          ...(txBounds as [number, number, number, number]),
        );
        v.scene.globe.clippingPolygons = new C.ClippingPolygonCollection({
          inverse: true,
          polygons: [
            new C.ClippingPolygon({
              positions: C.Cartesian3.fromDegreesArray(
                texasRing.slice(0, -1).flat(),
              ),
            }),
          ],
        });
        v.scene.globe.maximumScreenSpaceError = 1;
        const provider = new C.UrlTemplateImageryProvider({
          url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
          credit: 'Esri, HERE, Garmin, OpenStreetMap contributors',
          maximumLevel: 16,
        });
        provider.errorEvent.addEventListener(() => {
          if (!cancelled) setBasemapIssue(true);
        });
        v.imageryLayers.addImageryProvider(provider);
        v.scene.screenSpaceCameraController.minimumZoomDistance = 500;
        v.scene.screenSpaceCameraController.maximumZoomDistance = 1800000;
        v.camera.setView({
          destination: C.Rectangle.fromDegrees(
            -99.425,
            29.925,
            -99.115,
            30.125,
          ),
        });
        const pickedArea = (position: Cesium.Cartesian2) => {
          const entity = v.scene.pick(position)?.id;
          const sector = entity?.properties?.sectorId?.getValue();
          if (typeof sector === 'string') return sector;
          return mock.sectors.some((s) => s.id === entity?.id)
            ? (entity.id as string)
            : null;
        };
        handler = new C.ScreenSpaceEventHandler(v.scene.canvas);
        handler.setInputAction((e: { position: Cesium.Cartesian2 }) => {
          const id = pickedArea(e.position);
          if (id) events.current.onSelect(id);
        }, C.ScreenSpaceEventType.LEFT_CLICK);
        handler.setInputAction((e: { endPosition: Cesium.Cartesian2 }) => {
          const id = pickedArea(e.endPosition);
          setHovered(id);
          events.current.onHover?.(id);
          v.scene.canvas.style.cursor = id ? 'pointer' : 'grab';
        }, C.ScreenSpaceEventType.MOUSE_MOVE);
        // Restrict navigation to Texas in 2D and the archived DEM coverage in 3D.
        let correcting = false;
        removeMove = v.camera.moveEnd.addEventListener(() => {
          if (correcting) return;
          const carto = v.camera.positionCartographic,
            lon = C.Math.toDegrees(carto.longitude),
            lat = C.Math.toDegrees(carto.latitude);
          const [w, s, e, n] = boundsRef.current;
          if (
            lon < w ||
            lon > e ||
            lat < s ||
            lat > n ||
            (!modeRef.current && !containsPoint(texasRing, lon, lat))
          ) {
            correcting = true;
            v.camera.setView({
              destination: modeRef.current
                ? C.Cartesian3.fromDegrees(-99.265, 29.94, 18500)
                : C.Rectangle.fromDegrees(-99.425, 29.925, -99.115, 30.125),
              orientation: {
                heading: 0,
                pitch: C.Math.toRadians(-65),
                roll: 0,
              },
            });
            correcting = false;
            v.scene.requestRender();
          }
        });
        resize = new ResizeObserver(() => {
          if (!v.isDestroyed()) {
            v.resize();
            v.scene.requestRender();
          }
        });
        resize.observe(container.current);
        setReady(true);
      })
      .catch(() => {
        if (!cancelled)
          setError(
            'Map rendering is unavailable on this device. Area details remain available.',
          );
      });
    return () => {
      cancelled = true;
      resize?.disconnect();
      handler?.destroy();
      removeMove?.();
      if (viewer.current && !viewer.current.isDestroyed())
        viewer.current.destroy();
      viewer.current = null;
    };
  }, []);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C || (mode3d && !dem)) return;
    modeRef.current = mode3d;
    boundsRef.current = mode3d ? terrain.bounds : txBounds;
    v.scene.globe.cartographicLimitRectangle = C.Rectangle.fromDegrees(
      ...(boundsRef.current as [number, number, number, number]),
    );
    if (mode3d && dem) {
      const scheme = new C.GeographicTilingScheme();
      v.terrainProvider = new C.CustomHeightmapTerrainProvider({
        width: 65,
        height: 65,
        tilingScheme: scheme,
        credit: 'USGS 3DEP · 2021-11-03 · NAVD88',
        callback: (x, y, level) => {
          const rect = scheme.tileXYToRectangle(x, y, level),
            heights = new Float32Array(65 * 65);
          for (let row = 0; row < 65; row++)
            for (let col = 0; col < 65; col++) {
              const lon = C.Math.toDegrees(
                  rect.west + ((rect.east - rect.west) * col) / 64,
                ),
                lat = C.Math.toDegrees(
                  rect.north - ((rect.north - rect.south) * row) / 64,
                );
              // Edge padding is outside the clipped DEM extent and is never shown.
              heights[row * 65 + col] = sampleElevation(
                dem,
                terrain,
                Math.max(terrain.bounds[0], Math.min(terrain.bounds[2], lon)),
                Math.max(terrain.bounds[1], Math.min(terrain.bounds[3], lat)),
              )!;
            }
          return heights;
        },
      });
      v.scene.globe.material = undefined;
      v.scene.morphTo3D(0);
    } else {
      v.scene.globe.material = undefined;
      v.terrainProvider = new C.EllipsoidTerrainProvider();
      v.scene.morphTo2D(0);
    }
    const imagery = v.imageryLayers.get(0);
    imagery.alpha = 1;
    imagery.saturation = 0.65;
    imagery.brightness = 1;
    v.scene.screenSpaceCameraController.maximumZoomDistance = mode3d
      ? 28000
      : 1800000;
    resetView();
  }, [ready, mode3d, dem, resetView]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C) return;
    v.entities.removeAll();
    const color = (s: string) => C.Color.fromCssColorString(s);
    const ground = (lon: number, lat: number) =>
      mode3d && dem ? (sampleElevation(dem, terrain, lon, lat) ?? 0) : 0;
    const positions = (ring: number[][]) =>
      C.Cartesian3.fromDegreesArray(ring.flat());
    const level = fixtureDepth(1.4, target, initial, member);
    const progress = floodForecastProgress(target, initial);
    const riverPositions =
      mode3d && dem
        ? C.Cartesian3.fromDegreesArrayHeights(
            mock.river.flatMap((value, i) =>
              i % 2 === 0
                ? [
                    value,
                    mock.river[i + 1],
                    ground(value, mock.river[i + 1]) + level + 4,
                  ]
                : [],
            ),
          )
        : C.Cartesian3.fromDegreesArray(mock.river);
    if (layers.flood) {
      if (mode3d && dem) {
        const floodSurface = terrainFloodFootprint(
          dem,
          terrain,
          mock.river,
          level,
          progress,
        );
        v.entities.add({
          id: 'flood:extent',
          polygon: {
            hierarchy: C.Cartesian3.fromDegreesArray(
              floodSurface.flatMap((point) => point.slice(0, 2)),
            ),
            material: color('#2a7fff').withAlpha(0.5),
          },
        });
      } else {
        v.entities.add({
          id: 'flood:extent',
          corridor: {
            positions: C.Cartesian3.fromDegreesArray(mock.river),
            width: Math.max(420, 520 + progress * 1280 + level * 180),
            material: color('#1596c7').withAlpha(0.42),
            outline: true,
            outlineColor: color('#8ee5ff').withAlpha(0.85),
          },
        });
      }
    }
    // The river remains visible at every time and layer combination so the
    // forecast's origin is immediately legible.
    v.entities.add({
      id: 'source:river-halo',
      polyline: {
        positions: riverPositions,
        clampToGround: !mode3d,
        width: 14,
        material: color('#e9fbff').withAlpha(0.9),
      },
    });
    v.entities.add({
      id: 'source:river',
      position: C.Cartesian3.fromDegrees(
        mock.river[10],
        mock.river[11],
        ground(mock.river[10], mock.river[11]) + 30,
      ),
      polyline: {
        positions: riverPositions,
        clampToGround: !mode3d,
        width: 8,
        material: color('#07557c'),
      },
      label: {
        text: fieldCopy ? 'GUADALUPE RIVER' : 'GUADALUPE RIVER · FLOOD SOURCE',
        font: fieldCopy ? 'bold 12px Arial' : 'bold 16px Arial',
        fillColor: C.Color.WHITE,
        showBackground: true,
        backgroundColor: color('#063e5c').withAlpha(0.96),
        backgroundPadding: new C.Cartesian2(10, 6),
        pixelOffset: new C.Cartesian2(0, -24),
        disableDepthTestDistance: Infinity,
      },
    });
    if (layers.flow)
      for (let i = 0; i < mock.river.length - 2; i += 2)
        v.entities.add({
          id: `flow:${i}`,
          polyline: {
            positions: C.Cartesian3.fromDegreesArray(
              mock.river.slice(i, i + 4),
            ),
            clampToGround: true,
            width: 9,
            material: new C.PolylineArrowMaterialProperty(color('#21769e')),
          },
        });
    if (layers.sectors)
      mock.sectors.forEach((s) => {
        const ring = areaFootprint(s.lon, s.lat);
        v.entities.add({
          id: s.id,
          position: C.Cartesian3.fromDegrees(
            s.lon,
            s.lat,
            ground(s.lon, s.lat) + 15,
          ),
          polygon: {
            hierarchy: positions(ring),
            material: color('#cf8b47').withAlpha(0.1),
          },
          polyline: {
            positions: positions(ring),
            clampToGround: true,
            width: 2,
            material: color('#a5682e'),
          },
          point: {
            pixelSize: 7,
            color: color('#213f51'),
            outlineWidth: 2,
            outlineColor: C.Color.WHITE,
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: s.code,
            font: 'bold 13px Arial',
            fillColor: C.Color.WHITE,
            showBackground: true,
            backgroundColor: color('#263d4c'),
            backgroundPadding: new C.Cartesian2(7, 4),
            pixelOffset: new C.Cartesian2(0, -22),
            disableDepthTestDistance: Infinity,
          },
        });
      });
    for (const feature of features) {
      if (!(feature.category === 'hazard' ? layers.hazards : layers.people))
        continue;
      if (!feature.active && feature.state === 'predicted') continue;
      const verified = feature.state === 'verified';
      const predicted = feature.state === 'predicted';
      const hue = !feature.active
        ? '#80dab8'
        : predicted
          ? '#7fd7ff'
          : verified
            ? '#63dcad'
            : '#ffbc66';
      const prefix = predicted ? '?' : verified ? '✓' : '◇';
      const count =
        feature.category === 'people' && feature.active
          ? `${feature.count[0] === feature.count[1] ? feature.count[0] : feature.count.join('–')} · `
          : '';
      v.entities.add({
        id: feature.id,
        properties: { sectorId: feature.sectorId },
        position: C.Cartesian3.fromDegrees(
          feature.lon,
          feature.lat,
          ground(feature.lon, feature.lat) + 25,
        ),
        point: {
          pixelSize: predicted ? 8 : 13,
          color: color(hue),
          outlineColor: color('#07111f'),
          outlineWidth: 2,
          disableDepthTestDistance: Infinity,
        },
        ...(feature.active
          ? {
              ellipse: {
                semiMajorAxis:
                  (feature.category === 'hazard' ? 180 : 300) +
                  (predicted ? progress * 250 : 0),
                semiMinorAxis:
                  (feature.category === 'hazard' ? 130 : 230) +
                  (predicted ? progress * 180 : 0),
                material: color(hue).withAlpha(predicted ? 0.1 : 0.2),
              },
            }
          : {}),
        label: {
          text: `${prefix} ${count}${feature.label} · ${feature.state}`,
          font: 'bold 12px Arial',
          pixelOffset: new C.Cartesian2(
            0,
            feature.category === 'people' ? 28 : -25,
          ),
          fillColor: color(hue),
          showBackground: true,
          backgroundColor: color('#080e18').withAlpha(0.94),
          backgroundPadding: new C.Cartesian2(8, 5),
          disableDepthTestDistance: Infinity,
        },
      });
      if (predicted && feature.category === 'people') {
        const origin = mock.sectors.find((s) => s.id === feature.sectorId)!;
        v.entities.add({
          id: `movement:${feature.id}`,
          polyline: {
            positions: C.Cartesian3.fromDegreesArray([
              origin.lon,
              origin.lat,
              feature.lon,
              feature.lat,
            ]),
            clampToGround: true,
            width: 4,
            material: new C.PolylineArrowMaterialProperty(
              color('#7fd7ff').withAlpha(0.7),
            ),
          },
        });
      }
    }
    if (layers.landmarks)
      mock.places.forEach((s) =>
        v.entities.add({
          id: `landmark:${s.name}`,
          position: C.Cartesian3.fromDegrees(
            s.lon,
            s.lat,
            ground(s.lon, s.lat) + 15,
          ),
          label: {
            text: `◆ ${s.name}`,
            font: '12px Arial',
            fillColor: color('#dbe7f3'),
            showBackground: true,
            backgroundColor: color('#080e18').withAlpha(0.94),
            disableDepthTestDistance: Infinity,
          },
        }),
      );
    if (layers.teams)
      mock.teams.forEach((s) =>
        v.entities.add({
          id: s.id,
          position: C.Cartesian3.fromDegrees(
            s.lon,
            s.lat,
            ground(s.lon, s.lat) + 15,
          ),
          point: {
            pixelSize: 7,
            color: color('#17685d'),
            outlineColor: C.Color.WHITE,
            outlineWidth: 2,
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: s.name,
            font: '11px Arial',
            pixelOffset: new C.Cartesian2(0, 17),
            fillColor: color('#7fd7ff'),
            showBackground: true,
            backgroundColor: color('#080e18').withAlpha(0.94),
            disableDepthTestDistance: Infinity,
          },
        }),
      );
    v.scene.requestRender();
  }, [
    ready,
    mode3d,
    dem,
    layers,
    target,
    initial,
    member,
    features,
    fieldCopy,
  ]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C) return;
    mock.sectors.forEach((s) => {
      const entity = v.entities.getById(s.id);
      if (!entity?.polygon || !entity.polyline) return;
      const active = s.id === selected,
        over = s.id === hovered;
      const color = C.Color.fromCssColorString(
        active
          ? '#238ed0'
          : over
            ? '#e6ba59'
            : s.severity === 'Critical'
              ? '#b75044'
              : '#b7803d',
      );
      entity.polygon.material = new C.ColorMaterialProperty(
        color.withAlpha(over ? 0.23 : active ? 0.17 : 0.07),
      );
      entity.polyline.material = new C.ColorMaterialProperty(
        color.withAlpha(active || over ? 1 : 0.65),
      );
      entity.polyline.width = new C.ConstantProperty(active || over ? 4 : 2);
      if (entity.label) {
        entity.label.text = new C.ConstantProperty(
          active || over ? `${s.code} · ${s.name}` : s.code,
        );
        entity.label.backgroundColor = new C.ConstantProperty(
          active
            ? C.Color.fromCssColorString('#185b80')
            : C.Color.fromCssColorString('#263d4c'),
        );
      }
    });
    v.scene.requestRender();
  }, [ready, selected, hovered, layers, dem, mode3d, target, features]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C || !dem || focus === 0) return;
    const s = mock.sectors.find((s) => s.id === selected);
    if (!s) return;
    v.camera.setView({
      destination: mode3d
        ? C.Cartesian3.fromDegrees(s.lon, s.lat - 0.015, 6000)
        : C.Rectangle.fromDegrees(
            s.lon - 0.025,
            s.lat - 0.025,
            s.lon + 0.025,
            s.lat + 0.025,
          ),
      orientation: { heading: 0, pitch: C.Math.toRadians(-65), roll: 0 },
    });
    v.scene.requestRender();
  }, [focus, selected, ready, mode3d, dem]);
  const selectedArea =
    mock.sectors.find((s) => s.id === selected) ?? mock.sectors[0];
  const elevation = dem
    ? sampleElevation(dem, terrain, selectedArea.lon, selectedArea.lat)
    : null;
  return (
    <section
      className={`map-module ${fieldCopy ? 'field-map-copy' : ''}`}
      aria-label={fieldCopy ? 'Latest field area map' : 'Texas operational map'}
    >
      <div className="map-toolbar">
        <span className="river-source-key">
          <i aria-hidden="true" /> Guadalupe River · flood source
        </span>
        <button
          className="icon-button"
          aria-label="Reset map to affected area"
          title="Reset to affected area"
          onClick={resetView}
        >
          <LocateFixed size={16} />
        </button>
      </div>
      <fieldset className="map-layer-controls" aria-label="Visible map layers">
        {(Object.keys(layers) as (keyof typeof layers)[]).map((key) => (
          <label key={key}>
            <Checkbox
              checked={layers[key]}
              onCheckedChange={(checked) =>
                setLayers({ ...layers, [key]: Boolean(checked) })
              }
            />
            {
              {
                flood: 'Flood',
                sectors: 'Areas',
                teams: 'Teams',
                hazards: 'Hazards',
                people: 'People',
                landmarks: 'Landmarks',
                flow: 'Flow',
              }[key]
            }
          </label>
        ))}
      </fieldset>
      <div
        className="map-panel"
        onMouseLeave={() => {
          setHovered(null);
          onHover?.(null);
        }}
      >
        <div ref={container} className="cesium-host" />
        {(!ready || (mode3d && !dem)) && !error && !elevationError && (
          <output className="map-loading">
            {mode3d
              ? 'Loading historical USGS elevation…'
              : 'Loading terrain map…'}
          </output>
        )}
        {(error || (mode3d && elevationError)) && (
          <div className="map-failure" role="alert">
            <TriangleAlert />
            <p>{error || elevationError}</p>
          </div>
        )}
        <div className="map-controls">
          <button
            aria-label="Zoom in"
            onClick={() => {
              viewer.current?.camera.zoomIn(
                (viewer.current.camera.positionCartographic.height ?? 20000) *
                  0.3,
              );
              viewer.current?.scene.requestRender();
            }}
          >
            <Plus size={18} />
          </button>
          <button
            aria-label="Zoom out"
            onClick={() => {
              viewer.current?.camera.zoomOut(
                (viewer.current.camera.positionCartographic.height ?? 20000) *
                  0.3,
              );
              viewer.current?.scene.requestRender();
            }}
          >
            <Minus size={18} />
          </button>
        </div>
        <div className="map-selection-label">
          {hovered
            ? mock.sectors.find((s) => s.id === hovered)?.name
            : `${selectedArea.code} · ${selectedArea.name}`}
          <small>
            {hovered
              ? 'Click to select area'
              : 'Blue outline = selected area · shaded footprints are simulated'}
          </small>
        </div>
        <div className="forecast-map-status">
          <strong>
            {new Intl.DateTimeFormat('en-US', {
              timeZone: 'America/Chicago',
              hour: '2-digit',
              minute: '2-digit',
              hour12: false,
            }).format(target)}{' '}
            CDT · {projectedHazards.length} hazard areas
          </strong>
          <span>? Predicted · ◇ Reported · ✓ Verified</span>
        </div>
      </div>
      <div className="map-caption">
        {basemapIssue ? (
          <span>Street tiles unavailable; map overlays remain simulated.</span>
        ) : mode3d ? (
          <>
            <span>
              Ground {elevation?.toFixed(1) ?? '—'} m NAVD88 · depth{' '}
              {fixtureDepth(
                selectedArea.depth,
                target,
                initial,
                member,
              ).toFixed(1)}{' '}
              m predicted · historical terrain
            </span>
            <a
              href={terrain.sources[0].metaUrl}
              target="_blank"
              rel="noreferrer"
            >
              USGS source
            </a>
          </>
        ) : (
          <span>Esri basemap · USGS terrain · flood estimates simulated</span>
        )}
      </div>
    </section>
  );
}
