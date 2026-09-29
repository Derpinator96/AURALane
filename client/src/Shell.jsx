import { createContext, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { ADMIN_GROUPS, ADMIN_TABS } from "./Admin.jsx";
import { Banner, ThemeToggle } from "./Chrome.jsx";
import { BrandLogo, CloseIcon, MenuIcon, SearchIcon } from "./components/Icons.jsx";
import { Monogram, PopoverButton } from "./components/ui.jsx";
import { useMediaQuery } from "./hooks.js";
import { Footer } from "./Legal.jsx";

// The app frame: a frosted window on the field, a floating top bar and a scrolling body.
// The worklist puts its own tabs into the bar through <Slot name="nav">. Outside a
// frame (unit tests that render one screen alone) a Slot renders its children in place.

const SlotContext = createContext({});

export function Slot({ name, children }) {
  const node = useContext(SlotContext)[name];
  return node ? createPortal(children, node) : children;
}

export function titleFor(pathname) {
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

// Admin destinations, in the bar. Wide screens list every tab; a narrower bar folds
// them into an Operations and a Model menu.
function AdminNav({ superadmin, compact }) {
  const groups = superadmin ? ADMIN_GROUPS : ADMIN_GROUPS.filter((g) => g.label !== "Access");
  if (!compact) {
    return (
      <div className="seg topnav-seg">
        {groups.flatMap((g) => g.tabs).map(([path, label]) => (
          <NavLink key={path} to={`/admin/${path}`}>{label}</NavLink>
        ))}
      </div>
    );
  }
  return (
    <div className="topnav-menus">
      {groups.map((g) => (
        <PopoverButton key={g.label} label={g.label} align="left" menu chevron>
          {(close) => g.tabs.map(([path, label]) => (
            <NavLink key={path} to={`/admin/${path}`} className="pop-item" onClick={close}>{label}</NavLink>
          ))}
        </PopoverButton>
      ))}
    </div>
  );
}

function UserMenu({ session, onSignOut }) {
  const groups = session.user.groups || [];
  const name = String(session.user.email || "").replace(/@.*/, "");
  return (
    <PopoverButton align="right" menu chevron pillProps={{ className: "pill user-pill", "data-testid": "user-menu" }}
                   icon={<Monogram name={name} />}
                   label={<span className="user-name">{name}</span>}>
      {() => (
        <>
          <div className="pop-label" title={session.user.email}>{session.user.email}</div>
          <div className="user-groups">{groups.map((g) => <span key={g} className="chip chip-quiet role">{g}</span>)}</div>
          <button type="button" className="pop-item" role="menuitem" onClick={onSignOut}>Sign out</button>
        </>
      )}
    </PopoverButton>
  );
}

function TopBar({ session, onSignOut, setNav }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const compact = useMediaQuery("(min-width: 721px) and (max-width: 1360px)");
  const groups = session.user.groups || [];
  const isRadiologist = groups.includes("radiologist");

  useEffect(() => { setMenuOpen(false); }, [pathname]);

  const search = () => {
    if (pathname !== "/") navigate("/", { state: { focusSearch: true } });
    else window.dispatchEvent(new CustomEvent("auralane:search"));
  };

  return (
    <header className={`topbar ${menuOpen ? "menu-open" : ""}`}>
      <Link to={isRadiologist ? "/" : "/admin"} className="brand"><BrandLogo size={24} /><span>AURALane</span></Link>
      <nav className="topnav" aria-label="Main" onClick={(e) => { if (e.target.closest("button, a")) setMenuOpen(false); }}>
        {isRadiologist && pathname === "/" && <div ref={setNav} className="nav-slot" />}
        {isRadiologist && pathname !== "/" && (
          <div className="seg"><NavLink to="/" end>Worklist</NavLink></div>
        )}
        {!isRadiologist && <AdminNav superadmin={groups.includes("superadmin")} compact={compact} />}
      </nav>
      <div className="topbar-right">
        {isRadiologist && (
          <button type="button" className="circle" aria-label="Search the worklist" title="Search the worklist" onClick={search}>
            <SearchIcon size={18} />
          </button>
        )}
        <ThemeToggle />
        <Banner />
        <UserMenu session={session} onSignOut={onSignOut} />
        <button type="button" className="circle menu-toggle" aria-label={menuOpen ? "Close menu" : "Open menu"}
                aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
          {menuOpen ? <CloseIcon size={18} /> : <MenuIcon size={18} />}
        </button>
      </div>
    </header>
  );
}

export default function Shell({ session, onSignOut, children }) {
  const { pathname } = useLocation();
  const [nav, setNav] = useState(null);

  // The worklist names its own tabs; every other screen is named by its route.
  useEffect(() => {
    if (pathname !== "/") document.title = `${titleFor(pathname)} · AURALane`;
  }, [pathname]);

  if (!session) {
    return (
      <div className="app app-bare">
        <div className="frame">
          <div className="bare-bar">
            <Link to="/login" className="brand"><BrandLogo size={24} /><span>AURALane</span></Link>
            <span className="spacer" />
            <Banner />
            <ThemeToggle />
          </div>
          <div className="bare-body"><div className="bare-card">{children}</div></div>
          <Footer />
        </div>
      </div>
    );
  }

  return (
    <SlotContext.Provider value={{ nav }}>
      <div className="app">
        <div className="frame">
          <div className="frame-body" data-testid="frame-body">
            <TopBar session={session} onSignOut={onSignOut} setNav={setNav} />
            {children}
          </div>
          <Footer />
        </div>
      </div>
    </SlotContext.Provider>
  );
}
