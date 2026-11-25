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
  private generation = 0;
  private wanted = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private retryDelayMs = 1000;

  // O JWT não vai mais na URL: cada conexão usa um bilhete de uso único,
  // pedido com o login normal (cabeçalho Authorization do `api`).
  connect(_token?: string): void {
    this.disconnect();
    this.wanted = true;
    void this.open(this.generation);
  }

  private async open(generation: number): Promise<void> {
    let ticket: string;
    try {
      const { data } = await api.post<{ ticket: string }>("/notifications/stream-ticket");
      ticket = data.ticket;
    } catch (err) {
      // Sessão vencida: quem cuida é o fluxo de login, não adianta insistir.
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status !== 401 && generation === this.generation) this.scheduleRetry();
      return;
    }
    if (!this.wanted || generation !== this.generation) return;

    const baseUrl = import.meta.env.VITE_API_URL || "/api/v1";
    const source = new EventSource(
      `${baseUrl}/notifications/stream?ticket=${encodeURIComponent(ticket)}`
    );
    this.eventSource = source;

    source.onopen = () => {
      this.retryDelayMs = 1000;
    };

    source.addEventListener("new_detection", (event) => {
      try {
        const data: SSENotificationEvent = JSON.parse(event.data);
        this.listeners.forEach((cb) => cb(data));
      } catch {
        // ignore parse errors
      }
    });

    source.onerror = () => {
      // O bilhete vale uma conexão só: a reconexão automática do EventSource
      // usaria o bilhete gasto. Fecha e reabre com um bilhete novo.
      source.close();
      if (this.eventSource === source) {
        this.eventSource = null;
        this.scheduleRetry();
      }
    };
  }

  private scheduleRetry(): void {
    if (!this.wanted || this.retryTimer) return;
    const generation = this.generation;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.wanted && generation === this.generation) void this.open(generation);
    }, this.retryDelayMs);
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, 30000);
  }

  disconnect(): void {
    this.wanted = false;
    this.generation += 1;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
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
