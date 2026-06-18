import api from './api';

export interface IndicatorPeriod {
  start: string;
  end: string;
}

export interface IndicatorCard {
  id: string;
  name: string;
  unit: string;
  polarity: 'higher_better' | 'lower_better';
  periodicity: string;
  value: number | null;
  secondary: number | null;
  value_label: string | null;
  secondary_label: string | null;
  has_data: boolean;
  trackable: boolean;
}

export interface IndicatorsSummary {
  period: IndicatorPeriod;
  cards: IndicatorCard[];
}

export interface CameraUptime {
  camera_id: number;
  name: string | null;
  device_id: string | null;
  bairro: string | null;
  uptime_pct: number | null;
  online_checks: number;
  total_checks: number;
}

export interface SurveillanceReliability {
  period: IndicatorPeriod;
  average_uptime_pct: number | null;
  worst_uptime_pct: number | null;
  worst_camera: string | null;
  cameras: CameraUptime[];
  has_data: boolean;
}

export interface LatencyStat {
  label: string;
  p50_seconds: number | null;
  p95_seconds: number | null;
  sample_size: number;
}

export interface AlertSpeed {
  period: IndicatorPeriod;
  primary: LatencyStat;
  breakdown: LatencyStat[];
}

export interface IdentificationQuality {
  period: IndicatorPeriod;
  quality_pct: number | null;
  crops_extracted: number;
  offenders_present: number;
  has_data: boolean;
}

export interface AccuracyReading {
  accuracy_pct: number | null;
  confirmed: number;
  rejected: number;
  total_evaluated: number;
  has_data: boolean;
}

export interface DetectionAccuracy {
  period: IndicatorPeriod;
  model: AccuracyReading;
  human: AccuracyReading;
}

export interface DossierCompleteness {
  period: IndicatorPeriod;
  completeness_pct: number | null;
  complete: number;
  total: number;
  missing_photo: number;
  missing_location: number;
  missing_datetime: number;
  missing_waste_type: number;
  missing_volume: number;
  has_data: boolean;
}

type Range = { start?: string; end?: string };
const params = (r: Range) => ({ params: { start: r.start, end: r.end } });

export const getIndicatorsSummary = (r: Range = {}) =>
  api.get<IndicatorsSummary>('/indicators/summary', params(r)).then((res) => res.data);

export const getSurveillanceReliability = (r: Range = {}) =>
  api.get<SurveillanceReliability>('/indicators/surveillance-reliability', params(r)).then((res) => res.data);

export const getAlertSpeed = (r: Range = {}) =>
  api.get<AlertSpeed>('/indicators/alert-speed', params(r)).then((res) => res.data);

export const getIdentificationQuality = (r: Range = {}) =>
  api.get<IdentificationQuality>('/indicators/identification-quality', params(r)).then((res) => res.data);

export const getDetectionAccuracy = (r: Range = {}) =>
  api.get<DetectionAccuracy>('/indicators/detection-accuracy', params(r)).then((res) => res.data);

export const getDossierCompleteness = (r: Range = {}) =>
  api.get<DossierCompleteness>('/indicators/dossier-completeness', params(r)).then((res) => res.data);
