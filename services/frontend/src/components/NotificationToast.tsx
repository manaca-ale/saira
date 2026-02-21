import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { X, MapPin } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useNotifications } from "../contexts/NotificationContext";
import type { SSENotificationEvent } from "../services/notificationService";

interface Toast {
  id: string;
  event: SSENotificationEvent;
  timestamp: number;
}

const MAX_VISIBLE = 3;
const AUTO_DISMISS_MS = 8000;

export const NotificationToastContainer: React.FC = () => {
  const { realtimeEvent } = useNotifications();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const navigate = useNavigate();

  // Add new toast when a realtime event arrives
  useEffect(() => {
    if (!realtimeEvent) return;

    const newToast: Toast = {
      id: crypto.randomUUID(),
      event: realtimeEvent,
      timestamp: Date.now(),
    };

    setToasts((prev) => [newToast, ...prev].slice(0, MAX_VISIBLE));
  }, [realtimeEvent]);

  // Auto-dismiss
  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setInterval(() => {
      const now = Date.now();
      setToasts((prev) => prev.filter((t) => now - t.timestamp < AUTO_DISMISS_MS));
    }, 1000);
    return () => clearInterval(timer);
  }, [toasts.length]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const handleClick = useCallback(
    (toast: Toast) => {
      const meta = toast.event.metadata;
      const params = new URLSearchParams();
      if (meta?.rpa) params.set("rpa", String(meta.rpa));
      if (meta?.detection_id) params.set("detection_id", String(meta.detection_id));
      navigate(`/detections?${params.toString()}`);
      dismiss(toast.id);
    },
    [navigate, dismiss]
  );

  return (
    <div className="fixed top-4 right-4 z-[10001] flex flex-col gap-3 w-80">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            layout
            initial={{ opacity: 0, x: 80, scale: 0.95 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 80, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            onClick={() => handleClick(toast)}
            className="bg-white rounded-xl shadow-xl border border-gray-100 p-4 cursor-pointer hover:shadow-2xl transition-shadow"
          >
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center flex-shrink-0">
                <MapPin size={16} className="text-red-500" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {toast.event.title}
                </p>
                <p className="text-xs text-gray-500 truncate mt-0.5">
                  {toast.event.message}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  dismiss(toast.id);
                }}
                className="text-gray-300 hover:text-gray-500 transition-colors flex-shrink-0"
              >
                <X size={14} />
              </button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};
