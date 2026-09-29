import { Slot } from "../Shell.jsx";
import { ClockIcon, HistoryIcon, ReportsIcon, SettingsIcon, WorklistIcon } from "./Icons.jsx";

export default function Sidebar({
  activeNav,
  onNavChange,
  specialtyFilter,
  onSpecialtyChange,
  counts = {},
}) {
  const NAV_ITEMS = [
    { id: "worklist", label: "Worklist", icon: <WorklistIcon size={16} />, badge: counts.total },
    { id: "recent", label: "Read cases", icon: <ClockIcon size={16} />, badge: counts.recent },
    { id: "history", label: "History", icon: <HistoryIcon size={16} /> },
    { id: "reports", label: "Reports", icon: <ReportsIcon size={16} /> },
    { id: "settings", label: "Settings", icon: <SettingsIcon size={16} /> },
  ];

  const SPECIALTIES = [
    { id: "ALL", label: "All modalities", code: "ALL" },
    { id: "CR", label: "Chest radiography", code: "CXR" },
    { id: "MR", label: "Brain tumor MRI", code: "MR-T" },
    { id: "CT", label: "Head CT", code: "CT" },
  ];

  return (
    <Slot name="nav">
      <div className="nav-group" data-testid="workstation-sidebar">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`nav-item ${activeNav === item.id ? "active" : ""}`}
            aria-current={activeNav === item.id ? "page" : undefined}
            onClick={() => onNavChange(item.id)}
            data-testid={`nav-${item.id}`}
          >
            {item.icon}
            <span>{item.label}</span>
            {item.badge != null && <span className="nav-count">{item.badge}</span>}
          </button>
        ))}
      </div>

      <div className="nav-group">
        <div className="nav-label">Modality</div>
        {SPECIALTIES.map((spec) => (
          <button
            key={spec.id}
            type="button"
            className={`nav-item nav-item-quiet ${specialtyFilter === spec.id ? "active" : ""}`}
            aria-pressed={specialtyFilter === spec.id}
            onClick={() => onSpecialtyChange(spec.id)}
            data-testid={`specialty-${spec.id}`}
          >
            <span className="nav-code mono">{spec.code}</span>
            <span>{spec.label}</span>
          </button>
        ))}
      </div>
    </Slot>
  );
}
