'use client';
import {
  useEffect,
  useMemo,
  useReducer,
  useState,
  type CSSProperties,
} from 'react';
import {
  Activity,
  ArrowRight,
  Check,
  ChevronRight,
  ClipboardList,
  Download,
  LocateFixed,
  Map,
  MessageSquareText,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Send,
  ShieldCheck,
  Signal,
  TriangleAlert,
  WifiOff,
  X,
} from 'lucide-react';
import mock from '@/data/mock.json';
import scenario from '@/data/scenario.json';
import OperationalMap, { type HuntWater } from '@/components/operational-map';
import FieldObservationForm, {
  type ObservationDraft,
} from '@/components/field-observation-form';
import { deriveLiveMap, tacticsPresets } from '@/lib/live-map';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Slider } from '@/components/ui/slider';
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  fixtureDepth,
  objectivePresets,
  operationsReducer,
  visibleReports,
  type Operations,
  type TeamStatus,
} from '@/lib/operations';
const feetText = (value: number | null | undefined, digits = 1) =>
  value == null ? '—' : (value / 0.3048).toFixed(digits);
const cfsText = (value: number | null | undefined) =>
  value == null ? '—' : (value / (0.3048 ** 3)).toFixed(1);
const initialTime = Date.parse(mock.initialTime),
  start = Date.parse(mock.timelineStart),
  end = Date.parse(mock.timelineEnd);
