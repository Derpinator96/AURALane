import { useState } from "react";
import { Link } from "react-router-dom";
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
        <label className="field-label">
          User
          <input autoComplete="username" value={username}
                 onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="field-label">
          Password
          <input type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="pill pill-primary wide" disabled={busy || !username || !password}>Sign in</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <Link to="/request-access" className="pill pill-quiet wide">Create an account</Link>
    </main>
  );
}
