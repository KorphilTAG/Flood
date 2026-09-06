'use client';
import { useState } from 'react';
import { ArrowLeft, ArrowRight, Send, X } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { reportPresets, type MapFeature } from '@/lib/live-map';
import type { MapObservation } from '@/lib/operations';
import terrain from '@/data/terrain.json';

export type ObservationDraft = {
  kind: string;
  text: string;
  confidence: string;
  observation: MapObservation;
};
type Props = {
  area: { id: string; code: string; name: string; lon: number; lat: number };
  features: MapFeature[];
  offline: boolean;
  onClose: () => void;
  onSubmit: (draft: ObservationDraft) => void;
};

export default function FieldObservationForm({
  area,
  features,
  offline,
  onClose,
  onSubmit,
}: Props) {
  const [step, setStep] = useState(0);
  const [preset, setPreset] = useState(reportPresets[0]);
  const [text, setText] = useState(reportPresets[0].text);
  const [newId] = useState(() => `field:${crypto.randomUUID()}`);
  const [targetId, setTargetId] = useState(`hazard:${area.id}`);
  const [lon, setLon] = useState((area.lon + 0.007).toFixed(5));
  const [lat, setLat] = useState((area.lat + 0.002).toFixed(5));
  const [count, setCount] = useState('');
  const [confidence, setConfidence] = useState('Medium');
  const category = preset.action.startsWith('hazard_') ? 'hazard' : 'people';
  const targets = features.filter(
    (f) => f.sectorId === area.id && f.category === category,
  );
  const needsCount = ['people_found', 'people_relocated'].includes(
    preset.action,
  );
  const coordinatesValid =
    lon.trim() !== '' &&
    lat.trim() !== '' &&
    Number.isFinite(Number(lon)) &&
    Number.isFinite(Number(lat)) &&
    Number(lon) >= terrain.bounds[0] &&
    Number(lon) <= terrain.bounds[2] &&
    Number(lat) >= terrain.bounds[1] &&
    Number(lat) <= terrain.bounds[3];
  const countValid =
    !needsCount ||
    (count.trim() !== '' &&
      Number.isInteger(Number(count)) &&
      Number(count) > 0 &&
      Number(count) <= 10000);
  const targetValid =
    targetId === newId
      ? ['hazard_present', 'people_found'].includes(preset.action)
      : targets.some((f) => f.id === targetId);
  function chooseTarget(id: string) {
    setTargetId(id);
    const feature = targets.find((f) => f.id === id);
    setLon((feature?.lon ?? area.lon).toFixed(5));
    setLat((feature?.lat ?? area.lat).toFixed(5));
    setCount(
      feature &&
        feature.state !== 'predicted' &&
        feature.count[0] === feature.count[1]
        ? String(feature.count[1])
        : '',
    );
  }
  function choosePreset(p: typeof preset) {
    setPreset(p);
    setText(p.text);
    const nextCategory = p.action.startsWith('hazard_') ? 'hazard' : 'people';
    const existing = features.find(
      (f) => f.sectorId === area.id && f.category === nextCategory,
    );
    const newGroup = p.action === 'people_found';
    setTargetId(newGroup ? newId : (existing?.id ?? newId));
    setLon((newGroup ? area.lon : (existing?.lon ?? area.lon)).toFixed(5));
    setLat((newGroup ? area.lat : (existing?.lat ?? area.lat)).toFixed(5));
    setCount('');
  }
  return (
    <dialog
      open
      className="phone-map-overlay phone-report-overlay"
      aria-label="Report an observation"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      <header>
        <div>
          <strong>Report observation</strong>
          <span>
            {area.code} · {area.name}
          </span>
        </div>
        <button aria-label="Close report" onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <ol className="report-steps" aria-label="Report progress">
        {['Observation', 'Location', 'Review'].map((label, i) => (
          <li key={label} aria-current={i === step ? 'step' : undefined}>
            {i + 1}. {label}
          </li>
        ))}
      </ol>
      <div className="phone-report-body">
        {step === 0 && (
          <>
            <h2>What changed?</h2>
            <div className="report-preset-grid">
              {reportPresets.map((p) => (
                <button
                  key={p.action}
                  aria-pressed={preset.action === p.action}
                  onClick={() => choosePreset(p)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <label htmlFor="field-report-text">
              Observation details · editable
            </label>
            <textarea
              id="field-report-text"
              rows={6}
              maxLength={240}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <small>
              {text.length}/240 characters · the selected outcome controls the
              map update.
            </small>
          </>
        )}
        {step === 1 && (
          <>
            <h2>Locate this observation</h2>
            <label htmlFor="field-report-target">
              {category === 'hazard'
                ? 'Which hazard?'
                : 'Which group / search location?'}
            </label>
            <Select
              value={targetId}
              onValueChange={(v) => {
                if (v) chooseTarget(String(v));
              }}
            >
              <SelectTrigger id="field-report-target">
                <SelectValue>
                  {targetId === newId
                    ? `New ${category === 'hazard' ? 'hazard' : 'group'}`
                    : (targets.find((f) => f.id === targetId)?.label ??
                      'Select a map feature')}
                </SelectValue>
              </SelectTrigger>
              <SelectContent className="choice-menu">
                {['hazard_present', 'people_found'].includes(preset.action) && (
                  <SelectItem value={newId}>
                    New {category === 'hazard' ? 'hazard' : 'group'}
                  </SelectItem>
                )}
                {targets.map((f, i) => (
                  <SelectItem key={f.id} value={f.id}>
                    {i + 1}. {f.label} · {f.state}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="location-presets">
              {[
                { label: 'Area center', lon: area.lon, lat: area.lat },
                {
                  label: 'West approach',
                  lon: area.lon - 0.003,
                  lat: area.lat,
                },
                {
                  label: 'East approach',
                  lon: area.lon + 0.003,
                  lat: area.lat,
                },
              ].map((p) => (
                <button
                  key={p.label}
                  onClick={() => {
                    setLon(p.lon.toFixed(5));
                    setLat(p.lat.toFixed(5));
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="report-coordinate-grid">
              <label>
                Latitude
                <input
                  aria-label="Observation latitude"
                  inputMode="decimal"
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                />
              </label>
              <label>
                Longitude
                <input
                  aria-label="Observation longitude"
                  inputMode="decimal"
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                />
              </label>
            </div>
            <small>
              Coordinates are editable. Presets are exercise locations, not
              device GPS.
            </small>
            {needsCount && (
              <label>
                People observed
                <input
                  aria-label="People observed"
                  type="number"
                  min="1"
                  max="10000"
                  value={count}
                  onChange={(e) => setCount(e.target.value)}
                  placeholder="Enter observed count"
                />
              </label>
            )}
            <label htmlFor="field-report-confidence">Confidence</label>
            <Select
              value={confidence}
              onValueChange={(v) => {
                if (v) setConfidence(String(v));
              }}
            >
              <SelectTrigger id="field-report-confidence">
                <SelectValue>{confidence}</SelectValue>
              </SelectTrigger>
              <SelectContent className="choice-menu">
                {['Low', 'Medium', 'High'].map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {(!coordinatesValid || !targetValid) && (
              <p className="report-validation">
                {!coordinatesValid
                  ? 'Choose a location within the mapped Kerr County area.'
                  : 'Select an existing feature for this update.'}
              </p>
            )}
          </>
        )}
        {step === 2 && (
          <>
            <h2>{preset.label}</h2>
            <p className="phone-report-summary">{text}</p>
            <dl className="facts-list">
              <div>
                <dt>Location</dt>
                <dd>
                  {Number(lat).toFixed(5)}, {Number(lon).toFixed(5)}
                </dd>
              </div>
              {needsCount && (
                <div>
                  <dt>People observed</dt>
                  <dd>{count}</dd>
                </div>
              )}
              <div>
                <dt>Confidence</dt>
                <dd>{confidence}</dd>
              </div>
              <div>
                <dt>Map status</dt>
                <dd>
                  {offline
                    ? 'Queued until connected'
                    : 'Reported · awaiting review'}
                </dd>
              </div>
            </dl>
            <p className="report-map-impact">
              {preset.action === 'hazard_absent'
                ? 'Replaces this predicted hazard with a “not found” report at the marked point.'
                : preset.action === 'people_not_seen'
                  ? 'Marks the observation point as checked; it does not erase potential occupants.'
                  : preset.action === 'people_evacuated'
                    ? 'Marks only this group as evacuated; other groups remain on the map.'
                    : 'Updates the selected map feature at these coordinates. A new group adds a separate marker.'}
            </p>
          </>
        )}
      </div>
      <footer>
        {step > 0 && (
          <button onClick={() => setStep(step - 1)}>
            <ArrowLeft size={16} />
            Back
          </button>
        )}
        <button
          className="primary-action"
          disabled={
            text.trim().length < 8 ||
            (step > 0 && (!coordinatesValid || !countValid || !targetValid))
          }
          onClick={() =>
            step < 2
              ? setStep(step + 1)
              : onSubmit({
                  kind: preset.kind,
                  text: text.trim(),
                  confidence,
                  observation: {
                    action: preset.action,
                    targetId,
                    lon: Number(lon),
                    lat: Number(lat),
                    ...(needsCount ? { count: Number(count) } : {}),
                  },
                })
          }
        >
          {step === 2 ? (
            <>
              <Send size={16} />
              {offline ? 'Queue report' : 'Send report'}
            </>
          ) : (
            <>
              Continue
              <ArrowRight size={16} />
            </>
          )}
        </button>
      </footer>
    </dialog>
  );
}
