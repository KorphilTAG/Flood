export type EvidenceState =
  | 'Confirmed'
  | 'Reported'
  | 'Inferred'
  | 'Unknown'
  | 'Stale';
export type TeamStatus =
  | 'Assigned'
  | 'En route'
  | 'On scene'
  | 'Recon complete'
  | 'Unable to proceed';
export type Assignment = {
  teamId: string;
  sectorId: string;
  objective: string;
  status: TeamStatus;
  updatedAt: number;
};
export type Report = {
  id: string;
  teamId: string;
  sectorId: string;
  kind: string;
  text: string;
  confidence: string;
  createdAt: number;
};
export type LogEntry = {
  id: string;
  time: number;
  text: string;
  sectorId?: string;
};
export type Operations = {
  assignments: Assignment[];
  reports: Report[];
  queued: Report[];
  offline: boolean;
  log: LogEntry[];
};
export type Action =
  | { type: 'assign'; assignment: Assignment; id: string }
  | {
      type: 'status';
      teamId: string;
      status: TeamStatus;
      time: number;
      id: string;
    }
  | { type: 'report'; report: Report }
  | { type: 'connectivity'; offline: boolean; time: number; id: string };
export function operationsReducer(
  state: Operations,
  action: Action,
): Operations {
  if (action.type === 'assign') {
    if (
      state.assignments.some(
        (a) =>
          a.teamId === action.assignment.teamId &&
          a.status !== 'Recon complete',
      )
    )
      return state;
    return {
      ...state,
      assignments: [
        ...state.assignments.filter(
          (a) => a.teamId !== action.assignment.teamId,
        ),
        action.assignment,
      ],
      log: [
        {
          id: action.id,
          time: action.assignment.updatedAt,
          text: 'Assignment approved in simulation',
          sectorId: action.assignment.sectorId,
        },
        ...state.log,
      ],
    };
  }
  if (action.type === 'status') {
    const assignment = state.assignments.find(
      (a) => a.teamId === action.teamId,
    );
    if (!assignment || assignment.status === action.status) return state;
    return {
      ...state,
      assignments: state.assignments.map((a) =>
        a.teamId === action.teamId
          ? { ...a, status: action.status, updatedAt: action.time }
          : a,
      ),
      log: [
        {
          id: action.id,
          time: action.time,
          text: `Team status: ${action.status}`,
          sectorId: assignment.sectorId,
        },
        ...state.log,
      ],
    };
  }
  if (action.type === 'report') {
    if (
      !action.report.text.trim() ||
      [...state.reports, ...state.queued].some((r) => r.id === action.report.id)
    )
      return state;
    if (state.offline)
      return { ...state, queued: [action.report, ...state.queued] };
    return {
      ...state,
      reports: [action.report, ...state.reports],
      log: [
        {
          id: action.report.id,
          time: action.report.createdAt,
          text: `New ${action.report.kind.toLowerCase()} report · requires review`,
          sectorId: action.report.sectorId,
        },
        ...state.log,
      ],
    };
  }
  if (action.type === 'connectivity') {
    if (action.offline) return { ...state, offline: true };
    const incoming = state.queued.filter(
      (r) => !state.reports.some((existing) => existing.id === r.id),
    );
    return {
      ...state,
      offline: false,
      queued: [],
      reports: [...incoming, ...state.reports],
      log: incoming.length
        ? [
            {
              id: action.id,
              time: action.time,
              text: `${incoming.length} queued report${incoming.length === 1 ? '' : 's'} received · requires review`,
            },
            ...state.log,
          ]
        : state.log,
    };
  }
  return state;
}
export function deriveTimes(
  clock: number,
  mode: string,
  minutes: number,
  start: number,
  end: number,
) {
  const p = mode === 'stale' ? Math.max(start, clock - minutes * 60000) : clock;
  const t =
    mode === 'forecast' ? Math.min(end, clock + minutes * 60000) : clock;
  return { p, t, horizon: Math.round((t - p) / 60000) };
}
export function visibleReports(
  state: Operations,
  sectorId: string,
  cutoff: number,
) {
  return state.reports.filter(
    (r) => r.sectorId === sectorId && r.createdAt <= cutoff,
  );
}
export function fixtureDepth(
  base: number,
  target: number,
  initial: number,
  member: string,
) {
  const change = (target - initial) / 3600000;
  const factor = member === 'low' ? 0.75 : member === 'high' ? 1.25 : 1;
  return Math.max(0, Math.round((base + change * 0.22) * factor * 10) / 10);
}
