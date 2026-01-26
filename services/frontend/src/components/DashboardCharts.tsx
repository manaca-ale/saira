import React, { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { Maximize2, X, MapPin } from "lucide-react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import api from "../services/api";

// Fix for default marker icons in React-Leaflet
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png",
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png",
});

// --- CHART COMPONENT ---
const data = [
  { name: "JAN", val: 35 },
  { name: "FEV", val: 22 },
  { name: "MAR", val: 14 },
  { name: "ABR", val: 35 },
  { name: "MAI", val: 22 },
  { name: "JUN", val: 14 },
  { name: "JUL", val: 35 },
  { name: "AGO", val: 22 },
  { name: "SET", val: 14 },
  { name: "OUT", val: 35 },
  { name: "NOV", val: 22 },
  { name: "DEZ", val: 14 },
];

export const OccurrencesChart: React.FC = () => {
  return (
    <div className="w-full h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barSize={12}>
          <CartesianGrid
            strokeDasharray="3 3"
            vertical={false}
            stroke="#e5e5e5"
          />
          <XAxis
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 10, fill: "#666" }}
            dy={10}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: "#666" }}
            domain={[0, 40]}
            ticks={[0, 10, 20, 30, 40]}
          />
          <Tooltip
            cursor={{ fill: "transparent" }}
            contentStyle={{
              borderRadius: "8px",
              border: "none",
              boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
            }}
          />
          <Bar dataKey="val" fill="#a3e635" radius={[4, 4, 4, 4]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// --- MAP COMPONENT ---
interface Camera {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  logradouro?: string;
  bairro?: string;
  is_active: boolean;
}

interface MapWidgetProps {
  isExpanded: boolean;
  onToggleExpand: () => void;
}

export const MapWidget: React.FC<MapWidgetProps> = ({
  isExpanded,
  onToggleExpand,
}) => {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);

  // Coordenadas iniciais (Recife - Centro)
  const initialCoords: [number, number] = [-8.0476, -34.877];

  useEffect(() => {
    const fetchCameras = async () => {
      try {
        const response = await api.get("/cameras");
        setCameras(response.data);
      } catch (error) {
        console.error("Erro ao carregar câmeras:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchCameras();
  }, []);

  return (
    <div
      className={`relative w-full h-full rounded-2xl overflow-hidden shadow-lg ${
        isExpanded ? "fixed inset-0 z-50 m-0 rounded-none" : ""
      }`}
    >
      {loading ? (
        <div className="absolute inset-0 bg-gray-100 flex items-center justify-center">
          <div className="text-gray-500">Carregando mapa...</div>
        </div>
      ) : (
        <MapContainer
          center={initialCoords}
          zoom={13}
          style={{ width: "100%", height: "100%" }}
          className="z-0"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {cameras.map((camera) => (
            <Marker
              key={camera.id}
              position={[camera.latitude, camera.longitude]}
            >
              <Popup>
                <div className="text-sm">
                  <div className="font-bold text-base mb-2">{camera.name}</div>
                  {camera.logradouro && (
                    <div className="text-gray-700">{camera.logradouro}</div>
                  )}
                  {camera.bairro && (
                    <div className="text-gray-600">{camera.bairro}</div>
                  )}
                  <div
                    className={`mt-2 inline-block px-2 py-1 rounded text-xs ${
                      camera.is_active
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {camera.is_active ? "Ativa" : "Inativa"}
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      )}

      {/* Expand/Close Button */}
      <button
        onClick={onToggleExpand}
        className="absolute top-4 right-4 bg-white p-2 rounded-lg shadow-lg hover:bg-gray-50 transition-colors z-[1000] text-gray-700"
      >
        {isExpanded ? <X size={20} /> : <Maximize2 size={20} />}
      </button>

      {/* Camera Count Badge */}
      {!loading && cameras.length > 0 && (
        <div className="absolute bottom-4 left-4 bg-white px-3 py-2 rounded-lg shadow-lg z-[1000] flex items-center gap-2">
          <MapPin size={16} className="text-green-600" />
          <span className="text-sm font-medium text-gray-700">
            {cameras.length} câmera{cameras.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}
    </div>
  );
};
