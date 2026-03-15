import api from "./api";
import type { GeocodingResult } from "../types/geocoding";

export async function searchAddress(
  query: string,
  limit = 5,
): Promise<GeocodingResult[]> {
  const response = await api.get<GeocodingResult[]>("/geocoding/search", {
    params: { q: query, limit },
  });
  return response.data;
}
