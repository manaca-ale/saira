import api from "./api";

/** Família do hardware. Fonte da verdade das capacidades da câmera; vem do
 *  backend (coluna cameras.camera_type). NULL = tipo ainda não classificado. */
export type CameraType = "esp32" | "pi" | "unknown";

export interface Camera {
  id: number;
  name: string;
  device_id?: string | null;
  camera_type?: CameraType | null;
  logradouro?: string | null;
  bairro?: string | null;
  rpa?: string | null;
  latitude: number | string;
  longitude: number | string;
  rtsp_url?: string | null;
  capture_interval_seconds: number;
  is_active: boolean;
  last_capture_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CameraPayload {
  name: string;
  device_id?: string;
  camera_type?: CameraType | null;
  logradouro?: string;
  bairro?: string;
  rpa?: string;
  latitude: number;
  longitude: number;
  rtsp_url?: string;
  capture_interval_seconds: number;
  is_active: boolean;
}

/** Sessão de modo ao vivo (POST /cameras/{id}/live/start|renew). */
export interface CameraLiveSession {
  camera_id: number;
  device_id: string;
  status: string;
  expires_at: string;
  hard_deadline: string;
  /** Segundos até o teto duro da sessão (ancorado no start, não desliza). */
  remaining_s: number;
  lease_s: number;
  /** Ritmo de renovação ditado pelo servidor — não hardcodar no frontend. */
  renew_after_s: number;
}

export interface DetectionSummary {
  id: string;
  camera_id: number | null;
  timestamp: string;
  image_url?: string | null;
}

export interface CameraLatestImage {
  camera_id: number;
  device_id?: string | null;
  image_url?: string | null;
  captured_at?: string | null;
  file_path?: string | null;
}

export async function getCameras(params?: {
  skip?: number;
  limit?: number;
  is_active?: boolean;
  rpa?: string;
}): Promise<Camera[]> {
  const response = await api.get("/cameras/", { params });
  return response.data as Camera[];
}

export async function createCamera(data: CameraPayload): Promise<Camera> {
  const response = await api.post("/cameras/", data);
  return response.data as Camera;
}

export async function updateCamera(
  id: number,
  data: Partial<CameraPayload>,
): Promise<Camera> {
  const response = await api.patch(`/cameras/${id}`, data);
  return response.data as Camera;
}

export async function deleteCamera(id: number): Promise<void> {
  await api.delete(`/cameras/${id}`);
}

export async function getLatestDetectionForCamera(
  cameraId: number,
): Promise<DetectionSummary | null> {
  const response = await api.get("/detections/", {
    params: { camera_id: cameraId, limit: 1, skip: 0 },
  });
  const detections = response.data as DetectionSummary[];
  return detections.length > 0 ? detections[0] : null;
}

export async function getLatestCameraImageFromFolder(
  cameraId: number,
): Promise<CameraLatestImage | null> {
  const response = await api.get<CameraLatestImage>(`/cameras/${cameraId}/latest-image`);
  return response.data ?? null;
}

/**
 * Pede um frame atual sob demanda (dispositivos event-driven, ex.: Pi, que não
 * mandam mais heartbeat-imagem). Best-effort: dispositivos que ignoram o comando
 * (esp32) não falham. Após chamar, espere ~3s e rebusque getLatestCameraImageFromFolder.
 */
export async function requestCameraSnapshot(cameraId: number): Promise<void> {
  try {
    await api.post(`/cameras/${cameraId}/request-snapshot`);
  } catch (error) {
    console.warn(`request-snapshot falhou p/ câmera ${cameraId}:`, error);
  }
}

/** Só o que é preciso para decidir capacidades — aceita Camera inteira. */
export type CameraCaps = Pick<Camera, "device_id" | "camera_type">;

/**
 * As câmeras ESP32 não aceitam comandos remotos (snapshot sob demanda, zoom)
 * nem têm lente motorizada. Dispositivos event-driven (ex.: Pi/Intelbras) sim.
 *
 * O camera_type manda. Quando ele é NULL (câmera ainda não classificada) o
 * fallback é FAIL-OPEN, caindo na heurística de prefixo legada — preserva
 * exatamente o comportamento anterior, sem regressão para a frota existente.
 */
export function cameraSupportsRemoteControl(c?: CameraCaps | null): boolean {
  const t = (c?.camera_type || "").trim().toLowerCase();
  if (t) return t !== "esp32";
  const d = (c?.device_id || "").trim().toLowerCase();
  return d.length > 0 && !d.startsWith("esp32");
}

/**
 * Modo ao vivo (~1 fps, para instalação em campo). Exige tipo 'pi' EXPLÍCITO:
 * FAIL-CLOSED. Feature nova não tem legado a preservar, e errar para o lado
 * aberto dá um botão que não funciona e queima 4G do dispositivo à toa.
 */
export function cameraSupportsLive(c?: CameraCaps | null): boolean {
  return (c?.camera_type || "").trim().toLowerCase() === "pi";
}

/**
 * Abre/renova/encerra a sessão de modo ao vivo.
 *
 * Ao contrário de requestCameraSnapshot, estas NÃO engolem erro: o hook precisa
 * ver o 409 (teto duro atingido) e o 404 (sessão sumiu) para parar de renovar.
 * Engolir aqui recriaria exatamente o bug que a feature existe para fechar — um
 * loop que nunca morre consumindo 4G.
 */
export async function startLiveSession(cameraId: number): Promise<CameraLiveSession> {
  const response = await api.post<CameraLiveSession>(`/cameras/${cameraId}/live/start`);
  return response.data;
}

export async function renewLiveSession(cameraId: number): Promise<CameraLiveSession> {
  const response = await api.post<CameraLiveSession>(`/cameras/${cameraId}/live/renew`);
  return response.data;
}

export async function stopLiveSession(cameraId: number): Promise<void> {
  await api.post(`/cameras/${cameraId}/live/stop`);
}

/** Ajusta o zoom óptico (0 = aberto, 1 = aproximado). Só dispositivos com lente
 *  motorizada (Pi/Intelbras) reagem; aplica em ~2-4s e sobe um frame novo. */
export async function setCameraZoom(cameraId: number, zoom: number): Promise<void> {
  await api.post(`/cameras/${cameraId}/zoom`, { zoom });
}

/** Dispara o autofoco da lente motorizada. */
export async function cameraAutofocus(cameraId: number): Promise<void> {
  await api.post(`/cameras/${cameraId}/autofocus`);
}
