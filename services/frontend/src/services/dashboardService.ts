import api from './api';

export interface DashboardStats {
  total_occurrences: number;
  daily_volume_m3: number;
  pending_count: number;
  in_analysis_count: number;
  resolved_count: number;
}

export interface OccurrencesByMonth {
  month: string;
  count: number;
}

export interface RecurrentLocation {
  logradouro: string;
  bairro: string;
  rpa: string;
  count: number;
}

export interface VolumeByRPA {
  rpa: string;
  avg_volume_m3: number;
  total_volume_m3: number;
  count: number;
}

export const getDashboardStats = () => api.get<DashboardStats>('/dashboard/stats').then(r => r.data);
export const getOccurrencesByMonth = () => api.get<OccurrencesByMonth[]>('/dashboard/occurrences-by-month').then(r => r.data);
export const getRecurrentLocations = () => api.get<RecurrentLocation[]>('/dashboard/recurrent-locations').then(r => r.data);
export const getVolumeByRPA = () => api.get<VolumeByRPA[]>('/dashboard/volume-by-rpa').then(r => r.data);
