import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api.js";
import { EyeIcon, EyeOffIcon } from "./components/Icons.jsx";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function fillDemo() {
    setUsername("radiologist");
    setPassword("<NewPassword1!>");
    setError(null);
  }

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
      <button
        type="button"
        className="demo-credentials-box"
        onClick={fillDemo}
      >
        <div className="demo-credentials-head">
          <span className="demo-credentials-title">Login using demo credentials</span>
          <span className="demo-credentials-badge">Auto-fill</span>
        </div>
        <div className="demo-credentials-creds">
          <span>Username: <strong>radiologist</strong></span>
          <span className="demo-credentials-sep">·</span>
          <span>Password: <strong>&lt;NewPassword1!&gt;</strong></span>
        </div>
      </button>
      <form onSubmit={submit}>
        <label className="field-label">
          User
          <input autoComplete="username" value={username}
                 onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="field-label">
          Password
          <div className="password-input-wrap">
            <input
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className="password-toggle-btn"
              aria-label={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
            </button>
          </div>
        </label>
        <button type="submit" className="pill pill-primary wide" disabled={busy || !username || !password}>Sign in</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <Link to="/request-access" className="pill pill-quiet wide">Create an account</Link>
    </main>
  );
}
