import React, { useState, useMemo, useCallback, useEffect } from "react";
import { Sidebar } from "../components/Sidebar";
import { Tooltip } from "../components/Tooltip";
import { getAllDetections } from "../services/detectionService";
import type { PoiData } from "../services/detectionService";
import type { WasteType } from "../services/mockData";
import {
  Info,
  Filter as FilterIcon,
  AlertTriangle,
  Users,
  Circle,
  CheckCircle2,
  MapPin,
  Download,
} from "lucide-react";

// Recharts imports
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
} from "recharts";

// Import Shared Filter Components
import {
  FilterPopover,
  FilterMultiSelect,
  FilterAutocomplete,
} from "../components/SharedFilters";

// --- DATE HELPERS ---
function toDateInputStatic(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function getDefault30DayRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 29);
  return { start: toDateInputStatic(start), end: toDateInputStatic(end) };
}

// --- CONSTANTS & HELPERS ---
const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];
const STATUS_OPTIONS = ["Pendente", "Resolvido", "Em análise"];
const RPA_OPTIONS = ["RPA 1", "RPA 2", "RPA 3", "RPA 4", "RPA 5", "RPA 6"];
const OFFENDER_OPTIONS = ["Identificado", "Não Identificado"];

// Define Colors
const WASTE_COLORS: Record<string, string> = {
  Entulho: "#ccff33",
  "Lixo domiciliar": "#4ade80",
  Poda: "#16a34a",
  Plástico: "#dcfce7",
};

const OFFENDER_COLORS = {
  Identificado: "#bef264",
  "Não Identificado": "#e5e7eb",
};

const getRpaForPoi = (poi: PoiData) => {
  const key = `${poi.bairro}-${poi.logradouro}`;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % 6;
  return `RPA ${index + 1}`;
};

interface FilterState {
  date: string;
  startTime: string;
  endTime: string;
  status: string[];
  logradouro: string;
  bairro: string;
  rpa: string[];
  tipoResiduo: WasteType[];
  volMin: string;
  volMax: string;
  infratores: string[];
}

// --- KPI CARD COMPONENT ---
const StatCard: React.FC<{
  icon: React.ElementType;
  value: number;
  label: string;
  color: string;
  bg: string;
}> = ({ icon: Icon, value, label, color, bg }) => (
  <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex items-center gap-4 flex-1 min-w-[200px]">
    <div
      className={`w-12 h-12 ${bg} rounded-full flex items-center justify-center`}
    >
      <Icon size={24} className={color} />
    </div>
    <div>
      <span className="text-xs text-gray-500 block mb-1 font-medium">
        {label}
      </span>
      <h3 className="text-3xl font-bold text-[#1a1a1a]">{value}</h3>
    </div>
  </div>
);

