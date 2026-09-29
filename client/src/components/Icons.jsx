// One thin line-icon set: 24px grid, 1.5px stroke, currentColor. Icons label a
// nav item, a metadata row or an action; nothing here is decoration.

function Icon({ size = 16, className = "", children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}
         aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export function BrandLogo({ size = 20, className = "" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="var(--ink)" />
      <path d="M12 6.5v11M6.5 12h11" stroke="var(--on-ink)" strokeWidth="1.6" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export const WorklistIcon = (p) => (
  <Icon {...p}><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8 9h8M8 12.5h8M8 16h5" /></Icon>
);
export const ClockIcon = (p) => (
  <Icon {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></Icon>
);
export const HistoryIcon = (p) => (
  <Icon {...p}><path d="M6 3.5h8l4 4v13H6z" /><path d="M14 3.5v4h4M9 12h6M9 15.5h6" /></Icon>
);
export const ReportsIcon = (p) => (
  <Icon {...p}><path d="M5 20V10M12 20V4M19 20v-7" /></Icon>
);
export const SettingsIcon = (p) => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" /></Icon>
);
export const SearchIcon = (p) => (
  <Icon {...p}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></Icon>
);
export const UploadIcon = (p) => (
  <Icon {...p}><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4M12 4v11M8 8l4-4 4 4" /></Icon>
);
export const AnalyseIcon = (p) => (
  <Icon {...p}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="2.5" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" /></Icon>
);
export const CheckIcon = (p) => (
  <Icon {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>
);
export const CloseIcon = (p) => (
  <Icon {...p}><path d="M6 6l12 12M18 6L6 18" /></Icon>
);

// Shell and worklist
export const SidebarIcon = (p) => (
  <Icon {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><path d="M9.5 4.5v15" /></Icon>
);
export const ListIcon = (p) => (
  <Icon {...p}><path d="M8 7h11M8 12h11M8 17h11M4.5 7h.01M4.5 12h.01M4.5 17h.01" /></Icon>
);
export const BoardIcon = (p) => (
  <Icon {...p}><rect x="4" y="4.5" width="4.5" height="15" rx="1.5" /><rect x="10" y="4.5" width="4.5" height="9" rx="1.5" /><rect x="16" y="4.5" width="4" height="12" rx="1.5" /></Icon>
);
export const UserIcon = (p) => (
  <Icon {...p}><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c.6-3.4 3.4-5.5 7-5.5s6.4 2.1 7 5.5" /></Icon>
);
export const CalendarIcon = (p) => (
  <Icon {...p}><rect x="4" y="5.5" width="16" height="14" rx="2.5" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></Icon>
);
export const GaugeIcon = (p) => (
  <Icon {...p}><path d="M4 16a8 8 0 1 1 16 0" /><path d="M12 16l3.5-5" /></Icon>
);
export const PlayIcon = (p) => (
  <Icon {...p}><path d="M8 5.5v13l10-6.5z" /></Icon>
);
export const ActivityIcon = (p) => (
  <Icon {...p}><path d="M3 12h4l3-7 4 14 3-7h4" /></Icon>
);
export const UsersIcon = (p) => (
  <Icon {...p}><circle cx="9" cy="9" r="3" /><path d="M3.5 19c.5-3 2.7-4.7 5.5-4.7s5 1.7 5.5 4.7M16 6.5a3 3 0 0 1 0 5.5M17.5 14.5c1.7.5 2.7 2 3 4.5" /></Icon>
);
export const ScrollIcon = (p) => (
  <Icon {...p}><path d="M7 4.5h10a2 2 0 0 1 2 2V19H9a2 2 0 0 1-2-2z" /><path d="M7 17V6.5M11 9h5M11 12.5h5" /></Icon>
);
export const SlidersIcon = (p) => (
  <Icon {...p}><path d="M5 6h6M15 6h4M5 12h2M11 12h8M5 18h9M18 18h1" /><circle cx="13" cy="6" r="1.8" /><circle cx="9" cy="12" r="1.8" /><circle cx="16" cy="18" r="1.8" /></Icon>
);
export const ModelIcon = (p) => (
  <Icon {...p}><path d="M12 3.5l7.5 4.2v8.6L12 20.5l-7.5-4.2V7.7z" /><path d="M12 12l7.5-4.3M12 12L4.5 7.7M12 12v8.5" /></Icon>
);
export const InboxIcon = (p) => (
  <Icon {...p}><path d="M4 13l2.5-7.5h11L20 13v5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z" /><path d="M4 13h4.5l1 2.5h5l1-2.5H20" /></Icon>
);
export const MoonIcon = (p) => (
  <Icon {...p}><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" /></Icon>
);
export const SunIcon = (p) => (
  <Icon {...p}><circle cx="12" cy="12" r="3.8" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" /></Icon>
);
export const ChevronIcon = (p) => (
  <Icon {...p}><path d="M9 6l6 6-6 6" /></Icon>
);
export const ChevronDownIcon = (p) => (
  <Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>
);
export const ArrowUpRightIcon = (p) => (
  <Icon {...p}><path d="M7 17L17 7M8.5 7H17v8.5" /></Icon>
);
export const PlusIcon = (p) => (
  <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>
);
export const MenuIcon = (p) => (
  <Icon {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Icon>
);
export const PinIcon = (p) => (
  <Icon {...p}><path d="M12 21s6.5-5.6 6.5-11a6.5 6.5 0 1 0-13 0c0 5.4 6.5 11 6.5 11z" /><circle cx="12" cy="10" r="2.3" /></Icon>
);
export const CopyIcon = (p) => (
  <Icon {...p}><rect x="8.5" y="8.5" width="11" height="11" rx="2.5" /><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5" /></Icon>
);
export const PrintIcon = (p) => (
  <Icon {...p}><path d="M7 9V4h10v5M7 17H5a1.5 1.5 0 0 1-1.5-1.5v-5A1.5 1.5 0 0 1 5 9h14a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 19 17h-2" /><rect x="7" y="14" width="10" height="6" rx="1.5" /></Icon>
);
export const EyeIcon = (p) => (
  <Icon {...p}><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></Icon>
);
export const RefreshIcon = (p) => (
  <Icon {...p}><path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5" /></Icon>
);
export const AlertIcon = (p) => (
  <Icon {...p}><path d="M12 4.5l8.5 15h-17z" /><path d="M12 10v4.5M12 17.2v.01" /></Icon>
);
export const FilterIcon = SlidersIcon;
