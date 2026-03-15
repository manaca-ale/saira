export interface GeocodingResult {
  display_name: string;
  latitude: number;
  longitude: number;
  logradouro: string | null;
  bairro: string | null;
}
