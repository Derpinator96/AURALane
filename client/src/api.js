// The API client. Same calls whichever runtime serves the API (local, fixture
// or AWS): nothing here knows or asks which one it is talking to.

const KEY = "auralane.session";

// Where the API lives. Empty in development: the Vite proxy forwards /api on the
// same origin. The hosted client is built with VITE_API_BASE set to the API's own
// origin, a different host, and every call below goes through this one prefix.
const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

export function loadSession() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    if (session) sessionStorage.setItem(KEY, JSON.stringify(session));
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage unavailable: the session lasts until reload.
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { token, method = "GET", body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail || res.statusText);
  return data;
}

// The same GET asked for twice while the first is still in flight (a viewer and a
// panel opening the same study) is one request.
const inflight = new Map();

function call(path, opts = {}) {
  if ((opts.method || "GET") !== "GET") {
    forgetStudyFor(path);
    return request(path, opts);
  }
  const key = `${opts.token || ""} ${path}`;
  if (!inflight.has(key)) {
    inflight.set(key, request(path, opts).finally(() => inflight.delete(key)));
  }
  return inflight.get(key);
}

// The last few study payloads, so going back to a study is instant. A payload
// is dropped after a minute (its evidence links are short-lived) and whenever
// this client writes to that study.
const STUDY_TTL_MS = 60_000;
const STUDY_KEEP = 6;
const studies = new Map();

function forgetStudyFor(path) {
  const m = /^\/api\/studies\/([^/]+)/.exec(path);
  if (m) studies.delete(decodeURIComponent(m[1]));
  else if (path.startsWith("/api/annotations") || path.startsWith("/api/admin/assignments") || path.startsWith("/api/distribute")) {
    studies.clear();
  }
}

function cachedStudy(token, id) {
  const hit = studies.get(id);
  if (hit && hit.token === token && Date.now() - hit.at < STUDY_TTL_MS) {
    studies.delete(id);
    studies.set(id, hit);                     // most recently used last
    return Promise.resolve(hit.data);
  }
  return null;
}

async function fetchStudy(token, id) {
  const data = await call(`/api/studies/${encodeURIComponent(id)}`, { token });
  studies.set(id, { token, at: Date.now(), data });
  while (studies.size > STUDY_KEEP) studies.delete(studies.keys().next().value);
  return data;
}

export const api = {
  login: (username, password) =>
    call("/api/auth/login", { method: "POST", body: { username, password } }),
  worklist: (token) => call("/api/worklist", { token }),
  study: (token, id) => cachedStudy(token, id) || fetchStudy(token, id),
  clearCache: () => { studies.clear(); inflight.clear(); },
  series: (token, id, seriesUid) =>
    call(`/api/studies/${encodeURIComponent(id)}/series/${encodeURIComponent(seriesUid)}`, { token }),
  verdict: (token, id, verdict) =>
    call(`/api/studies/${encodeURIComponent(id)}/verdict`, { token, method: "POST", body: { verdict } }),
  audit: (token) => call("/api/admin/audit", { token }),
  laneMix: (token) => call("/api/admin/lane-mix", { token }),
  models: (token) => call("/api/admin/models", { token }),
  requestAccess: (body) => call("/api/access-requests", { method: "POST", body }),
  accessRequests: (token) => call("/api/admin/access-requests", { token }),
  decideAccess: (token, username, decision) =>
    call(`/api/admin/access-requests/${encodeURIComponent(username)}`, { token, method: "POST", body: { decision } }),
  intake: (token) => call("/api/admin/intake", { token }),
  startIntake: (token, count) => call("/api/admin/intake", { token, method: "POST", body: { count } }),
  // 3D viewer: each answers {url, name}, a presigned URL NiiVue loads directly.
  volume: (token, study, sequence) =>
    call(`/api/studies/${encodeURIComponent(study)}/volume/${encodeURIComponent(sequence)}`, { token }),
  segmentation: (token, study) =>
    call(`/api/studies/${encodeURIComponent(study)}/segmentation`, { token }),
  metrics: (token, study) =>
    call(`/api/studies/${encodeURIComponent(study)}/metrics`, { token }),
  saveDraft: (token, study, text, reviewed) =>
    call(`/api/studies/${encodeURIComponent(study)}/draft`, { token, method: "POST", body: { text, reviewed } }),
  // The abstention tray: place an abstained study in a lane, send it for a second
  // read, or mark it technically inadequate. Each answers {study}.
  setLane: (token, study, lane, reason) =>
    call(`/api/studies/${encodeURIComponent(study)}/lane`, { token, method: "POST", body: { lane, reason } }),
  secondRead: (token, study, reader) =>
    call(`/api/studies/${encodeURIComponent(study)}/second-read`, { token, method: "POST", body: { reader } }),
  markInadequate: (token, study, reason) =>
    call(`/api/studies/${encodeURIComponent(study)}/inadequate`, { token, method: "POST", body: { reason } }),
  // The signed-in radiologist's saved reports (latest version per study).
  reports: (token, status) => call(`/api/reports${status ? `?status=${encodeURIComponent(status)}` : ""}`, { token }),
  report: (token, study, version) =>
    call(`/api/reports/${encodeURIComponent(study)}/${encodeURIComponent(version)}`, { token }),
  readers: (token) => call("/api/readers", { token }),
  distribute: (token, readers) => call("/api/distribute", { token, method: "POST", body: { readers } }),
  simulateInfo: (token) => call("/api/simulate", { token }),
  simulateEstimate: (token, counts) => call("/api/simulate/estimate", { token, method: "POST", body: counts }),
  simulate: (token, counts, readers) => call("/api/simulate", { token, method: "POST", body: { counts, readers } }),
  simulateStatus: (token, batch) => call(`/api/simulate/${encodeURIComponent(batch)}`, { token }),
  myHistory: (token) => call("/api/me/history", { token }),
  assignments: (token) => call("/api/admin/assignments", { token }),
  reassign: (token, study, reader) =>
    call(`/api/admin/assignments/${encodeURIComponent(study)}`, { token, method: "POST", body: { reader } }),
  pipeline: (token) => call("/api/admin/pipeline", { token }),
  pipelineStudy: (token, study) => call(`/api/admin/pipeline/${encodeURIComponent(study)}`, { token }),
  getAnnotations: (token, study) =>
    call(`/api/studies/${encodeURIComponent(study)}/annotations`, { token }),
  createAnnotation: (token, study, data) =>
    call(`/api/studies/${encodeURIComponent(study)}/annotations`, { token, method: "POST", body: data }),
  updateAnnotation: (token, annotationId, data) =>
    call(`/api/annotations/${encodeURIComponent(annotationId)}`, { token, method: "PATCH", body: data }),
  deleteAnnotation: (token, annotationId) =>
    call(`/api/annotations/${encodeURIComponent(annotationId)}`, { token, method: "DELETE" }),
};

