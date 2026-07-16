import React, { useState, useMemo, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  classifyDetection,
  getAllDetections,
  getDetectionById,
  getFilterOptions,
  searchDetections,
} from "../services/detectionService";
import type { ClassifyStatus, PoiData } from "../services/detectionService";
import { offenderTypeLabel, addDetectionOffender } from "../services/offenderService";
import type { OffenderType } from "../services/offenderService";
import { getCameras } from "../services/cameraService";
import type { Camera as CameraOption } from "../services/cameraService";
import { Sidebar } from "../components/Sidebar";
import { formatDateTimeBrazil } from "../utils/datetime";

type WasteType = "Entulho" | "Lixo domiciliar" | "Poda" | "Plástico";
import {
  Filter as FilterIcon,
  ChevronDown,
  Download,
  Eye,
  ChevronRight,
  ChevronLeft,
  CheckCircle,
  XCircle,
  HelpCircle,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
} from "lucide-react";
import { OccurrenceModal } from "../components/OccurrenceModal";
import { ClassifyConfirmationModal } from "../components/ClassifyConfirmationModal";
import { Tooltip } from "../components/Tooltip";

import {
  FilterPopover,
  FilterMultiSelect,
  FilterAutocomplete,
} from "../components/SharedFilters";

// --- DATA INTERFACE AND STATUS ---
interface Detection extends PoiData {
  rpa: string;
}

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
  camera: string[];
}

const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const STATUS_OPTIONS = ["Pendente", "Confirmado", "Rejeitado", "Indeterminado"] as const;
const DEFAULT_STATUS_FILTER: readonly string[] = [];
const RPA_OPTIONS = [
  "RPA 1",
  "RPA 2",
  "RPA 3",
  "RPA 4",
  "RPA 5",
  "RPA 6",
];

const getRpaForPoi = (poi: PoiData) => {
  const key = `${poi.bairro}-${poi.logradouro}`;
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % 6;
  return `RPA ${index + 1}`;
};

// --- COLUMN CONFIGURATION ---
const TABLE_COLUMNS = [
  { label: "ID", width: "w-24", sortKey: null },
  { label: "Logradouro", width: "w-64", sortKey: "logradouro" },
  { label: "Bairro", width: "w-48", sortKey: "bairro" },
  { label: "RPA", width: "w-24", sortKey: "rpa" },
  { label: "Data e Hora", width: "w-40", sortKey: "timestamp" },
  { label: "Tipo de resíduo", width: "w-48", sortKey: "waste_type" },
  { label: "Volumetria", width: "w-32", sortKey: "volume_m3" },
  { label: "Tipo de descarte", width: "w-56", sortKey: null },
  { label: "Status", width: "w-32", sortKey: "status" },
  { label: "Ação", width: "w-36", sortKey: null },
] as const;

