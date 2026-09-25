import { useCallback, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, loadSession, saveSession } from "./api.js";
import Admin from "./Admin.jsx";
import { Header } from "./Chrome.jsx";
import { Footer, Privacy, Terms } from "./Legal.jsx";
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
  const loadAudit = useCallback(() => api.audit(token), [token]);
  const loadLaneMix = useCallback(() => api.laneMix(token), [token]);
  const loadModels = useCallback(() => api.models(token), [token]);
  const radiologist = session?.user.groups.includes("radiologist");

  return (
    <>
      <Header session={session} onSignOut={onSignOut} />
      <Routes>
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/login" element={session ? <Navigate to={home(session)} /> : <Login onLogin={onLogin} />} />
        <Route path="/" element={radiologist ? <Worklist load={loadWorklist} /> : <Navigate to={home(session)} />} />
        <Route path="/studies/:id" element={radiologist
          ? <Study load={loadStudy} loadSeries={loadSeries} sendVerdict={sendVerdict} />
          : <Navigate to={home(session)} />} />
        <Route path="/admin/*" element={session && !radiologist
          ? <Admin loadAudit={loadAudit} loadLaneMix={loadLaneMix} loadModels={loadModels} />
          : <Navigate to={home(session)} />} />
        <Route path="*" element={<Navigate to={home(session)} />} />
      </Routes>
      <Footer />
    </>
  );
}
