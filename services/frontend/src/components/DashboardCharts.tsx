import React, { useEffect, useState, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip as RechartsTooltip,
} from "recharts";
import { X, Settings, Palette, Clock, Trash2, HelpCircle, Camera, UserX } from "lucide-react";
import { MapContainer, TileLayer, useMap, Marker, Popup, CircleMarker, Tooltip as LeafletTooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import "leaflet.heat";
import { masterPois } from "../services/mockData";
import type { PoiData } from "../services/mockData";
import { BRAZIL_TIME_ZONE } from "../utils/datetime";

// --- ENVIRONMENT VARIABLE ---
const mapMode = import.meta.env.VITE_MAP_MODE || 'heatmap';

// --- COLOR MAPPING for BUBBLE MAP ---
const statusColors: Record<PoiData["status"], string> = {
  "Pendente": "#f97316",
  "Confirmado": "#22c55e",
  "Rejeitado": "#ef4444",
  "Indeterminado": "#eab308",
};

// --- ICON FIX ---
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
});


// --- REUSABLE COMPONENTS ---
export const OccurrencesChart: React.FC<{ data?: PoiData[]; series?: { name: string; val: number }[] }> = ({ data, series }) => {
    const sourceData = data ?? masterPois;
    const monthLabels = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"];
    const counts = new Array(12).fill(0);
    sourceData.forEach((item) => {
        const monthIndex = Number(new Intl.DateTimeFormat("en", { month: "numeric", timeZone: BRAZIL_TIME_ZONE }).format(new Date(item.timestamp))) - 1;
        counts[monthIndex] += 1;
    });
    const fallbackData = monthLabels.map((name, index) => ({ name, val: counts[index] }));
    const chartData = series && series.length > 0 ? series : fallbackData;
    return (
        <div className="w-full h-64">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} barSize={12}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e5e5" />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#666" }} dy={10} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: "#666" }} />
                    <RechartsTooltip cursor={{ fill: "transparent" }} contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }} />
                    <Bar dataKey="val" fill="#a3e635" radius={[4, 4, 4, 4]} />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
};

const Slider: React.FC<{ label: string; value: number; min: number; max: number; step: number; unit?: string; hint?: string; onChange: (v: number) => void; }> = ({ label, value, min, max, step, unit, hint, onChange }) => (
    <div>
        <label className="flex justify-between text-sm text-gray-800">
            <span>{label}</span>
            <span className="text-gray-900 font-medium">{value.toFixed(2)}{unit} {hint && <span className="text-gray-500 font-normal">{hint}</span>}</span>
        </label>
        <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} className="w-full h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-lime-500 mt-1" />
    </div>
);

const getStatusStyle = (status: PoiData['status']) => {
    switch (status) { case "Pendente": return "bg-orange-100 text-orange-600"; case "Confirmado": return "bg-green-100 text-green-600"; case "Rejeitado": return "bg-red-100 text-red-600"; case "Indeterminado": return "bg-yellow-100 text-yellow-600"; default: return "bg-gray-100 text-gray-600"; }
};


// --- MAP LAYERS & LEGEND ---
const HeatmapLayer: React.FC<{ points: L.HeatLatLngTuple[]; options: L.HeatMapOptions; }> = ({ points, options }) => {
  const map = useMap();
  const layerRef = useRef<L.HeatLayer | null>(null);
  useEffect(() => {
    if (!layerRef.current) {
      layerRef.current = L.heatLayer(points, options).addTo(map);
    } else {
      layerRef.current.setOptions(options);
      layerRef.current.setLatLngs(points);
    }
  }, [map, points, options]);
  return null;
};

const BubbleMapLayer: React.FC<{ points: PoiData[]; scaleFactor: number; onMarkerClick?: (poi: PoiData) => void }> = ({ points, scaleFactor, onMarkerClick }) => {
    const getBubbleRadius = (volume: number) => {
        // Normalize tiny m³ values (e.g., 0.05) so markers stay visible without overgrowing large events.
        const safeVolume = Math.max(volume, 0);
        const normalized = Math.sqrt((safeVolume * 100) + 1);
        return Math.min(50, Math.max(8, normalized * scaleFactor));
    };

    return <> {points.map(point => (
        <CircleMarker
            key={point.id}
            center={[point.latitude, point.longitude]}
            radius={getBubbleRadius(point.volume)}
            pathOptions={{ color: statusColors[point.status], fillColor: statusColors[point.status], fillOpacity: 0.6, weight: 1 }}
        >
            <LeafletTooltip>
                <div className="font-bold">{point.bairro}</div>
                <div>{point.wasteType} - {point.volume} m³</div>
            </LeafletTooltip>
            <RichPopup point={point} onMarkerClick={onMarkerClick} />
        </CircleMarker>
    ))} </>;
};

