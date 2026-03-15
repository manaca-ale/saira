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
  material_type?: string;
  volume_m3?: number;
  offenders?: string;
  status: string;
  image_url?: string;
  confidence_score?: number;
}

export type PoiData = FrontendPoiData;

export interface DetectionSearchParams {
  skip?: number;
  limit?: number;
  rpa?: string | string[];
  status?: string | string[];
  start_date?: string;
  end_date?: string;
  bairro?: string;
  logradouro?: string;
  waste_type?: WasteType | WasteType[];
  volume_min?: number;
  volume_max?: number;
  has_offender?: boolean;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

interface DetectionSearchApiResponse {
  items: Detection[];
  total: number;
  skip: number;
  limit: number;
}

export interface PaginatedDetections {
  items: PoiData[];
  total: number;
  skip: number;
  limit: number;
}

export interface DetectionAnalyzedFrame {
  frame_name: string;
  image_url: string;
  is_default: boolean;
}

export interface DetectionAnalyzedFramesResponse {
  detection_id: string;
  selected_frame_name?: string | null;
  frames: DetectionAnalyzedFrame[];
}

function normalizeImageUrl(url?: string | null): string {
  if (!url) return '';
  // Strip scheme + host so the browser loads the image through the same-origin
  // nginx proxy (/uploads/ → esp32-server:5000), regardless of what PUBLIC_BASE_URL
  // was configured in the worker (e.g. http://localhost:5002 or http://esp32-server:5000).
  const match = url.match(/(\/uploads\/.+)/);
  return match ? match[1] : url;
}

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
  if (value === 'entulho' || value === 'construcao' || value === 'construção' || value === 'debris') return 'Entulho';
  if (value.includes('residuo') || value.includes('resíduo') || value.includes('lixo') || value === 'solid waste')
    return 'Lixo domiciliar';
  return 'Entulho';
}

function normalizeStatus(raw?: string): FrontendPoiData['status'] {
  const value = (raw || '').trim().toLowerCase();
  if (value === 'resolvido') return 'Resolvido';
  if (value === 'em analise' || value === 'em análise') return 'Em análise';
  return 'Pendente';
}

function normalizeStatusFilter(raw?: string): string | undefined {
  const value = (raw || '').trim().toLowerCase();
  if (!value) return undefined;
  if (value === 'em análise' || value === 'em analise') return 'Em analise';
  if (value === 'resolvido') return 'Resolvido';
  if (value === 'pendente') return 'Pendente';
  return raw;
}

function normalizeWasteTypeFilter(raw: string): string {
  const value = raw.trim().toLowerCase();
  if (value === 'plástico' || value === 'plastico') return 'plastico';
  if (value === 'lixo domiciliar') return 'lixo domiciliar';
  if (value === 'poda') return 'poda';
  if (value === 'entulho') return 'entulho';
  return value;
}

function ensureStringArray(value?: string | string[]): string[] | undefined {
  if (!value) return undefined;
  return Array.isArray(value) ? value.filter(Boolean) : [value];
}

function toCsv(values?: string[]): string | undefined {
  if (!values || values.length === 0) return undefined;
  return values.join(',');
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
    photoUrl: normalizeImageUrl(d.image_url),
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
    status_filter: normalizeStatusFilter(params?.status),
    start_date: params?.start_date,
    end_date: params?.end_date,
    bairro: params?.bairro,
  };

  const response = await api.get('/detections/', { params: queryParams });
  return response.data.map(toFrontendFormat);
}

export async function searchDetections(params?: DetectionSearchParams): Promise<PaginatedDetections> {
  const safeLimit = Math.min(Math.max(params?.limit ?? 10, 1), 100);
  const statusValues = ensureStringArray(params?.status)?.map((value) =>
    normalizeStatusFilter(value) ?? value,
  );
  const wasteTypeValues = ensureStringArray(params?.waste_type as string | string[] | undefined)
    ?.map(normalizeWasteTypeFilter);

  const queryParams = {
    skip: params?.skip ?? 0,
    limit: safeLimit,
    rpa: toCsv(ensureStringArray(params?.rpa)),
    status_filter: toCsv(statusValues),
    start_date: params?.start_date,
    end_date: params?.end_date,
    bairro: params?.bairro,
    logradouro: params?.logradouro,
    waste_type: toCsv(wasteTypeValues),
    volume_min: params?.volume_min,
    volume_max: params?.volume_max,
    has_offender: params?.has_offender,
    sort_by: params?.sort_by,
    sort_order: params?.sort_order,
  };

  const response = await api.get<DetectionSearchApiResponse>('/detections/search', { params: queryParams });
  return {
    items: response.data.items.map(toFrontendFormat),
    total: response.data.total,
    skip: response.data.skip,
    limit: response.data.limit,
  };
}

interface GetAllDetectionsParams extends DetectionSearchParams {
  pageSize?: number;
  maxRecords?: number;
}

export async function getAllDetections(params?: GetAllDetectionsParams): Promise<PoiData[]> {
  const pageSize = Math.min(Math.max(params?.pageSize ?? 100, 1), 100);
  const maxRecords = Math.max(params?.maxRecords ?? 10000, pageSize);
  const { pageSize: _pageSize, maxRecords: _maxRecords, ...searchParams } = params ?? {};
  const all: PoiData[] = [];
  let skip = 0;

  while (all.length < maxRecords) {
    const page = await searchDetections({
      ...searchParams,
      skip,
      limit: pageSize,
    });

    all.push(...page.items);

    if (page.items.length < pageSize || all.length >= page.total) {
      break;
    }

    skip += pageSize;
  }

  return all.slice(0, maxRecords);
}

export async function getDetectionById(id: string): Promise<PoiData> {
  const response = await api.get<Detection>(`/detections/${id}`);
  return toFrontendFormat(response.data);
}

export async function updateDetectionStatus(id: string, status: string): Promise<Detection> {
  const response = await api.patch(`/detections/${id}`, { status });
  return response.data;
}

export async function updateDetectionImage(id: string, image_url: string): Promise<Detection> {
  const response = await api.patch(`/detections/${id}`, { image_url });
  return response.data;
}

export async function getDetectionAnalyzedFrames(id: string): Promise<DetectionAnalyzedFramesResponse> {
  const response = await api.get<DetectionAnalyzedFramesResponse>(`/detections/${id}/analyzed-frames`);
  return {
    ...response.data,
    frames: (response.data.frames || []).map((frame) => ({
      ...frame,
      image_url: normalizeImageUrl(frame.image_url),
    })),
  };
}

export async function resolveDetection(
  id: string,
  data: {
    resolved_at: string;
    forwarded_to_sector: string;
    resolution_justification: string;
  }
): Promise<Detection> {
  const response = await api.post(`/detections/${id}/resolve`, data);
  return response.data;
}

export async function startAnalysis(id: string): Promise<Detection> {
  const response = await api.post(`/detections/${id}/start-analysis`);
  return response.data;
}
