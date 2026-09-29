// Three small SVG charts. Colours come from tokens through CSS classes; nothing
// here is drawn from a number that did not come from a row.

// Waiting studies per lane: one thin bar each, in the lane's own colour.
export function MiniBars({ items, label }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="minibars" role="img" aria-label={label}>
      {items.map((i) => (
        <span key={i.key} className={`minibar lane-${i.key}`} title={`${i.label}: ${i.value}`}>
          <span className="minibar-fill" style={{ height: `${Math.max(i.value ? 14 : 4, (i.value / max) * 100)}%` }} />
        </span>
      ))}
    </div>
  );
}

const SERIES_CLASS = ["series-a", "series-b", "series-c"];

// Stacked bars, one per UTC hour. The first pool is blue, the second navy.
export function ArrivalsChart({ hours, pools, max }) {
  const W = 640, H = 176, L = 30, B = 24, T = 8;
  const top = Math.max(2, max);
  const bw = (W - L - 6) / 24;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const ticks = [0, Math.round(top / 2), top].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <svg className="arrivals" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Studies arrived per hour, split by reading pool">
      {ticks.map((v) => (
        <text key={v} x={L - 8} y={y(v) + 4} textAnchor="end" className="axis">{v}</text>
      ))}
      {hours.map((h) => {
        let acc = 0;
        return (
          <g key={h.hour}>
            <title>{`${String(h.hour).padStart(2, "0")}:00 UTC, ${h.total} ${h.total === 1 ? "study" : "studies"}`}</title>
            {pools.map((p, i) => {
              const n = h.counts[p] || 0;
              if (!n) return null;
              const y1 = y(acc + n), y0 = y(acc);
              acc += n;
              return (
                <rect key={p} className={SERIES_CLASS[i % SERIES_CLASS.length]} x={L + h.hour * bw + bw * 0.16}
                      width={bw * 0.68} y={y1} height={Math.max(2, y0 - y1 - 1)} rx={Math.min(5, bw * 0.3)} />
              );
            })}
            {h.hour % 4 === 0 && (
              <text x={L + h.hour * bw + bw / 2} y={H - 6} textAnchor="middle" className="axis">
                {String(h.hour).padStart(2, "0")}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

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
