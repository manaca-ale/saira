import React, { useMemo, useState, useCallback, useEffect } from "react";
import { Sidebar } from "../components/Sidebar";
import { MapWidget, OccurrencesChart } from "../components/DashboardCharts";
import {
  Filter as FilterIcon,
  Trash2,
  AlertTriangle,
  Info,
  Disc,
} from "lucide-react";
import {
  FilterPopover,
  FilterMultiSelect,
  FilterAutocomplete,
} from "../components/SharedFilters";
import {
  classifyDetection,
  getAllDetections,
  getFilterOptions,
} from "../services/detectionService";
import type { ClassifyStatus, PoiData } from "../services/detectionService";
import { Tooltip } from "../components/Tooltip";
import { OccurrenceModal } from "../components/OccurrenceModal";
import { LoginNotificationBanner } from "../components/LoginNotificationBanner";
import { ClassifyConfirmationModal } from "../components/ClassifyConfirmationModal";
import { OffenderDashboardTab } from "../components/OffenderDashboardTab";
import { ImageExportTab } from "../components/ImageExportTab";
import { toBrazilDateString, BRAZIL_TIME_ZONE } from "../utils/datetime";

type WasteType = "Entulho" | "Lixo domiciliar" | "Poda" | "Plástico";

// --- DATA INTERFACE AND STATUS ---
interface FilterState {
  dateStart: string;
  dateEnd: string;
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

const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

// Rejeitado/Indeterminado are intentionally absent: they only appear on the camera detections screen.
const STATUS_OPTIONS = ["Pendente", "Confirmado"] as const;
const RPA_OPTIONS = [
  "RPA 1",
  "RPA 2",
  "RPA 3",
  "RPA 4",
  "RPA 5",
  "RPA 6",
];
const MONTHS_SHORT = [
  "Jan",
  "Fev",
  "Mar",
  "Abr",
  "Mai",
  "Jun",
  "Jul",
  "Ago",
  "Set",
  "Out",
  "Nov",
  "Dez",
];

const buildDateRange = (start?: string, end?: string) => {
  if (!start && !end) return null;
  const startDate = new Date(`${start || end}T00:00:00`);
  const endDate = new Date(`${end || start}T23:59:59`);
  return { start: startDate, end: endDate };
};

function toDateInputStatic(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function getDefaultDateRange() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(end.getFullYear() - 1);
  return { dateStart: toDateInputStatic(start), dateEnd: toDateInputStatic(end) };
}

const getRpaForPoi = (poi: PoiData) => {
  const key = `${poi.bairro}-${poi.logradouro}`;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % 6;
  return `RPA ${index + 1}`;
};

const dedupeLatestByLocation = (items: PoiData[]) => {
  const map = new Map<string, PoiData>();
  items.forEach((item) => {
    const key = `${item.latitude.toFixed(6)}|${item.longitude.toFixed(6)}`;
    const existing = map.get(key);
    if (!existing || new Date(item.timestamp) > new Date(existing.timestamp)) {
      map.set(key, item);
    }
  });
  return Array.from(map.values());
};

const diffDays = (start: Date, end: Date) =>
  Math.max(0, Math.ceil((end.getTime() - start.getTime()) / 86400000));

const formatDayLabel = (date: Date) => {
  const parts = new Intl.DateTimeFormat("en", { day: "2-digit", month: "2-digit", timeZone: BRAZIL_TIME_ZONE }).formatToParts(date);
  const day = parts.find(p => p.type === "day")!.value;
  const month = parts.find(p => p.type === "month")!.value;
  return `${day}/${month}`;
};

const toBrazilHourKey = (date: Date): string => {
  const d = toBrazilDateString(date);
  const h = String(Number(new Intl.DateTimeFormat("en", { hour: "numeric", hour12: false, timeZone: BRAZIL_TIME_ZONE }).format(date))).padStart(2, "0");
  return `${d}T${h}`;
};

const buildChartSeries = (data: PoiData[], start: Date, end: Date) => {
  const daysSpan = diffDays(start, end);

  if (daysSpan <= 2) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const date = new Date(item.timestamp);
      const key = toBrazilHourKey(date);
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    cursor.setMinutes(0, 0, 0);
    while (cursor <= end) {
      const key = toBrazilHourKey(cursor);
      const hour = String(Number(new Intl.DateTimeFormat("en", { hour: "numeric", hour12: false, timeZone: BRAZIL_TIME_ZONE }).format(cursor))).padStart(2, "0");
      const label = `${formatDayLabel(cursor)} ${hour}h`;
      series.push({ name: label, val: buckets.get(key) || 0 });
      cursor.setHours(cursor.getHours() + 1);
    }
    return series;
  }

