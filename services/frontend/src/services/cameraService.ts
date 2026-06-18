import api from "./api";

export interface Camera {
  id: number;
  name: string;
  device_id?: string | null;
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
  logradouro?: string;
  bairro?: string;
  rpa?: string;
  latitude: number;
  longitude: number;
  rtsp_url?: string;
  capture_interval_seconds: number;
  is_active: boolean;
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
