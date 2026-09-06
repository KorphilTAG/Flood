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
  receivedAt?: number;
  observation?: MapObservation;
  verifiedAt?: number;
};
export type ObservationKind =
  | 'hazard_present'
  | 'hazard_absent'
  | 'people_found'
  | 'people_relocated'
  | 'people_not_seen'
  | 'people_evacuated'
  | 'note';
export type MapObservation = {
  action: ObservationKind;
  targetId: string;
  lon: number;
  lat: number;
  count?: number;
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
  | { type: 'verify'; reportId: string; time: number; id: string }
  | { type: 'connectivity'; offline: boolean; time: number; id: string };
export function operationsReducer(
  state: Operations,
  action: Action,
): Operations {
  if (action.type === 'verify') {
    const report = state.reports.find((r) => r.id === action.reportId);
    if (
      !report ||
      report.verifiedAt !== undefined ||
      action.time <
        Math.max(report.createdAt, report.receivedAt ?? report.createdAt)
    )
      return state;
    return {
      ...state,
      reports: state.reports.map((r) =>
        r.id === report.id ? { ...r, verifiedAt: action.time } : r,
      ),
      log: [
        {
          id: action.id,
          time: action.time,
          sectorId: report.sectorId,
          text: `Commander verified ${report.kind.toLowerCase()} observation · exercise only`,
        },
        ...state.log,
      ],
    };
  }
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
      reports: [
        { ...action.report, receivedAt: action.report.createdAt },
        ...state.reports,
      ],
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
    const incoming = state.queued
      .filter((r) => !state.reports.some((existing) => existing.id === r.id))
      .map((r) => ({ ...r, receivedAt: Math.max(action.time, r.createdAt) }));
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
    (r) =>
      r.sectorId === sectorId &&
      Math.max(r.createdAt, r.receivedAt ?? r.createdAt) <= cutoff,
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

/** Evidence-record share, not probability of correctness or geographic coverage. */
export function evidenceCoverage(
  state: Operations,
  sectorId: string,
  cutoff: number,
  seed: { state: string }[],
) {
  const reports = visibleReports(state, sectorId, cutoff);
  const reviewed = reports.filter(
    (r) => r.verifiedAt !== undefined && r.verifiedAt <= cutoff,
  ).length;
  const confirmed =
    seed.filter((e) => e.state === 'Confirmed').length + reviewed;
  const total = seed.length + reports.length;
  const verified = total ? Math.round((100 * confirmed) / total) : 0;
  return {
    confirmed,
    total,
    verified,
    modeled: 100 - verified,
    pending: reports.length - reviewed,
  };
}
export function objectivePresets(capability: string, area: string) {
  const prompts: Record<string, [string, string][]> = {
    'Swift-water': [
      [
        'Assess water hazards',
        'Observe flow, debris, and potential entrapment hazards from a safe position. Report conditions and confidence to Command.',
      ],
      [
        'Verify rescue access',
        'Assess possible water-entry and extraction points. Report limitations and required support before any movement.',
      ],
      [
        'Check occupied structures',
        'Verify visible occupancy and identify structures requiring further assessment. Report estimated people and observation time.',
      ],
    ],
    'Boat team': [
      [
        'Survey boat approach',
        'Assess boat approach and landing locations. Identify obstructions, water conditions, and alternate access for commander review.',
      ],
      [
        'Locate people',
        'Observe potential occupied locations and report visible people, assistance needs, and location confidence.',
      ],
      [
        'Check extraction points',
        'Assess candidate pickup and transfer points. Report capacity constraints and hazards before committing a route.',
      ],
    ],
    'Recon team': [
      [
        'Verify road access',
        'Check road and crossing conditions from a safe observation point. Report closures, obstructions, and available alternate approaches.',
      ],
      [
        'Confirm reported hazard',
        'Recheck the reported hazard and record its location, observed condition, and timestamp. Distinguish observation from inference.',
      ],
      [
        'Verify occupancy',
        'Observe priority structures and report signs of occupancy, estimated people, and remaining uncertainty.',
      ],
    ],
    Medical: [
      [
        'Assess assistance needs',
        'Assess reported medical assistance needs and relay urgency, approximate patient numbers, and required support to Command.',
      ],
      [
        'Check medical staging',
        'Verify staging access, available capacity, and transfer constraints. Report changes before team deployment.',
      ],
    ],
    Logistics: [
      [
        'Verify staging capacity',
        'Check staging access, resource capacity, and supply constraints. Report conditions and timestamp to Command.',
      ],
      [
        'Check supply access',
        'Assess supply approach and alternate staging options. Identify blocked access and equipment requirements.',
      ],
    ],
  };
  return (prompts[capability] ?? prompts['Recon team']).map(
    ([label, text]) => ({ label, text: `${area}: ${text}` }),
  );
}

export function observationPresets(kind: string, area: string) {
  const options: Record<string, [string, string][]> = {
    Access: [
      [
        'Road blocked',
        'The observed road approach is blocked. Alternate access has not been verified.',
      ],
      [
        'Water over road',
        'Water is visible across the road approach. Depth and passability have not been verified.',
      ],
      [
        'Approach clear',
        'The observed approach is clear at the time of this report. Conditions may change.',
      ],
    ],
    Hazard: [
      [
        'Debris observed',
        'Debris is visible in the observed area. Its extent and movement need further assessment.',
      ],
      [
        'Crossing damaged',
        'Visible damage observed at the crossing. Access safety has not been established.',
      ],
      [
        'Water rising',
        'Water appears to be rising compared with our earlier observation. No measured rise rate is available.',
      ],
    ],
    'Assistance needs': [
      [
        'People visible',
        'People are visible in the observed area. Exact count and assistance needs require confirmation.',
      ],
      [
        'Medical help requested',
        'Medical assistance has been requested. Patient count and urgency require assessment.',
      ],
      [
        'No people visible',
        'No people are visible from our current observation point. This does not establish that the area is unoccupied.',
      ],
    ],
    'Search progress': [
      [
        'Assessment started',
        'Our team has started assessing the assigned area. Search coverage is not yet complete.',
      ],
      [
        'Area checked',
        'The assigned observation area has been checked from accessible positions. Inaccessible locations remain unverified.',
      ],
      [
        'Unable to assess',
        'Our team cannot safely assess the assigned area from the current position. Further support or alternate access is needed.',
      ],
    ],
  };
  return (options[kind] ?? options.Access).map(([label, text]) => ({
    label,
    text: `Area ${area}: ${text}`,
  }));
}
