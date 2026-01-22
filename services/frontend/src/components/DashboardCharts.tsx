import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { Maximize2, X, Plus, Minus } from "lucide-react";

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
          {/* Matches the lime green color in prototype */}
          <Bar dataKey="val" fill="#a3e635" radius={[4, 4, 4, 4]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// --- MAP COMPONENT ---
interface MapWidgetProps {
  isExpanded: boolean;
  onToggleExpand: () => void;
}

export const MapWidget: React.FC<MapWidgetProps> = ({
  isExpanded,
  onToggleExpand,
}) => {
  // Styles to simulate the Heatmap look from the screenshot without needing complex GIS data
  // In a real app, this would be a Leaflet/Google Maps instance.
  const mapStyle = {
    backgroundImage:
      "radial-gradient(circle at 50% 50%, rgba(255, 0, 0, 0.5), transparent 60%), radial-gradient(circle at 30% 40%, rgba(255, 165, 0, 0.6), transparent 50%), linear-gradient(135deg, #0ea5e9 0%, #10b981 100%)",
    backgroundSize: "cover",
  };

  return (
    <div
      className={`relative w-full h-full rounded-2xl overflow-hidden shadow-inner group ${isExpanded ? "fixed inset-0 z-50 m-0 rounded-none" : ""}`}
    >
      {/* Simulated Map Background (Blue/Green with heatmap spots) */}
      <div className="absolute inset-0 bg-[#0f766e] opacity-90"></div>
      {/* Heatmap Simulation Gradients */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-yellow-400 rounded-full blur-[100px] opacity-60 mix-blend-screen animate-pulse"></div>
      <div className="absolute top-1/2 left-1/2 w-80 h-80 bg-red-500 rounded-full blur-[80px] opacity-70 mix-blend-screen"></div>

      {/* Map Labels / Overlay UI */}
      <div className="absolute inset-0 p-6 pointer-events-none">
        <span className="text-white/80 font-bold text-lg tracking-widest uppercase absolute top-10 left-10">
          Torre
        </span>
        <span className="text-white/60 font-semibold absolute top-20 right-20">
          Olinda
        </span>
        <span className="text-white/60 font-semibold absolute bottom-20 left-20">
          Cordeiro
        </span>

        {/* Floating "Pins" or Heatmap centers */}
        <div className="absolute top-[40%] left-[45%] bg-orange-500/90 w-10 h-10 rounded-full flex items-center justify-center text-white font-bold shadow-lg border-2 border-white">
          35
        </div>
        <div className="absolute top-[30%] left-[30%] bg-orange-400/90 w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg border-2 border-white">
          12
        </div>
      </div>

      {/* Controls */}
      <div className="absolute bottom-4 left-4 flex flex-col gap-2 pointer-events-auto">
        <button className="w-8 h-8 bg-white rounded-md flex items-center justify-center shadow-md hover:bg-gray-100 text-gray-700 font-bold">
          <Plus size={16} />
        </button>
        <button className="w-8 h-8 bg-white rounded-md flex items-center justify-center shadow-md hover:bg-gray-100 text-gray-700 font-bold">
          <Minus size={16} />
        </button>
      </div>

      {/* Expand/Close Button */}
      <button
        onClick={onToggleExpand}
        className="absolute top-4 right-4 bg-white p-2 rounded-lg shadow-lg hover:bg-gray-50 transition-colors pointer-events-auto text-gray-700"
      >
        {isExpanded ? <X size={20} /> : <Maximize2 size={20} />}
      </button>
    </div>
  );
};
