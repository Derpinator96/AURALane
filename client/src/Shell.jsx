import { createContext, useContext, useState } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ADMIN_GROUPS, ADMIN_TABS } from "./Admin.jsx";
import { Banner, ThemeToggle } from "./Chrome.jsx";
import {
  ActivityIcon, BrandLogo, GaugeIcon, InboxIcon, ModelIcon, PlayIcon,
  ScrollIcon, SidebarIcon, SlidersIcon, UsersIcon, WorklistIcon,
} from "./components/Icons.jsx";
import { Footer } from "./Legal.jsx";

// The app frame: a sidebar on the canvas and a white sheet with a top bar.
// Screens put their own navigation and actions into the frame through
// <Slot name="nav"> and <Slot name="actions">. Outside a frame (unit tests
// that render one screen alone) a Slot renders its children in place.

const SlotContext = createContext({});

export function Slot({ name, children }) {
  const node = useContext(SlotContext)[name];
  return node ? createPortal(children, node) : children;
}

const ADMIN_ICONS = {
  pipeline: ActivityIcon, assignments: UsersIcon, audit: ScrollIcon, lanes: GaugeIcon,
  thresholds: SlidersIcon, models: ModelIcon, intake: PlayIcon, access: InboxIcon,
};

function titleFor(pathname) {
  if (pathname === "/") return "Worklist";
  if (pathname.startsWith("/studies/")) return "Study";
  if (pathname.startsWith("/admin")) {
    const tab = ADMIN_TABS.concat([["access", "Waitlist"]]).find(([p]) => pathname.startsWith(`/admin/${p}`));
    return tab ? tab[1] : "Cloud console";
  }
  if (pathname === "/login") return "Sign in";
  if (pathname === "/request-access") return "Request access";
  if (pathname === "/privacy") return "Privacy";
  if (pathname === "/terms") return "Terms";
  return "";
}

function AdminNav({ superadmin }) {
  const groups = superadmin ? ADMIN_GROUPS : ADMIN_GROUPS.filter((g) => g.label !== "Access");
  return (
    <>
      {groups.map((g) => (
        <div key={g.label} className="nav-group">
          <div className="nav-label">{g.label}</div>
          {g.tabs.map(([path, label]) => {
            const Ico = ADMIN_ICONS[path];
            return (
              <NavLink key={path} to={`/admin/${path}`} className="nav-item">
                <Ico size={16} /><span>{label}</span>
              </NavLink>
            );
          })}
        </div>
      ))}
    </>
  );
}

export default function Shell({ session, onSignOut, children }) {
  const { pathname } = useLocation();
  const [nav, setNav] = useState(null);
  const [actions, setActions] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const groups = session?.user?.groups || [];
  const isRadiologist = groups.includes("radiologist");

  if (!session) {
    return (
      <div className="app app-bare">
        <div className="bare-bar">
          <Link to="/login" className="brand"><BrandLogo size={20} /><span>AURALane</span></Link>
          <Banner />
          <ThemeToggle />
        </div>
        <div className="bare-sheet">{children}</div>
        <Footer />
      </div>
    );
  }

  return (
    <SlotContext.Provider value={{ nav, actions }}>
      <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
        <aside className="shell-sidebar" aria-label="Sidebar">
          <Link to={isRadiologist ? "/" : "/admin"} className="brand">
            <BrandLogo size={20} /><span>AURALane</span>
          </Link>
          <nav className="shell-nav" aria-label="Main">
            {isRadiologist && pathname === "/" && <div ref={setNav} className="nav-slot" />}
            {isRadiologist && pathname !== "/" && (
              <NavLink to="/" className="nav-item" end><WorklistIcon size={16} /><span>Worklist</span></NavLink>
            )}
            {!isRadiologist && <AdminNav superadmin={groups.includes("superadmin")} />}
          </nav>
          <div className="shell-user">
            <span className="user-email mono" title={session.user.email}>{session.user.email}</span>
            <span className="user-roles">
              {groups.map((g) => <span key={g} className="role">{g}</span>)}
            </span>
            <button type="button" className="btn" onClick={onSignOut}>Sign out</button>
          </div>
        </aside>

        <div className="sheet">
          <header className="topbar">
            <button type="button" className="icon-btn" onClick={() => setCollapsed((v) => !v)}
                    aria-label="Toggle sidebar" aria-pressed={collapsed} title="Toggle sidebar">
              <SidebarIcon size={16} />
            </button>
            <span className="topbar-rule" aria-hidden="true" />
            <span className="topbar-title">{titleFor(pathname)}</span>
            <span className="topbar-spacer" />
            <Banner />
            <div ref={setActions} className="topbar-actions" />
            <ThemeToggle />
          </header>
          <div className="sheet-body">{children}</div>
          <Footer />
        </div>
      </div>
    </SlotContext.Provider>
  );
}
