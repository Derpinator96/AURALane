import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";

// Patient names, from the demo display layer (sim/edge/display_names.py).
//
// The API answers with a fictional name only for a patient whose source record carried a placeholder
// name, and leaves everyone else out. So a name is shown only if the API gave one, and a patient without
// one is shown by pseudonym alone, as it always was: nothing here makes a name up, and there is no
// "Unknown" or "Name unavailable" text. A failed or empty lookup changes nothing on screen.
//
// Screens ask for the pseudonyms they show (through PatientLabel, or ensure() for a whole list); the
// provider collects the asks of one moment into one request and never asks about the same id twice.
const NamesContext = createContext({ names: {}, ensure: () => {} });

export function NamesProvider({ token, children }) {
  const [names, setNames] = useState({});
  const asked = useRef(new Set());
  const queue = useRef(new Set());
  const timer = useRef(null);

  const flush = useCallback(async () => {
    timer.current = null;
    const ids = [...queue.current];
    queue.current = new Set();
    for (let i = 0; i < ids.length; i += 200) {
      try {
        const r = await api.resolveNames(token, ids.slice(i, i + 200));
        if (r?.patients && Object.keys(r.patients).length) setNames((n) => ({ ...n, ...r.patients }));
      } catch {
        // A name is a convenience. The pseudonym stays on screen.
      }
    }
  }, [token]);

  const ensure = useCallback((ids) => {
    let added = false;
    for (const id of ids) {
      if (id && !asked.current.has(id)) {
        asked.current.add(id);
        queue.current.add(id);
        added = true;
      }
    }
    if (added && !timer.current) timer.current = setTimeout(flush, 40);
  }, [flush]);

  const value = useMemo(() => ({ names, ensure }), [names, ensure]);
  return <NamesContext.Provider value={value}>{children}</NamesContext.Provider>;
}

export const useNames = () => useContext(NamesContext);

// The API's entry for one pseudonym ({name, dob, sex, source}), or null. Asks for it.
export function usePatientName(id) {
  const { names, ensure } = useContext(NamesContext);
  useEffect(() => { ensure([id]); }, [id, ensure]);
  return (id && names[id]) || null;
}

// A patient as a row shows it. Named: the name, and the pseudonym under it. Not named: the pseudonym in
// the same place and the same style as a named row's, nothing else. `inline` puts them on one line;
// `detail` adds sex and date of birth, only where the identity map had them.
export function PatientLabel({ id, fallback, inline = false, detail = false }) {
  const who = usePatientName(id);
  const shown = id || fallback;
  if (!who) return <span className="patient-id mono-id">{shown}</span>;
  const demo = [who.sex, who.dob && `born ${who.dob}`].filter(Boolean).join(", ");
  return (
    <span className={`patient-label${inline ? " inline" : ""}`} data-named="true">
      <span className="patient-name" title={`${who.name}. A fictional name from the demo layer.`}>{who.name}</span>
      <span className="patient-id mono-id">{shown}</span>
      {detail && demo && <span className="patient-demo">{demo}</span>}
    </span>
  );
}
