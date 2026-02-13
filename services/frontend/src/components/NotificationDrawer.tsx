import React from "react";
import { X, CheckCheck, Bell } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useNotifications } from "../contexts/NotificationContext";

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "agora";
  if (diffMin < 60) return `há ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `há ${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `há ${diffD}d`;
}

export const NotificationDrawer: React.FC = () => {
  const {
    notifications,
    unreadCount,
    isDrawerOpen,
    closeDrawer,
    markAsRead,
    markAllAsRead,
    clearViewedNotifications,
  } = useNotifications();
  const navigate = useNavigate();
  const viewedCount = notifications.filter((n) => n.is_read).length;

  if (!isDrawerOpen) return null;

  const handleNotificationClick = async (notif: typeof notifications[0]) => {
    if (!notif.is_read) {
      await markAsRead(notif.id);
    }

    // Abre a ocorrencia especifica em Detecoes (modal unificado).
    const meta = notif.metadata_ as Record<string, string> | null;
    if (meta) {
      const params = new URLSearchParams();
      if (meta.detection_id) params.set("detection_id", meta.detection_id);
      navigate(`/detections?${params.toString()}`);
    } else {
      navigate("/detections");
    }

    closeDrawer();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[9998] bg-black/30 backdrop-blur-sm"
        onClick={closeDrawer}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 bottom-0 z-[9999] w-96 max-w-[calc(100vw-80px)] bg-white shadow-2xl flex flex-col animate-[slideIn_0.2s_ease-out]">
        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
        `}</style>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Bell size={18} className="text-gray-700" />
            <h2 className="text-base font-bold text-gray-800">Notificações</h2>
            {unreadCount > 0 && (
              <span className="bg-red-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
                {unreadCount}
              </span>
            )}
          </div>
          <button
            onClick={closeDrawer}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Notification list */}
        <div className="flex-1 overflow-y-auto">
          {notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <Bell size={40} className="mb-3 opacity-30" />
              <p className="text-sm">Nenhuma notificação</p>
            </div>
          ) : (
            notifications.map((notif) => (
              <button
                key={notif.id}
                onClick={() => handleNotificationClick(notif)}
                className={`w-full text-left px-5 py-3.5 border-b border-gray-50 hover:bg-gray-50 transition-colors ${
                  !notif.is_read ? "bg-blue-50/50" : ""
                }`}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${
                      notif.is_read ? "bg-transparent" : "bg-blue-500"
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm truncate ${!notif.is_read ? "font-semibold text-gray-900" : "text-gray-700"}`}>
                      {notif.title}
                    </p>
                    <p className="text-xs text-gray-500 truncate mt-0.5">
                      {notif.message}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {timeAgo(notif.created_at)}
                    </p>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        {notifications.length > 0 && (unreadCount > 0 || viewedCount > 0) && (
          <div className="px-5 py-3 border-t border-gray-100">
            <div className="flex items-center justify-between gap-3">
              {unreadCount > 0 ? (
                <button
                  onClick={markAllAsRead}
                  className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-700 font-medium transition-colors"
                >
                  <CheckCheck size={16} />
                  Marcar todas como lidas
                </button>
              ) : <span />}
              {viewedCount > 0 && (
                <button
                  onClick={clearViewedNotifications}
                  className="text-sm text-gray-500 hover:text-gray-700 font-medium transition-colors"
                >
                  Limpar visualizadas
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
};
