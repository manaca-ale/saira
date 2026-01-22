import React, { useState } from "react";
import { Sidebar } from "../components/Sidebar";
import { MapWidget, OccurrencesChart } from "../components/DashboardCharts";
import { Filter, Trash2, AlertTriangle, ChevronDown } from "lucide-react";

export const Dashboard: React.FC = () => {
  // --- State Management ---
  const [mapExpanded, setMapExpanded] = useState(false);

  return (
    // --- Main Layout Container ---
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      {/* --- Sidebar Navigation --- */}
      <Sidebar />

      {/* --- Main Content Area --- */}
      <main className="flex-1 ml-20 p-4 md:p-8 h-full overflow-y-auto">
        {/* --- Page Header --- */}
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-6">Dashboard</h1>

        {/* --- Tab Navigation Section --- */}
        <div className="flex flex-wrap items-center gap-1 bg-white p-1 rounded-xl w-fit mb-8 border border-gray-200 shadow-sm">
          <button className="px-6 py-2 bg-[#e9fbc0] text-[#1a1a1a] font-semibold rounded-lg text-sm whitespace-nowrap">
            Dashboard de ocorrências
          </button>
          <button className="px-6 py-2 text-gray-500 hover:bg-gray-50 font-medium rounded-lg text-sm whitespace-nowrap">
            Dashboard de Infratores
          </button>
        </div>

        {/* --- Filter Controls Section --- */}
        <div className="flex flex-wrap gap-4 mb-8">
          {["Periodo", "Status", "Logradouro", "Bairro", "RPA"].map(
            (label, idx) => (
              <div
                key={idx}
                className="flex-1 min-w-[140px] bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors cursor-pointer group"
              >
                <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                  {label}
                </span>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-700 font-medium">
                    {label.includes("Pesquisar") ? "Pesquisar" : "Selecionar"}
                  </span>
                  <ChevronDown
                    size={14}
                    className="text-gray-400 group-hover:text-gray-600"
                  />
                </div>
              </div>
            ),
          )}
          <button className="w-14 bg-white border border-gray-200 rounded-lg flex items-center justify-center hover:bg-gray-50 shadow-sm text-gray-600">
            <Filter size={20} />
          </button>
        </div>

        {/* --- Upper Dashboard Grid: Map & Statistics --- */}
        <div className="grid grid-cols-12 gap-6 mb-8 lg:h-[500px] h-auto">
          {/* Map Component Container */}
          <div
            className={`col-span-12 lg:col-span-7 transition-all ${mapExpanded ? "fixed inset-0 z-50 w-full h-full" : "relative h-[400px] lg:h-full"}`}
          >
            <MapWidget
              isExpanded={mapExpanded}
              onToggleExpand={() => setMapExpanded(!mapExpanded)}
            />
          </div>

          {/* Statistics & Charts Container */}
          <div className="col-span-12 lg:col-span-5 flex flex-col gap-6 h-full">
            {/* KPI Cards Row */}
            <div className="flex flex-col sm:flex-row gap-6 h-auto sm:h-32">
              {/* Total Occurrences Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <span className="text-gray-500 text-xs font-medium uppercase">
                  Total de ocorrências
                </span>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-orange-100 flex items-center justify-center text-orange-500">
                    <AlertTriangle size={24} />
                  </div>
                  <span className="text-4xl font-bold text-[#1a1a1a]">450</span>
                </div>
              </div>

              {/* Volume Metric Card */}
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <span className="text-gray-500 text-xs font-medium uppercase">
                  Volume diário de resíduos
                </span>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-[#ecfccb] flex items-center justify-center text-[#65a30d]">
                    <Trash2 size={24} />
                  </div>
                  <div className="flex items-baseline">
                    <span className="text-4xl font-bold text-[#1a1a1a]">
                      150
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
                  Ocorrências por mês
                </h3>
                <button className="text-gray-400 hover:text-gray-600">
                  <div className="w-4 h-4 border border-gray-300 rounded-full text-[10px] flex items-center justify-center">
                    ?
                  </div>
                </button>
              </div>
              <OccurrencesChart />
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
              <div className="w-4 h-4 border border-gray-300 rounded-full text-[10px] flex items-center justify-center text-gray-400">
                ?
              </div>
            </div>
            <div className="p-2 overflow-x-auto">
              {[
                {
                  id: "1º",
                  name: "Rua do Sossego, Boa Vista",
                  val: "350 atividades",
                  color: "bg-red-200 text-red-700",
                },
                {
                  id: "2º",
                  name: "Av. Norte Miguel Arraes de Alencar",
                  val: "250 atividades",
                  color: "bg-red-200 text-red-700",
                },
                {
                  id: "3º",
                  name: "Rua Imperial, São José",
                  val: "150 atividades",
                  color: "bg-red-200 text-red-700",
                },
                {
                  id: "4º",
                  name: "Rua da Aurora, Santo Amaro",
                  val: "100 atividades",
                  color: "bg-orange-100 text-orange-600",
                },
                {
                  id: "5º",
                  name: "Av. Recife, Estância",
                  val: "50 atividades",
                  color: "bg-orange-100 text-orange-600",
                },
              ].map((item, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg text-sm min-w-[300px]"
                >
                  <div className="flex items-center gap-3 text-gray-700 font-medium truncate">
                    <span className="text-gray-400 w-6">{item.id}</span>
                    <span className="truncate max-w-[200px]">{item.name}</span>
                  </div>
                  <span
                    className={`px-3 py-1 rounded-md text-xs font-bold ${item.color}`}
                  >
                    {item.val}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* List 2: Volumetry per RPA */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-5 border-b border-gray-100 flex justify-between items-center">
              <h3 className="font-bold text-gray-800 text-sm">
                Média diária de volumetria por RPA
              </h3>
              <div className="w-4 h-4 border border-gray-300 rounded-full text-[10px] flex items-center justify-center text-gray-400">
                ?
              </div>
            </div>
            <div className="p-2 overflow-x-auto">
              {[
                {
                  name: "RPA 1",
                  val: "350m³",
                  color: "bg-red-200 text-red-700",
                },
                {
                  name: "RPA 2",
                  val: "250m³",
                  color: "bg-red-200 text-red-700",
                },
                {
                  name: "RPA 3",
                  val: "150m³",
                  color: "bg-red-200 text-red-700",
                },
                {
                  name: "RPA 4",
                  val: "100m³",
                  color: "bg-orange-100 text-orange-600",
                },
                {
                  name: "RPA 5",
                  val: "50m³",
                  color: "bg-orange-100 text-orange-600",
                },
              ].map((item, i) => (
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
      </main>
    </div>
  );
};