  if (daysSpan <= 31) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const key = toBrazilDateString(item.timestamp);
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    cursor.setHours(0, 0, 0, 0);
    while (cursor <= end) {
      const key = toBrazilDateString(cursor);
      series.push({ name: formatDayLabel(cursor), val: buckets.get(key) || 0 });
      cursor.setDate(cursor.getDate() + 1);
    }
    return series;
  }

  if (daysSpan <= 90) {
    const buckets = new Map<string, number>();
    data.forEach((item) => {
      const date = new Date(item.timestamp);
      const weekStart = new Date(date);
      const day = (weekStart.getDay() + 6) % 7;
      weekStart.setDate(weekStart.getDate() - day);
      weekStart.setHours(0, 0, 0, 0);
      const key = toBrazilDateString(weekStart);
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });

    const series = [] as { name: string; val: number }[];
    const cursor = new Date(start);
    const day = (cursor.getDay() + 6) % 7;
    cursor.setDate(cursor.getDate() - day);
    cursor.setHours(0, 0, 0, 0);
    while (cursor <= end) {
      const key = toBrazilDateString(cursor);
      series.push({ name: formatDayLabel(cursor), val: buckets.get(key) || 0 });
      cursor.setDate(cursor.getDate() + 7);
    }
    return series;
  }

  const buckets = new Map<string, number>();
  data.forEach((item) => {
    const date = new Date(item.timestamp);
    const key = `${date.getFullYear()}-${date.getMonth()}`;
    buckets.set(key, (buckets.get(key) || 0) + 1);
  });

  const series = [] as { name: string; val: number }[];
  const cursor = new Date(start.getFullYear(), start.getMonth(), 1);
  const endCursor = new Date(end.getFullYear(), end.getMonth(), 1);
  while (cursor <= endCursor) {
    const key = `${cursor.getFullYear()}-${cursor.getMonth()}`;
    const label = `${MONTHS_SHORT[cursor.getMonth()]} ${String(
      cursor.getFullYear(),
    ).slice(2)}`;
    series.push({ name: label, val: buckets.get(key) || 0 });
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return series;
};

