import { useCallback, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, loadSession, saveSession } from "./api.js";
import { Header, NotBuilt } from "./Chrome.jsx";
import Login from "./Login.jsx";
import Worklist from "./Worklist.jsx";

// Screens follow the account's group. This is navigation only: the API
// refuses an admin token on study routes and a radiologist token on admin
// routes regardless of what the browser shows.
const home = (session) =>
  !session ? "/login" : session.user.groups.includes("radiologist") ? "/" : "/admin";

export default function App() {
  const [session, setSession] = useState(loadSession);
  const navigate = useNavigate();

  const onLogin = (s) => { saveSession(s); setSession(s); navigate(home(s)); };
  const onSignOut = () => { saveSession(null); setSession(null); navigate("/login"); };
  const loadWorklist = useCallback(() => api.worklist(session?.token), [session]);
  const radiologist = session?.user.groups.includes("radiologist");

  return (
    <>
      <Header session={session} onSignOut={onSignOut} />
      <Routes>
        <Route path="/login" element={session ? <Navigate to={home(session)} /> : <Login onLogin={onLogin} />} />
        <Route path="/" element={radiologist ? <Worklist load={loadWorklist} /> : <Navigate to={home(session)} />} />
        <Route path="/studies/:id" element={radiologist ? <NotBuilt what="Study detail and viewer" task="Prompt 4, Task 3" /> : <Navigate to={home(session)} />} />
        <Route path="/admin" element={session && !radiologist ? <NotBuilt what="Admin screens" task="Prompt 4, Task 5" /> : <Navigate to={home(session)} />} />
        <Route path="*" element={<Navigate to={home(session)} />} />
      </Routes>
    </>
  );
}
