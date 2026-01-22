import React, { useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  Filter,
  ChevronDown,
  Download,
  Eye,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { OccurrenceModal } from "../components/OccurrenceModal";

// --- Mock Data Configuration ---
const MOCK_DATA = Array(8)
  .fill(null)
  .map((_, i) => ({
    id: "000000",
    logradouro: "Rua da Aurora",
    bairro: "Santo Amaro",
    rpa: "RPA 1",
    data: "12/06/2025, 15:35",
    tipo: [
      "Entulho",
      "Lixo domiciliar",
      "Lixo domiciliar",
      "Lixo domiciliar",
      "Entulho",
      "Entulho",
      "Lixo domiciliar",
      "Resíduos de poda",
    ][i],
    volumetria: "~1,2 m³",
    infratores: [
      "Não Identificado",
      "-",
      "Não Identificado",
      "Não Identificado",
      "-",
      "-",
      "Não Identificado",
      "Não Identificado",
    ][i],
    status: [
      "Pendente",
      "Pendente",
      "Pendente",
      "Em análise",
      "Em análise",
      "Em análise",
      "Resolvido",
      "Resolvido",
    ][i],
  }));

export const Detections: React.FC = () => {
  // --- State Management ---
  const [selectedItem, setSelectedItem] = useState<any | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // --- Event Handlers ---
  const handleOpenModal = (item: any) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  // --- Helper Functions ---
  const getStatusStyle = (status: string) => {
    switch (status) {
      case "Pendente":
        return "bg-red-100 text-red-500"; // Light red/pink
      case "Em análise":
        return "bg-orange-100 text-orange-500"; // Light orange
      case "Resolvido":
        return "bg-[#dcfce7] text-[#16a34a]"; // Light green
      default:
        return "bg-gray-100 text-gray-500";
    }
  };

  return (
    // --- Main Layout Container ---
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      {/* --- Sidebar Navigation --- */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto">
        {/* --- Page Header --- */}
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">
            Detecções de câmeras
          </h1>
        </div>

        {/* --- Filter Controls Section --- */}
        <div className="flex items-center gap-4 mb-8">
          {/* Dropdown Filters Group */}
          <div className="flex flex-1 gap-4">
            {["Período", "Status", "Logradouro", "Bairro", "RPA"].map(
              (label, idx) => (
                <div
                  key={idx}
                  className="flex-1 bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors cursor-pointer group min-w-[120px]"
                >
                  <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                    {label}
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-gray-700 font-medium">
                      {label.includes("Pesquisar") ||
                      label === "Logradouro" ||
                      label === "Bairro"
                        ? "Pesquisar"
                        : "Selecionar"}
                    </span>
                    {!(label === "Logradouro" || label === "Bairro") && (
                      <ChevronDown
                        size={14}
                        className="text-gray-400 group-hover:text-gray-600"
                      />
                    )}
                  </div>
                </div>
              ),
            )}
            <button className="w-12 bg-white border border-gray-200 rounded-lg flex items-center justify-center hover:bg-gray-50 text-gray-600">
              <Filter size={20} />
            </button>
          </div>

          {/* Action Buttons */}
          <button className="h-full px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black">
            <Download size={24} />
          </button>
        </div>

        {/* --- Data Table Section --- */}
        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              {/* Table Header */}
              <thead>
                <tr className="border-b border-gray-100">
                  {[
                    "ID",
                    "Logradouro",
                    "Bairro",
                    "RPA",
                    "Data e Hora",
                    "Tipo de resíduo",
                    "Volumetria",
                    "Infratores",
                    "Status",
                    "Ação",
                  ].map((head, i) => (
                    <th
                      key={i}
                      className="px-6 py-5 text-sm font-bold text-[#1a1a1a] whitespace-nowrap"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>

              {/* Table Body */}
              <tbody>
                {MOCK_DATA.map((row, index) => (
                  <tr
                    key={index}
                    className="hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-0 group"
                  >
                    <td className="px-6 py-4 text-sm text-gray-500 font-medium">
                      {row.id}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                      {row.logradouro}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                      {row.bairro}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                      {row.rpa}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a] whitespace-nowrap">
                      {row.data}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                      {row.tipo}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                      {row.volumetria}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {row.infratores}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold ${getStatusStyle(row.status)}`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <button
                        onClick={() => handleOpenModal(row)}
                        className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#1a1a1a] hover:border-[#1a1a1a] transition-all"
                      >
                        <Eye size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* --- Pagination Controls --- */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
            <span className="text-sm text-gray-500">
              Mostrando 10 de 100 linhas
            </span>

            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>
              <div className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer">
                10 <ChevronDown size={14} />
              </div>

              <div className="flex items-center gap-2 ml-4">
                <button className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-600">
                  <ChevronLeft size={16} />
                </button>
                <button className="w-6 h-6 flex items-center justify-center rounded-full bg-[#ccff33] text-black text-xs font-bold shadow-sm">
                  1
                </button>
                <button className="w-6 h-6 flex items-center justify-center text-gray-500 text-xs hover:bg-gray-100 rounded-full transition-colors">
                  2
                </button>
                <button className="w-6 h-6 flex items-center justify-center text-gray-500 text-xs hover:bg-gray-100 rounded-full transition-colors">
                  3
                </button>
                <button className="w-6 h-6 flex items-center justify-center text-gray-500 text-xs hover:bg-gray-100 rounded-full transition-colors">
                  4
                </button>
                <button className="w-6 h-6 flex items-center justify-center text-gray-500 text-xs hover:bg-gray-100 rounded-full transition-colors">
                  5
                </button>
                <button className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-600">
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* --- Modal Overlay --- */}
      {selectedItem && (
        <OccurrenceModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          data={selectedItem}
        />
      )}
    </div>
  );
};
