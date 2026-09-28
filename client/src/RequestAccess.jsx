import { useState } from "react";
import { Link } from "react-router-dom";

// Create an account. The person chooses their own password; it goes to the
// identity provider's sign-up call through the API and is never stored by
// AURALANE. The account waits on the waitlist, unable to sign in, until the
// super admin approves the role.
export default function RequestAccess({ request }) {
  const [form, setForm] = useState({ username: "", email: "", password: "", confirm: "", role: "radiologist" });
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const mismatch = form.confirm && form.password !== form.confirm;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { confirm, ...body } = form;
      setDone(await request(body));
    } catch (err) {
      setError(String(err.message));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <main className="login">
        <h1>Account created</h1>
        <p data-testid="request-sent">
          {done.username} is on the waitlist for {done.role} access. You can sign in with the password
          you chose once the super admin approves your role.
        </p>
        <Link to="/login">Back to sign in</Link>
      </main>
    );
  }
  return (
    <main className="login">
      <h1>Create an account</h1>
      <form onSubmit={submit}>
        <label>Username<input autoComplete="username" value={form.username} onChange={set("username")} /></label>
        <label>Email<input type="email" autoComplete="email" value={form.email} onChange={set("email")} /></label>
        <label>Password<input type="password" autoComplete="new-password" value={form.password} onChange={set("password")} /></label>
        <label>Confirm password<input type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} /></label>
        <label>Role you are requesting
          <select value={form.role} onChange={set("role")}>
            <option value="radiologist">Radiologist: reads the worklist and studies</option>
            <option value="admin">Administrator: configuration and audit, no studies</option>
          </select>
        </label>
        <p className="note">
          Password: at least 8 characters, with upper and lower case letters, a number and a symbol.
        </p>
        {mismatch && <p className="error" role="alert">The passwords do not match.</p>}
        <button type="submit" disabled={busy || mismatch || !form.username || !form.email || !form.password}>
          Create account
        </button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <p className="note"><Link to="/login">Back to sign in</Link></p>
    </main>
  );
}
