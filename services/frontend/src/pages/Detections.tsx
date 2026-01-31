import React, { useState, useMemo, useEffect, useCallback } from "react";
import { masterPois } from "../services/mockData";
import type { PoiData, WasteType } from "../services/mockData";
import { Sidebar } from "../components/Sidebar";
import {
  Filter as FilterIcon,
  ChevronDown,
  Download,
  Eye,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { OccurrenceModal } from "../components/OccurrenceModal";
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

const WASTE_TYPE_OPTIONS: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const STATUS_OPTIONS = ["Pendente", "Resolvido", "Em análise"] as const;
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
  { label: "ID", width: "w-24" },
  { label: "Logradouro", width: "w-64" },
  { label: "Bairro", width: "w-48" },
  { label: "RPA", width: "w-24" },
  { label: "Data e Hora", width: "w-40" },
  { label: "Tipo de resíduo", width: "w-48" },
  { label: "Volumetria", width: "w-32" },
  { label: "Infratores", width: "w-48" },
  { label: "Status", width: "w-32" },
  { label: "Ação", width: "w-20" },
];

// --- MAIN COMPONENT ---
export const Detections: React.FC = () => {
  const [detections, setDetections] = useState<Detection[]>([]);
  const [selectedItem, setSelectedItem] = useState<Detection | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [showAllFilters, setShowAllFilters] = useState(false);
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);
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
  const [activePopover, setActivePopover] = useState<"period" | "volumetry" | null>(null);

  const matchesFilters = useCallback((item: Detection, exclude?: keyof FilterState) => {
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
    if (exclude !== "rpa" && filters.rpa.length > 0 && !filters.rpa.includes(item.rpa))
      return false;
    if (
      exclude !== "tipoResiduo" &&
      filters.tipoResiduo.length > 0 &&
      !filters.tipoResiduo.includes(item.wasteType)
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
    if (filters.volMin && item.volume < parseFloat(filters.volMin.replace(",", ".")))
      return false;
    if (filters.volMax && item.volume > parseFloat(filters.volMax.replace(",", ".")))
      return false;
    if (filters.date) {
      const itemDate = new Date(item.timestamp);
      const itemIsoDate = `${itemDate.getFullYear()}-${String(itemDate.getMonth() + 1).padStart(2, "0")}-${String(itemDate.getDate()).padStart(2, "0")}`;
      const itemTime = `${String(itemDate.getHours()).padStart(2, "0")}:${String(itemDate.getMinutes()).padStart(2, "0")}`;
      if (itemIsoDate !== filters.date) return false;
      if (filters.startTime && itemTime < filters.startTime) return false;
      if (filters.endTime && itemTime > filters.endTime) return false;
    }
    return true;
  }, [filters]);

  const bairroOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "bairro"));
    return Array.from(new Set(filtered.map((item) => item.bairro))).sort();
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const logradouroOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "logradouro"),
    );
    return Array.from(new Set(filtered.map((item) => item.logradouro))).sort();
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const rpaOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "rpa"));
    const present = new Set(filtered.map((item) => item.rpa));
    return RPA_OPTIONS.filter((rpa) => present.has(rpa));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const tipoResiduoOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "tipoResiduo"),
    );
    const present = new Set(filtered.map((item) => item.wasteType));
    return WASTE_TYPE_OPTIONS.filter((type) => present.has(type));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const offenderOptions = useMemo(() => {
    const filtered = detections.filter((item) =>
      matchesFilters(item, "infratores"),
    );
    const options = [] as string[];
    if (filtered.some((item) => item.hasOffender)) options.push("Identificado");
    if (filtered.some((item) => !item.hasOffender))
      options.push("Não Identificado");
    return options;
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  const statusOptions = useMemo(() => {
    const filtered = detections.filter((item) => matchesFilters(item, "status"));
    const present = new Set(filtered.map((item) => item.status));
    return STATUS_OPTIONS.filter((status) => present.has(status));
  }, [
    detections,
    filters.bairro,
    filters.date,
    filters.endTime,
    filters.infratores,
    filters.logradouro,
    filters.rpa,
    filters.startTime,
    filters.status,
    filters.tipoResiduo,
    filters.volMax,
    filters.volMin,
  ]);

  useEffect(() => {
    const formattedDetections = masterPois.map((poi) => ({
      ...poi,
      rpa: getRpaForPoi(poi),
    }));
    setDetections(formattedDetections);
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [filters, itemsPerPage]);

  const handleOpenModal = (item: Detection) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleDownloadCSV = () => {
    const headers = ["Data", "Local", "Tipo", "Volume", "Status", "Infrator"];
    const rows = filteredData.map((item) => {
      const date = new Date(item.timestamp).toLocaleString("pt-BR");
      const local = `${item.logradouro} - ${item.bairro}`;
      const tipo = item.wasteType;
      const volume = `${item.volume} m³`;
      const status = item.status;
      const infrator = item.hasOffender ? "Identificado" : "Não identificado";
      return [date, local, tipo, volume, status, infrator];
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
  };

  const getStatusStyle = (status: string) => {
    switch (status) {
      case "Pendente":
        return "bg-red-100 text-red-500";
      case "Em análise":
        return "bg-orange-100 text-orange-500";
      case "Resolvido":
        return "bg-green-100 text-green-500";
      default:
        return "bg-gray-100 text-gray-500";
    }
  };

  const filteredData = useMemo(
    () => detections.filter((item: Detection) => matchesFilters(item)),
    [detections, filters],
  );

  const totalPages = Math.ceil(filteredData.length / itemsPerPage);
  const visibleData = filteredData.slice(
    (currentPage - 1) * itemsPerPage,
    (currentPage - 1) * itemsPerPage + itemsPerPage,
  );

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
                  hasValue={!!(filters.date || filters.startTime || filters.endTime)}
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
                            setFilters((p) => ({ ...p, startTime: e.target.value }))
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
                  <div className="hidden md:block"></div>
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
              className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
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
                      className={`px-6 py-5 text-sm font-bold text-[#1a1a1a] whitespace-nowrap ${c.width}`}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleData.length > 0 ? (
                  visibleData.map((row: Detection, i: number) => (
                    <tr
                      key={i}
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
                        {new Date(row.timestamp).toLocaleString("pt-BR")}
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
                        {row.hasOffender ? "Sim" : "Não"}
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
                        <Tooltip text="Visualizar ocorrência" className="w-fit" spacing="mb-2">
                          <button
                            onClick={() => handleOpenModal(row)}
                            className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#1a1a1a] hover:border-[#1a1a1a] transition-all bg-white"
                          >
                            <Eye size={16} />
                          </button>
                        </Tooltip>
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
              Mostrando {visibleData.length > 0 ? (currentPage - 1) * itemsPerPage + 1 : 0} -
              {(currentPage - 1) * itemsPerPage + visibleData.length} de {filteredData.length}
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
        />
      )}
    </div>
  );
};
