// The half-ring gauge. Colours come from tokens through CSS classes; nothing here is
// drawn from a number that did not come from a row.

// A half ring of ticks: the read share is filled; the unread count sits in the middle.
export function Gauge({ read, unread }) {
  const total = read + unread;
  const N = 30, cx = 130, cy = 128, r0 = 82, r1 = 112;
  const filled = total ? Math.round((read / total) * N) : 0;
  return (
    <div className="gauge">
      <svg viewBox="0 0 260 142" role="img" aria-label={`${unread} unread, ${read} read`}>
        {Array.from({ length: N }, (_, i) => {
          const a = Math.PI - (i / (N - 1)) * Math.PI;
          const c = Math.cos(a), s = Math.sin(a);
          return (
            <line key={i} className={i < filled ? "tick on" : "tick"} x1={cx + r0 * c} y1={cy - r0 * s}
                  x2={cx + r1 * c} y2={cy - r1 * s} strokeLinecap="round" />
          );
        })}
      </svg>
      <div className="gauge-centre">
        <span className="gauge-number">{unread}</span>
        <span className="meta">unread</span>
      </div>
    </div>
  );
}
