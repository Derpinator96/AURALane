import { useCallback, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, loadSession, saveSession } from "./api.js";
import Admin from "./Admin.jsx";
import { Privacy, Terms } from "./Legal.jsx";
import Login from "./Login.jsx";
import RequestAccess from "./RequestAccess.jsx";
import Shell from "./Shell.jsx";
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
  const loadIntake = useCallback(() => api.intake(token), [token]);
  const startIntake = useCallback((count) => api.startIntake(token, count), [token]);
  const loadAccess = useCallback(() => api.accessRequests(token), [token]);
  const saveDraft = useCallback((id, text, reviewed) => api.saveDraft(token, id, text, reviewed), [token]);
  const loadPipeline = useCallback(() => api.pipeline(token), [token]);
  const loadPipelineStudy = useCallback((id) => api.pipelineStudy(token, id), [token]);
  const loadAssignments = useCallback(() => api.assignments(token), [token]);
  const reassign = useCallback((id, reader) => api.reassign(token, id, reader), [token]);
  const decideAccess = useCallback((u, d) => api.decideAccess(token, u, d), [token]);
  const radiologist = session?.user.groups.includes("radiologist");

  return (
    <Shell session={session} onSignOut={onSignOut}>
      <Routes>
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/request-access" element={session ? <Navigate to={home(session)} />
                                                       : <RequestAccess request={api.requestAccess} />} />
        <Route path="/login" element={session ? <Navigate to={home(session)} /> : <Login onLogin={onLogin} />} />
        <Route path="/" element={radiologist ? <Worklist load={loadWorklist} token={token} /> : <Navigate to={home(session)} />} />
        <Route path="/studies/:id" element={radiologist
          ? <Study load={loadStudy} loadSeries={loadSeries} sendVerdict={sendVerdict}
                   saveDraft={saveDraft} token={token} />
          : <Navigate to={home(session)} />} />
        <Route path="/admin/*" element={session && !radiologist
          ? <Admin loadAudit={loadAudit} loadLaneMix={loadLaneMix} loadModels={loadModels}
                   loadIntake={loadIntake} startIntake={startIntake}
                   superadmin={session?.user.groups.includes("superadmin")}
                   loadAccess={loadAccess} decideAccess={decideAccess}
                   loadPipeline={loadPipeline} loadPipelineStudy={loadPipelineStudy}
                   loadAssignments={loadAssignments} reassign={reassign} />
          : <Navigate to={home(session)} />} />
        <Route path="*" element={<Navigate to={home(session)} />} />
      </Routes>
    </Shell>
  );
}
