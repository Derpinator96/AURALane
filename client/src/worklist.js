// Worklist arrangement. Pure functions over what /api/worklist returns.
//
// Nothing here computes an acuity, a lane or an order of lanes: the API sends
// the rows already in priority order and the lane sections in display order.
// The client only groups, filters and, when asked, re-sorts by arrival time.
//
// Pinned sections (NEEDS HUMAN TRIAGE, PIPELINE FAILED) ignore every filter.
// A study the model refused to place must never be something a user can hide.
//
// Rows are grouped by reading pool first (Neuro for MR, Chest for CR), then by
// lane inside each pool. Ranking never crosses pools. Pinned sections are per
// pool: a brain MRI the model could not place still needs a neuroradiologist to
// place it, and a failed chest study goes back to the chest reader.

export const SORTS = {
  priority: "Priority",
  "arrival-oldest": "Arrival, oldest first",
  "arrival-newest": "Arrival, newest first",
};

export const READ_FILTERS = { all: "All", unread: "Unread", read: "Read" };

export function isUnread(row) {
  return !row.verdict;
}

function passes(row, { lane, read }) {
  if (lane !== "ALL" && row.lane !== lane) return false;
  if (read === "unread" && !isUnread(row)) return false;
  if (read === "read" && isUnread(row)) return false;
  return true;
}

/**
 * -> [{ lane, label, clock, pinned, rows }] in display order.
 *
 * priority: one section per lane, in the API's lane order; rows keep the
 *   API's order inside each section.
 * arrival-*: pinned sections first, then every other row in one section
 *   ordered by arrival time.
 * Pinned sections always appear; NEEDS HUMAN TRIAGE appears even when empty.
 */
export function arrange(studies, lanes, { sort = "priority", lane = "ALL", read = "all" } = {}) {
  const byLane = (l) => studies.filter((r) => r.lane === l.lane);
  const pinned = lanes
    .filter((l) => l.pinned)
    .map((l) => ({ ...l, rows: byLane(l) }))
    .filter((s) => s.lane === "ABSTAIN" || s.rows.length > 0);

  if (sort === "priority") {
    const sections = [];
    for (const l of lanes) {
      if (l.pinned) {
        const p = pinned.find((s) => s.lane === l.lane);
        if (p) sections.push(p);
        continue;
      }
      const rows = byLane(l).filter((r) => passes(r, { lane, read }));
      if (rows.length) sections.push({ ...l, rows });
    }
    return sections;
  }

  const pinnedLanes = new Set(lanes.filter((l) => l.pinned).map((l) => l.lane));
  const rest = studies
    .filter((r) => !pinnedLanes.has(r.lane) && passes(r, { lane, read }))
    .slice()
    .sort((a, b) => (a.arrived < b.arrived ? -1 : a.arrived > b.arrived ? 1 : 0));
  if (sort === "arrival-newest") rest.reverse();
  const flat = { lane: "BY_ARRIVAL", label: "All other lanes, by arrival", clock: null,
                 pinned: false, rows: rest };
  return [...pinned, ...(rest.length ? [flat] : [])];
}

/**
 * -> [{ pool, label, sections }] in the API's pool order, each pool arranged by
 * arrange() over its own rows only. Every pool the API lists is shown, so each
 * pool's NEEDS HUMAN TRIAGE section is always there.
 */
export function arrangePools(studies, pools, lanes, opts = {}) {
  return pools.map((p) => ({
    ...p,
    sections: arrange(studies.filter((r) => r.pool === p.pool), lanes, opts),
  }));
}

export function timeUTC(iso) {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toISOString().slice(11, 16);
}
