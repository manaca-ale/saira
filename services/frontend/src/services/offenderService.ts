import api from "./api";

// ── Types ────────────────────────────────────────────────────────────

export type OffenderType = "Carroca" | "Carro" | "Moto" | "Pessoa" | "Outro";

export interface Offender {
  id: string;
  name: string | null;
  type: OffenderType;
  plate: string | null;
  vehicle_color: string | null;
  description: string | null;
  is_active: boolean;
  sighting_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface DetectionOffenderLink {
  id: string;
  detection_id: string;
  offender_id: string | null;
  offender_type: OffenderType;
  plate: string | null;
  vehicle_color: string | null;
  waste_type: string | null;
  estimated_volume_m3: number | null;
  source: "ai" | "manual";
  confidence_score: number | null;
  offender_bbox?: number[] | null; // [y_min, x_min, y_max, x_max] normalized 0-1000
  created_by: number | null;
  notes: string | null;
  created_at: string;
  offender?: Offender | null;
}

export interface OffenderStats {
  total_offenders: number;
  recurrent_offenders: number;
  high_recurrence: number;
  identified_plates: number;
  estimated_volume_m3: number;
}

export interface OffendersByType {
  type: string;
  count: number;
  percentage: number;
}

export interface RecidivismByType {
  type: string;
  recurrent_count: number;
}

export interface OffenderVolumeByType {
  type: string;
  total_volume_m3: number;
}

export interface WasteBreakdownItem {
  waste_type: string;
  count: number;
}

export interface WasteByOffenderType {
  offender_type: string;
  waste_breakdown: WasteBreakdownItem[];
}

export interface TopPlate {
  plate: string;
  occurrences: number;
}

export interface VehicleColor {
  color: string;
  count: number;
  percentage: number;
}

// ── Dashboard filters ────────────────────────────────────────────────

export interface DashboardFilters {
  start_date?: string;
  end_date?: string;
  status?: string;
  logradouro?: string;
  bairro?: string;
  rpa?: string;
}

// ── CRUD — Offender profiles ─────────────────────────────────────────

export async function getOffenders(params?: {
  type?: string;
  plate?: string;
  name?: string;
  is_active?: boolean;
  skip?: number;
  limit?: number;
}): Promise<Offender[]> {
  const response = await api.get("/offenders/", { params });
  return response.data;
}

export async function getOffender(id: string): Promise<Offender> {
  const response = await api.get(`/offenders/${id}`);
  return response.data;
}

export async function createOffender(data: {
  name?: string;
  type: OffenderType;
  plate?: string;
  vehicle_color?: string;
  description?: string;
}): Promise<Offender> {
  const response = await api.post("/offenders/", data);
  return response.data;
}

export async function updateOffender(
  id: string,
  data: Partial<{
    name: string;
    type: OffenderType;
    plate: string;
    vehicle_color: string;
    description: string;
    is_active: boolean;
  }>
): Promise<Offender> {
  const response = await api.patch(`/offenders/${id}`, data);
  return response.data;
}

export async function deleteOffender(id: string): Promise<void> {
  await api.delete(`/offenders/${id}`);
}

// ── Detection ↔ Offender sightings ──────────────────────────────────

export async function getDetectionOffenders(
  detectionId: string
): Promise<DetectionOffenderLink[]> {
  const response = await api.get(
    `/offenders/detections/${detectionId}/offenders`
  );
  return response.data;
}

export async function addDetectionOffender(
  detectionId: string,
  data: {
    offender_id?: string;
    offender_type: OffenderType;
    plate?: string;
    vehicle_color?: string;
    waste_type?: string;
    estimated_volume_m3?: number;
    notes?: string;
  }
): Promise<DetectionOffenderLink> {
  const response = await api.post(
    `/offenders/detections/${detectionId}/offenders`,
    data
  );
  return response.data;
}

export async function updateDetectionOffender(
  sightingId: string,
  data: Partial<{
    offender_id: string;
    offender_type: OffenderType;
    plate: string;
    vehicle_color: string;
    waste_type: string;
    estimated_volume_m3: number;
    notes: string;
  }>
): Promise<DetectionOffenderLink> {
  const response = await api.patch(
    `/offenders/detection-offenders/${sightingId}`,
    data
  );
  return response.data;
}

export async function deleteDetectionOffender(
  sightingId: string
): Promise<void> {
  await api.delete(`/offenders/detection-offenders/${sightingId}`);
}

export async function linkOffenderToDetection(
  detectionId: string,
  offenderId: string
): Promise<DetectionOffenderLink> {
  const response = await api.post(
    `/offenders/detections/${detectionId}/offenders/link/${offenderId}`
  );
  return response.data;
}

// ── Dashboard aggregations ───────────────────────────────────────────

export async function getOffenderStats(
  filters?: DashboardFilters
): Promise<OffenderStats> {
  const response = await api.get("/offenders/dashboard/offender-stats", {
    params: filters,
  });
  return response.data;
}

export async function getOffendersByType(
  filters?: DashboardFilters
): Promise<OffendersByType[]> {
  const response = await api.get("/offenders/dashboard/offenders-by-type", {
    params: filters,
  });
  return response.data;
}

export async function getRecidivismByType(
  filters?: DashboardFilters
): Promise<RecidivismByType[]> {
  const response = await api.get("/offenders/dashboard/recidivism-by-type", {
    params: filters,
  });
  return response.data;
}

export async function getOffenderVolumeByType(
  filters?: DashboardFilters
): Promise<OffenderVolumeByType[]> {
  const response = await api.get(
    "/offenders/dashboard/offender-volume-by-type",
    { params: filters }
  );
  return response.data;
}

export async function getWasteByOffenderType(
  filters?: DashboardFilters
): Promise<WasteByOffenderType[]> {
  const response = await api.get(
    "/offenders/dashboard/waste-by-offender-type",
    { params: filters }
  );
  return response.data;
}

export async function getTopPlates(
  filters?: DashboardFilters & { limit?: number }
): Promise<TopPlate[]> {
  const response = await api.get("/offenders/dashboard/top-plates", {
    params: filters,
  });
  return response.data;
}

export async function getVehicleColors(
  filters?: DashboardFilters
): Promise<VehicleColor[]> {
  const response = await api.get("/offenders/dashboard/vehicle-colors", {
    params: filters,
  });
  return response.data;
}