export const Dashboard: React.FC = () => {
  // --- State Management ---
  const [activeTab, setActiveTab] = useState<"ocorrencias" | "infratores" | "exportar">("ocorrencias");
  const [detections, setDetections] = useState<PoiData[]>([]);
  const [loading, setLoading] = useState(true);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [filters, setFilters] = useState<FilterState>(() => {
    const { dateStart, dateEnd } = getDefaultDateRange();
    return {
      dateStart,
      dateEnd,
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
    };
  });
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [activePopover, setActivePopover] = useState<
    "period" | "volumetry" | null
  >(null);
  const [selectedOccurrence, setSelectedOccurrence] = useState<PoiData | null>(null);
  const [isOccurrenceModalOpen, setIsOccurrenceModalOpen] = useState(false);
  const [classifyTarget, setClassifyTarget] = useState<{
    detection: PoiData;
    action: ClassifyStatus;
  } | null>(null);
  const [isClassifying, setIsClassifying] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  // Opções de Bairro/Logradouro vindas do banco (domínio completo).
  const [bairrosOptions, setBairrosOptions] = useState<string[]>([]);
  const [logradouroOptions, setLogradouroOptions] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    getFilterOptions()
      .then((opts) => {
        if (!cancelled) {
          setBairrosOptions(opts.bairros);
          setLogradouroOptions(opts.logradouros);
        }
      })
      .catch((e) => console.error("Failed to load filter options:", e));
    return () => {
      cancelled = true;
    };
  }, []);

  // --- Load Data from API ---
  useEffect(() => {
    let cancelled = false;
    async function loadDetections() {
      setLoading(true);
      try {
        const startDate = filters.dateStart ? `${filters.dateStart}T${filters.startTime || "00:00"}:00` : undefined;
        const endDate = filters.dateEnd ? `${filters.dateEnd}T${filters.endTime || "23:59"}:59` : undefined;
        const data = await getAllDetections({
          start_date: startDate,
          end_date: endDate,
          status: filters.status.length > 0 ? filters.status : [...STATUS_OPTIONS],
          maxRecords: 2000,
          pageSize: 100,
        });
        if (!cancelled) setDetections(data);
      } catch (e) {
        console.error("Failed to load detections:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadDetections();
    return () => { cancelled = true; };
  }, [filters.dateStart, filters.dateEnd, filters.startTime, filters.endTime, filters.status]);

  const toDateInput = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate(),
    ).padStart(2, "0")}`;

  const applyDatePreset = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setFilters((p) => ({
      ...p,
      dateStart: toDateInput(start),
      dateEnd: toDateInput(end),
    }));
  };

  const baseData = useMemo(() => {
    const dateRange = buildDateRange(filters.dateStart, filters.dateEnd);

    return detections.filter((item) => {
      const itemDate = new Date(item.timestamp);
      if (dateRange) {
        if (itemDate < dateRange.start || itemDate > dateRange.end) return false;
      }

      if (filters.startTime && filters.endTime) {
        const itemTime = `${String(itemDate.getHours()).padStart(2, "0")}:${String(
          itemDate.getMinutes(),
        ).padStart(2, "0")}`;
        if (itemTime < filters.startTime) return false;
        if (itemTime > filters.endTime) return false;
      }

      return true;
    });
  }, [detections, filters.dateStart, filters.dateEnd, filters.startTime, filters.endTime]);

  const matchesFilters = useCallback((item: PoiData, exclude?: keyof FilterState) => {
    const rpa = getRpaForPoi(item);

    if (exclude !== "status" && filters.status.length > 0) {
      if (!filters.status.includes(item.status)) return false;
    }
    if (
      exclude !== "logradouro" &&
      filters.logradouro &&
      !item.logradouro.toLowerCase().includes(filters.logradouro.toLowerCase())
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
      !filters.rpa.includes(rpa)
    )
      return false;
    if (
      exclude !== "tipoResiduo" &&
      filters.tipoResiduo.length > 0 &&
      !filters.tipoResiduo.includes(item.wasteType)
    )
      return false;
    if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
      return false;
    if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
      return false;
    if (exclude !== "infratores" && filters.infratores.length > 0) {
      const wantsIdentified = filters.infratores.includes("Identificado");
      const wantsUnknown = filters.infratores.includes("Não Identificado");
      const matches =
        (item.hasOffender && wantsIdentified) ||
        (!item.hasOffender && wantsUnknown);
      if (!matches) return false;
    }

    return true;
  }, [filters]);

  const rpaOptions = useMemo(() => {
    const filtered = baseData.filter((item) => matchesFilters(item, "rpa"));
    const present = new Set(filtered.map((item) => getRpaForPoi(item)));
    return RPA_OPTIONS.filter((rpa) => present.has(rpa));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const tipoResiduoOptions = useMemo(() => {
    const filtered = baseData.filter((item) =>
      matchesFilters(item, "tipoResiduo"),
    );
    const present = new Set(filtered.map((item) => item.wasteType));
    return WASTE_TYPE_OPTIONS.filter((type) => present.has(type));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const offenderOptions = useMemo(() => {
    const filtered = baseData.filter((item) =>
      matchesFilters(item, "infratores"),
    );
    const options = [] as string[];
    if (filtered.some((item) => item.hasOffender)) options.push("Identificado");
    if (filtered.some((item) => !item.hasOffender))
      options.push("Não Identificado");
    return options;
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const statusOptions = useMemo(() => {
    const filtered = baseData.filter((item) => matchesFilters(item, "status"));
    const present = new Set(filtered.map((item) => item.status));
    return STATUS_OPTIONS.filter((status) => present.has(status));
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const handleLiveMode = () => {
    const today = new Date();
    const pastYear = new Date();
    pastYear.setFullYear(today.getFullYear() - 1);

    setFilters({
      dateStart: toDateInput(pastYear),
      dateEnd: toDateInput(today),
      startTime: "",
      endTime: "",
      status: ["Confirmado"],
      logradouro: "",
      bairro: "",
      rpa: [],
      tipoResiduo: [],
      volMin: "",
      volMax: "",
      infratores: [],
    });
  };

  const generalFilteredData = useMemo(() => {
    return baseData.filter((item) => {
      const rpa = getRpaForPoi(item);

      if (
        filters.logradouro &&
        !item.logradouro
          .toLowerCase()
          .includes(filters.logradouro.toLowerCase())
      )
        return false;
      if (
        filters.bairro &&
        !item.bairro.toLowerCase().includes(filters.bairro.toLowerCase())
      )
        return false;
      if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
        return false;
      if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
        return false;
      if (filters.rpa.length > 0 && !filters.rpa.includes(rpa)) return false;
      if (
        filters.tipoResiduo.length > 0 &&
        !filters.tipoResiduo.includes(item.wasteType)
      )
        return false;

      if (filters.infratores.length > 0) {
        const wantsIdentified = filters.infratores.includes("Identificado");
        const wantsUnknown = filters.infratores.includes("Não Identificado");
        const matches =
          (item.hasOffender && wantsIdentified) ||
          (!item.hasOffender && wantsUnknown);
        if (!matches) return false;
      }

      return true;
    });
  }, [
    baseData,
    filters.bairro,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const mapFilteredData = useMemo(() => {
    const withStatus =
      filters.status.length === 0
        ? generalFilteredData
        : generalFilteredData.filter((item) =>
            filters.status.includes(item.status),
          );
    return dedupeLatestByLocation(withStatus);
  }, [generalFilteredData, filters.status]);

  const totalOccurrences = generalFilteredData.length;
  const totalVolume = generalFilteredData.reduce(
    (sum, item) => sum + item.volume,
    0,
  );

  const recurrentLocations = useMemo(() => {
    const counts = new Map<
      string,
      { count: number; bairro: string; logradouro: string }
    >();

    generalFilteredData.forEach((item) => {
      const key = `${item.logradouro}||${item.bairro}`;
      const current = counts.get(key);
      if (current) {
        current.count += 1;
      } else {
        counts.set(key, {
          count: 1,
          bairro: item.bairro,
          logradouro: item.logradouro,
        });
      }
    });

    const palette = [
      "bg-red-200 text-red-700",
      "bg-red-200 text-red-700",
      "bg-red-200 text-red-700",
      "bg-orange-100 text-orange-600",
      "bg-orange-100 text-orange-600",
    ];

    return Array.from(counts.values())
      .sort((a, b) => b.count - a.count)
      .slice(0, 5)
      .map((item, index) => ({
        id: `${index + 1}º`,
        name: `${item.logradouro}, ${item.bairro}`,
        val: `${item.count} atividades`,
        color: palette[index] || "bg-gray-100 text-gray-600",
      }));
  }, [generalFilteredData]);

  const volumetryByRPA = useMemo(() => {
    const totals = new Map<string, number>();
    generalFilteredData.forEach((item) => {
      const rpa = getRpaForPoi(item);
      totals.set(rpa, (totals.get(rpa) || 0) + item.volume);
    });

    return RPA_OPTIONS.map((rpa) => ({
      name: rpa,
      val: `${Math.round(totals.get(rpa) || 0)}m³`,
      color:
        (totals.get(rpa) || 0) > 0
          ? "bg-red-200 text-red-700"
          : "bg-gray-100 text-gray-500",
    }));
  }, [generalFilteredData]);

  const chartRange = useMemo(() => {
    const dateRange = buildDateRange(filters.dateStart, filters.dateEnd);
    if (dateRange) return dateRange;
    if (generalFilteredData.length === 0) {
      const today = new Date();
      const pastYear = new Date();
      pastYear.setFullYear(today.getFullYear() - 1);
      return { start: pastYear, end: today };
    }
    const dates = generalFilteredData.map((item) => new Date(item.timestamp));
    const minDate = new Date(Math.min(...dates.map((d) => d.getTime())));
    const maxDate = new Date(Math.max(...dates.map((d) => d.getTime())));
    return { start: minDate, end: maxDate };
  }, [filters.dateEnd, filters.dateStart, generalFilteredData]);

  const chartSeries = useMemo(
    () => buildChartSeries(generalFilteredData, chartRange.start, chartRange.end),
    [chartRange, generalFilteredData],
  );

  const handleOpenOccurrence = (poi: PoiData) => {
    setSelectedOccurrence(poi);
    setIsOccurrenceModalOpen(true);
  };

  const modalData = selectedOccurrence
    ? {
        id: selectedOccurrence.id,
        logradouro: selectedOccurrence.logradouro,
        bairro: selectedOccurrence.bairro,
        rpa: getRpaForPoi(selectedOccurrence),
        timestamp: selectedOccurrence.timestamp,
        tipo: selectedOccurrence.wasteType,
        volume_m3: selectedOccurrence.volume,
        infratores: selectedOccurrence.hasOffender
          ? "Identificado"
          : "Não Identificado",
        status: selectedOccurrence.status,
        latitude: selectedOccurrence.latitude,
        longitude: selectedOccurrence.longitude,
        hasOffender: selectedOccurrence.hasOffender,
        image_url: selectedOccurrence.photoUrl || undefined,
        validityComment: selectedOccurrence.validityComment,
      }
    : null;

  const handleClassify = async (validityComment?: string) => {
    if (!classifyTarget) return;
    setIsClassifying(true);
    setClassifyError(null);
    try {
      await classifyDetection(
        classifyTarget.detection.id,
        classifyTarget.action,
        validityComment,
      );
      const newStatus = classifyTarget.action;
      // Se virou algo diferente de Confirmado, remove do dashboard (que só mostra Confirmado).
      setDetections((prev) =>
        newStatus === "Confirmado"
          ? prev.map((d) =>
              d.id === classifyTarget.detection.id
                ? { ...d, status: newStatus, validityComment }
                : d,
            )
          : prev.filter((d) => d.id !== classifyTarget.detection.id),
      );
      if (selectedOccurrence?.id === classifyTarget.detection.id) {
        if (newStatus === "Confirmado") {
          setSelectedOccurrence((prev) =>
            prev ? { ...prev, status: newStatus, validityComment } : null,
          );
        } else {
          setSelectedOccurrence(null);
        }
      }
      setClassifyTarget(null);
    } catch (e: any) {
      const detail =
        e?.response?.data?.detail ||
        (typeof e?.message === "string" ? e.message : null) ||
        "Falha ao atualizar ocorrência. Tente novamente.";
      setClassifyError(detail);
    } finally {
      setIsClassifying(false);
    }
  };

  const openClassifyFromModal = (action: ClassifyStatus) => {
    if (!selectedOccurrence) return;
    setIsOccurrenceModalOpen(false);
    setClassifyError(null);
    setClassifyTarget({ detection: selectedOccurrence, action });
  };

  const handleOccurrencePhotoUpdated = (imageUrl: string) => {
    const currentId = selectedOccurrence?.id;
    if (!currentId) return;
    setSelectedOccurrence((prev) => (prev ? { ...prev, photoUrl: imageUrl } : prev));
    setDetections((prev) =>
      prev.map((item) =>
        item.id === currentId ? { ...item, photoUrl: imageUrl } : item,
      ),
    );
  };

  return (
    // --- Main Layout Container ---
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      {/* --- Sidebar Navigation --- */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <main className="flex-1 ml-20 p-4 md:p-8 h-full overflow-y-auto">
        {/* --- Login Notification Banner --- */}
        <LoginNotificationBanner />

        {/* --- Page Header --- */}
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-6">Dashboard</h1>

        {/* --- Tab Navigation Section --- */}
        <div className="flex flex-wrap items-center gap-1 bg-white p-1 rounded-xl w-fit mb-8 border border-gray-200 shadow-sm">
          <button
            onClick={() => setActiveTab("ocorrencias")}
            className={`px-6 py-2 rounded-lg text-sm whitespace-nowrap transition-colors ${
              activeTab === "ocorrencias"
                ? "bg-[#e9fbc0] text-[#1a1a1a] font-semibold"
                : "text-gray-500 hover:bg-gray-50 font-medium"
            }`}
          >
            Dashboard de ocorrencias
          </button>
          <button
            onClick={() => setActiveTab("infratores")}
            className={`px-6 py-2 rounded-lg text-sm whitespace-nowrap transition-colors ${
              activeTab === "infratores"
                ? "bg-[#e9fbc0] text-[#1a1a1a] font-semibold"
                : "text-gray-500 hover:bg-gray-50 font-medium"
            }`}
          >
            Dashboard de Infratores
          </button>
          <button
            onClick={() => setActiveTab("exportar")}
            className={`px-6 py-2 rounded-lg text-sm whitespace-nowrap transition-colors ${
              activeTab === "exportar"
                ? "bg-[#e9fbc0] text-[#1a1a1a] font-semibold"
                : "text-gray-500 hover:bg-gray-50 font-medium"
            }`}
          >
            Exportar Imagens
          </button>
        </div>

        {/* --- Live Monitoring Section (ocorrencias only) --- */}
        {activeTab === "ocorrencias" && (
        <div className="mb-6 bg-white border border-gray-200 rounded-2xl shadow-sm p-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-bold text-gray-800">
              Monitoramento em Tempo Real
            </h2>
            <p className="text-xs text-gray-500">
              Ative o modo ao vivo para monitorar ocorrências recentes.
            </p>
          </div>
          <button
            onClick={handleLiveMode}
            className="h-11 px-5 rounded-full bg-red-600 hover:bg-red-700 text-white font-semibold flex items-center gap-2 shadow-sm"
          >
            <Disc size={16} className="text-white" />
            Ao Vivo
          </button>
        </div>
        )}

        {/* --- Filter Controls Section (hidden for the export tab) --- */}
        {activeTab !== "exportar" && (
        <div className="relative z-[2000]">
          <div className="flex items-start gap-4 mb-8">
            <div className="flex-1">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                <div className="relative">
                  <FilterPopover
                    label="Período"
                    active={activePopover === "period"}
                    hasValue={
                      !!(
                        filters.dateStart ||
                        filters.dateEnd ||
                        filters.startTime ||
                        filters.endTime
                      )
                    }
                    onClear={() =>
                      setFilters((p) => ({
                        ...p,
                        dateStart: "",
                        dateEnd: "",
                        startTime: "",
                        endTime: "",
                      }))
                    }
                    onClick={() =>
                      setActivePopover((p) => (p === "period" ? null : "period"))
                    }
                    onClose={() => setActivePopover(null)}
                  >
                    <div className="flex flex-wrap gap-2 mb-3">
                      {[
                        { label: "Últimos 7 dias", days: 7 },
                        { label: "Últimos 30 dias", days: 30 },
                        { label: "Último ano", days: 365 },
                      ].map((preset) => (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => applyDatePreset(preset.days)}
                          className="px-3 py-1.5 rounded-full border border-gray-200 text-xs font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                    <div className="flex flex-col gap-3">
                      <div className="flex gap-2">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            De
                          </label>
                          <input
                            type="date"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.dateStart}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, dateStart: e.target.value }))
                            }
                          />
                        </div>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Até
                          </label>
                          <input
                            type="date"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.dateEnd}
                            onChange={(e) =>
                              setFilters((p) => ({ ...p, dateEnd: e.target.value }))
                            }
                          />
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            De
                          </label>
                          <input
                            type="time"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.startTime}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                startTime: e.target.value,
                              }))
                            }
                          />
                        </div>
                        <div className="flex-1">
                          <label className="text-xs text-gray-500 font-bold mb-1 block">
                            Até
                          </label>
                          <input
                            type="time"
                            className="w-full border border-gray-300 rounded p-2 text-sm"
                            value={filters.endTime}
                            onChange={(e) =>
                              setFilters((p) => ({
                                ...p,
                                endTime: e.target.value,
                              }))
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </FilterPopover>
                </div>
                <FilterMultiSelect
                  label="Status"
                  value={filters.status}
                  options={statusOptions}
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
                  options={bairrosOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, bairro: v }))}
                />
                <FilterMultiSelect
                  label="RPA"
                  value={filters.rpa}
                  options={rpaOptions}
                  onChange={(v) => setFilters((p) => ({ ...p, rpa: v }))}
                />
                {showAllFilters && (
                  <>
                    <div className="animate-in slide-in-from-top-2 duration-300">
                      <FilterMultiSelect
                        label="Tipo de Resíduo"
                        value={filters.tipoResiduo}
                        options={tipoResiduoOptions}
                        onChange={(v) =>
                          setFilters((p) => ({ ...p, tipoResiduo: v as WasteType[] }))
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
                                setFilters((p) => ({ ...p, volMin: e.target.value }))
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
                                setFilters((p) => ({ ...p, volMax: e.target.value }))
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
                        options={offenderOptions}
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
              <div className="flex flex-col gap-3">
                <button
                  onClick={() => setShowAllFilters(!showAllFilters)}
                  className={`w-14 h-[50px] bg-white border border-gray-200 rounded-xl flex items-center justify-center hover:bg-gray-50 text-gray-600 transition-colors ${
                    showAllFilters ? "bg-gray-100 ring-2 ring-gray-200" : ""
                  }`}
                >
                  <FilterIcon size={22} />
                </button>
              </div>
            </div>
          </div>
        </div>
        )}

        {/* --- Image Export Tab Content --- */}
        {activeTab === "exportar" && <ImageExportTab />}

        {/* --- Infratores Tab Content --- */}
        {activeTab === "infratores" && (
          <OffenderDashboardTab filters={filters} />
        )}

        {/* --- Ocorrencias Tab Content --- */}
        {activeTab === "ocorrencias" && (<>
        {/* --- Upper Dashboard Grid: Map & Statistics --- */}
        <div className="grid grid-cols-12 gap-6 mb-8 lg:h-[500px] h-auto">
          {/* Map Component Container */}
          <div
            className={`col-span-12 lg:col-span-7 transition-all ${
              mapExpanded
                ? "fixed inset-0 z-50 w-full h-full"
                : "relative h-[400px] lg:h-full"
            }`}
          >
            <MapWidget
              isExpanded={mapExpanded}
              onToggleExpand={() => setMapExpanded(!mapExpanded)}
              points={mapFilteredData}
              onMarkerClick={handleOpenOccurrence}
            />
          </div>

          {/* Statistics & Charts Container */}
          <div className="col-span-12 lg:col-span-5 flex flex-col gap-6 h-full">
            {/* KPI Cards Row */}
            <div className="flex flex-col sm:flex-row gap-6 h-auto sm:h-32">
              {/* Total Occurrences Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Total de ocorrências no período
                  </span>
                  <Tooltip content="Exibe o número total de descartes irregulares no período selecionado.">
                    <Info size={14} className="text-gray-400 cursor-pointer" />
                  </Tooltip>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-orange-100 flex items-center justify-center text-orange-500">
                    <AlertTriangle size={24} />
                  </div>
                  <span className="text-4xl font-bold text-[#1a1a1a]">
                    {totalOccurrences}
                  </span>
                </div>
              </div>

              {/* Volume Metric Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Volume de resíduos no período
                  </span>
                  <Tooltip content="Soma do volume estimado (em m³) de todos os resíduos identificados no período selecionado.">
                    <Info size={14} className="text-gray-400 cursor-pointer" />
                  </Tooltip>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-[#ecfccb] flex items-center justify-center text-[#65a30d]">
                    <Trash2 size={24} />
                  </div>
                  <div className="flex items-baseline">
                    <span className="text-4xl font-bold text-[#1a1a1a]">
                      {Math.round(totalVolume)}
                    </span>
                    <span className="text-sm text-gray-500 font-medium ml-1">
                      m³
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Monthly Occurrences Chart */}
            <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 min-h-[300px]">
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-gray-800 text-sm">
                  Ocorrências por período
                </h3>
                <Tooltip content="Distribuição de ocorrências conforme o período selecionado.">
                  <Info size={16} className="text-gray-400 cursor-pointer" />
                </Tooltip>
              </div>
              <OccurrencesChart series={chartSeries} />
            </div>
          </div>
        </div>

      {/* --- Lower Dashboard Grid: Data Lists --- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-6">
          {/* List 1: Recurrent Locations */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="font-bold text-gray-800 text-sm">
                Locais reincidentes
              </h3>
              <Tooltip content="Lista dos endereços com maior frequência de detecções, ordenados do maior para o menor.">
                <Info size={16} className="text-gray-400 cursor-pointer" />
              </Tooltip>
            </div>
            <div className="p-2 overflow-x-auto">
              {recurrentLocations.length === 0 ? (
                <div className="px-6 py-10 text-center text-gray-500 text-sm">
                  Nenhuma ocorrência encontrada.
                </div>
              ) : (
                recurrentLocations.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between py-6 px-5 hover:bg-gray-50 rounded-lg text-sm min-w-[300px]"
                  >
                    <div className="flex items-center gap-3 text-gray-700 font-medium truncate flex-1 min-w-0">
                      <span className="text-gray-400 w-6">{item.id}</span>
                      <Tooltip text={item.name}>
                        <span className="truncate flex-1 min-w-0">{item.name}</span>
                      </Tooltip>
                    </div>
                    <span
                      className={`px-3 py-1 rounded-md text-xs font-bold ${item.color}`}
                    >
                      {item.val}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* List 2: Volumetry per RPA */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="font-bold text-gray-800 text-sm">
                Média de volumetria por RPA no período
              </h3>
              <Tooltip content="Volume médio de lixo descartado por dia, segmentado por Região Político-Administrativa.">
                <Info size={16} className="text-gray-400 cursor-pointer" />
              </Tooltip>
            </div>
            <div className="p-2 overflow-x-auto">
              {volumetryByRPA.map((item, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg text-sm min-w-[200px]"
                >
                  <span className="text-gray-700 font-medium">{item.name}</span>
                  <span
                    className={`px-3 py-1 rounded-md text-xs font-bold ${item.color}`}
                  >
                    {item.val}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
        </>)}
      </main>
      {isOccurrenceModalOpen && modalData && (
        <OccurrenceModal
          isOpen={isOccurrenceModalOpen}
          onClose={() => setIsOccurrenceModalOpen(false)}
          data={modalData}
          onClassify={openClassifyFromModal}
          onPhotoUpdated={handleOccurrencePhotoUpdated}
        />
      )}
      {classifyTarget && (
        <ClassifyConfirmationModal
          isOpen={!!classifyTarget}
          action={classifyTarget.action}
          onClose={() => {
            setClassifyTarget(null);
            setClassifyError(null);
          }}
          onConfirm={handleClassify}
          isLoading={isClassifying}
          errorMessage={classifyError}
        />
      )}
    </div>
  );
};