const Legend: React.FC<{ map: L.Map | null; points: PoiData[] }> = ({ map, points }) => {
    const legendRef = useRef<L.Control | null>(null);

    useEffect(() => {
        if (!map) return;
        
        // Remove old legend if it exists
        if (legendRef.current) {
            legendRef.current.remove();
        }

        const legend = new L.Control({ position: 'bottomright' });
        legend.onAdd = () => {
            const div = L.DomUtil.create('div', 'info legend bg-white/80 backdrop-blur-md p-3 rounded-lg shadow-lg');
            if (mapMode === 'heatmap') {
                div.innerHTML = `
                    <h4 class="font-bold text-sm mb-2">Intensidade (Volume)</h4>
                    <div class="w-full h-5 rounded-md" style="background: linear-gradient(to right, blue, cyan, purple, red);"></div>
                    <div class="flex justify-between text-xs mt-1">
                        <span>Baixo</span>
                        <span>Médio</span>
                        <span>Alto</span>
                    </div>
                `;
            } else { // bubble mode
                const statusEntries: Array<PoiData["status"]> = [
                  "Pendente",
                  "Confirmado",
                  "Rejeitado",
                  "Indeterminado",
                ];
                let content = '<h4 class="font-bold text-sm mb-2">Status</h4>';
                statusEntries.forEach((status) => {
                    content += `
                        <div class="flex items-center gap-2 mt-1">
                            <i class="w-3 h-3 rounded-full" style="background-color: ${statusColors[status]}"></i>
                            <span class="text-xs">${status}</span>
                        </div>
                    `;
                });
                div.innerHTML = content;
            }
            return div;
        };

        legend.addTo(map);
        legendRef.current = legend;

        return () => {
            if (legendRef.current) {
                legendRef.current.remove();
            }
        };
    }, [map, mapMode, points]);

    return null;
};


