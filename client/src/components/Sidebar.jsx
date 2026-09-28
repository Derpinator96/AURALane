import {
  BrandLogo,
  ClockIcon,
  HistoryIcon,
  ReportsIcon,
  SettingsIcon,
  WorklistIcon,
} from "./Icons.jsx";

export default function Sidebar({
  activeNav,
  onNavChange,
  specialtyFilter,
  onSpecialtyChange,
  counts = {},
}) {
  const NAV_ITEMS = [
    { id: "worklist", label: "AI Worklist", icon: <WorklistIcon size={16} />, badge: counts.total },
    { id: "recent", label: "Read Cases", icon: <ClockIcon size={16} />, badge: counts.recent },
    { id: "history", label: "All Cases / Patient History", icon: <HistoryIcon size={16} /> },
    { id: "reports", label: "Reports", icon: <ReportsIcon size={16} /> },
    { id: "settings", label: "Settings", icon: <SettingsIcon size={16} /> },
  ];

  const SPECIALTIES = [
    { id: "ALL", label: "All Modalities", code: "ALL" },
    { id: "CR", label: "Chest Radiography", code: "CXR" },
    { id: "MR", label: "Brain Tumor MRI", code: "MR-T" },
    { id: "CT", label: "Head CT", code: "CT" },
  ];

  return (
    <aside className="workstation-sidebar" data-testid="workstation-sidebar">
      <div className="sidebar-brand-section">
        <BrandLogo size={22} className="brand-logo-svg" />
        <div>
          <h1 className="brand-name">AURALane</h1>
          <span className="brand-badge">Clinician Workstation</span>
        </div>
      </div>

      <div className="sidebar-section-title">CLINICAL NAVIGATION</div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar-nav-btn ${activeNav === item.id ? "active" : ""}`}
            onClick={() => onNavChange(item.id)}
            data-testid={`nav-${item.id}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
            {item.badge != null && <span className="nav-badge">{item.badge}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-section-title">READING SPECIALTY</div>
      <div className="sidebar-specialties">
        {SPECIALTIES.map((spec) => (
          <button
            key={spec.id}
            type="button"
            className={`specialty-pill ${specialtyFilter === spec.id ? "active" : ""}`}
            onClick={() => onSpecialtyChange(spec.id)}
            data-testid={`specialty-${spec.id}`}
          >
            <span className="spec-code-tag">{spec.code}</span>
            <span className="spec-label">{spec.label}</span>
          </button>
        ))}
      </div>

    </aside>
  );
}
