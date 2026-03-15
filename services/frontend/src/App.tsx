import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { Login } from "./pages/Login";
import { ConectaCallback } from "./pages/ConectaCallback";
import { Dashboard } from "./pages/Dashboard";
import { Detections } from "./pages/Detections";
import { UsersPage } from "./pages/UsersPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NotificationDrawer } from "./components/NotificationDrawer";
import { NotificationToastContainer } from "./components/NotificationToast";

function App() {
  return (
    <div className="fixed inset-0 w-[125%] h-[125vh] origin-top-left scale-[0.8] overflow-hidden bg-[#f8f9fa]">
      <Router>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/login" element={<Login />} />
          <Route path="/login/callback" element={<ConectaCallback />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/detections" element={<Detections />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <NotificationDrawer />
        <NotificationToastContainer />
      </Router>
    </div>
  );
}

export default App;
