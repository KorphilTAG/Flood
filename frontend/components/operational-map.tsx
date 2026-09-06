'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type * as Cesium from 'cesium';
import { Minus, Plus, LocateFixed, TriangleAlert } from 'lucide-react';
import mock from '@/data/mock.json';
import { terrainElevation, riverSample } from '@/lib/topography';
import { fixtureDepth } from '@/lib/operations';
import { Checkbox } from '@/components/ui/checkbox';
import 'cesium/Build/Cesium/Widgets/widgets.css';
type Props = {
  selected: string;
  confirmedHazards: string[];
  onSelect: (id: string) => void;
  target: number;
  initial: number;
  member: string;
  focus: number;
  mode3d: boolean;
  setMode3d: (v: boolean) => void;
};
export default function OperationalMap({
  selected,
  confirmedHazards,
  onSelect,
  target,
  initial,
  member,
  focus,
  mode3d,
  setMode3d,
}: Props) {
  const container = useRef<HTMLDivElement>(null),
    viewer = useRef<Cesium.Viewer | null>(null),
    api = useRef<typeof Cesium | null>(null),
    callback = useRef(onSelect);
  const [ready, setReady] = useState(false),
    [error, setError] = useState(''),
    [basemapIssue, setBasemapIssue] = useState(false);
  const [layers, setLayers] = useState({
    flood: true,
    sectors: true,
    teams: true,
    hazards: true,
    people: false,
    landmarks: true,
    flow: true,
  });
  useEffect(() => {
    callback.current = onSelect;
  }, [onSelect]);
  const resetView = useCallback(() => {
    const v = viewer.current,
      C = api.current;
    if (!v || !C) return;
    v.camera.setView({
      destination: mode3d
        ? C.Cartesian3.fromDegrees(mock.center[0], mock.center[1] - 0.06, 26000)
        : C.Rectangle.fromDegrees(
            mock.center[0] - 0.17,
            mock.center[1] - 0.1,
            mock.center[0] + 0.17,
            mock.center[1] + 0.1,
          ),
      orientation: { heading: 0, pitch: C.Math.toRadians(-70), roll: 0 },
    });
    v.scene.requestRender();
  }, [mode3d]);
  useEffect(() => {
    let cancelled = false;
    let resize: ResizeObserver | undefined;
    let handler: Cesium.ScreenSpaceEventHandler | undefined;
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
          sceneMode: C.SceneMode.SCENE2D,
          terrainProvider: new C.CustomHeightmapTerrainProvider({
            width: 32,
            height: 32,
            credit: 'Procedural exercise terrain · not surveyed elevation',
            callback: (x, y, level) => {
              const rect = new C.GeographicTilingScheme().tileXYToRectangle(
                x,
                y,
                level,
              );
              const heights = new Float32Array(32 * 32);
              for (let row = 0; row < 32; row++)
                for (let col = 0; col < 32; col++) {
                  const lon = C.Math.toDegrees(
                    rect.west + ((rect.east - rect.west) * col) / 31,
                  );
                  const lat = C.Math.toDegrees(
                    rect.north - ((rect.north - rect.south) * row) / 31,
                  );
                  heights[row * 32 + col] =
                    lon > -99.65 && lon < -98.95 && lat > 29.7 && lat < 30.3
                      ? terrainElevation(lon, lat, mock.river)
                      : 0;
                }
              return heights;
            },
          }),
          requestRenderMode: true,
          maximumRenderTimeChange: Infinity,
          skyBox: false,
          skyAtmosphere: false,
        });
        viewer.current = v;
        v.scene.backgroundColor = C.Color.fromCssColorString('#182329');
        v.scene.globe.baseColor = C.Color.fromCssColorString('#a2aa95');
        v.scene.globe.material = C.Material.fromType('ElevationContour', {
          color: C.Color.fromCssColorString('#374b42').withAlpha(0.6),
          spacing: 20,
          width: 1.2,
        });
        const provider = new C.OpenStreetMapImageryProvider({
          url: 'https://tile.openstreetmap.org/',
        });
        provider.errorEvent.addEventListener(() => {
          if (!cancelled) setBasemapIssue(true);
        });
        const imagery = v.imageryLayers.addImageryProvider(provider);
        imagery.saturation = 0.15;
        imagery.brightness = 0.9;
        v.camera.setView({
          destination: C.Rectangle.fromDegrees(
            mock.center[0] - 0.17,
            mock.center[1] - 0.1,
            mock.center[0] + 0.17,
            mock.center[1] + 0.1,
          ),
        });
        handler = new C.ScreenSpaceEventHandler(v.scene.canvas);
        handler.setInputAction((event: { position: Cesium.Cartesian2 }) => {
          const pick = v.scene.pick(event.position);
          const id = pick?.id?.id;
          if (typeof id === 'string') {
            const areaId = id.replace(/^(hazard|people):/, '');
            if (mock.sectors.some((s) => s.id === areaId))
              callback.current(areaId);
          }
        }, C.ScreenSpaceEventType.LEFT_CLICK);
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
            'Map rendering is unavailable on this device. All area details and field actions remain available.',
          );
      });
    return () => {
      cancelled = true;
      resize?.disconnect();
      handler?.destroy();
      if (viewer.current && !viewer.current.isDestroyed())
        viewer.current.destroy();
      viewer.current = null;
    };
  }, []);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C) return;
    v.entities.removeAll();
    const color = (value: string) => C.Color.fromCssColorString(value);
    const factor = member === 'high' ? 1.25 : member === 'low' ? 0.75 : 1;
    const width =
      Math.max(160, 650 + ((target - initial) / 3600000) * 180) * factor;
    // A graded water ribbon follows the exercise river bed. Width and surface
    // elevation respond to the clock; the ground elevation remains fixed.
    const surface = (lon: number) =>
      riverSample(lon, mock.river).bed +
      fixtureDepth(1.4, target, initial, member);
    const ribbon: number[] = [];
    const steps = 100;
    const offset = width / 2 / 111000;
    for (let j = 0; j <= steps; j++) {
      const lon =
        mock.river[0] +
        ((mock.river[mock.river.length - 2] - mock.river[0]) * j) / steps;
      ribbon.push(lon, riverSample(lon, mock.river).lat + offset, surface(lon));
    }
    for (let j = steps; j >= 0; j--) {
      const lon =
        mock.river[0] +
        ((mock.river[mock.river.length - 2] - mock.river[0]) * j) / steps;
      ribbon.push(lon, riverSample(lon, mock.river).lat - offset, surface(lon));
    }
    if (layers.flood)
      v.entities.add({
        id: 'demo:flood-extent',
        polygon: {
          hierarchy: C.Cartesian3.fromDegreesArrayHeights(ribbon),
          perPositionHeight: true,
          material: color('#368bb5').withAlpha(0.72),
          outline: false,
        },
      });
    if (layers.flow)
      for (let i = 0; i < mock.river.length - 2; i += 2) {
        const phase = ((((target - initial) / 600000) % 1) + 1) % 1;
        const lon1 =
          mock.river[i] + (mock.river[i + 2] - mock.river[i]) * phase * 0.3;
        const lon2 = lon1 + (mock.river[i + 2] - mock.river[i]) * 0.5;
        v.entities.add({
          id: `flow:${i}`,
          polyline: {
            positions: C.Cartesian3.fromDegreesArrayHeights([
              lon1,
              riverSample(lon1, mock.river).lat,
              surface(lon1) + 5,
              lon2,
              riverSample(lon2, mock.river).lat,
              surface(lon2) + 5,
            ]),
            width: 10,
            material: new C.PolylineArrowMaterialProperty(
              color('#d6f1f5').withAlpha(0.9),
            ),
          },
        });
      }
    if (layers.hazards)
      mock.sectors
        .filter((s) => ['Critical', 'High'].includes(s.severity))
        .forEach((s) => {
          v.entities.add({
            id: `hazard:${s.id}`,
            position: C.Cartesian3.fromDegrees(
              s.lon + 0.008,
              s.lat + 0.003,
              terrainElevation(s.lon + 0.008, s.lat + 0.003, mock.river) + 20,
            ),
            label: {
              text: `${confirmedHazards.includes(s.id) ? '✓' : '▲'} ${s.id.startsWith('crossing:') ? 'CLOSED CROSSING' : 'DEBRIS / ACCESS'}`,
              font: 'bold 11px Arial',
              fillColor: color('#ffd29a'),
              showBackground: true,
              backgroundColor: color('#342b24').withAlpha(0.95),
              backgroundPadding: new C.Cartesian2(7, 5),
              disableDepthTestDistance: Infinity,
            },
          });
        });
    if (layers.people)
      mock.sectors
        .filter((s) => s.people[1] > 0)
        .forEach((s) => {
          v.entities.add({
            id: `people:${s.id}`,
            position: C.Cartesian3.fromDegrees(
              s.lon,
              s.lat,
              terrainElevation(s.lon, s.lat, mock.river) + 30,
            ),
            ellipse: {
              semiMajorAxis: 600,
              semiMinorAxis: 450,
              material: color('#d795ac').withAlpha(0.32),
            },
            label: {
              text: `${s.people[0]}–${s.people[1]} people?`,
              font: 'bold 12px Arial',
              pixelOffset: new C.Cartesian2(0, 35),
              fillColor: color('#ffe4ee'),
              showBackground: true,
              backgroundColor: color('#4c3040'),
              disableDepthTestDistance: Infinity,
            },
          });
        });
    if (layers.landmarks)
      mock.places.forEach((place) => {
        v.entities.add({
          id: `landmark:${place.name}`,
          position: C.Cartesian3.fromDegrees(
            place.lon,
            place.lat,
            terrainElevation(place.lon, place.lat, mock.river) + 20,
          ),
          point: {
            pixelSize: 5,
            color: color('#fffce6'),
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: `◆ ${place.name}`,
            font: '12px Arial',
            fillColor: color('#fffce6'),
            showBackground: true,
            backgroundColor: color('#394438'),
            pixelOffset: new C.Cartesian2(0, -16),
            disableDepthTestDistance: Infinity,
          },
        });
      });
    if (layers.sectors)
      mock.sectors.forEach((s) => {
        const active = s.id === selected,
          c =
            s.state === 'Unknown'
              ? '#7c6282'
              : s.severity === 'Critical'
                ? '#a84237'
                : '#a66f1d';
        const corners = [
          s.lon - 0.006,
          s.lat - 0.003,
          s.lon + 0.006,
          s.lat - 0.003,
          s.lon + 0.007,
          s.lat + 0.004,
          s.lon - 0.004,
          s.lat + 0.006,
        ];
        v.entities.add({
          id: s.id,
          position: C.Cartesian3.fromDegrees(
            s.lon,
            s.lat,
            terrainElevation(s.lon, s.lat, mock.river) + 15,
          ),
          polygon: {
            hierarchy: C.Cartesian3.fromDegreesArray(corners),

            material: color(c).withAlpha(active ? 0.3 : 0.12),
            outline: true,
            outlineColor: color(active ? '#e5f3f7' : c),
          },
          point: {
            pixelSize: active ? 10 : 7,
            color: color(active ? '#e6f3fc' : '#203442'),
            outlineColor: color('#192c3a'),
            outlineWidth: 2,
            disableDepthTestDistance: Infinity,
          },
          label: {
            text: s.code.replace('–', '-'),
            font: 'bold 13px Arial',
            fillColor: color('#f4f7fa'),
            showBackground: true,
            backgroundColor: color('#172a38'),
            backgroundPadding: new C.Cartesian2(7, 4),
            pixelOffset: new C.Cartesian2(0, -24),
            disableDepthTestDistance: Infinity,
          },
        });
      });
    if (layers.teams)
      mock.teams.forEach((team) =>
        v.entities.add({
          id: team.id,
          position: C.Cartesian3.fromDegrees(
            team.lon,
            team.lat,
            terrainElevation(team.lon, team.lat, mock.river) + 16,
          ),
          point: {
            pixelSize: 7,
            color: color('#006958'),
            outlineColor: C.Color.WHITE,
            outlineWidth: 2,
          },
          label: {
            text: team.name,
            font: '12px Arial',
            fillColor: color('#143b35'),
            showBackground: true,
            backgroundColor: C.Color.WHITE.withAlpha(0.9),
            pixelOffset: new C.Cartesian2(0, 18),
            disableDepthTestDistance: Infinity,
          },
        }),
      );
    v.scene.requestRender();
  }, [
    ready,
    selected,
    target,
    initial,
    member,
    layers,
    mode3d,
    confirmedHazards,
  ]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C) return;
    const imagery = v.imageryLayers.get(0);
    if (imagery) imagery.alpha = mode3d ? 0.38 : 0.85;
    if (mode3d) v.scene.morphTo3D(0);
    else v.scene.morphTo2D(0);
    resetView();
  }, [mode3d, ready, resetView]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C || focus === 0) return;
    const s = mock.sectors.find((s) => s.id === selected);
    if (!s) return;
    v.camera.setView({
      destination: mode3d
        ? C.Cartesian3.fromDegrees(s.lon, s.lat - 0.015, 6500)
        : C.Rectangle.fromDegrees(
            s.lon - 0.035,
            s.lat - 0.025,
            s.lon + 0.035,
            s.lat + 0.025,
          ),
      orientation: { heading: 0, pitch: C.Math.toRadians(-65), roll: 0 },
    });
    v.scene.requestRender();
  }, [focus, ready, selected, mode3d]);
  return (
    <section className="map-panel" aria-label="Operational map">
      <div ref={container} className="cesium-host" />
      {!ready && !error && (
        <output className="map-loading">Loading geographic map…</output>
      )}
      {error && (
        <div className="map-failure" role="alert">
          <TriangleAlert />
          <p>{error}</p>
        </div>
      )}
      <div className="map-top">
        <div className="map-title">
          AREA OF OPERATIONS <span>Topographic exercise / 20 m contours</span>
        </div>
        <fieldset className="map-mode" aria-label="Map dimension">
          <button aria-pressed={!mode3d} onClick={() => setMode3d(false)}>
            2D
          </button>
          <button aria-pressed={mode3d} onClick={() => setMode3d(true)}>
            3D
          </button>
        </fieldset>
      </div>
      <div className="map-layers">
        {(
          [
            'flood',
            'sectors',
            'teams',
            'hazards',
            'people',
            'landmarks',
            'flow',
          ] as const
        ).map((key) => (
          <label key={key}>
            <Checkbox
              checked={layers[key]}
              onCheckedChange={(checked) =>
                setLayers({ ...layers, [key]: Boolean(checked) })
              }
            />
            {
              {
                flood: 'Flood extent',
                sectors: 'Areas',
                teams: 'Teams',
                hazards: 'Hazards',
                people: 'People hotspots',
                landmarks: 'Landmarks',
                flow: 'Water flow',
              }[key]
            }
          </label>
        ))}
      </div>
      <div className="elevation-key">
        <span>EXERCISE ELEVATION</span>
        {(() => {
          const area =
            mock.sectors.find((s) => s.id === selected) ?? mock.sectors[0];
          const ground = terrainElevation(area.lon, area.lat, mock.river);
          const water = fixtureDepth(area.depth, target, initial, member);
          return (
            <>
              <strong>
                {area.code} · ground {ground.toFixed(1)} m
              </strong>
              <div>Water surface {(ground + water).toFixed(1)} m</div>
              <small>Depth {water.toFixed(1)} m · ground fixed</small>
            </>
          );
        })()}
      </div>
      <div className="map-controls">
        <button
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => {
            viewer.current?.camera.zoomIn(
              (viewer.current?.camera.positionCartographic.height ?? 20000) *
                0.3,
            );
            viewer.current?.scene.requestRender();
          }}
        >
          <Plus size={18} />
        </button>
        <button
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => {
            viewer.current?.camera.zoomOut(
              (viewer.current?.camera.positionCartographic.height ?? 20000) *
                0.3,
            );
            viewer.current?.scene.requestRender();
          }}
        >
          <Minus size={18} />
        </button>
        <button
          title="Reset map extent"
          aria-label="Reset map extent"
          onClick={resetView}
        >
          <LocateFixed size={18} />
        </button>
      </div>
      <div className="map-bottom">
        <div className="map-legend">
          <span>
            <i className="flood-key" />
            Modeled flood
          </span>
          <span>
            <i className="sector-key" />
            Review area
          </span>
          <span>
            <i className="team-key" />
            Team
          </span>
        </div>
        <p>
          {basemapIssue
            ? 'Basemap tiles unavailable. Overlays remain illustrative.'
            : mode3d
              ? 'Synthetic terrain · 20 m contours · arrows show modeled flow'
              : 'Drag to pan · select area or hotspot · all overlays simulated'}
        </p>
      </div>
    </section>
  );
}
