import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Detections } from "./pages/Detections";
import { UsersPage } from "./pages/UsersPage";

function App() {
  return (
    // Responsive Fix:
    // We maintain the scale-[0.8] for that specific look you requested.
    // However, we ensure 'overflow-hidden' handles the layout correctly.
    // The previous structure is generally solid, but the DASHBOARD grid fix above
    // is the real key to solving the missing map.
    <div className="fixed inset-0 w-[125%] h-[125vh] origin-top-left scale-[0.8] overflow-hidden bg-[#1a1a1a]">
      <Router>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/detections" element={<Detections />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </div>
  );
}

export default App;
