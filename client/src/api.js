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

async function call(path, { token, method = "GET", body } = {}) {
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

export const api = {
  login: (username, password) =>
    call("/api/auth/login", { method: "POST", body: { username, password } }),
  worklist: (token) => call("/api/worklist", { token }),
  study: (token, id) => call(`/api/studies/${encodeURIComponent(id)}`, { token }),
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
};