const initialOperations: Operations = {
  assignments: [
    {
      teamId: mock.teams[1].id,
      sectorId: mock.sectors[1].id,
      objective: mock.sectors[1].next,
      status: 'Assigned',
      updatedAt: initialTime,
    },
  ],
  reports: [],
  queued: [],
  offline: false,
  log: [
    {
      id: 'model-start',
      time: initialTime,
      text: 'Initial probabilistic map loaded · awaiting field observations',
    },
  ],
};
function time(value: number) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: scenario.timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(value);
}
function Choice({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => {
        if (typeof v === 'string') onChange(v);
      }}
    >
      <SelectTrigger id={id} aria-label={label} className="choice">
        <SelectValue>
          {options.find((o) => o.value === value)?.label ?? value}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="choice-menu">
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
function StateTag({ value }: { value: string }) {
  return (
    <span className={`evidence-state state-${value.toLowerCase()}`}>
      <i />
      {value}
    </span>
  );
}
function download(name: string, content: string) {
  const url = URL.createObjectURL(
    new Blob([content], { type: 'application/json' }),
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export default function Home() {
  const [huntWater, setHuntWater] = useState<HuntWater | null>(null);
  const [view, setView] = useState('command'),
    [selectedId, setSelectedId] = useState(mock.sectors[0].id),
    [inspector, setInspector] = useState('evidence');
  const [detailsOpen, setDetailsOpen] = useState(false),
    [resourcesOpen, setResourcesOpen] = useState(false),
    [phoneZoom, setPhoneZoom] = useState('100');
  const [clock, setClock] = useState(initialTime),
    [playing, setPlaying] = useState(false);
  const member = 'mid',
    p = clock,
    t = clock;
  const [filter, setFilter] = useState('all'),
    [query, setQuery] = useState(''),
    [focus, setFocus] = useState(0);
  const [operations, dispatch] = useReducer(
    operationsReducer,
    initialOperations,
  );
  const [fieldTeam, setFieldTeam] = useState(mock.teams[1].id),
    [notice, setNotice] = useState(''),
    [activityOpen, setActivityOpen] = useState(false);
  const [assignTeam, setAssignTeam] = useState(''),
    [objective, setObjective] = useState('');
  const [reportOpen, setReportOpen] = useState(false);
  const [fieldTab, setFieldTab] = useState('access'),
    [fieldDetailsOpen, setFieldDetailsOpen] = useState(false),
    [hazardPage, setHazardPage] = useState(0),
    [objectivePage, setObjectivePage] = useState(0),
    [fieldMapOpen, setFieldMapOpen] = useState(false),
    [fieldMapArea, setFieldMapArea] = useState(mock.sectors[1].id),
    [fieldReportsOpen, setFieldReportsOpen] = useState(false),
    [hoveredArea, setHoveredArea] = useState<string | null>(null);
  const [plan, setPlan] = useState(''),
    [reviews, setReviews] = useState<
      Record<string, { plan: string; at: number; findings: string[] }>
    >({});
  const liveMap = useMemo(
    () => deriveLiveMap(mock.sectors, operations.reports, p, t, initialTime),
    [operations.reports, p, t],
  );
  const sectors = mock.sectors.map((s) => {
    const local = liveMap.features.filter((f) => f.sectorId === s.id);
    const people = local.filter((f) => f.category === 'people' && f.active);
    const state = local.some((f) => f.state === 'reported')
      ? 'Reported'
      : local.some((f) => f.state === 'verified')
        ? 'Confirmed'
        : 'Inferred';
    return {
      ...s,
      state,
      people: [
        people.reduce((n, f) => n + (f.count[0] ?? 0), 0),
        people.reduce((n, f) => n + (f.count[1] ?? 0), 0),
      ],
      evidence: s.evidence.map((e) => ({
        ...e,
        state: 'Inferred',
        source: 'Initial model hypothesis',
      })),
    };
  });
  const selected = sectors.find((s) => s.id === selectedId) ?? sectors[0];
  const isHunt = selected.id === 'site:demo-c04';
  // Retain the last completed forecast during forward playback, but never show
  // a future cutoff after rewinding the simulation.
  const currentHuntWater = huntWater && Date.parse(huntWater.p) <= p ? huntWater : null;
  const huntUpdating = isHunt && (!currentHuntWater || p - Date.parse(currentHuntWater.p) >= 300000);
  const huntTrend = currentHuntWater?.series.filter((point) =>
    Date.parse(point.t) >= start && Date.parse(point.t) <= end
  ) ?? [];
  const huntTrendMin = Math.min(...huntTrend.map((point) => point.wse));
  const huntTrendMax = Math.max(...huntTrend.map((point) => point.wse));
  const waterValue = isHunt ? currentHuntWater?.stage : fixtureDepth(selected.depth, t, initialTime, member);
  const waterTime = isHunt && currentHuntWater ? Date.parse(currentHuntWater.t) : t;
  const selectedFeatures = liveMap.features.filter(
    (f) => f.sectorId === selectedId,
  );
  const depth = fixtureDepth(selected.depth, t, initialTime, member);
  const fieldAssignment = operations.assignments.find(
    (a) => a.teamId === fieldTeam,
  );
  const objectivePages = useMemo(() => {
    const pages = [''];
    for (const word of (fieldAssignment?.objective ?? '').split(/\s+/)) {
      if (pages[pages.length - 1].length + word.length > 140) pages.push('');
      pages[pages.length - 1] += `${pages[pages.length - 1] ? ' ' : ''}${word}`;
    }
    return pages;
  }, [fieldAssignment?.objective]);
  const objectiveIndex = Math.min(objectivePage, objectivePages.length - 1);
  const fieldSector =
    sectors.find((s) => s.id === fieldAssignment?.sectorId) ?? selected;
  const fieldHazard = liveMap.features.find(
    (f) =>
      f.sectorId === fieldSector.id &&
      f.category === 'hazard' &&
      f.state !== 'predicted',
  );
  const fieldTeamData =
    mock.teams.find((team) => team.id === fieldTeam) ?? mock.teams[1];
  const fieldEvidenceList = [
    ...liveMap.features
      .filter((f) => f.sectorId === fieldSector.id && f.state !== 'predicted')
      .map((f) => ({
        state: f.state === 'verified' ? 'Confirmed' : 'Reported',
        label: `${f.label}${f.category === 'people' && f.active ? ` · ${f.count[1]} people` : ''}`,
        source: `${f.lat.toFixed(4)}, ${f.lon.toFixed(4)} · ${time(f.observedAt!)}`,
      })),
    ...fieldSector.evidence,
  ];
  const hazardIndex = Math.min(hazardPage, fieldEvidenceList.length - 1);
  const fieldEvidence = fieldEvidenceList[hazardIndex];
  const available = mock.teams.filter(
    (team) =>
      !operations.assignments.some(
        (a) => a.teamId === team.id && a.status !== 'Recon complete',
      ),
  );
  const filtered = sectors.filter(
    (s) =>
      (filter === 'all' || s.state === filter) &&
      (s.name + ' ' + s.code + ' ' + s.kind)
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const reports = visibleReports(operations, selected.id, p);
  const unseen = operations.reports.filter(
    (r) => r.sectorId === selected.id && r.createdAt > p,
  ).length;
  const evidenceAge = Math.max(
    0,
    selected.age + Math.floor((p - initialTime) / 60000),
  );
  const review = reviews[selected.id];
  const coverage = liveMap.coverage;
  const presets = objectivePresets(
    mock.teams.find((team) => team.id === assignTeam)?.capability ??
      selected.capability,
    selected.name,
  );
  function openDetails(tab: string) {
    const team =
      available.find((team) => team.capability === selected.capability) ??
      available[0];
    setAssignTeam(team?.id ?? '');
    setObjective(
      team
        ? objectivePresets(team.capability, selected.name)[0].text
        : selected.next,
    );
    setInspector(tab);
    setDetailsOpen(true);
  }
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () =>
        setClock((current) => {
          const next = Math.min(end, current + 60000);
          if (next === end) setPlaying(false);
          return next;
        }),
      1000,
    );
    return () => clearInterval(timer);
  }, [playing]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 7000);
    return () => clearTimeout(timer);
  }, [notice]);
  function selectArea(id: string) {
    setSelectedId(id);
    setFocus((value) => value + 1);
    setPlan('');
  }
  function confirmAssignment() {
    if (!assignTeam || !objective.trim()) return;
    dispatch({
      type: 'assign',
      id: crypto.randomUUID(),
      assignment: {
        teamId: assignTeam,
        sectorId: selected.id,
        objective: objective.trim(),
        status: 'Assigned',
        updatedAt: clock,
      },
    });
    setFieldTeam(assignTeam);
    setDetailsOpen(false);
    setNotice(
      'Assignment approved. The selected team’s Field workspace now has the objective.',
    );
  }
  function submitReport(draft: ObservationDraft) {
    dispatch({
      type: 'report',
      report: {
        id: crypto.randomUUID(),
        teamId: fieldTeam,
        sectorId: fieldSector.id,
        ...draft,
        createdAt: clock,
      },
    });
    setReportOpen(false);
    setNotice(
      operations.offline
        ? 'Report queued on this session. Resume simulated sync to share it with Command.'
        : 'Map updated with your observation. Command can review and verify it.',
    );
  }
  function reviewPlan() {
    if (plan.trim().length < 15) return;
    setReviews({
      ...reviews,
      [selected.id]: {
        plan: plan.trim(),
        at: clock,
        findings: [
          `Access constraint: ${selected.access.toLowerCase()}. Verify the approach before committing resources.`,
          `Information gap: ${selected.next}`,
          `Required capability in this fixture: ${selected.capability}. Match the assigned team and retain an alternate approach.`,
        ],
      },
    });
  }
  function exportLog() {
    download(
      'lira-simulation-decision-log.json',
      JSON.stringify(
        {
          label: 'UI MOCK — NOT AN OPERATIONAL RECORD',
          scenario_id: scenario.scenario_id,
          knowledgeCutoff: new Date(p).toISOString(),
          target: new Date(t).toISOString(),
          ...operations,
          reviews,
        },
        null,
        2,
      ),
    );
    setNotice('Simulation decision log exported.');
  }
  return (
    <main className="ops-app">
      <Tabs
        value={view}
        onValueChange={(value) => {
          setView(String(value));
          setPlaying(false);
        }}
        className="view-tabs"
      >
        <header className="app-header">
          <div className="wordmark">
            <span className="wordmark-icon">
              <Activity size={20} />
            </span>
            <strong>L.I.R.A.</strong>
            <span>DECISION SUPPORT</span>
          </div>
          <TabsList className="main-navigation" aria-label="Workspace">
            <TabsTrigger value="command">
              <Map size={16} />
              Command
            </TabsTrigger>
            <TabsTrigger value="field">
              <Radio size={16} />
              Field
            </TabsTrigger>
          </TabsList>
          <button className="quiet-button export-button" onClick={exportLog}>
            <Download size={15} />
            Export log
          </button>
        </header>
        <div className="simulation-banner">
          <ShieldCheck size={14} />
          <strong>SIMULATION</strong>
          <span>
            Exercise · predictions become field-informed as reports arrive.
            Historical USGS terrain; no emergency dispatch.
          </span>
        </div>
        <TabsContent value="command" className="command-view">
          <div className="command-grid">
            <div className="map-workspace">
              <OperationalMap
                onWater={setHuntWater}
                selected={selectedId}
                onSelect={selectArea}
                onHover={setHoveredArea}
                target={t}
                initial={initialTime}
                member={member}
                focus={focus}
                features={liveMap.features}
              />
            </div>
            <aside className="priority-panel" aria-label="Priority areas">
              <details className="priority-disclosure" open>
              <summary className="panel-title">
                <span className="priority-heading">Priority areas</span>
                <span>
                  {filtered.length} / {mock.sectors.length}
                </span>
                <ChevronRight className="priority-chevron" size={18} aria-hidden="true" />
              </summary>
              <div className="priority-content">
              <div className="queue-controls">
                <label className="sr-only" htmlFor="area-search">
                  Find area or sector
                </label>
                <input
                  id="area-search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Find area or sector…"
                />
                <Choice
                  label="Filter by evidence state"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: 'All evidence states' },
                    ...[
                      'Confirmed',
                      'Reported',
                      'Inferred',
                      'Unknown',
                      'Stale',
                    ].map((v) => ({ value: v, label: v })),
                  ]}
                />
              </div>
              <div className="priority-list">
                {filtered.length === 0 ? (
                  <div className="empty-state">
                    <p>No areas match this search.</p>
                    <button
                      className="text-button"
                      onClick={() => {
                        setQuery('');
                        setFilter('all');
                      }}
                    >
                      Clear filters
                    </button>
                  </div>
                ) : (
                  filtered.map((s) => (
                    <button
                      className={`area-row ${selectedId === s.id ? 'is-selected' : ''} ${hoveredArea === s.id ? 'is-map-hovered' : ''}`}
                      key={s.id}
                      aria-pressed={selectedId === s.id}
                      onClick={() => selectArea(s.id)}
                    >
                      <div className="area-top">
                        <span className="sector-code">{s.code}</span>
                        <strong>{s.name}</strong>
                      </div>
                      <div className="area-bottom">
                        <span
                          className={`severity severity-${s.severity.toLowerCase()}`}
                        >
                          {s.severity}
                        </span>
                        <span>
                          {s.people[1]
                            ? `${s.people[0]}–${s.people[1]} people?`
                            : 'Access / staging'}
                        </span>
                        <ChevronRight size={15} />
                      </div>
                    </button>
                  ))
                )}
              </div>
              <div className="selected-map-summary" aria-live="polite">
                <div>
                  <span>SELECTED AREA · {selected.code}</span>
                  <strong>{selected.name}</strong>
                </div>
                <div>
                  <span>
                    People ·{' '}
                    {selected.state === 'Inferred'
                      ? 'predicted'
                      : 'field-informed'}
                  </span>
                  <strong>
                    {selected.people[1]
                      ? `${selected.people[0]}–${selected.people[1]}`
                      : 'No estimate'}
                  </strong>
                </div>
                <div>
                  <span>{isHunt ? 'Water stage' : 'Water depth'} · {time(waterTime)}</span>
                  <strong>{feetText(waterValue)} ft</strong>
                </div>
                <div className="coverage-summary" aria-live="polite">
                  <div>
                    <strong>{coverage.verified}% verified</strong>
                    <span>
                      {coverage.reported}% reported · {coverage.modeled}%
                      predicted
                    </span>
                  </div>
                  <Progress
                    className="coverage-bar"
                    style={
                      {
                        '--verified-share': `${coverage.verified + coverage.reported ? (100 * coverage.verified) / (coverage.verified + coverage.reported) : 0}%`,
                      } as CSSProperties
                    }
                    value={coverage.verified + coverage.reported}
                    aria-label={`${coverage.verified}% verified, ${coverage.reported}% reported, ${coverage.modeled}% predicted map features`}
                  />
                  <small>
                    {coverage.verifiedCount + coverage.reportedCount}/
                    {coverage.total} map features field-informed
                  </small>
                  <small>
                    {coverage.reportedCount} map update(s) awaiting review
                  </small>
                </div>
              </div>
              <div className="side-tools">
                <p className="workflow-summary">
                  Review observations and access, check a plan, then assign a
                  team.
                </p>
                <button
                  className="action-button primary-action"
                  onClick={() => openDetails('evidence')}
                >
                  <ClipboardList size={16} />
                  Review & assign
                  <ArrowRight size={16} />
                </button>
                <div className="side-utilities">
                  <button onClick={() => setResourcesOpen(true)}>
                    Teams · {available.length} available
                  </button>
                  <button onClick={() => setActivityOpen(true)}>
                    Activity · {operations.log.length}
                  </button>
                </div>
              </div>
              </div>
              </details>
            </aside>
          </div>
          <footer className="time-panel">
            <div className="time-controls">
              <div className="clock-controls">
                <button
                  className="icon-button"
                  aria-label={
                    playing
                      ? 'Pause timeline'
                      : 'Play timeline at 60 times speed'
                  }
                  onClick={() => setPlaying((v) => !v)}
                  disabled={clock === end}
                >
                  {playing ? <Pause size={17} /> : <Play size={17} />}
                </button>
                <button
                  className="icon-button"
                  aria-label="Reset timeline"
                  onClick={() => {
                    setClock(initialTime);
                    setPlaying(false);
                  }}
                >
                  <RefreshCw size={16} />
                </button>
                <strong>
                  {time(clock)} <small>CDT</small>
                </strong>
                <span className="muted">
                  {playing ? '60× replay' : 'Paused'}
                </span>
              </div>
              <span className="time-context">
                Scenario replay · <b>{time(clock)} CDT</b> · water estimates are
                simulated
              </span>
            </div>
            <div className="timeline-water">
              <span title={isHunt && currentHuntWater ? `Forecast issued ${time(Date.parse(currentHuntWater.p))} CDT` : undefined}>{selected.code} · {isHunt ? `water elevation · NAVD88${huntUpdating ? ' · updating' : ''}` : 'modeled water-depth trend'}</span>
              <div className="water-trend">
                {isHunt ? huntTrend.map((point) => (
                  <i
                    key={point.t}
                    title={`${time(Date.parse(point.t))} · ${feetText(point.wse, 2)} ft NAVD88`}
                    style={{
                      height: `${4 + 22 * (point.wse - huntTrendMin) / Math.max(huntTrendMax - huntTrendMin, 0.01)}px`,
                      opacity: Date.parse(point.t) <= clock ? 1 : 0.4,
                    }}
                  />
                )) : Array.from({ length: 37 }, (_, i) => {
                  const value = fixtureDepth(
                    selected.depth,
                    start + i * 600000,
                    initialTime,
                    member,
                  );
                  return (
                    <i
                      key={i}
                      title={`${time(start + i * 600000)} · ${feetText(value)} ft`}
                      style={{
                        height: `${4 + value * 9}px`,
                        opacity: start + i * 600000 <= clock ? 1 : 0.4,
                      }}
                    />
                  );
                })}
              </div>
              <span>
                {feetText(isHunt ? huntTrend[0]?.wse : fixtureDepth(
                  selected.depth,
                  start,
                  initialTime,
                  member,
                ))}{' '}
                →{' '}
                {feetText(isHunt ? huntTrend.at(-1)?.wse : fixtureDepth(selected.depth, end, initialTime, member))}{' '}
                ft
              </span>
            </div>
            <div className="timeline-track">
              <Slider
                value={[(clock - start) / 60000]}
                min={0}
                max={(end - start) / 60000}
                step={5}
                aria-label="Scenario timeline in minutes"
                onValueChange={(v) => {
                  setClock(start + (Array.isArray(v) ? v[0] : v) * 60000);
                  setPlaying(false);
                }}
              />
              <div className="time-labels">
                {Array.from({ length: 7 }, (_, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setClock(start + i * 3600000);
                      setPlaying(false);
                    }}
                  >
                    {time(start + i * 3600000)}
                  </button>
                ))}
              </div>
            </div>
            <div className="time-note">
              UTC stored internally · Central time displayed · estimates change
              illustratively with time; no forecasting engine is connected.
            </div>
          </footer>
        </TabsContent>
        <TabsContent value="field" className="field-view">
          <div className="phone-demo-toolbar">
            <div>
              <strong>Field workspace</strong>
              <span>390 × 844 · phone viewport</span>
            </div>
            <Choice
              label="Phone preview zoom"
              value={phoneZoom}
              onChange={setPhoneZoom}
              options={['75', '100', '125', '150'].map((z) => ({
                value: z,
                label: `${z}% zoom`,
              }))}
            />
          </div>
          <div className="phone-stage">
            <div
              className="phone-frame"
              style={{ zoom: Number(phoneZoom) / 100 }}
            >
              <div className="phone-status">
                <strong>L.I.R.A. / FIELD</strong>
                <span>{time(clock)} CDT · Exercise</span>
              </div>
              <div
                className="phone-screen"
                inert={fieldMapOpen || fieldDetailsOpen || reportOpen}
              >
                <div className="phone-incident">
                  <strong>{mock.incidentName}</strong>
                  <span>{mock.areaLabel} · Local exercise</span>
                </div>
                <div className="field-toolbar">
                  <div>
                    <span className="overline">ACTIVE TEAM</span>
                    <Choice
                      label="Field team"
                      value={fieldTeam}
                      onChange={(value) => {
                        setFieldTeam(value);
                        setHazardPage(0);
                        setObjectivePage(0);
                      }}
                      options={mock.teams.map((team) => ({
                        value: team.id,
                        label: team.name,
                      }))}
                    />
                  </div>
                  <div className="field-sync">
                    <span>
                      {operations.offline ? (
                        <WifiOff size={16} />
                      ) : (
                        <Signal size={16} />
                      )}{' '}
                      {operations.offline
                        ? 'Offline · reports queued locally'
                        : 'Simulated sync active'}
                      <b>{operations.queued.length} queued</b>
                    </span>
                    <button
                      className="quiet-button"
                      onClick={() => {
                        dispatch({
                          type: 'connectivity',
                          offline: !operations.offline,
                          time: clock,
                          id: crypto.randomUUID(),
                        });
                        setNotice(
                          operations.offline
                            ? 'Simulated sync restored. Queued reports are now visible in Command.'
                            : 'Offline simulation enabled. New reports will remain queued in this session.',
                        );
                      }}
                    >
                      {operations.offline
                        ? 'Resume simulated sync'
                        : 'Simulate offline'}
                    </button>
                  </div>
                </div>
                {fieldAssignment ? (
                  <Tabs
                    value={fieldTab}
                    onValueChange={(v) => setFieldTab(String(v))}
                    className="field-task-tabs"
                  >
                    <TabsList className="field-task-navigation">
                      <TabsTrigger value="access">
                        Approach & hazards
                      </TabsTrigger>
                      <TabsTrigger value="assignment">
                        Current assignment
                      </TabsTrigger>
                    </TabsList>
                    <TabsContent value="assignment" className="mission-panel">
                      <div className="panel-title">
                        <h2>Current assignment</h2>
                        <span className="mission-status">
                          {fieldAssignment.status}
                        </span>
                      </div>
                      <div className="mission-body">
                        <div className="overline">
                          SECTOR {fieldSector.code} / {fieldSector.kind}
                        </div>
                        <h2>{fieldSector.name}</h2>
                        <p className="mission-objective">
                          {objectivePages[objectiveIndex]}
                        </p>
                        {objectivePages.length > 1 && (
                          <div className="objective-page-controls hazard-page-controls">
                            <button
                              disabled={objectiveIndex === 0}
                              onClick={() =>
                                setObjectivePage(objectiveIndex - 1)
                              }
                            >
                              Previous
                            </button>
                            <span>
                              {objectiveIndex + 1} / {objectivePages.length}
                            </span>
                            <button
                              disabled={
                                objectiveIndex === objectivePages.length - 1
                              }
                              onClick={() =>
                                setObjectivePage(objectiveIndex + 1)
                              }
                            >
                              Next
                            </button>
                          </div>
                        )}
                        <button
                          className="text-button team-details"
                          onClick={() => setFieldDetailsOpen(true)}
                        >
                          Team & assignment details
                        </button>
                        <div className="field-estimate">
                          <StateTag value={fieldSector.state} />
                          <strong>
                            {fieldSector.people[1]
                              ? `${fieldSector.people[0]}–${fieldSector.people[1]} people estimated`
                              : 'Access verification task'}
                          </strong>
                          <p>Simulated estimate · verify on arrival</p>
                        </div>
                      </div>
                      <div className="status-block">
                        <h3>Update team status</h3>
                        <p>
                          Updates are shared with Command in this local
                          exercise.
                        </p>
                        <div className="status-buttons">
                          {(
                            [
                              'En route',
                              'On scene',
                              'Recon complete',
                              'Unable to proceed',
                            ] as TeamStatus[]
                          ).map((status) => (
                            <button
                              key={status}
                              aria-pressed={fieldAssignment.status === status}
                              className={
                                status === 'Unable to proceed'
                                  ? 'unable-button'
                                  : ''
                              }
                              onClick={() => {
                                dispatch({
                                  type: 'status',
                                  teamId: fieldTeam,
                                  status,
                                  time: clock,
                                  id: crypto.randomUUID(),
                                });
                                setNotice(
                                  `Team status updated to “${status}” in Command.`,
                                );
                              }}
                            >
                              {fieldAssignment.status === status && (
                                <Check size={16} />
                              )}{' '}
                              {status}
                            </button>
                          ))}
                        </div>
                      </div>
                    </TabsContent>
                    <TabsContent value="access" className="field-access">
                      <div className="panel-title">
                        <h2>Approach & hazards</h2>
                        <TriangleAlert size={17} />
                      </div>
                      <div
                        className={`field-hazard-banner severity-${fieldSector.severity.toLowerCase()}`}
                      >
                        <TriangleAlert size={22} />
                        <div>
                          <span>
                            {fieldHazard
                              ? `${fieldHazard.state} observation`
                              : `${fieldSector.severity} · predicted`}
                          </span>
                          <strong>
                            {fieldHazard?.label ?? fieldSector.access}
                          </strong>
                          <small>
                            {fieldSector.code} · {fieldSector.name}
                          </small>
                        </div>
                      </div>
                      <div className="field-section">
                        <div className="route-step">
                          <span>01</span>
                          <div>
                            <strong>Proposed approach</strong>
                            <p>{fieldSector.route}</p>
                            <small>
                              {fieldSector.travel} min · planning estimate, not
                              navigation
                            </small>
                          </div>
                        </div>
                        <div className="route-step">
                          <span>02</span>
                          <div>
                            <strong>Alternate</strong>
                            <p>{fieldSector.alternative}</p>
                          </div>
                        </div>
                      </div>
                      <div className="field-section field-hazard-pages">
                        <div className="hazard-page-heading">
                          <h3>Hazards & observations</h3>
                          <span>
                            {hazardIndex + 1} / {fieldEvidenceList.length}
                          </span>
                        </div>
                        <article className="evidence-item" aria-live="polite">
                          <StateTag value={fieldEvidence.state} />
                          <p>{fieldEvidence.label}</p>
                          <small>{fieldEvidence.source}</small>
                        </article>
                        <div className="hazard-page-controls">
                          <button
                            disabled={hazardIndex === 0}
                            onClick={() => setHazardPage(hazardIndex - 1)}
                          >
                            Previous
                          </button>
                          <button
                            disabled={
                              hazardIndex === fieldEvidenceList.length - 1
                            }
                            onClick={() => setHazardPage(hazardIndex + 1)}
                          >
                            Next observation <ChevronRight size={16} />
                          </button>
                        </div>
                      </div>
                    </TabsContent>
                  </Tabs>
                ) : (
                  <div className="unassigned-state">
                    <ClipboardList size={32} />
                    <h2>No active assignment for {fieldTeamData.name}</h2>
                    <p>
                      Select a team with an assignment, or assign this team from
                      Command.
                    </p>
                    <span className="muted">
                      Waiting for an assignment from Command.
                    </span>
                  </div>
                )}
                {fieldAssignment && (
                  <div className="phone-actions">
                    {' '}
                    <div className="field-primary-actions">
                      <button
                        className="action-button primary-action"
                        onClick={() => {
                          setReportOpen(true);
                        }}
                      >
                        <Send size={17} />
                        Report observation
                      </button>
                      <button
                        className="action-button"
                        onClick={() => {
                          setFieldMapArea(fieldSector.id);
                          setFieldMapOpen(true);
                        }}
                      >
                        <LocateFixed size={17} />
                        Latest area map
                      </button>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => setFieldReportsOpen(true)}
                    >
                      Team reports ·{' '}
                      {
                        [...operations.reports, ...operations.queued].filter(
                          (r) => r.teamId === fieldTeam,
                        ).length
                      }
                    </button>
                  </div>
                )}
              </div>
              {reportOpen && (
                <FieldObservationForm
                  area={fieldSector}
                  features={liveMap.features}
                  offline={operations.offline}
                  onClose={() => setReportOpen(false)}
                  onSubmit={submitReport}
                />
              )}
              {fieldDetailsOpen && fieldAssignment && (
                <dialog
                  open
                  className="phone-map-overlay phone-detail-overlay"
                  aria-label="Team and assignment details"
                >
                  <header>
                    <strong>Team & assignment</strong>
                    <button
                      aria-label="Close team details"
                      onClick={() => setFieldDetailsOpen(false)}
                    >
                      <X size={18} />
                    </button>
                  </header>
                  <dl className="facts-list">
                    <div>
                      <dt>Assigned team</dt>
                      <dd>{fieldTeamData.name}</dd>
                    </div>
                    <div>
                      <dt>Capability / personnel</dt>
                      <dd>
                        {fieldTeamData.capability} / {fieldTeamData.people}
                      </dd>
                    </div>
                    <div>
                      <dt>Last status update</dt>
                      <dd>{time(fieldAssignment.updatedAt)} CDT</dd>
                    </div>
                    <div>
                      <dt>Command channel</dt>
                      <dd>Exercise only · no radio link</dd>
                    </div>
                    <div>
                      <dt>Estimate limitations</dt>
                      <dd>{fieldSector.uncertainty}</dd>
                    </div>
                  </dl>
                </dialog>
              )}
              {fieldMapOpen && (
                <dialog
                  open
                  className="phone-map-overlay"
                  aria-label="Latest area map"
                >
                  <header>
                    <div>
                      <strong>Latest area map</strong>
                      <span>{time(clock)} CDT · read-only field copy</span>
                    </div>
                    <button
                      aria-label="Close latest area map"
                      onClick={() => setFieldMapOpen(false)}
                    >
                      <X size={18} />
                    </button>
                  </header>
                  <OperationalMap
                    onWater={setHuntWater}
                    selected={fieldMapArea}
                    onSelect={setFieldMapArea}
                    features={liveMap.features}
                    target={clock}
                    initial={initialTime}
                    member="mid"
                    focus={1}
                    fieldCopy
                  />
                  <footer>
                    {operations.offline
                      ? 'Offline exercise snapshot'
                      : 'Latest shared exercise state'}
                    . Tap an area to inspect its map footprint.
                  </footer>
                </dialog>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
      {notice && (
        <output className="notice">
          <Check size={17} />
          <span>{notice}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice('')}
          >
            <X size={16} />
          </button>
        </output>
      )}
      <Dialog open={fieldReportsOpen} onOpenChange={setFieldReportsOpen}>
        <DialogContent className="ops-dialog">
          <DialogHeader>
            <DialogTitle>Team reports</DialogTitle>
            <DialogDescription>
              {fieldTeamData.name} · this exercise session
            </DialogDescription>
          </DialogHeader>{' '}
          <section className="field-report-feed">
            <div className="panel-title">
              <h2>Team reports</h2>
              <span>
                {operations.reports.filter((r) => r.teamId === fieldTeam)
                  .length +
                  operations.queued.filter((r) => r.teamId === fieldTeam)
                    .length}
              </span>
            </div>
            <div className="field-section">
              {[...operations.queued, ...operations.reports].filter(
                (r) => r.teamId === fieldTeam,
              ).length === 0 ? (
                <div className="empty-state">
                  <MessageSquareText size={24} />
                  <h3>No observations submitted</h3>
                  <p>
                    Report access, hazards, assistance needs, or search
                    progress. New reports appear in Command’s evidence chain.
                  </p>
                </div>
              ) : (
                [...operations.queued, ...operations.reports]
                  .filter((r) => r.teamId === fieldTeam)
                  .map((r) => (
                    <article key={r.id} className="evidence-item">
                      <div className="section-heading">
                        <strong>{r.kind}</strong>
                        <span>{time(r.createdAt)}</span>
                      </div>
                      <p>{r.text}</p>
                      <small>
                        {operations.queued.some((q) => q.id === r.id)
                          ? 'Queued · not received by Command'
                          : r.verifiedAt !== undefined
                            ? 'Verified by Command · exercise'
                            : 'Received by Command · awaiting verification'}
                      </small>
                    </article>
                  ))
              )}
            </div>
            <div className="field-note">
              <ShieldCheck size={17} />
              <p>
                Session-only prototype. Queued reports are not an offline backup
                and are lost on reload.
              </p>
            </div>
          </section>
        </DialogContent>
      </Dialog>
      <Dialog open={resourcesOpen} onOpenChange={setResourcesOpen}>
        <DialogContent className="ops-dialog resource-dialog">
          <DialogHeader>
            <DialogTitle>Resources & team status</DialogTitle>
            <DialogDescription>
              Select a team to read its current assignment and status.
            </DialogDescription>
          </DialogHeader>
          <section className="operations-bar" aria-label="Team status">
            <div>
              <span className="overline">RESOURCES</span>
              <strong>
                {mock.teams.length} teams / {operations.assignments.length}{' '}
                assigned
              </strong>
            </div>
            <div className="team-strip">
              {mock.teams.map((team) => {
                const assignment = operations.assignments.find(
                  (a) => a.teamId === team.id,
                );
                return (
                  <button
                    key={team.id}
                    onClick={() => {
                      const sector = mock.sectors.find(
                        (s) => s.id === assignment?.sectorId,
                      );
                      setNotice(
                        sector
                          ? `${team.name}: ${assignment?.status} at ${sector.code}. ${assignment?.objective}`
                          : `${team.name}: available · ${team.capability}`,
                      );
                    }}
                    title={`View ${team.name} status`}
                  >
                    <span>
                      <i
                        className={assignment ? 'busy-dot' : 'available-dot'}
                      />
                      {team.name}
                    </span>
                    <small>
                      {assignment
                        ? `${mock.sectors.find((s) => s.id === assignment.sectorId)?.code} · ${assignment.status}`
                        : 'Available'}
                      <ChevronRight size={12} />
                    </small>
                  </button>
                );
              })}
            </div>
            <button
              className="quiet-button changes-button"
              onClick={() => setActivityOpen(true)}
            >
              <ClipboardList size={16} />
              Changes <span>{operations.log.length}</span>
            </button>
          </section>
        </DialogContent>
      </Dialog>
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="ops-dialog area-dialog">
          <DialogHeader>
            <DialogTitle>Review & assign · {selected.code}</DialogTitle>
            <DialogDescription>
              {selected.name} · verify observations, assess access, and assign
              in one workspace.
            </DialogDescription>
          </DialogHeader>
          <aside
            className="inspection-panel"
            aria-label="Selected area details"
          >
            <div className="inspection-heading">
              <div className="area-top">
                <span className="overline">AREA {selected.code}</span>
                <button
                  className="icon-button"
                  aria-label="Locate selected area on map"
                  title="Locate on map"
                  onClick={() => setFocus((f) => f + 1)}
                >
                  <LocateFixed size={17} />
                </button>
              </div>
              <h2>{selected.name}</h2>
              <div className="area-state">
                <StateTag value={selected.state} />
                <span>{selected.kind}</span>
              </div>
            </div>
            <div className="inspection-metrics">
              <div>
                <span>People estimated</span>
                <strong>
                  {selected.people[1]
                    ? `${selected.people[0]}–${selected.people[1]}`
                    : '—'}
                </strong>
                <small>
                  {selected.people[1]
                    ? 'Not a confirmed count'
                    : 'No occupancy estimate'}
                </small>
              </div>
              <div>
                <span>{isHunt ? 'Modeled water stage' : 'Depth estimate'}</span>
                <strong>
                  {feetText(waterValue)} <em>ft</em>
                </strong>
                <small title={isHunt ? `Hunt gauge 08165500; reach stage, not ground-level depth. Discharge ${cfsText(currentHuntWater?.discharge)} cfs; rise ${feetText(currentHuntWater?.rise, 2)} ft/h.` : undefined}>
                  {time(waterTime)} · {isHunt ? 'Hunt forecast' : `${member} scenario`}
                </small>
              </div>
            </div>
            <Tabs
              value={inspector}
              onValueChange={(v) => setInspector(String(v))}
              className="inspector-tabs"
            >
              <TabsList className="detail-navigation">
                <TabsTrigger value="evidence">Evidence</TabsTrigger>
                <TabsTrigger value="access">Access</TabsTrigger>
                <TabsTrigger value="critique">Plan review</TabsTrigger>
                <TabsTrigger value="assign">Assign team</TabsTrigger>
              </TabsList>
              <TabsContent value="evidence" className="detail-content">
                <section>
                  <h3>Reason for priority</h3>
                  <p>{selected.rationale}</p>
                </section>
                <section className="next-check">
                  <h3>Next verification</h3>
                  <p>{selected.next}</p>
                </section>
                <section>
                  <div className="section-heading">
                    <h3>Evidence chain</h3>
                    <span>{evidenceAge} min age</span>
                  </div>
                  {reports.map((r) => (
                    <article key={r.id} className="evidence-item new-report">
                      <StateTag
                        value={
                          r.verifiedAt !== undefined && r.verifiedAt <= p
                            ? 'Confirmed'
                            : 'Reported'
                        }
                      />
                      <p>{r.text}</p>
                      <small>
                        {mock.teams.find((team) => team.id === r.teamId)?.name}{' '}
                        · {time(r.createdAt)} · {r.confidence} confidence
                      </small>
                      <small>
                        {r.verifiedAt !== undefined && r.verifiedAt <= p
                          ? 'Commander verified · exercise only'
                          : 'Awaiting commander verification'}
                      </small>
                      {!(r.verifiedAt !== undefined && r.verifiedAt <= p) && (
                        <button
                          className="action-button"
                          disabled={r.verifiedAt !== undefined}
                          onClick={() => {
                            dispatch({
                              type: 'verify',
                              reportId: r.id,
                              time: clock,
                              id: crypto.randomUUID(),
                            });
                            setNotice(
                              'Observation verified. The map marker and evidence coverage are updated.',
                            );
                          }}
                        >
                          <ShieldCheck size={15} />
                          Verify observation
                        </button>
                      )}
                    </article>
                  ))}
                  {selected.evidence.map((e, i) => (
                    <article className="evidence-item" key={i}>
                      <StateTag value={e.state} />
                      <p>{e.label}</p>
                      <small>
                        {e.source} ·{' '}
                        {e.age
                          ? `${Math.max(0, e.age + Math.floor((p - initialTime) / 60000))} min old`
                          : 'Not verified'}
                      </small>
                    </article>
                  ))}
                  {unseen > 0 && (
                    <p className="info-note">
                      {unseen} newer report(s) excluded by the selected
                      knowledge cutoff.
                    </p>
                  )}
                </section>
                <p className="caution-note">
                  <TriangleAlert size={15} />
                  {selected.uncertainty}
                </p>
              </TabsContent>
              <TabsContent value="access" className="detail-content">
                <section>
                  <h3>Access assessment</h3>
                  <div className="access-status">
                    <TriangleAlert size={16} />
                    {selected.access}
                  </div>
                  <dl className="facts-list">
                    <div>
                      <dt>Capability needed</dt>
                      <dd>{selected.capability}</dd>
                    </div>
                    <div>
                      <dt>Travel estimate</dt>
                      <dd>{selected.travel} min · illustrative</dd>
                    </div>
                    <div>
                      <dt>Confidence</dt>
                      <dd>{selected.confidence}</dd>
                    </div>
                  </dl>
                </section>
                <section>
                  <h3>Proposed approach</h3>
                  <p>{selected.route}</p>
                  <span className="route-flag">
                    Route geometry not verified
                  </span>
                </section>
                <section>
                  <h3>Alternate approach</h3>
                  <p>{selected.alternative}</p>
                </section>
                <p className="caution-note">
                  <TriangleAlert size={15} />
                  Access estimates are not a safe-route guarantee. Check local
                  conditions before any movement.
                </p>
              </TabsContent>
              <TabsContent value="critique" className="detail-content">
                <section>
                  <h3>Stress-test a proposed plan</h3>
                  <p className="muted">
                    Illustrative, rule-based review against this area’s mock
                    facts. No AI or historical corpus is connected.
                  </p>
                  <label className="form-label" htmlFor="plan">
                    Proposed tactics
                  </label>
                  <div className="tactics-presets">
                    {tacticsPresets(selected.name, selectedFeatures).map(
                      (prompt) => (
                        <button
                          key={prompt.label}
                          aria-pressed={plan === prompt.text}
                          onClick={() => setPlan(prompt.text)}
                        >
                          {prompt.label}
                        </button>
                      ),
                    )}
                  </div>
                  <textarea
                    id="plan"
                    value={plan}
                    onChange={(e) => setPlan(e.target.value)}
                    placeholder="Describe the approach, team capability, and contingency…"
                    rows={4}
                  />
                  <button
                    className="action-button"
                    disabled={plan.trim().length < 15}
                    onClick={reviewPlan}
                  >
                    Review against area facts <ArrowRight size={15} />
                  </button>
                </section>
                {review && (
                  <section className="review-result">
                    <h3>Illustrative review · {time(review.at)}</h3>
                    <p className="submitted-plan">{review.plan}</p>
                    {review.findings.map((finding, i) => (
                      <article key={i}>
                        <p>{finding}</p>
                        <button
                          className="source-ref"
                          onClick={() => setInspector('evidence')}
                        >
                          Source: {selected.id} <ChevronRight size={12} />
                        </button>
                      </article>
                    ))}
                  </section>
                )}
              </TabsContent>
              <TabsContent value="assign" className="assignment-content">
                <div className="assignment-context">
                  <h3>Assignment brief · {selected.code}</h3>
                  <p>{selected.next}</p>
                  <div className="access-status">{selected.access}</div>
                  <p>{selected.route}</p>
                  <small>
                    {reports.filter((r) => r.verifiedAt === undefined).length}{' '}
                    field observations awaiting verification
                  </small>
                  <button
                    className="text-button"
                    onClick={() => setInspector('evidence')}
                  >
                    Review evidence
                  </button>
                </div>
                <div className="assignment-form">
                  <label className="form-label" htmlFor="assign-team">
                    Available team
                  </label>
                  <Choice
                    id="assign-team"
                    label="Team to assign"
                    value={assignTeam}
                    onChange={(id) => {
                      setAssignTeam(id);
                      const capability =
                        mock.teams.find((team) => team.id === id)?.capability ??
                        '';
                      setObjective(
                        objectivePresets(capability, selected.name)[0].text,
                      );
                    }}
                    options={available.map((team) => ({
                      value: team.id,
                      label: `${team.name} · ${team.capability}`,
                    }))}
                  />
                  <p className="info-note">
                    Suggested capability: {selected.capability}. The commander
                    must assess the fit.
                  </p>
                  <label className="form-label" htmlFor="objective">
                    Assignment objective
                  </label>
                  <div className="objective-presets">
                    <span className="muted">
                      Suggested for{' '}
                      {mock.teams.find((team) => team.id === assignTeam)
                        ?.capability ?? 'selected team'}
                    </span>
                    {presets.map((prompt) => (
                      <button
                        key={prompt.label}
                        className="action-button"
                        aria-pressed={objective === prompt.text}
                        onClick={() => setObjective(prompt.text)}
                      >
                        {prompt.label}
                        <ArrowRight size={14} />
                      </button>
                    ))}
                  </div>
                  <textarea
                    id="objective"
                    rows={4}
                    value={objective}
                    onChange={(e) => setObjective(e.target.value)}
                  />
                  <div className="dialog-actions">
                    <button
                      className="action-button"
                      onClick={() => setDetailsOpen(false)}
                    >
                      Close review
                    </button>
                    <button
                      className="action-button primary-action"
                      disabled={!assignTeam || !objective.trim()}
                      onClick={confirmAssignment}
                    >
                      Approve assignment
                    </button>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
            <div className="inspection-actions workflow-footer">
              <span>Area {selected.code} · simulation only</span>
              {inspector !== 'assign' && (
                <button
                  className="action-button primary-action"
                  onClick={() => setInspector('assign')}
                >
                  Continue to assignment
                  <ArrowRight size={15} />
                </button>
              )}
            </div>
          </aside>
        </DialogContent>
      </Dialog>
      <Dialog open={activityOpen} onOpenChange={setActivityOpen}>
        <DialogContent className="ops-dialog wide-dialog">
          <DialogHeader>
            <DialogTitle>Changes & decision log</DialogTitle>
            <DialogDescription>
              Session activity and initial scenario events. All entries are
              simulated.
            </DialogDescription>
          </DialogHeader>
          <div className="activity-scroll">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time · CDT</TableHead>
                  <TableHead>Change</TableHead>
                  <TableHead>Area</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {operations.log.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>{time(entry.time)}</TableCell>
                    <TableCell>{entry.text}</TableCell>
                    <TableCell>
                      {entry.sectorId ? (
                        <button
                          className="text-button"
                          onClick={() => {
                            selectArea(entry.sectorId!);
                            setActivityOpen(false);
                            setView('command');
                          }}
                        >
                          {
                            mock.sectors.find((s) => s.id === entry.sectorId)
                              ?.code
                          }
                        </button>
                      ) : (
                        '—'
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <button className="action-button" onClick={exportLog}>
            <Download size={16} />
            Export full simulation log
          </button>
        </DialogContent>
      </Dialog>
    </main>
  );
}
