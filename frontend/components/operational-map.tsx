'use client';

import { useEffect, useRef, useState } from 'react';
import { Checkbox } from '@/components/ui/checkbox';

type Props = {
  selected: string;
  features: unknown[];
  onSelect: (id: string) => void;
  target: number;
  initial: number;
  member: string;
  focus: number;
  fieldCopy?: boolean;
  onHover?: (id: string | null) => void;
};

const layerLabels = {
  flood: 'Flood', sectors: 'Areas', teams: 'Teams', hazards: 'Hazards',
  people: 'People', landmarks: 'Landmarks', flow: 'Flow',
};

/** MapLibre terrain from feature/terrain-view inside the Command and Field shell. */
export default function OperationalMap({ selected, features, target, onSelect, fieldCopy = false, onHover }: Props) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [layers, setLayers] = useState({
    flood: true, sectors: true, teams: !fieldCopy, hazards: true,
    people: true, landmarks: true, flow: true,
  });
  const send = (type: string, payload: Record<string, unknown> = {}) =>
    frame.current?.contentWindow?.postMessage({ type, ...payload }, window.location.origin);

  useEffect(() => { send('incident-layers', { layers, selected }); }, [layers, selected]);
  useEffect(() => { send('incident-data', { features, selected, at: target }); }, [features, selected, target]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data) return;
      if (event.data.type === 'incident-select' && typeof event.data.id === 'string') onSelect(event.data.id);
      if (event.data.type === 'incident-hover') onHover?.(event.data.id ?? null);
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [onHover, onSelect]);

  return (
    <section className={`map-module ${fieldCopy ? 'field-map-copy' : ''}`} aria-label={fieldCopy ? 'Latest field area map' : 'Texas operational map'}>
      <div className="map-toolbar">
        <span className="river-source-key"><i aria-hidden="true" /> Guadalupe River · 3D terrain and flood overlay</span>
      </div>
      <fieldset className="map-layer-controls" aria-label="Visible map layers">
        {(Object.keys(layers) as (keyof typeof layers)[]).map((key) => (
          <label key={key}>
            <Checkbox checked={layers[key]} onCheckedChange={(checked) => setLayers((current) => ({ ...current, [key]: Boolean(checked) }))} />
            {layerLabels[key]}
          </label>
        ))}
      </fieldset>
      <div className="map-panel terrain-frame-wrap">
        <iframe ref={frame} className="terrain-frame" src="/terrain/terrain.html" title="Interactive 3D flood terrain" onLoad={() => { send('incident-layers', { layers, selected }); send('incident-data', { features, selected, at: target }); }} />
      </div>
      <div className="map-caption"><span>Public 3DEP terrain · engine depth overlay · simulated operational annotations</span></div>
    </section>
  );
}
