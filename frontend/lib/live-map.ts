import type { MapObservation, Report } from './operations.ts';
import {
  floodForecastProgress,
  projectedPeoplePosition,
} from './topography.ts';

type Sector = {
  id: string;
  code: string;
  lon: number;
  lat: number;
  people: number[];
};
export type MapFeature = {
  id: string;
  sectorId: string;
  category: 'hazard' | 'people';
  lon: number;
  lat: number;
  active: boolean;
  state: 'predicted' | 'reported' | 'verified';
  label: string;
  count: number[];
  action?: MapObservation['action'];
  reportId?: string;
  observedAt?: number;
};

/** Replays observations at a knowledge cutoff. New reports supersede the same
 * feature, while new groups keep independent identities. Search visibility is
 * deliberately not treated as proof that nobody is present. */
export function deriveLiveMap(
  sectors: Sector[],
  reports: Report[],
  cutoff: number,
  target: number,
  initial: number,
) {
  const progress = floodForecastProgress(target, initial);
  const features = new Map<string, MapFeature>();
  sectors.forEach((s, index) => {
    features.set(`hazard:${s.id}`, {
      id: `hazard:${s.id}`,
      sectorId: s.id,
      category: 'hazard',
      lon: s.lon + 0.007,
      lat: s.lat + 0.002,
      active: index < 3 || progress >= (index === 3 ? 0.55 : 0.8),
      state: 'predicted',
      label: s.id.startsWith('crossing:')
        ? 'Potential crossing hazard'
        : 'Potential access hazard',
      count: [],
    });
    if (s.people[1] > 0) {
      const [lon, lat] = projectedPeoplePosition(s.lon, s.lat, progress, index);
      features.set(`people:${s.id}`, {
        id: `people:${s.id}`,
        sectorId: s.id,
        category: 'people',
        lon,
        lat,
        active: true,
        state: 'predicted',
        label: 'Possible people',
        count: s.people,
      });
    }
  });
  [...reports]
    .reverse()
    .filter((r) => Math.max(r.createdAt, r.receivedAt ?? r.createdAt) <= cutoff)
    .sort(
      (a, b) =>
        a.createdAt - b.createdAt ||
        (a.receivedAt ?? a.createdAt) - (b.receivedAt ?? b.createdAt),
    )
    .forEach((r) => {
      const o = r.observation;
      if (
        !o ||
        o.action === 'note' ||
        !sectors.some((s) => s.id === r.sectorId) ||
        !Number.isFinite(o.lon) ||
        !Number.isFinite(o.lat)
      )
        return;
      const category = o.action.startsWith('hazard_') ? 'hazard' : 'people';
      const previous = features.get(o.targetId);
      if (
        previous &&
        (previous.sectorId !== r.sectorId || previous.category !== category)
      )
        return;
      const labels = {
        hazard_present: 'Hazard observed',
        hazard_absent: 'Hazard not found',
        people_found: 'People located',
        people_relocated: 'Group moved',
        people_not_seen: 'None visible · search incomplete',
        people_evacuated: 'Group evacuated',
      };
      const count =
        o.action === 'people_not_seen'
          ? (previous?.count ?? [0, 0])
          : o.action === 'people_evacuated'
            ? [0, 0]
            : category === 'people'
              ? [Math.max(0, o.count ?? 0), Math.max(0, o.count ?? 0)]
              : [];
      features.set(o.targetId, {
        id: o.targetId,
        sectorId: r.sectorId,
        category,
        lon: o.lon,
        lat: o.lat,
        active: o.action !== 'hazard_absent' && o.action !== 'people_evacuated',
        state:
          r.verifiedAt !== undefined && r.verifiedAt <= cutoff
            ? 'verified'
            : 'reported',
        label: labels[o.action],
        count,
        action: o.action,
        reportId: r.id,
        observedAt: r.createdAt,
      });
    });
  const all = [...features.values()];
  const verifiedCount = all.filter((f) => f.state === 'verified').length;
  const reportedCount = all.filter((f) => f.state === 'reported').length;
  const verified = Math.round((100 * verifiedCount) / Math.max(1, all.length));
  const reported = Math.round((100 * reportedCount) / Math.max(1, all.length));
  return {
    features: all,
    coverage: {
      verified,
      reported,
      modeled: 100 - verified - reported,
      verifiedCount,
      reportedCount,
      total: all.length,
    },
  };
}

export const reportPresets: {
  label: string;
  kind: string;
  action: MapObservation['action'];
  text: string;
}[] = [
  {
    label: 'Hazard observed',
    kind: 'Hazard',
    action: 'hazard_present',
    text: 'Hazard observed at the marked location. Assess extent and approach before proceeding.',
  },
  {
    label: 'Hazard not found',
    kind: 'Hazard',
    action: 'hazard_absent',
    text: 'The specific predicted hazard was not found at the marked location during this check. Other hazards remain possible.',
  },
  {
    label: 'People found',
    kind: 'Assistance needs',
    action: 'people_found',
    text: 'A group of people is visible at the marked location. Count and assistance needs are recorded below.',
  },
  {
    label: 'Group moved',
    kind: 'Assistance needs',
    action: 'people_relocated',
    text: 'The selected group has moved to the updated location. Further movement remains possible.',
  },
  {
    label: 'No people visible',
    kind: 'Search progress',
    action: 'people_not_seen',
    text: 'No people visible at the marked observation point. This does not establish that the area is unoccupied.',
  },
  {
    label: 'Group evacuated',
    kind: 'Search progress',
    action: 'people_evacuated',
    text: 'The selected group has been evacuated from this location. Other groups and unsearched areas remain possible.',
  },
];

export function tacticsPresets(area: string, features: MapFeature[]) {
  const unreviewed = features.some((f) => f.state === 'reported');
  const people = features.some(
    (f) => f.category === 'people' && f.active && f.state !== 'predicted',
  );
  return [
    {
      label: 'Verify uncertain access',
      text: `${area}: task a reconnaissance team to check the proposed approach and predicted hazards from a safe observation point. Request location, time, and alternate access; hold movement pending review.`,
    },
    {
      label: people ? 'Assess located group' : 'Locate potential occupants',
      text: `${area}: ${people ? 'review the newly reported group location and assistance needs' : 'verify potential occupied locations'}. Match team capability to observed conditions and identify a contingency before committing resources.`,
    },
    {
      label: unreviewed ? 'Reconcile new reports' : 'Refresh area picture',
      text: `${area}: ${unreviewed ? 'verify incoming observations and reconcile conflicting reports' : 'request fresh field observations'}. Update hazard and group locations, reassess staging, and confirm the next check with the assigned team.`,
    },
  ];
}
