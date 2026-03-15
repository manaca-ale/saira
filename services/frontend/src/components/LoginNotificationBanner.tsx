import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, X, ArrowRight } from "lucide-react";
import { useNotifications } from "../contexts/NotificationContext";

const AUTO_DISMISS_MS = 30000;

export const LoginNotificationBanner: React.FC = () => {
  const { sinceLastLogin, bannerDismissed, dismissBanner } = useNotifications();
  const navigate = useNavigate();

  const [visible, setVisible] = useState(() => !bannerDismissed && sinceLastLogin > 0);

  useEffect(() => {
    if (bannerDismissed || sinceLastLogin <= 0) {
      setVisible(false);
      return;
    }
    const timer = setTimeout(() => {
      dismissBanner();
      setVisible(false);
    }, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDismiss = () => {
    dismissBanner();
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3.5 mb-5 flex items-center gap-4">
      <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
        <AlertTriangle size={18} className="text-amber-600" />
      </div>
      <div className="flex-1">
        <p className="text-sm text-amber-900">
          Desde seu último acesso,{" "}
          <span className="font-bold">{sinceLastLogin} novas ocorrências</span>{" "}
          foram registradas.
        </p>
      </div>
      <button
        onClick={() => navigate("/detections?status=Pendente")}
        className="flex items-center gap-1.5 text-sm font-semibold text-amber-700 hover:text-amber-900 transition-colors whitespace-nowrap"
      >
        Ver ocorrências
        <ArrowRight size={14} />
      </button>
      <button
        onClick={handleDismiss}
        className="text-amber-400 hover:text-amber-600 transition-colors flex-shrink-0"
      >
        <X size={18} />
      </button>
    </div>
  );
};
