import api from './api';
import type { PoiData as FrontendPoiData, WasteType } from './mockData';

export interface Detection {
  id: string;
  camera_id?: number;
  timestamp: string;
  logradouro?: string;
  bairro?: string;
  rpa?: string;
  latitude: number;
  longitude: number;
  waste_type?: string;
  volume_m3?: number;
  offenders?: string;
  status: string;
  image_url?: string;
  confidence_score?: number;
}

export type PoiData = FrontendPoiData;

function toNumber(value: unknown, fallback = 0): number {
  const parsed =
    typeof value === 'number'
      ? value
      : typeof value === 'string'
        ? Number.parseFloat(value)
        : Number.NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeWasteType(raw?: string): WasteType {
  const value = (raw || '').trim().toLowerCase();
  if (value === 'lixo domiciliar' || value === 'household waste') return 'Lixo domiciliar';
  if (value === 'poda' || value === 'pruning') return 'Poda';
  if (value === 'plastico' || value === 'plástico' || value === 'plastic') return 'Plástico';
  return 'Entulho';
}

function normalizeStatus(raw?: string): FrontendPoiData['status'] {
  const value = (raw || '').trim().toLowerCase();
  if (value === 'resolvido') return 'Resolvido';
  if (value === 'em analise' || value === 'em análise') return 'Em análise';
  return 'Pendente';
}

function toFrontendFormat(d: Detection): PoiData {
  return {
    id: d.id,
    bairro: d.bairro || '',
    logradouro: d.logradouro || '',
    latitude: toNumber(d.latitude),
    longitude: toNumber(d.longitude),
    timestamp: d.timestamp,
    wasteType: normalizeWasteType(d.waste_type),
    volume: toNumber(d.volume_m3),
    status: normalizeStatus(d.status),
    photoUrl: d.image_url || '',
    hasOffender: !!d.offenders,
  };
}

export async function getDetections(params?: {
  skip?: number;
  limit?: number;
  rpa?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  bairro?: string;
}): Promise<PoiData[]> {
  const safeLimit = Math.min(Math.max(params?.limit ?? 100, 1), 100);
  const queryParams = {
    skip: params?.skip ?? 0,
    limit: safeLimit,
    rpa: params?.rpa,
    status_filter: params?.status,
    start_date: params?.start_date,
    end_date: params?.end_date,
    bairro: params?.bairro,
  };

  const response = await api.get('/detections', { params: queryParams });
  return response.data.map(toFrontendFormat);
}

export async function updateDetectionStatus(id: string, status: string): Promise<Detection> {
  const response = await api.patch(`/detections/${id}`, { status });
  return response.data;
}
