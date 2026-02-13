import api from "./api";

// --- Types ---
export interface NotificationData {
  id: string;
  user_id: number;
  detection_id: string | null;
  type: string;
  title: string;
  message: string;
  metadata_: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationData[];
  unread_count: number;
  total: number;
}

export interface NotificationSummary {
  unread_count: number;
  since_last_login: number;
  last_login_at: string | null;
  by_rpa: Record<string, number>;
}

export interface SSENotificationEvent {
  type: string;
  title: string;
  message: string;
  detection_id: string;
  metadata: Record<string, unknown>;
}

// --- REST API ---
export async function getNotifications(params?: {
  is_read?: boolean;
  skip?: number;
  limit?: number;
}): Promise<NotificationListResponse> {
  const response = await api.get("/notifications/", { params });
  return response.data;
}

export async function getNotificationSummary(): Promise<NotificationSummary> {
  const response = await api.get("/notifications/summary");
  return response.data;
}

export async function markAsRead(notificationId: string): Promise<void> {
  await api.patch(`/notifications/${notificationId}/read`);
}

export async function markAllAsRead(): Promise<void> {
  await api.patch("/notifications/read-all");
}

// --- SSE Service ---
type SSECallback = (event: SSENotificationEvent) => void;

class NotificationSSEService {
  private eventSource: EventSource | null = null;
  private listeners: Set<SSECallback> = new Set();

  connect(token: string): void {
    if (this.eventSource) {
      this.disconnect();
    }

    const baseUrl = import.meta.env.VITE_API_URL || "/api/v1";
    this.eventSource = new EventSource(
      `${baseUrl}/notifications/stream?token=${encodeURIComponent(token)}`
    );

    this.eventSource.addEventListener("new_detection", (event) => {
      try {
        const data: SSENotificationEvent = JSON.parse(event.data);
        this.listeners.forEach((cb) => cb(data));
      } catch {
        // ignore parse errors
      }
    });

    this.eventSource.onerror = () => {
      // EventSource reconnects automatically
    };
  }

  disconnect(): void {
    this.eventSource?.close();
    this.eventSource = null;
  }

  subscribe(callback: SSECallback): () => void {
    this.listeners.add(callback);
    return () => {
      this.listeners.delete(callback);
    };
  }
}

export const notificationSSE = new NotificationSSEService();
