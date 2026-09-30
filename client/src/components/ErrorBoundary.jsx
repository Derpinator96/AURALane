import { Component, lazy, Suspense, useMemo, useState } from "react";
import { RefreshIcon } from "./Icons.jsx";

// Catches a render error or a failed lazy import below it, so one broken piece (a
// viewer chunk that will not load) shows a message in its own place instead of
// unmounting the whole app.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) { return { error }; }

  componentDidCatch(error) {
    console.error("Caught by an error boundary:", error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const reset = () => { this.setState({ error: null }); this.props.onRetry?.(); };
    return this.props.fallback ? this.props.fallback({ error, reset }) : <Failed what="This part" onRetry={reset} />;
  }
}

export function Failed({ what = "Viewer", onRetry }) {
  return (
    <div className="failed" role="alert" data-testid="load-failed">
      <span>{what} failed to load</span>
      <span aria-hidden="true">·</span>
      <button type="button" className="pill pill-sm" onClick={onRetry}><RefreshIcon size={14} />Retry</button>
    </div>
  );
}

// A lazily imported view with its own boundary. Retry imports it again. `load` must be a
// stable function, for example () => import("./viewer/Viewer.jsx") defined at module level.
export function LazyView({ load, what = "Viewer", fallback = null, ...props }) {
  const [attempt, setAttempt] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const View = useMemo(() => lazy(load), [load, attempt]);
  return (
    <ErrorBoundary key={attempt} fallback={() => <Failed what={what} onRetry={() => setAttempt((a) => a + 1)} />}>
      <Suspense fallback={fallback}><View {...props} /></Suspense>
    </ErrorBoundary>
  );
}
