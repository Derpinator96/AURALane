// The API client. Same calls whichever runtime serves the API (local, fixture
// or AWS): nothing here knows or asks which one it is talking to.

const KEY = "auralane.session";

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
  const res = await fetch(path, {
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
};
