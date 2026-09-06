'use client';
import { useEffect, useReducer, useState } from 'react';
import {
  Activity,
  ArrowLeft,
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
  Users,
  WifiOff,
  X,
} from 'lucide-react';
import mock from '@/data/mock.json';
import scenario from '@/data/scenario.json';
import OperationalMap from '@/components/operational-map';
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
  deriveTimes,
  fixtureDepth,
  evidenceCoverage,
  objectivePresets,
  operationsReducer,
  visibleReports,
  type Operations,
  type TeamStatus,
} from '@/lib/operations';
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
  log: mock.changes.map((entry, i) => ({
    id: `seed-${i}`,
    time: initialTime - (i + 1) * 240000,
    text: entry.text,
  })),
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
  const [view, setView] = useState('command'),
    [selectedId, setSelectedId] = useState(mock.sectors[0].id),
    [inspector, setInspector] = useState('evidence');
  const [detailsOpen, setDetailsOpen] = useState(false),
    [resourcesOpen, setResourcesOpen] = useState(false),
    [phoneZoom, setPhoneZoom] = useState('100');
  const [clock, setClock] = useState(initialTime),
    [playing, setPlaying] = useState(false),
    [projection, setProjection] = useState('nowcast'),
    [minutes, setMinutes] = useState('60'),
    [member, setMember] = useState('mid');
  const [filter, setFilter] = useState('all'),
    [query, setQuery] = useState(''),
    [focus, setFocus] = useState(0),
    [mode3d, setMode3d] = useState(false);
  const [operations, dispatch] = useReducer(
    operationsReducer,
    initialOperations,
  );
  const [fieldTeam, setFieldTeam] = useState(mock.teams[1].id),
    [notice, setNotice] = useState(''),
    [activityOpen, setActivityOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false),
    [assignTeam, setAssignTeam] = useState(''),
    [objective, setObjective] = useState('');
  const [reportOpen, setReportOpen] = useState(false),
    [reportStage, setReportStage] = useState('edit'),
    [reportType, setReportType] = useState('Access'),
    [reportText, setReportText] = useState(''),
    [reportConfidence, setReportConfidence] = useState('Medium');
  const [plan, setPlan] = useState(''),
    [reviews, setReviews] = useState<
      Record<string, { plan: string; at: number; findings: string[] }>
    >({});
  const selected =
    mock.sectors.find((s) => s.id === selectedId) ?? mock.sectors[0];
  const { p, t, horizon } = deriveTimes(
    clock,
    projection,
    Number(minutes),
    start,
    end,
  );
  const depth = fixtureDepth(selected.depth, t, initialTime, member);
  const fieldAssignment = operations.assignments.find(
    (a) => a.teamId === fieldTeam,
  );
  const fieldSector =
    mock.sectors.find((s) => s.id === fieldAssignment?.sectorId) ?? selected;
  const fieldTeamData =
    mock.teams.find((team) => team.id === fieldTeam) ?? mock.teams[1];
  const available = mock.teams.filter(
    (team) =>
      !operations.assignments.some(
        (a) => a.teamId === team.id && a.status !== 'Recon complete',
      ),
  );
  const filtered = mock.sectors.filter(
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
  const coverage = evidenceCoverage(
    operations,
    selected.id,
    p,
    selected.evidence,
  );
  const presets = objectivePresets(
    mock.teams.find((team) => team.id === assignTeam)?.capability ??
      selected.capability,
    selected.name,
  );
  function openDetails(tab: string) {
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
    setPlan('');
  }
  function openAssign() {
    setAssignTeam(
      available.find((team) => team.capability === selected.capability)?.id ??
        available[0]?.id ??
        '',
    );
    setObjective(selected.next);
    setAssignOpen(true);
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
    setAssignOpen(false);
    setNotice('Assignment recorded. Open Field to view this team’s mission.');
  }
  function submitReport() {
    dispatch({
      type: 'report',
      report: {
        id: crypto.randomUUID(),
        teamId: fieldTeam,
        sectorId: fieldSector.id,
        kind: reportType,
        text: reportText.trim(),
        confidence: reportConfidence,
        createdAt: clock,
      },
    });
    setReportOpen(false);
    setReportText('');
    setReportStage('edit');
    setNotice(
      operations.offline
        ? 'Report queued on this session. Resume simulated sync to share it with Command.'
        : 'Report received by Command as reported evidence; verification is still required.',
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
      'flood-simulation-decision-log.json',
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
            <strong>FLOOD</strong>
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
            All flood estimates, people counts, teams, and reports are mock
            data. No operational services connected.
          </span>
        </div>
        <TabsContent value="command" className="command-view">
          <div className="command-grid">
            <div className="map-workspace">
              <div className="map-incident">
                <div>
                  <span className="overline">
                    INCIDENT COMMAND / {mock.areaLabel}
                  </span>
                  <h1>{mock.incidentName}</h1>
                </div>
                <span>
                  <Signal size={14} />
                  {operations.offline
                    ? 'Offline simulation'
                    : 'Exercise channel active'}
                </span>
              </div>
              <OperationalMap
                selected={selectedId}
                onSelect={selectArea}
                target={t}
                initial={initialTime}
                member={member}
                focus={focus}
                mode3d={mode3d}
                setMode3d={setMode3d}
                confirmedHazards={operations.reports
                  .filter(
                    (r) =>
                      r.kind === 'Hazard' &&
                      r.verifiedAt !== undefined &&
                      r.verifiedAt <= p,
                  )
                  .map((r) => r.sectorId)}
              />
              <div className="selected-map-summary" aria-live="polite">
                <div>
                  <span>SELECTED AREA · {selected.code}</span>
                  <strong>{selected.name}</strong>
                </div>
                <div>
                  <span>People estimated</span>
                  <strong>
                    {selected.people[1]
                      ? `${selected.people[0]}–${selected.people[1]}`
                      : 'No estimate'}
                  </strong>
                </div>
                <div>
                  <span>Water depth · {time(t)}</span>
                  <strong>{depth.toFixed(1)} m</strong>
                </div>
                <div className="coverage-summary" aria-live="polite">
                  <div>
                    <strong>{coverage.verified}% verified</strong>
                    <span>{coverage.modeled}% modeled / unverified</span>
                  </div>
                  <Progress
                    className="coverage-bar"
                    value={coverage.verified}
                    aria-label="Verified share of exercise evidence records"
                  />
                  <small>
                    Exercise evidence · {coverage.confirmed}/{coverage.total}{' '}
                    records verified · live data 0%
                  </small>
                  <small>
                    {coverage.pending} field report(s) awaiting review
                  </small>
                </div>
              </div>
            </div>
            <aside className="priority-panel" aria-label="Priority areas">
              <div className="panel-title">
                <h2>Priority areas</h2>
                <span>
                  {filtered.length} / {mock.sectors.length}
                </span>
              </div>
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
                      className={`area-row ${selectedId === s.id ? 'is-selected' : ''}`}
                      key={s.id}
                      aria-pressed={selectedId === s.id}
                      onClick={() => selectArea(s.id)}
                    >
                      <div className="area-top">
                        <span className="sector-code">{s.code}</span>
                        <span
                          className={`severity severity-${s.severity.toLowerCase()}`}
                        >
                          {s.severity}
                        </span>
                      </div>
                      <strong>{s.name}</strong>

                      <div className="area-bottom">
                        <span>
                          {s.people[1]
                            ? `${s.people[0]}–${s.people[1]} people estimated`
                            : 'Access / staging priority'}
                        </span>
                        <ChevronRight size={15} />
                      </div>
                    </button>
                  ))
                )}
              </div>
              <div className="side-tools">
                <span className="overline">SELECTED · {selected.code}</span>
                <div className="review-shortcuts">
                  <button onClick={() => openDetails('evidence')}>
                    Evidence <ChevronRight size={14} />
                  </button>
                  <button onClick={() => openDetails('access')}>
                    Access <ChevronRight size={14} />
                  </button>
                  <button onClick={() => openDetails('critique')}>
                    Plan review <ChevronRight size={14} />
                  </button>
                </div>
                <button
                  className="action-button primary-action"
                  disabled={!available.length}
                  onClick={openAssign}
                >
                  <Users size={15} />
                  Assign reconnaissance
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
              <div className="forecast-controls">
                <Choice
                  label="Time mode"
                  value={projection}
                  onChange={setProjection}
                  options={[
                    { value: 'nowcast', label: 'Current estimate' },
                    { value: 'forecast', label: 'Forecast' },
                    { value: 'stale', label: 'Stale information' },
                  ]}
                />
                {projection !== 'nowcast' && (
                  <Choice
                    label={
                      projection === 'forecast'
                        ? 'Forecast horizon'
                        : 'Information lag'
                    }
                    value={minutes}
                    onChange={setMinutes}
                    options={['30', '60', '120', '240'].map((v) => ({
                      value: v,
                      label: `${projection === 'forecast' ? '+' : '−'}${v} min`,
                    }))}
                  />
                )}
                <Choice
                  label="Scenario member"
                  value={member}
                  onChange={setMember}
                  options={[
                    { value: 'low', label: 'Low scenario' },
                    { value: 'mid', label: 'Mid scenario' },
                    { value: 'high', label: 'High scenario' },
                  ]}
                />
              </div>
              <span className="time-context">
                Known at <b>{time(p)}</b> → estimate for <b>{time(t)}</b>
                {projection !== 'nowcast' && ` (${horizon} min)`}
              </span>
            </div>
            <div className="timeline-water">
              <span>
                {selected.code} · water-depth trend / {member} exercise
              </span>
              <div className="water-trend">
                {Array.from({ length: 37 }, (_, i) => {
                  const value = fixtureDepth(
                    selected.depth,
                    start + i * 600000,
                    initialTime,
                    member,
                  );
                  return (
                    <i
                      key={i}
                      title={`${time(start + i * 600000)} · ${value.toFixed(1)} m`}
                      style={{
                        height: `${4 + value * 9}px`,
                        opacity: start + i * 600000 <= clock ? 1 : 0.4,
                      }}
                    />
                  );
                })}
              </div>
              <span>
                {fixtureDepth(
                  selected.depth,
                  start,
                  initialTime,
                  member,
                ).toFixed(1)}{' '}
                →{' '}
                {fixtureDepth(selected.depth, end, initialTime, member).toFixed(
                  1,
                )}{' '}
                m
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
              illustratively with time and scenario; no forecasting engine is
              connected.
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
                <strong>FLOOD / FIELD</strong>
                <span>{time(clock)} CDT · Exercise</span>
              </div>
              <div className="phone-screen">
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
                      onChange={setFieldTeam}
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
                  <div className="field-grid">
                    <section className="mission-panel">
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
                          {fieldAssignment.objective}
                        </p>
                        <dl className="facts-list">
                          <div>
                            <dt>Assigned team</dt>
                            <dd>{fieldTeamData.name}</dd>
                          </div>
                          <div>
                            <dt>Capability / personnel</dt>
                            <dd>
                              {fieldTeamData.capability} /{' '}
                              {fieldTeamData.people}
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
                        </dl>
                        <div className="field-estimate">
                          <StateTag value={fieldSector.state} />
                          <strong>
                            {fieldSector.people[1]
                              ? `${fieldSector.people[0]}–${fieldSector.people[1]} people estimated`
                              : 'Access verification task'}
                          </strong>
                          <p>{fieldSector.uncertainty}</p>
                        </div>
                        <div className="field-primary-actions">
                          <button
                            className="action-button primary-action"
                            onClick={() => {
                              setReportOpen(true);
                              setReportStage('edit');
                            }}
                          >
                            <Send size={17} />
                            Report observation
                          </button>
                          <button
                            className="action-button"
                            onClick={() => {
                              selectArea(fieldSector.id);
                              setView('command');
                              setFocus((f) => f + 1);
                            }}
                          >
                            <LocateFixed size={17} />
                            Locate on command map
                          </button>
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
                    </section>
                    <section className="field-access">
                      <div className="panel-title">
                        <h2>Approach & hazards</h2>
                        <TriangleAlert size={17} />
                      </div>
                      <div className="field-section">
                        <h3>Access assessment</h3>
                        <p className="access-status">{fieldSector.access}</p>
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
                        <div className="caution-note">
                          <TriangleAlert size={16} />
                          Verify route and bridge approaches. The mock does not
                          provide turn-by-turn navigation.
                        </div>
                      </div>
                      <div className="field-section">
                        <h3>Known and modeled hazards</h3>
                        {fieldSector.evidence.map((e, i) => (
                          <article className="evidence-item" key={i}>
                            <StateTag value={e.state} />
                            <p>{e.label}</p>
                            <small>{e.source}</small>
                          </article>
                        ))}
                      </div>
                    </section>
                    <section className="field-report-feed">
                      <div className="panel-title">
                        <h2>Team reports</h2>
                        <span>
                          {operations.reports.filter(
                            (r) => r.teamId === fieldTeam,
                          ).length +
                            operations.queued.filter(
                              (r) => r.teamId === fieldTeam,
                            ).length}
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
                              Report access, hazards, assistance needs, or
                              search progress. New reports appear in Command’s
                              evidence chain.
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
                                    : 'Received by Command · awaiting verification'}
                                </small>
                              </article>
                            ))
                        )}
                      </div>
                      <div className="field-note">
                        <ShieldCheck size={17} />
                        <p>
                          Session-only prototype. Queued reports are not an
                          offline backup and are lost on reload.
                        </p>
                      </div>
                    </section>
                  </div>
                ) : (
                  <div className="unassigned-state">
                    <ClipboardList size={32} />
                    <h2>No active assignment for {fieldTeamData.name}</h2>
                    <p>
                      Select a team with an assignment, or assign this team from
                      Command.
                    </p>
                    <button
                      className="action-button primary-action"
                      onClick={() => setView('command')}
                    >
                      <ArrowLeft size={16} />
                      Return to Command
                    </button>
                  </div>
                )}
              </div>
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
      <Dialog open={resourcesOpen} onOpenChange={setResourcesOpen}>
        <DialogContent className="ops-dialog resource-dialog">
          <DialogHeader>
            <DialogTitle>Resources & team status</DialogTitle>
            <DialogDescription>
              Select a team to open its Field workspace.
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
                      setFieldTeam(team.id);
                      setView('field');
                      setResourcesOpen(false);
                      setPlaying(false);
                    }}
                    title={`Open ${team.name} in Field`}
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
            <DialogTitle>Area review · {selected.code}</DialogTitle>
            <DialogDescription>
              Evidence, access, and proposed tactics for {selected.name}.
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
                <span>Depth estimate</span>
                <strong>
                  {depth.toFixed(1)} <em>m</em>
                </strong>
                <small>
                  {time(t)} · {member} scenario
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
                          onClick={() => {
                            dispatch({
                              type: 'verify',
                              reportId: r.id,
                              time: clock,
                              id: crypto.randomUUID(),
                            });
                            setNotice(
                              'Observation verified in this exercise. Area data coverage updated.',
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
            </Tabs>
            <div className="inspection-actions">
              <button
                className="action-button primary-action"
                disabled={!available.length}
                onClick={openAssign}
              >
                <Users size={16} />
                {available.length
                  ? 'Assign reconnaissance'
                  : 'No available teams'}
              </button>
              <small>Commander approval required · simulation only</small>
            </div>
          </aside>
        </DialogContent>
      </Dialog>
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="ops-dialog">
          <DialogHeader>
            <DialogTitle>Approve reconnaissance assignment</DialogTitle>
            <DialogDescription>
              Area {selected.code} · {selected.name}. This records a simulated
              assignment; nothing is dispatched.
            </DialogDescription>
          </DialogHeader>
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
                mock.teams.find((team) => team.id === id)?.capability ?? '';
              setObjective(objectivePresets(capability, selected.name)[0].text);
            }}
            options={available.map((team) => ({
              value: team.id,
              label: `${team.name} · ${team.capability}`,
            }))}
          />
          <p className="info-note">
            Suggested capability: {selected.capability}. The commander must
            assess the fit.
          </p>
          <label className="form-label" htmlFor="objective">
            Assignment objective
          </label>
          <div className="objective-presets">
            <span className="muted">
              Suggested for{' '}
              {mock.teams.find((team) => team.id === assignTeam)?.capability ??
                'selected team'}
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
              onClick={() => setAssignOpen(false)}
            >
              Cancel
            </button>
            <button
              className="action-button primary-action"
              disabled={!assignTeam || !objective.trim()}
              onClick={confirmAssignment}
            >
              Approve assignment
            </button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="ops-dialog">
          <DialogHeader>
            <DialogTitle>
              {reportStage === 'edit'
                ? 'Report an observation'
                : 'Review observation'}
            </DialogTitle>
            <DialogDescription>
              {fieldTeamData.name} · Area {fieldSector.code} · {time(clock)}{' '}
              CDT. Reports enter Command as unverified evidence.
            </DialogDescription>
          </DialogHeader>
          {reportStage === 'edit' ? (
            <>
              <label className="form-label" htmlFor="report-type">
                Report type
              </label>
              <Choice
                id="report-type"
                label="Report type"
                value={reportType}
                onChange={setReportType}
                options={[
                  'Access',
                  'Hazard',
                  'Assistance needs',
                  'Search progress',
                ].map((v) => ({ value: v, label: v }))}
              />
              <label className="form-label" htmlFor="observation">
                What did you observe?
              </label>
              <textarea
                id="observation"
                rows={5}
                value={reportText}
                onChange={(e) => setReportText(e.target.value)}
                placeholder="State the location, conditions, and what still needs verification."
              />
              <label className="form-label" htmlFor="report-confidence">
                Your confidence
              </label>
              <Choice
                id="report-confidence"
                label="Report confidence"
                value={reportConfidence}
                onChange={setReportConfidence}
                options={['Low', 'Medium', 'High'].map((v) => ({
                  value: v,
                  label: v,
                }))}
              />
              <button
                className="action-button primary-action"
                disabled={reportText.trim().length < 8}
                onClick={() => setReportStage('review')}
              >
                Review report <ArrowRight size={15} />
              </button>
            </>
          ) : (
            <>
              <dl className="facts-list">
                <div>
                  <dt>Type</dt>
                  <dd>{reportType}</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{reportConfidence}</dd>
                </div>
                <div>
                  <dt>Delivery</dt>
                  <dd>
                    {operations.offline
                      ? 'Queue in this session'
                      : 'Send to simulated Command'}
                  </dd>
                </div>
              </dl>
              <p className="report-preview">{reportText}</p>
              <p className="info-note">
                This does not notify emergency services or a real command
                center.
              </p>
              <div className="dialog-actions">
                <button
                  className="action-button"
                  onClick={() => setReportStage('edit')}
                >
                  Back to edit
                </button>
                <button
                  className="action-button primary-action"
                  onClick={submitReport}
                >
                  {operations.offline ? 'Queue report' : 'Submit report'}
                </button>
              </div>
            </>
          )}
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
