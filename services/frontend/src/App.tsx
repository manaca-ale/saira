import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
  useLocation,
} from "react-router-dom";
import { Login } from "./pages/Login";
import { ConectaCallback } from "./pages/ConectaCallback";
import { Dashboard } from "./pages/Dashboard";
import { Detections } from "./pages/Detections";
import { UsersPage } from "./pages/UsersPage";
import { HistoryPage } from "./pages/HistoryPage";
import { CamerasSettingsPage } from "./pages/CamerasSettingsPage";
import { CameraSnapshotsPage } from "./pages/CameraSnapshotsPage";
import { IndicadoresPage } from "./pages/IndicadoresPage";
import { LabelingPage } from "./pages/LabelingPage";
import { SetPasswordPage } from "./pages/SetPasswordPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { NotificationDrawer } from "./components/NotificationDrawer";
import { NotificationToastContainer } from "./components/NotificationToast";
import { labelingEnabled } from "./config/features";
import { useAuth } from "./contexts/AuthContext";
import type { ReactNode } from "react";

// Páginas só de administrador: quem não é volta para o painel.
function AdminOnly({ children }: { children: ReactNode }) {
  const { isAdmin, loading } = useAuth();
  if (loading) return null;
  return isAdmin ? <>{children}</> : <Navigate to="/dashboard" replace />;
}

// Senha provisória: leva para /trocar-senha antes de qualquer outra tela
// (o backend também bloqueia as rotas até a troca).
const PASSWORD_FREE_PATHS = ["/", "/login", "/login/callback", "/definir-senha", "/trocar-senha"];

function ForcePasswordChange() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  if (user?.must_change_password && !PASSWORD_FREE_PATHS.includes(pathname)) {
    return <Navigate to="/trocar-senha" replace />;
  }
  return null;
}

function App() {
  return (
    <div className="fixed inset-0 w-[125%] h-[125vh] origin-top-left scale-[0.8] overflow-hidden bg-[#f8f9fa]">
      <Router>
        <ForcePasswordChange />
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/login" element={<Login />} />
          <Route path="/login/callback" element={<ConectaCallback />} />
          <Route path="/definir-senha" element={<SetPasswordPage />} />
          <Route path="/trocar-senha" element={<ChangePasswordPage />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/indicadores" element={<IndicadoresPage />} />
          <Route path="/detections" element={<Detections />} />
          {labelingEnabled && (
            <Route path="/rotulagem" element={<LabelingPage />} />
          )}
          <Route path="/users" element={<AdminOnly><UsersPage /></AdminOnly>} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/cameras" element={<CameraSnapshotsPage />} />
          <Route path="/settings/cameras" element={<AdminOnly><CamerasSettingsPage /></AdminOnly>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <NotificationDrawer />
        <NotificationToastContainer />
      </Router>
    </div>
  );
}

export default App;
