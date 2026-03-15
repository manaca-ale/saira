import React, { useEffect } from "react";
import { MapContainer, TileLayer, Marker, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fix default icon with bundler (same pattern as DashboardCharts.tsx)
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png",
});

const DEFAULT_CENTER: [number, number] = [-8.06, -34.9]; // Recife
const DEFAULT_ZOOM = 13;

const MapRecenter: React.FC<{ position: [number, number] | null }> = ({ position }) => {
  const map = useMap();
  useEffect(() => {
    if (position) map.setView(position, map.getZoom());
  }, [position, map]);
  return null;
};

interface CameraMapPickerProps {
  latitude: number | null;
  longitude: number | null;
  onPositionChange: (lat: number, lng: number) => void;
}

export const CameraMapPicker: React.FC<CameraMapPickerProps> = ({
  latitude,
  longitude,
  onPositionChange,
}) => {
  const position: [number, number] | null =
    latitude !== null && longitude !== null ? [latitude, longitude] : null;

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200">
      <MapContainer
        center={position ?? DEFAULT_CENTER}
        zoom={DEFAULT_ZOOM}
        style={{ height: "220px", width: "100%" }}
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {position && (
          <Marker
            position={position}
            draggable
            eventHandlers={{
              dragend: (e) => {
                const { lat, lng } = e.target.getLatLng();
                onPositionChange(
                  parseFloat(lat.toFixed(8)),
                  parseFloat(lng.toFixed(8)),
                );
              },
            }}
          />
        )}
        <MapRecenter position={position} />
      </MapContainer>
      <p className="text-xs text-gray-400 text-center py-1">
        Arraste o marcador para ajustar a posição
      </p>
    </div>
  );
};
