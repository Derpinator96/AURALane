import { Slot } from "../Shell.jsx";

// The worklist's tabs, placed in the top bar's nav slot. (The old sidebar's modality
// list is now a filter on the worklist card; SPECIALTIES is shared with it.)

export const SPECIALTIES = [
  { id: "ALL", label: "All" },
  { id: "CR", label: "Chest X-ray" },
  { id: "MR", label: "Brain MRI" },
  { id: "CT", label: "Head CT" },
];

export const TITLES = { worklist: "Worklist", recent: "Read cases", opinions: "Second opinions", history: "History", reports: "Reports", settings: "Settings" };

export default function Sidebar({ activeNav, onNavChange, counts = {} }) {
  const items = [
    { id: "worklist", badge: counts.total },
    { id: "recent", badge: counts.recent },
    { id: "opinions", badge: counts.opinions || undefined },
    { id: "history" },
    { id: "reports" },
    { id: "settings" },
  ];
  return (
    <Slot name="nav">
      <div className="seg" role="group" aria-label="Sections" data-testid="workstation-sidebar">
        {items.map((item) => (
          <button key={item.id} type="button" aria-current={activeNav === item.id ? "page" : undefined}
                  onClick={() => onNavChange(item.id)} data-testid={`nav-${item.id}`}>
            {TITLES[item.id]}
            {item.badge != null && <span className="count mono nav-count">{item.badge}</span>}
          </button>
        ))}
      </div>
    </Slot>
  );
}