// --- MAIN COMPONENT ---
export const Detections: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [detections, setDetections] = useState<Detection[]>([]);
  const [selectedItem, setSelectedItem] = useState<Detection | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [classifyTarget, setClassifyTarget] = useState<{
    detection: Detection;
    action: ClassifyStatus;
  } | null>(null);
  const [isClassifying, setIsClassifying] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);
  const [filters, setFilters] = useState<FilterState>({
    dateStart: "",
    dateEnd: "",
    startTime: "",
    endTime: "",
    status: [...DEFAULT_STATUS_FILTER],
    logradouro: "",
    bairro: "",
    rpa: [],
    tipoResiduo: [],
    volMin: "",
    volMax: "",
    infratores: [],
    camera: [],
  });
  const [activePopover, setActivePopover] = useState<"period" | "volumetry" | null>(null);
  const [sortBy, setSortBy] = useState<string>("timestamp");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [totalRecords, setTotalRecords] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isDownloadingCsv, setIsDownloadingCsv] = useState(false);

  // Opções de Bairro/Logradouro vindas do banco (domínio completo), não do
  // subconjunto paginado carregado na tela.
  const [bairroOptions, setBairroOptions] = useState<string[]>([]);
  const [logradouroOptions, setLogradouroOptions] = useState<string[]>([]);
  const [cameras, setCameras] = useState<CameraOption[]>([]);

  useEffect(() => {
    let isMounted = true;
    getFilterOptions()
      .then((opts) => {
        if (isMounted) {
          setBairroOptions(opts.bairros);
          setLogradouroOptions(opts.logradouros);
        }
      })
      .catch((e) => console.error("Failed to load filter options:", e));
    getCameras({ limit: 100 })
      .then((list) => {
        if (isMounted) setCameras(list.filter((c) => c.device_id));
      })
      .catch((e) => console.error("Failed to load cameras:", e));
    return () => {
      isMounted = false;
    };
  }, []);

  const rpaOptions = RPA_OPTIONS;
  const tipoResiduoOptions = WASTE_TYPE_OPTIONS;
  const offenderOptions = ["Identificado", "Não Identificado"];
  const statusOptions = useMemo(() => [...STATUS_OPTIONS], []);

  // O FilterMultiSelect trabalha com strings; a label da câmera vira id na query.
  const cameraLabelToId = useMemo(() => {
    const map = new Map<string, number>();
    cameras.forEach((c) => map.set(`${c.name} (${c.device_id})`, c.id));
    return map;
  }, [cameras]);
  const cameraOptions = useMemo(
    () => Array.from(cameraLabelToId.keys()),
    [cameraLabelToId],
  );

  const queryFilters = useMemo(() => {
    const query: NonNullable<Parameters<typeof searchDetections>[0]> = {};
    const volumeMin = Number.parseFloat(filters.volMin.replace(",", "."));
    const volumeMax = Number.parseFloat(filters.volMax.replace(",", "."));

    if (filters.rpa.length > 0) query.rpa = filters.rpa;
    if (filters.status.length > 0) query.status = filters.status;
    if (filters.logradouro.trim()) query.logradouro = filters.logradouro.trim();
    if (filters.bairro.trim()) query.bairro = filters.bairro.trim();
    if (filters.tipoResiduo.length > 0) query.waste_type = filters.tipoResiduo;

    if (Number.isFinite(volumeMin)) query.volume_min = volumeMin;
    if (Number.isFinite(volumeMax)) query.volume_max = volumeMax;

    if (filters.infratores.length === 1) {
      query.has_offender = filters.infratores[0] === "Identificado";
    }

    if (filters.camera.length === 1) {
      const cameraId = cameraLabelToId.get(filters.camera[0]);
      if (cameraId) query.camera_id = cameraId;
    }

    if (filters.dateStart) {
      const startTime = filters.startTime || "00:00";
      query.start_date = `${filters.dateStart}T${startTime}:00`;
    }
    if (filters.dateEnd) {
      const endTime = filters.endTime || "23:59";
      query.end_date = `${filters.dateEnd}T${endTime}:59`;
    }

    return query;
  }, [filters, cameraLabelToId]);

  const handleSort = (key: string | null) => {
    if (!key) return;
    if (sortBy === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder("asc");
    }
  };

  const loadDetectionsPage = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await searchDetections({
        ...queryFilters,
        skip: (currentPage - 1) * itemsPerPage,
        limit: itemsPerPage,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      const formattedDetections = response.items.map((poi) => ({
        ...poi,
        rpa: getRpaForPoi(poi),
      }));
      setDetections(formattedDetections);
      setTotalRecords(response.total);
    } catch (e) {
      console.error("Failed to load detections:", e);
      setDetections([]);
      setTotalRecords(0);
    } finally {
      setIsLoading(false);
    }
  }, [currentPage, itemsPerPage, queryFilters, sortBy, sortOrder]);

  useEffect(() => {
    loadDetectionsPage();
  }, [loadDetectionsPage]);

  // Apply query param filters from notification navigation
  useEffect(() => {
    const rpaParam = searchParams.get("rpa");
    const statusParam = searchParams.get("status");
    const startDate = searchParams.get("start_date");
    const detectionIdParam = searchParams.get("detection_id");

    if (!rpaParam && !statusParam && !startDate && !detectionIdParam) return;

    if (rpaParam || statusParam || startDate) {
      setFilters((prev) => ({
        ...prev,
        rpa: rpaParam ? [rpaParam] : prev.rpa,
        status: statusParam ? [statusParam] : prev.status,
        dateStart: startDate ? startDate.split("T")[0] : prev.dateStart,
        dateEnd: startDate ? startDate.split("T")[0] : prev.dateEnd,
      }));
    }

    if (!detectionIdParam) {
      // Clear query params after applying
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    const detectionId = searchParams.get("detection_id");
    if (!detectionId) return;
    const detectionIdValue: string = detectionId;

    let isMounted = true;

    async function loadDetectionById() {
      try {
        const detection = await getDetectionById(detectionIdValue);
        if (!isMounted) return;

        setSelectedItem({
          ...detection,
          rpa: getRpaForPoi(detection),
        });
        setIsModalOpen(true);
      } catch (e) {
        console.error("Failed to load detection by id:", e);
      } finally {
        if (isMounted) {
          setSearchParams({}, { replace: true });
        }
      }
    }

    loadDetectionById();
    return () => {
      isMounted = false;
    };
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    setCurrentPage(1);
  }, [filters, itemsPerPage, sortBy, sortOrder]);

  const handleOpenModal = (item: Detection) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleClassify = async (
    validityComment?: string,
    offenderTypes?: OffenderType[],
  ) => {
    if (!classifyTarget) return;
    const detectionId = classifyTarget.detection.id;
    setIsClassifying(true);
    setClassifyError(null);
    try {
      await classifyDetection(detectionId, classifyTarget.action, validityComment);
      // Tipo de descarte indicado na confirmação → rótulo manual (source=manual).
      if (offenderTypes && offenderTypes.length > 0) {
        await Promise.all(
          offenderTypes.map((offender_type) =>
            addDetectionOffender(detectionId, { offender_type }),
          ),
        );
      }
      setClassifyTarget(null);
      await loadDetectionsPage();
    } catch (e) {
      console.error("Erro ao classificar:", e);
      setClassifyError("Falha ao salvar a classificação. Tente novamente.");
    } finally {
      setIsClassifying(false);
    }
  };

  const openClassifyFromModal = (action: ClassifyStatus) => {
    if (!selectedItem) return;
    setIsModalOpen(false);
    setClassifyError(null);
    setClassifyTarget({ detection: selectedItem, action });
  };

  const openClassifyFromRow = (detection: Detection, action: ClassifyStatus) => {
    setClassifyError(null);
    setClassifyTarget({ detection, action });
  };

  const handleOccurrencePhotoUpdated = (imageUrl: string) => {
    const currentId = selectedItem?.id;
    if (!currentId) return;
    setSelectedItem((prev) => (prev ? { ...prev, photoUrl: imageUrl } : prev));
    setDetections((prev) =>
      prev.map((item) =>
        item.id === currentId ? { ...item, photoUrl: imageUrl } : item,
      ),
    );
  };

  const handleDownloadCSV = async () => {
    setIsDownloadingCsv(true);
    try {
      const allDetections = await getAllDetections({
        ...queryFilters,
        pageSize: 100,
        maxRecords: 10000,
      });

      const formattedDetections = allDetections.map((poi) => ({
        ...poi,
        rpa: getRpaForPoi(poi),
      }));

      const headers = [
        "Data",
        "Local",
        "Câmera",
        "Tipo",
        "Volume",
        "Status",
        "Tipo de descarte",
      ];
      const rows = formattedDetections.map((item) => {
        const date = formatDateTimeBrazil(item.timestamp);
        const local = `${item.logradouro} - ${item.bairro}`;
        const camera = item.cameraName || "";
        const tipo = item.wasteType;
        const volume = `${item.volume} m³`;
        const status = item.status;
        const infrator =
          item.offenderTypes && item.offenderTypes.length > 0
            ? item.offenderTypes.map(offenderTypeLabel).join(" / ")
            : "Não identificado";
        return [date, local, camera, tipo, volume, status, infrator];
      });

      const escapeCell = (value: string) =>
        `"${value.replace(/"/g, '""')}"`;

      const csvContent = [
        headers.map(escapeCell).join(","),
        ...rows.map((row) => row.map(escapeCell).join(",")),
      ].join("\n");

      const blob = new Blob([`\uFEFF${csvContent}`], {
        type: "text/csv;charset=utf-8;",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `detecoes_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Erro ao exportar CSV:", e);
    } finally {
      setIsDownloadingCsv(false);
    }
  };

  const getStatusStyle = (status: string) => {
    switch (status) {
      case "Pendente":
        return "bg-orange-100 text-orange-500";
      case "Confirmado":
        return "bg-green-100 text-green-500";
      case "Rejeitado":
        return "bg-red-100 text-red-500";
      case "Indeterminado":
        return "bg-yellow-100 text-yellow-600";
      default:
        return "bg-gray-100 text-gray-500";
    }
  };

  const totalPages = Math.ceil(totalRecords / itemsPerPage);
  const visibleData = detections;
  const fromRecord = totalRecords === 0 ? 0 : (currentPage - 1) * itemsPerPage + 1;
  const toRecord =
    totalRecords === 0
      ? 0
      : Math.min(totalRecords, (currentPage - 1) * itemsPerPage + visibleData.length);

  useEffect(() => {
    if (totalPages > 0 && currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const getPageNumbers = () => {
    const pages = [] as number[];
    const maxVisible = 5;
    if (totalPages <= maxVisible) {
      for (let i = 1; i <= totalPages; i += 1) pages.push(i);
    } else {
      let start = Math.max(1, currentPage - 2);
      let end = Math.min(totalPages, start + maxVisible - 1);
      if (end - start < maxVisible - 1) {
        start = Math.max(1, end - maxVisible + 1);
      }
      for (let i = start; i <= end; i += 1) pages.push(i);
    }
    return pages;
  };

  const modalData = selectedItem
    ? {
        id: selectedItem.id,
        logradouro: selectedItem.logradouro,
        bairro: selectedItem.bairro,
        rpa: selectedItem.rpa,
        timestamp: selectedItem.timestamp,
        tipo: selectedItem.wasteType,
        volume_m3: selectedItem.volume,
        infratores: selectedItem.hasOffender ? "Identificado" : "Não Identificado",
        status: selectedItem.status,
        latitude: selectedItem.latitude,
        longitude: selectedItem.longitude,
        hasOffender: selectedItem.hasOffender,
        offenderTypes: selectedItem.offenderTypes ?? [],
        cameraName: selectedItem.cameraName,
        image_url: selectedItem.photoUrl || undefined,
        validityComment: selectedItem.validityComment,
      }
    : null;

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">Detecções de câmeras</h1>
        </div>
        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-4">
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
                            setFilters((p) => ({
                              ...p,
                              dateStart: e.target.value,
                            }))
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
                          Hora início
                        </label>
                        <input
                          type="time"
                          className="w-full border border-gray-300 rounded p-2 text-sm"
                          value={filters.startTime}
                          onChange={(e) =>
                            setFilters((p) => ({ ...p, startTime: e.target.value }))
                          }
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-xs text-gray-500 font-bold mb-1 block">
                          Hora fim
                        </label>
                        <input
                          type="time"
                          className="w-full border border-gray-300 rounded p-2 text-sm"
                          value={filters.endTime}
                          onChange={(e) =>
                            setFilters((p) => ({ ...p, endTime: e.target.value }))
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
                options={bairroOptions}
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
                        setActivePopover((p) => (p === "volumetry" ? null : "volumetry"))
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
                      onChange={(v) => setFilters((p) => ({ ...p, infratores: v }))}
                    />
                  </div>
                  <div className="animate-in slide-in-from-top-2 duration-300">
                    <FilterMultiSelect
                      label="Câmera"
                      value={filters.camera}
                      options={cameraOptions}
                      onChange={(v) =>
                        // Backend filtra por 1 camera_id; manter só a última escolha.
                        setFilters((p) => ({ ...p, camera: v.slice(-1) }))
                      }
                    />
                  </div>
                  <div className="hidden md:block"></div>
                </>
              )}
            </div>
          </div>
          <div className="flex gap-4 pt-[25px]">
            <button
              onClick={() => setShowAllFilters(!showAllFilters)}
              className={`w-14 h-[50px] bg-white border border-gray-200 rounded-xl flex items-center justify-center hover:bg-gray-50 text-gray-600 transition-colors ${
                showAllFilters ? "bg-gray-100 ring-2 ring-gray-200" : ""
              }`}
            >
              <FilterIcon size={22} />
            </button>
            <button
              onClick={handleDownloadCSV}
              disabled={isDownloadingCsv}
              className={`h-[50px] px-6 py-2 rounded-xl transition-colors flex items-center justify-center text-black shadow-sm ${
                isDownloadingCsv
                  ? "bg-[#d8f28e] cursor-not-allowed"
                  : "bg-[#ccff33] hover:bg-[#b8e62e]"
              }`}
            >
              <Download size={24} />
            </button>
          </div>
        </div>
        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100">
                  {TABLE_COLUMNS.map((c, i) => (
                    <th
                      key={i}
                      onClick={() => handleSort(c.sortKey)}
                      className={`px-6 py-5 text-sm font-bold text-[#1a1a1a] whitespace-nowrap ${c.width} ${
                        c.sortKey ? "cursor-pointer select-none hover:bg-gray-50 transition-colors" : ""
                      }`}
                    >
                      <span className="inline-flex items-center gap-1">
                        {c.label}
                        {c.sortKey && (
                          sortBy === c.sortKey
                            ? sortOrder === "asc"
                              ? <ArrowUp size={14} className="text-[#1a1a1a]" />
                              : <ArrowDown size={14} className="text-[#1a1a1a]" />
                            : <ArrowUpDown size={14} className="text-gray-300" />
                        )}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td
                      colSpan={10}
                      className="px-6 py-12 text-center text-gray-500 italic"
                    >
                      Carregando ocorrências...
                    </td>
                  </tr>
                ) : visibleData.length > 0 ? (
                  visibleData.map((row: Detection, i: number) => (
                    <tr
                      key={row.id}
                      className={`transition-colors border-b border-gray-50 last:border-0 group ${
                        i % 2 === 0 ? "bg-gray-50" : "bg-white"
                      } hover:bg-gray-100`}
                    >
                      <td className="px-6 py-4 text-sm text-gray-500 font-medium">
                        {row.id}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.logradouro}>
                          <span className="truncate max-w-[260px] block">
                            {row.logradouro}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.bairro}>
                          <span className="truncate max-w-[200px] block">
                            {row.bairro}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        {row.rpa}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a] whitespace-nowrap">
                        {formatDateTimeBrazil(row.timestamp)}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.wasteType}>
                          <span className="truncate max-w-[200px] block">
                            {row.wasteType}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a] font-medium">
                        {`${row.volume} m³`}
                      </td>
                      <td className="px-6 py-4 text-sm font-medium">
                        {row.offenderTypes && row.offenderTypes.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {row.offenderTypes.map((type) => (
                              <span
                                key={type}
                                className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 text-xs font-bold whitespace-nowrap"
                              >
                                {offenderTypeLabel(type)}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <Tooltip text={row.status}>
                          <span
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold ${getStatusStyle(
                              row.status,
                            )}`}
                          >
                            {row.status}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1">
                          <Tooltip text="Visualizar ocorrência" className="w-fit" spacing="mb-2">
                            <button
                              onClick={() => handleOpenModal(row)}
                              className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#1a1a1a] hover:border-[#1a1a1a] transition-all bg-white"
                            >
                              <Eye size={16} />
                            </button>
                          </Tooltip>
                          {row.status !== "Confirmado" && (
                            <Tooltip text="Confirmar ocorrência" className="w-fit" spacing="mb-2">
                              <button
                                onClick={() => openClassifyFromRow(row, "Confirmado")}
                                className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-green-500 hover:border-green-500 transition-all bg-white"
                              >
                                <CheckCircle size={16} />
                              </button>
                            </Tooltip>
                          )}
                          {row.status !== "Rejeitado" && (
                            <Tooltip text="Rejeitar (falso positivo)" className="w-fit" spacing="mb-2">
                              <button
                                onClick={() => openClassifyFromRow(row, "Rejeitado")}
                                className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-red-500 hover:border-red-500 transition-all bg-white"
                              >
                                <XCircle size={16} />
                              </button>
                            </Tooltip>
                          )}
                          {row.status !== "Indeterminado" && (
                            <Tooltip text="Marcar como indeterminado" className="w-fit" spacing="mb-2">
                              <button
                                onClick={() => openClassifyFromRow(row, "Indeterminado")}
                                className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-yellow-500 hover:border-yellow-500 transition-all bg-white"
                              >
                                <HelpCircle size={16} />
                              </button>
                            </Tooltip>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={10}
                      className="px-6 py-12 text-center text-gray-500 italic"
                    >
                      Nenhuma ocorrência encontrada.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-white">
            <span className="text-sm text-gray-500">
              Mostrando {fromRecord} - {toRecord} de {totalRecords}
            </span>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>
              <div className="relative">
                <div
                  onClick={() => setShowItemsMenu(!showItemsMenu)}
                  className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-300 select-none min-w-[60px] justify-between"
                >
                  {itemsPerPage}
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${
                      showItemsMenu ? "rotate-180" : ""
                    }`}
                  />
                </div>
                {showItemsMenu && (
                  <div className="absolute bottom-full left-0 mb-1 w-full bg-white border border-gray-200 rounded-lg shadow-xl z-30 animate-in fade-in zoom-in-95 ">
                    {[10, 20, 30].map((n) => (
                      <div
                        key={n}
                        onClick={() => {
                          setItemsPerPage(n);
                          setShowItemsMenu(false);
                        }}
                        className={`px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 text-center ${
                          itemsPerPage === n
                            ? "font-bold bg-gray-50 text-[#1a1a1a]"
                            : "text-gray-600"
                        }`}
                      >
                        {n}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === 1
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronLeft size={16} />
                </button>
                {getPageNumbers().map((p) => (
                  <button
                    key={p}
                    onClick={() => setCurrentPage(p)}
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold transition-all ${
                      currentPage === p
                        ? "bg-[#ccff33] text-black shadow-sm"
                        : "text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages || totalPages === 0}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === totalPages || totalPages === 0
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
      {isModalOpen && modalData && (
        <OccurrenceModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
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
