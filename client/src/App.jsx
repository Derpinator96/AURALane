import { useCallback, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, loadSession, saveSession } from "./api.js";
import { Header, NotBuilt } from "./Chrome.jsx";
import Login from "./Login.jsx";
import Study from "./Study.jsx";
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
  const token = session?.token;
  const loadWorklist = useCallback(() => api.worklist(token), [token]);
  const loadStudy = useCallback((id) => api.study(token, id), [token]);
  const loadSeries = useCallback((id, uid) => api.series(token, id, uid), [token]);
  const sendVerdict = useCallback((id, v) => api.verdict(token, id, v), [token]);
  const radiologist = session?.user.groups.includes("radiologist");

  return (
    <>
      <Header session={session} onSignOut={onSignOut} />
      <Routes>
        <Route path="/login" element={session ? <Navigate to={home(session)} /> : <Login onLogin={onLogin} />} />
        <Route path="/" element={radiologist ? <Worklist load={loadWorklist} /> : <Navigate to={home(session)} />} />
        <Route path="/studies/:id" element={radiologist
          ? <Study load={loadStudy} loadSeries={loadSeries} sendVerdict={sendVerdict} />
          : <Navigate to={home(session)} />} />
        <Route path="/admin" element={session && !radiologist ? <NotBuilt what="Admin screens" task="Prompt 4, Task 5" /> : <Navigate to={home(session)} />} />
        <Route path="*" element={<Navigate to={home(session)} />} />
      </Routes>
    </>
  );
}
