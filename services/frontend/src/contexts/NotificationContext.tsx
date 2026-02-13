import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import {
  getNotifications,
  getNotificationSummary,
  markAsRead as apiMarkAsRead,
  markAllAsRead as apiMarkAllAsRead,
  notificationSSE,
} from "../services/notificationService";
import type {
  NotificationData,
  SSENotificationEvent,
} from "../services/notificationService";

interface NotificationContextType {
  notifications: NotificationData[];
  unreadCount: number;
  sinceLastLogin: number;
  lastLoginAt: string | null;
  byRpa: Record<string, number>;
  isDrawerOpen: boolean;
  toggleDrawer: () => void;
  closeDrawer: () => void;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  clearViewedNotifications: () => void;
  realtimeEvent: SSENotificationEvent | null;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user, isAuthenticated } = useAuth();
  const [notifications, setNotifications] = useState<NotificationData[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [sinceLastLogin, setSinceLastLogin] = useState(0);
  const [lastLoginAt, setLastLoginAt] = useState<string | null>(null);
  const [byRpa, setByRpa] = useState<Record<string, number>>({});
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [realtimeEvent, setRealtimeEvent] = useState<SSENotificationEvent | null>(null);
  const sseConnected = useRef(false);

  // Fetch initial data when authenticated
  useEffect(() => {
    if (!isAuthenticated || !user) {
      setNotifications([]);
      setUnreadCount(0);
      setSinceLastLogin(0);
      setLastLoginAt(null);
      setByRpa({});
      return;
    }

    async function loadInitial() {
      try {
        const [notifResponse, summary] = await Promise.all([
          getNotifications({ limit: 50 }),
          getNotificationSummary(),
        ]);
        setNotifications(notifResponse.items);
        setUnreadCount(notifResponse.unread_count);
        setSinceLastLogin(summary.since_last_login);
        setLastLoginAt(summary.last_login_at);
        setByRpa(summary.by_rpa);
      } catch {
        // Silently fail — notifications are non-critical
      }
    }

    loadInitial();
  }, [isAuthenticated, user]);

  // SSE connection
  useEffect(() => {
    if (!isAuthenticated) {
      if (sseConnected.current) {
        notificationSSE.disconnect();
        sseConnected.current = false;
      }
      return;
    }

    const token = localStorage.getItem("@Saira:token");
    if (!token) return;

    notificationSSE.connect(token);
    sseConnected.current = true;

    const unsubscribe = notificationSSE.subscribe((event) => {
      setRealtimeEvent(event);
      setUnreadCount((prev) => prev + 1);

      // Add to top of notifications list
      const newNotif: NotificationData = {
        id: `temp-${crypto.randomUUID()}`,
        user_id: user?.id ?? 0,
        detection_id: event.detection_id,
        type: event.type,
        title: event.title,
        message: event.message,
        metadata_: event.metadata,
        is_read: false,
        created_at: new Date().toISOString(),
      };
      setNotifications((prev) => [newNotif, ...prev].slice(0, 50));
    });

    return () => {
      unsubscribe();
      notificationSSE.disconnect();
      sseConnected.current = false;
    };
  }, [isAuthenticated, user]);

  const toggleDrawer = useCallback(() => {
    setIsDrawerOpen((prev) => !prev);
  }, []);

  const closeDrawer = useCallback(() => {
    setIsDrawerOpen(false);
  }, []);

  const markAsRead = useCallback(async (id: string) => {
    const target = notifications.find((n) => n.id === id);
    if (!target || target.is_read) return;

    // Otimista: marca local primeiro para refletir "visto" de imediato.
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
    setUnreadCount((prev) => Math.max(0, prev - 1));

    // SSE usa itens temporarios sem id persistido; evita chamada invalida.
    if (id.startsWith("temp-")) return;

    try {
      await apiMarkAsRead(id);
    } catch {
      // Se falhar no backend, mantem estado local para UX consistente.
    }
  }, [notifications]);

  const markAllAsReadFn = useCallback(async () => {
    try {
      await apiMarkAllAsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch {
      // ignore
    }
  }, []);

  const clearViewedNotifications = useCallback(() => {
    setNotifications((prev) => prev.filter((n) => !n.is_read));
  }, []);

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        sinceLastLogin,
        lastLoginAt,
        byRpa,
        isDrawerOpen,
        toggleDrawer,
        closeDrawer,
        markAsRead,
        markAllAsRead: markAllAsReadFn,
        clearViewedNotifications,
        realtimeEvent,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotifications must be used within a NotificationProvider");
  }
  return context;
}
