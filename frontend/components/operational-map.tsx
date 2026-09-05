'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type * as Cesium from 'cesium';
import { Minus, Plus, LocateFixed, TriangleAlert } from 'lucide-react';
import mock from '@/data/mock.json';
import { Checkbox } from '@/components/ui/checkbox';
import 'cesium/Build/Cesium/Widgets/widgets.css';
type Props = {
  selected: string;
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
          terrainProvider: new C.EllipsoidTerrainProvider(),
          requestRenderMode: true,
          maximumRenderTimeChange: Infinity,
          skyBox: false,
          skyAtmosphere: false,
        });
        viewer.current = v;
        v.scene.backgroundColor = C.Color.fromCssColorString('#182329');
        v.scene.globe.baseColor = C.Color.fromCssColorString('#b5c0bc');
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
          if (typeof id === 'string' && mock.sectors.some((s) => s.id === id))
            callback.current(id);
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
    if (layers.flood)
      v.entities.add({
        id: 'demo:flood-extent',
        corridor: {
          positions: C.Cartesian3.fromDegreesArray(mock.river),
          width,
          material: color('#087bb3').withAlpha(0.38),
          outline: false,
          height: 3,
        },
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
          position: C.Cartesian3.fromDegrees(s.lon, s.lat, 20),
          polygon: {
            hierarchy: C.Cartesian3.fromDegreesArray(corners),
            height: 8,
            extrudedHeight: mode3d ? 100 : 8,
            material: color(c).withAlpha(active ? 0.3 : 0.12),
            outline: true,
            outlineColor: color(active ? '#152c3b' : c),
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
          position: C.Cartesian3.fromDegrees(team.lon, team.lat, 16),
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
  }, [ready, selected, target, initial, member, layers, mode3d]);
  useEffect(() => {
    const v = viewer.current,
      C = api.current;
    if (!ready || !v || !C) return;
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
          AREA OF OPERATIONS{' '}
          <span>Geographic basemap / illustrative overlays</span>
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
        {(['flood', 'sectors', 'teams'] as const).map((key) => (
          <label key={key}>
            <Checkbox
              checked={layers[key]}
              onCheckedChange={(checked) =>
                setLayers({ ...layers, [key]: Boolean(checked) })
              }
            />
            {key === 'flood'
              ? 'Flood estimate'
              : key === 'sectors'
                ? 'Areas'
                : 'Resources'}
          </label>
        ))}
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
              ? '3D globe · flat terrain · synthetic area heights'
              : 'Drag to pan · scroll to zoom · select an area'}
        </p>
      </div>
    </section>
  );
}
