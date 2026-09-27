import { useState } from "react";
import { api } from "./api.js";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await api.login(username, password));
    } catch (err) {
      setError(err.status === 401 ? "Unknown user or wrong password." : String(err.message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <h1>Sign in to the reading worklist</h1>
      <form onSubmit={submit}>
        <label>
          User
          <input autoComplete="username" value={username}
                 onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || !username || !password}>Sign in</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <p className="note">
        Radiologists see the worklist. Administrators see configuration and audit, and cannot
        open studies.
      </p>
    </main>
  );
}