export const HistoryPage: React.FC = () => {
  // --- STATE ---
  const [detections, setDetections] = useState<PoiData[]>([]);
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [activePopover, setActivePopover] = useState<
    "period" | "volumetry" | null
  >(null);
  const [filters, setFilters] = useState<FilterState>({
    date: "",
    startTime: "",
    endTime: "",
    status: [],
    logradouro: "",
    bairro: "",
    rpa: [],
    tipoResiduo: [],
    volMin: "",
    volMax: "",
    infratores: [],
  });

  useEffect(() => {
    let isMounted = true;

    async function loadDetections() {
      try {
        const range = getDefault30DayRange();
        const all = await getAllDetections({
          start_date: `${range.start}T00:00:00`,
          end_date: `${range.end}T23:59:59`,
        });

        if (isMounted) {
          setDetections(all);
        }
      } catch (e) {
        console.error("Failed to load history detections:", e);
      }
    }

    loadDetections();
    return () => {
      isMounted = false;
    };
  }, []);

  // --- FILTERING LOGIC ---
  const matchesFilters = useCallback(
    (item: PoiData, exclude?: keyof FilterState) => {
      const itemRpa = getRpaForPoi(item);

      if (exclude !== "status" && filters.status.length > 0) {
        if (!filters.status.includes(item.status)) return false;
      }
      if (
        exclude !== "logradouro" &&
        filters.logradouro &&
        !item.logradouro
          .toLowerCase()
          .includes(filters.logradouro.toLowerCase())
      )
        return false;
      if (
        exclude !== "bairro" &&
        filters.bairro &&
        !item.bairro.toLowerCase().includes(filters.bairro.toLowerCase())
      )
        return false;
      if (
        exclude !== "rpa" &&
        filters.rpa.length > 0 &&
        !filters.rpa.includes(itemRpa)
      )
        return false;
      if (
        exclude !== "tipoResiduo" &&
        filters.tipoResiduo.length > 0 &&
        !filters.tipoResiduo.includes(item.wasteType)
      )
        return false;
      if (
        filters.volMin &&
        item.volume < parseFloat(filters.volMin.replace(",", "."))
      )
        return false;
      if (
        filters.volMax &&
        item.volume > parseFloat(filters.volMax.replace(",", "."))
      )
        return false;
      if (exclude !== "infratores" && filters.infratores.length > 0) {
        const wantsIdentified = filters.infratores.includes("Identificado");
        const wantsUnknown = filters.infratores.includes("Não Identificado");
        const matches =
          (item.hasOffender && wantsIdentified) ||
          (!item.hasOffender && wantsUnknown);
        if (!matches) return false;
      }
      if (filters.date) {
        const itemDate = new Date(item.timestamp);
        const itemIsoDate = itemDate.toISOString().slice(0, 10);
        const itemTime = itemDate.toISOString().slice(11, 16);
        if (itemIsoDate !== filters.date) return false;
        if (filters.startTime && itemTime < filters.startTime) return false;
        if (filters.endTime && itemTime > filters.endTime) return false;
      }
      return true;
    },
    [filters],
  );

  // --- MEMOIZED DATA ---
  const filteredData = useMemo(
    () => detections.filter((item) => matchesFilters(item)),
    [detections, matchesFilters],
  );

  const bairroOptions = useMemo(
    () => Array.from(new Set(detections.map((i) => i.bairro))).sort(),
    [detections],
  );
  const logradouroOptions = useMemo(
    () => Array.from(new Set(detections.map((i) => i.logradouro))).sort(),
    [detections],
  );

  // --- CHART DATA CALCULATIONS ---

  // 1. Evolution Data
  const evolutionData = useMemo(() => {
    const timestamps = filteredData.map((d) => new Date(d.timestamp).getTime());
    const maxDateMs =
      timestamps.length > 0 ? Math.max(...timestamps) : Date.now();
    const anchorDate = new Date(maxDateMs);

    const dataMap = new Map<string, { open: number; closed: number }>();
    filteredData.forEach((item) => {
      const d = new Date(item.timestamp);
      const key = d.toISOString().split("T")[0];
      if (!dataMap.has(key)) dataMap.set(key, { open: 0, closed: 0 });

      if (item.status === "Resolvido") {
        dataMap.get(key)!.closed++;
      } else {
        dataMap.get(key)!.open++;
      }
    });

    const result = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(anchorDate);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().split("T")[0];
      const stats = dataMap.get(key) || { open: 0, closed: 0 };

      result.push({
        dayLabel: 30 - i,
        date: key,
        closed: stats.closed,
        open: stats.open,
      });
    }
    return result;
  }, [filteredData]);

  // 2. Hourly Distribution
  const hourlyData = useMemo(() => {
    const timestamps = filteredData.map((d) => new Date(d.timestamp).getTime());
    const maxDateMs =
      timestamps.length > 0 ? Math.max(...timestamps) : Date.now();
    const anchorDate = new Date(maxDateMs);
    const thirtyDaysAgo = new Date(anchorDate);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    const hourCounts = new Array(24).fill(0);

    filteredData.forEach((item) => {
      const d = new Date(item.timestamp);
      if (d >= thirtyDaysAgo && d <= anchorDate) {
        const h = d.getHours();
        hourCounts[h]++;
      }
    });

    const allHours = hourCounts.map((count, i) => ({
      originalHour: i,
      label: `${String(i).padStart(2, "0")}h`,
      count: count,
    }));

    const top16 = allHours.sort((a, b) => b.count - a.count).slice(0, 16);

    return top16.sort((a, b) => a.originalHour - b.originalHour);
  }, [filteredData]);

  // 3. Weekday Distribution
  const weekdayData = useMemo(() => {
    const timestamps = filteredData.map((d) => new Date(d.timestamp).getTime());
    const maxDateMs =
      timestamps.length > 0 ? Math.max(...timestamps) : Date.now();
    const anchorDate = new Date(maxDateMs);
    anchorDate.setHours(0, 0, 0, 0);

    const days: { name: string; date: string; count: number }[] = [];
    const dayByDate = new Map<string, { name: string; date: string; count: number }>();

    for (let i = 6; i >= 0; i--) {
      const d = new Date(anchorDate);
      d.setDate(d.getDate() - i);

      const dateKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const dayName = d
        .toLocaleDateString("pt-BR", { weekday: "short" })
        .toUpperCase()
        .replace(".", "");

      const dayEntry = {
        name: dayName,
        date: dateKey,
        count: 0,
      };
      days.push(dayEntry);
      dayByDate.set(dateKey, dayEntry);
    }

    filteredData.forEach((item) => {
      const d = new Date(item.timestamp);
      const itemDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const targetDay = dayByDate.get(itemDate);
      if (targetDay) {
        targetDay.count++;
      }
    });

    return days;
  }, [filteredData]);

  // 4. UPDATED: Top Locations (Dynamic Size)
  const topLocations = useMemo(() => {
    const locMap = new Map<string, { count: number; bairro: string }>();
    filteredData.forEach((item) => {
      const key = item.logradouro;
      if (!locMap.has(key)) locMap.set(key, { count: 0, bairro: item.bairro });
      locMap.get(key)!.count++;
    });
    // Removed slice(0,5) to allow dynamic filling
    return Array.from(locMap.entries()).sort((a, b) => b[1].count - a[1].count);
  }, [filteredData]);

  // 5. Waste Type
  const wasteTypeData = useMemo(() => {
    const counts: Record<string, number> = {};
    WASTE_TYPE_OPTIONS.forEach((t) => (counts[t] = 0));

    let total = 0;
    filteredData.forEach((item) => {
      if (counts[item.wasteType] !== undefined) {
        counts[item.wasteType]++;
        total++;
      }
    });

    return Object.entries(counts)
      .map(([name, value]) => ({
        name,
        value,
        pct: total > 0 ? Math.round((value / total) * 100) : 0,
      }))
      .filter((item) => item.value > 0);
  }, [filteredData]);

  // 6. Offender Stats
  const offenderData = useMemo(() => {
    let yes = 0;
    let no = 0;
    filteredData.forEach((item) => (item.hasOffender ? yes++ : no++));
    const total = yes + no;
    return {
      yes,
      no,
      pctYes: total > 0 ? Math.round((yes / total) * 100) : 0,
      pctNo: total > 0 ? Math.round((no / total) * 100) : 0,
    };
  }, [filteredData]);

  const offenderChartData = useMemo(
    () =>
      [
        {
          name: "Identificado",
          value: offenderData.yes,
          color: OFFENDER_COLORS["Identificado"],
          pct: offenderData.pctYes,
        },
        {
          name: "Não Identificado",
          value: offenderData.no,
          color: OFFENDER_COLORS["Não Identificado"],
          pct: offenderData.pctNo,
        },
      ].filter((item) => item.value > 0),
    [offenderData],
  );

  const totalOccurrences = filteredData.length;
  const totalOffenders = filteredData.filter((i) => i.hasOffender).length;
  const totalOpen = filteredData.filter((i) => i.status !== "Resolvido").length;
  const totalClosed = filteredData.filter(
    (i) => i.status === "Resolvido",
  ).length;

  const handleDownloadCSV = () => {
    alert(`Exportando ${totalOccurrences} registros...`);
  };

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto overflow-x-hidden">
        {/* Header */}
        <div className="flex items-center gap-2 mb-8">
          <h1 className="text-2xl font-bold text-[#1a1a1a]">
            Análise do histórico das ocorrências
          </h1>
          <Tooltip text="Visão geral e indicadores de desempenho das ocorrências registradas no sistema.">
            <Info
              size={18}
              className="text-gray-400 cursor-pointer hover:text-gray-600"
            />
          </Tooltip>
        </div>

        {/* --- FILTERS SECTION --- */}
        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-4">
              <div className="relative">
                <FilterPopover
                  label="Período"
                  active={activePopover === "period"}
                  hasValue={
                    !!(filters.date || filters.startTime || filters.endTime)
                  }
                  onClear={() =>
                    setFilters((p) => ({
                      ...p,
                      date: "",
                      startTime: "",
                      endTime: "",
                    }))
                  }
                  onClick={() =>
                    setActivePopover((p) => (p === "period" ? null : "period"))
                  }
                  onClose={() => setActivePopover(null)}
                >
                  <div className="flex flex-col gap-3">
                    <div>
                      <label className="text-xs text-gray-500 font-bold mb-1 block">
                        Data
                      </label>
                      <input
                        type="date"
                        className="w-full border border-gray-300 rounded p-2 text-sm"
                        value={filters.date}
                        onChange={(e) =>
                          setFilters((p) => ({ ...p, date: e.target.value }))
                        }
                      />
                    </div>
                  </div>
                </FilterPopover>
              </div>
              <FilterMultiSelect
                label="Status"
                value={filters.status}
                options={STATUS_OPTIONS}
                onChange={(v) => setFilters((p) => ({ ...p, status: v }))}
              />
              <FilterAutocomplete
                label="Logradouro"
                value={filters.logradouro}
                options={logradouroOptions}
                onChange={(v) => setFilters((p) => ({ ...p, logradouro: v }))}
              />
              <FilterAutocomplete
                label="Bairro"
                value={filters.bairro}
                options={bairroOptions}
                onChange={(v) => setFilters((p) => ({ ...p, bairro: v }))}
              />
              <FilterMultiSelect
                label="RPA"
                value={filters.rpa}
                options={RPA_OPTIONS}
                onChange={(v) => setFilters((p) => ({ ...p, rpa: v }))}
              />
              {showAllFilters && (
                <>
                  <div className="animate-in slide-in-from-top-2 duration-300">
                    <FilterMultiSelect
                      label="Tipo de Resíduo"
                      value={filters.tipoResiduo}
                      options={WASTE_TYPE_OPTIONS}
                      onChange={(v) =>
                        setFilters((p) => ({
                          ...p,
                          tipoResiduo: v as WasteType[],
                        }))
                      }
                    />
                  </div>
                  <div className="relative animate-in slide-in-from-top-2 duration-300">
                    <FilterPopover
                      label="Volumetria"
                      active={activePopover === "volumetry"}
                      hasValue={!!(filters.volMin || filters.volMax)}
                      onClear={() =>
                        setFilters((p) => ({ ...p, volMin: "", volMax: "" }))
                      }
                      onClick={() =>
                        setActivePopover((p) =>
                          p === "volumetry" ? null : "volumetry",
                        )
                      }
                      onClose={() => setActivePopover(null)}
                    >
                      <div className="flex gap-2 items-center">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Min (m³)
                          </label>
                          <input
                            type="number"
                            step="0.1"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            placeholder="0.0"
                            value={filters.volMin}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                volMin: e.target.value,
                              }))
                            }
                          />
                        </div>
                        <span className="pt-5 text-gray-400">-</span>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Max (m³)
                          </label>
                          <input
                            type="number"
                            step="0.1"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            placeholder="100.0"
                            value={filters.volMax}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                volMax: e.target.value,
                              }))
                            }
                          />
                        </div>
                      </div>
                    </FilterPopover>
                  </div>
                  <div className="animate-in slide-in-from-top-2 duration-300">
                    <FilterMultiSelect
                      label="Infratores"
                      value={filters.infratores}
                      options={OFFENDER_OPTIONS}
                      onChange={(v) =>
                        setFilters((p) => ({ ...p, infratores: v }))
                      }
                    />
                  </div>
                  <div className="hidden md:block"></div>
                  <div className="hidden md:block"></div>
                </>
              )}
            </div>
          </div>
          <div className="flex gap-4 pt-[25px]">
            <Tooltip
              text={showAllFilters ? "Recolher filtros" : "Expandir filtros"}
              className="w-fit"
            >
              <button
                onClick={() => setShowAllFilters(!showAllFilters)}
                className={`w-14 h-[50px] bg-white border border-gray-200 rounded-xl flex items-center justify-center hover:bg-gray-50 text-gray-600 transition-colors ${
                  showAllFilters ? "bg-gray-100 ring-2 ring-gray-200" : ""
                }`}
              >
                <FilterIcon size={22} />
              </button>
            </Tooltip>
            <Tooltip text="Exportar relatório" className="w-fit">
              <button
                onClick={handleDownloadCSV}
                className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
              >
                <Download size={24} />
              </button>
            </Tooltip>
          </div>
        </div>

        {/* --- KPI Cards --- */}
        <div className="flex flex-wrap gap-6 mb-8">
          <StatCard
            icon={AlertTriangle}
            value={totalOccurrences}
            label="Total de ocorrências"
            color="text-yellow-600"
            bg="bg-yellow-50"
          />
          <StatCard
            icon={Users}
            value={totalOffenders}
            label="Total de infratores"
            color="text-red-500"
            bg="bg-red-50"
          />
          <StatCard
            icon={Circle}
            value={totalOpen}
            label="Ocorrências abertas"
            color="text-orange-400"
            bg="bg-orange-50"
          />
          <StatCard
            icon={CheckCircle2}
            value={totalClosed}
            label="Ocorrências fechadas"
            color="text-green-500"
            bg="bg-green-50"
          />
        </div>

        {/* --- Charts Row 1 --- */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          {/* Evolution Chart */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[320px]">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-sm font-bold text-gray-700">
                Evolução das ocorrências nos últimos 30 dias
              </h3>
              <Tooltip text="Acompanhamento diário.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={evolutionData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    stroke="#e5e5e5"
                  />
                  <XAxis
                    dataKey="dayLabel"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "#666" }}
                    dy={10}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "#666" }}
                  />
                  <RechartsTooltip
                    cursor={{ fill: "transparent" }}
                    contentStyle={{
                      borderRadius: "8px",
                      border: "none",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    }}
                  />
                  <Bar
                    dataKey="closed"
                    name="Fechados"
                    fill="#a3e635"
                    barSize={12}
                    radius={[4, 4, 0, 0]}
                  />
                  <Line
                    type="monotone"
                    dataKey="open"
                    name="Abertas"
                    stroke="#f97316"
                    strokeWidth={3}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="flex items-center justify-center gap-4 mt-2">
              <div className="flex items-center gap-1.5 text-xs text-gray-500">
                <div className="w-2.5 h-2.5 rounded-full bg-[#a3e635]"></div>
                <span>Fechados</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-gray-500">
                <div className="w-2.5 h-2.5 rounded-full bg-[#f97316]"></div>
                <span>Abertas</span>
              </div>
            </div>
          </div>

          {/* Hours Chart */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[320px]">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-sm font-bold text-gray-700">
                Horários de maior incidência
              </h3>
              <Tooltip text="Horários com maior acúmulo de ocorrências nos últimos 30 dias.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={hourlyData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    stroke="#e5e5e5"
                  />
                  <XAxis
                    dataKey="label"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "#666" }}
                    dy={10}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: "#666" }}
                  />
                  <RechartsTooltip
                    cursor={{ fill: "transparent" }}
                    contentStyle={{
                      borderRadius: "8px",
                      border: "none",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    }}
                  />
                  <Bar
                    dataKey="count"
                    name="Ocorrências"
                    fill="#a3e635"
                    barSize={12}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Days Chart */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[320px]">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-sm font-bold text-gray-700">
                Dias de maior incidência
              </h3>
              <Tooltip text="Ocorrências nos últimos 7 dias.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>
            <div className="flex-1 w-full min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={weekdayData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
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
                    tick={{ fontSize: 10, fill: "#666" }}
                  />
                  <RechartsTooltip
                    cursor={{ fill: "transparent" }}
                    contentStyle={{
                      borderRadius: "8px",
                      border: "none",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    }}
                    labelFormatter={(label, payload) => {
                      if (payload && payload.length > 0) {
                        return `${label} (${payload[0].payload.date})`;
                      }
                      return label;
                    }}
                  />
                  <Bar
                    dataKey="count"
                    name="Ocorrências"
                    fill="#a3e635"
                    barSize={16}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* --- Charts Row 2 --- */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* UPDATED: Top Locations List (Dynamic Size) */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[400px]">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-sm font-bold text-gray-700">
                Locais com mais ocorrências
              </h3>
              <Tooltip text="Ranking das ruas e bairros.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>
            <div className="flex text-xs font-bold text-gray-400 mb-2 border-b border-gray-100 pb-2 px-3">
              <span className="flex-1">Local</span>
              <span className="w-24">Bairro</span>
              <span className="w-16 text-right">Qtd.</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {topLocations.map(([name, data], i) => (
                <div
                  key={i}
                  className={`flex items-center text-sm py-3 px-3 rounded-lg ${i % 2 !== 0 ? "bg-gray-50" : "bg-white"}`}
                >
                  <div className="flex-1 flex items-center gap-2 text-gray-700">
                    <div className="p-1 bg-orange-100 rounded-full text-orange-500">
                      <MapPin size={10} />
                    </div>
                    <span className="truncate max-w-[150px]" title={name}>
                      {name}
                    </span>
                  </div>
                  <span
                    className="w-24 text-gray-500 truncate"
                    title={data.bairro}
                  >
                    {data.bairro}
                  </span>
                  <div className="w-16 text-right">
                    <span className="bg-red-100 text-red-500 font-bold px-2 py-1 rounded-md text-xs">
                      {data.count}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Waste Type Pie Chart */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[400px]">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-sm font-bold text-gray-700">
                Tipos de lixo descartado
              </h3>
              <Tooltip text="Proporção dos tipos de resíduos.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>

            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={wasteTypeData}
                    cx="50%"
                    cy="50%"
                    innerRadius={0}
                    outerRadius={120}
                    paddingAngle={0}
                    dataKey="value"
                    stroke="none"
                  >
                    {wasteTypeData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={WASTE_COLORS[entry.name]}
                      />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{
                      borderRadius: "8px",
                      border: "none",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    }}
                    formatter={(val: any) => [`${val} ocorrências`, "Qtd"]}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 mt-2">
              {wasteTypeData.map((item) => (
                <div
                  key={item.name}
                  className="flex items-center gap-2 text-sm font-medium text-gray-600"
                >
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: WASTE_COLORS[item.name] }}
                  ></div>
                  <span>
                    {item.name}{" "}
                    <span className="font-bold text-black ml-1">
                      {item.pct}%
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Offenders Donut Chart */}
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col h-[400px]">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-sm font-bold text-gray-700">
                Status do Infrator
              </h3>
              <Tooltip text="Identificado vs Não Identificado.">
                <Info
                  size={14}
                  className="text-gray-300 cursor-pointer hover:text-gray-500"
                />
              </Tooltip>
            </div>

            <div className="flex-1 flex items-center justify-center relative min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={offenderChartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={80}
                    outerRadius={120}
                    paddingAngle={0}
                    dataKey="value"
                    stroke="none"
                    startAngle={90}
                    endAngle={-270}
                  >
                    {offenderChartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{
                      borderRadius: "8px",
                      border: "none",
                      boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    }}
                    formatter={(val: any) => [`${val} ocorrências`, "Qtd"]}
                  />
                </PieChart>
              </ResponsiveContainer>

              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-3xl font-bold text-gray-800">
                  {offenderData.pctYes}%
                </span>
                <span className="text-xs text-gray-500 font-medium">
                  Identificado
                </span>
              </div>
            </div>

            <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 mt-2">
              {offenderChartData.map((item) => (
                <div
                  key={item.name}
                  className="flex items-center gap-2 text-sm font-medium text-gray-600"
                >
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: item.color }}
                  ></div>
                  <span>
                    {item.name}{" "}
                    <span className="font-bold text-black ml-1">
                      {item.pct}%
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};
