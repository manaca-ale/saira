import api from './api';

export type ImageExportStatus = 'pending' | 'running' | 'ready' | 'failed' | 'expired';

export interface ImageExport {
  id: string;
  user_id: number;
  camera_id: number;
  camera_name?: string | null;
  camera_device_id?: string | null;
  start_at: string;
  end_at: string;
  include_occurrences: boolean;
  include_non_occurrences: boolean;
  status: ImageExportStatus;
  progress: number;
  total_images?: number | null;
  download_url?: string | null;
  expires_at?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateImageExportPayload {
  camera_id: number;
  start_at: string;
  end_at: string;
  include_occurrences: boolean;
  include_non_occurrences: boolean;
}

export async function createImageExport(
  payload: CreateImageExportPayload,
): Promise<ImageExport> {
  const response = await api.post<ImageExport>('/exports/', payload);
  return response.data;
}

export async function listImageExports(limit = 20): Promise<ImageExport[]> {
  const response = await api.get<ImageExport[]>('/exports/', { params: { limit } });
  return response.data;
}

export async function getImageExport(id: string): Promise<ImageExport> {
  const response = await api.get<ImageExport>(`/exports/${id}`);
  return response.data;
}

export async function deleteImageExport(id: string): Promise<void> {
  await api.delete(`/exports/${id}`);
}