// --- POPUP COMPONENT ---
const RichPopup: React.FC<{ point: PoiData; onMarkerClick?: (poi: PoiData) => void }> = ({ point, onMarkerClick }) => (
    <Popup>
        <div className="w-64">
            <div className="font-bold text-lg mb-1">{point.bairro}</div>
            <div className="text-gray-600 text-sm mb-3">{point.logradouro}</div>
            <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2"><Clock size={14} className="text-gray-500"/><span>{new Date(point.timestamp).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span></div>
                <div className="flex items-center gap-2"><Trash2 size={14} className="text-gray-500"/><span>{point.wasteType} ({point.volume} m³)</span></div>
                <div className="flex items-center gap-2"><HelpCircle size={14} className="text-gray-500"/><span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${getStatusStyle(point.status)}`}>{point.status}</span></div>
                <div className="flex items-center gap-2"><UserX size={14} className="text-gray-500"/><span>Infrator: <span className={point.hasOffender ? 'font-bold text-red-500' : 'font-medium text-gray-700'}>{point.hasOffender ? 'Identificado' : 'Não'}</span></span></div>
            </div>
            <button
              type="button"
              onClick={() => onMarkerClick?.(point)}
              className="mt-4 w-full bg-lime-500 text-black text-center font-bold py-2 rounded-lg hover:bg-lime-600 transition-colors flex items-center justify-center gap-2"
            >
              <Camera size={16}/> Ver Foto
            </button>
        </div>
    </Popup>
);


// --- MAIN WIDGET ---
export const MapWidget: React.FC<{ isExpanded: boolean; onToggleExpand: () => void; points?: PoiData[]; onMarkerClick?: (poi: PoiData) => void }> = ({ isExpanded, onToggleExpand, points, onMarkerClick }) => {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [mapInstance, setMapInstance] = useState<L.Map | null>(null);
  const dataPoints = points ?? masterPois;

  // Heatmap settings
  const [radius, setRadius] = useState(25);
  const [blur, setBlur] = useState(15);
  const [maxIntensity, setMaxIntensity] = useState(1.0);
  const [minOpacity, setMinOpacity] = useState(0.5);
  const [lowThreshold, setLowThreshold] = useState(0.3);
  const [highThreshold, setHighThreshold] = useState(0.6);

  // Bubble map settings
  const [scaleFactor, setScaleFactor] = useState(1.5);

  const heatmapPoints = dataPoints.map(p => [p.latitude, p.longitude, p.volume / 100] as L.HeatLatLngTuple);
  const heatmapOptions: L.HeatMapOptions = { radius, blur, minOpacity, max: maxIntensity, gradient: { 0.0: 'blue', [lowThreshold]: 'cyan', [highThreshold]: 'purple', 1.0: 'red' } };

  return (
    <div className={`relative w-full h-full rounded-2xl overflow-hidden shadow-lg group ${isExpanded ? "fixed inset-0 z-50 m-0 rounded-none" : ""}`}>
        
        {isSettingsOpen && (
            <div className="absolute top-16 right-4 bg-white/95 backdrop-blur-sm text-gray-900 p-4 z-[1001] w-80 rounded-2xl shadow-2xl border border-gray-200 animate-in fade-in-5 zoom-in-95 duration-200">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-bold flex items-center gap-2 text-gray-800"><Palette size={20}/>Config. do Mapa</h3>
                    <button onClick={() => setIsSettingsOpen(false)} className="p-1 rounded-full hover:bg-black/10 transition-colors"><X size={20}/></button>
                </div>
                <div className="space-y-4">
                    {mapMode === 'heatmap' ? (
                        <>
                            <Slider label="Limite Azul-Roxo" value={lowThreshold} min={0.0} max={1.0} step={0.05} onChange={setLowThreshold} hint={`(${(lowThreshold * 100).toFixed(0)}m³)`} />
                            <Slider label="Limite Roxo-Vermelho" value={highThreshold} min={0.0} max={1.0} step={0.05} onChange={setHighThreshold} hint={`(${(highThreshold * 100).toFixed(0)}m³)`} />
                            <hr className="border-gray-200 my-2" />
                            <Slider label="Radius" value={radius} min={5} max={50} step={1} unit="px" onChange={setRadius} />
                            <Slider label="Blur" value={blur} min={5} max={50} step={1} unit="px" onChange={setBlur} />
                            <Slider label="Max Intensity" value={maxIntensity} min={0.1} max={1.0} step={0.05} onChange={setMaxIntensity} />
                            <Slider label="Min Opacity" value={minOpacity} min={0} max={1} step={0.05} onChange={setMinOpacity} />
                        </>
                    ) : ( // bubble mode
                        <Slider label="Fator de Escala" value={scaleFactor} min={1} max={12} step={0.1} unit="x" onChange={setScaleFactor} />
                    )}
                </div>
            </div>
        )}

      <MapContainer ref={setMapInstance} center={[-8.06, -34.90]} zoom={12} scrollWheelZoom={true} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        
        {mapMode === 'heatmap' ? (
          <HeatmapLayer points={heatmapPoints} options={heatmapOptions} />
        ) : (
          <BubbleMapLayer points={dataPoints} scaleFactor={scaleFactor} onMarkerClick={onMarkerClick} />
        )}
        
        {/* Render Markers on top of Heatmap, but not for Bubble Map */}
        {mapMode === 'heatmap' && dataPoints.map((point: PoiData) => (
          <Marker key={point.id} position={[point.latitude, point.longitude]}>
            <RichPopup point={point} onMarkerClick={onMarkerClick} />
          </Marker>
        ))}

        <Legend map={mapInstance} points={dataPoints} />
      </MapContainer>

      {/* ACTION BUTTONS */}
      <div className="absolute top-4 right-4 z-[1000] flex flex-col gap-2">
          <button onClick={() => setIsSettingsOpen(!isSettingsOpen)} className={`bg-white p-2 rounded-lg shadow-lg hover:bg-gray-100 transition-colors text-gray-700 ${isSettingsOpen ? 'bg-lime-400 text-black' : ''}`}><Settings size={20} /></button>
      </div>
    </div>
  );
};

