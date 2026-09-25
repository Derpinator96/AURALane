// Shared page frame. The non-diagnostic statement is part of the frame, so no
// screen, login included, can render without it.

export function Banner() {
  return (
    <div className="banner" role="note" aria-label="Non-diagnostic notice">
      NON-DIAGNOSTIC. DECISION SUPPORT ONLY.
    </div>
  );
}

export function Header({ session, onSignOut }) {
  return (
    <header className="top">
      <span className="brand">AURALane</span>
      <Banner />
      {session && (
        <span className="who">
          <span className="mono">{session.user.email}</span>
          {session.user.groups.map((g) => (
            <span key={g} className="role">[{g}]</span>
          ))}
          <button type="button" onClick={onSignOut}>Sign out</button>
        </span>
      )}
    </header>
  );
}

export function NotBuilt({ what, task }) {
  return (
    <main className="notbuilt">
      <h1>{what}: not built yet</h1>
      <p>Scheduled for {task}.</p>
    </main>
  );
}
