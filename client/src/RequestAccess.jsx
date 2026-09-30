import { useState } from "react";
import { Link } from "react-router-dom";

// The API accepts usernames of 3 to 64 letters, digits, dots, underscores and hyphens. A person's name
// ("Jane Doe"), which some browsers fill in, has a space and is refused, so say so before sending.
const USERNAME = /^[A-Za-z0-9._-]{3,64}$/;
export function usernameProblem(v) {
  if (!v || USERNAME.test(v)) return null;
  if (/\s/.test(v)) {
    const suggestion = v.trim().toLowerCase().replace(/\s+/g, ".");
    return { kind: "chars", text: `A username cannot contain spaces.${USERNAME.test(suggestion) ? ` Try ${suggestion}.` : ""}` };
  }
  if (/[^A-Za-z0-9._-]/.test(v)) return { kind: "chars", text: "A username can use letters, numbers, dots, underscores and hyphens only." };
  return v.length < 3 ? { kind: "short", text: "A username needs at least 3 characters." }
                      : { kind: "long", text: "A username can be at most 64 characters." };
}
const passwordProblem = (v) => (v && v.length < 8 ? { kind: "short", text: "A password needs at least 8 characters." } : null);

// Create an account. The person chooses their own password; it goes to the
// identity provider's sign-up call through the API and is never stored by
// AURALANE. The account waits on the waitlist, unable to sign in, until the
// super admin approves the role.
export default function RequestAccess({ request }) {
  const [form, setForm] = useState({ username: "", email: "", password: "", confirm: "", role: "radiologist" });
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState({});                  // fields the person has moved on from
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const leave = (k) => () => setLeft((l) => ({ ...l, [k]: true }));
  const mismatch = form.confirm && form.password !== form.confirm;
  // A field that is too short is only flagged once they leave it; one with a wrong character at once.
  const problems = [["username", usernameProblem(form.username)], ["password", passwordProblem(form.password)]]
    .filter(([, p]) => p);
  const shown = problems.filter(([k, p]) => left[k] || p.kind !== "short");

  async function submit(e) {
    e.preventDefault();
    if (problems.length) {
      setLeft({ username: true, password: true });
      return;
    }
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
        <Link to="/login" className="pill wide">Back to sign in</Link>
      </main>
    );
  }
  return (
    <main className="login">
      <h1>Create an account</h1>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label className="field-label">Username<input autoComplete="username" value={form.username} onChange={set("username")}
                                                        onBlur={leave("username")} /></label>
          <label className="field-label">Email<input type="email" autoComplete="email" value={form.email} onChange={set("email")} /></label>
          <label className="field-label">Password<input type="password" autoComplete="new-password" value={form.password} onChange={set("password")}
                                                        onBlur={leave("password")} /></label>
          <label className="field-label">Confirm password<input type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} /></label>
          <label className="field-label span-2">Role you are requesting
            <select value={form.role} onChange={set("role")}>
              <option value="radiologist">Radiologist: reads the worklist and studies</option>
              <option value="admin">Administrator: configuration and audit, no studies</option>
            </select>
          </label>
        </div>
        <p className="note caption">
          Password: at least 8 characters, with upper and lower case letters, a number and a symbol.
        </p>
        {shown.map(([k, p]) => <p key={k} className="error" role="status" data-testid={`${k}-problem`}>{p.text}</p>)}
        {mismatch && <p className="error" role="alert">The passwords do not match.</p>}
        <button type="submit" className="pill pill-primary wide" disabled={busy || mismatch || !form.username || !form.email || !form.password}>
          Create account
        </button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <Link to="/login" className="pill pill-quiet wide">Back to sign in</Link>
    </main>
  );
}
