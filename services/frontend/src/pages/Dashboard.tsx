import React, { useState, useEffect } from "react";
import { Sidebar } from "../components/Sidebar";
import { MapWidget, OccurrencesChart } from "../components/DashboardCharts";
import { Filter, Trash2, AlertTriangle, ChevronDown, Info } from "lucide-react";
import api from "../services/api";

interface DashboardStats {
  total_occurrences: number;
  daily_volume_m3: number;
  pending_count: number;
  in_analysis_count: number;
  resolved_count: number;
}

interface RecurrentLocation {
  logradouro: string;
  bairro: string;
  rpa: string;
  count: number;
}

interface VolumeByRPA {
  rpa: string;
  avg_volume_m3: number;
  total_volume_m3: number;
  count: number;
}

export const Dashboard: React.FC = () => {
  const [mapExpanded, setMapExpanded] = useState(false);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recurrentLocations, setRecurrentLocations] = useState<RecurrentLocation[]>([]);
  const [volumeByRPA, setVolumeByRPA] = useState<VolumeByRPA[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        const [statsRes, locationsRes, volumeRes] = await Promise.all([
          api.get("/dashboard/stats"),
          api.get("/dashboard/recurrent-locations"),
          api.get("/dashboard/volume-by-rpa"),
        ]);

        setStats(statsRes.data);
        setRecurrentLocations(locationsRes.data);
        setVolumeByRPA(volumeRes.data);
      } catch (error) {
        console.error("Erro ao carregar dados do dashboard:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      <main className="flex-1 ml-20 p-4 md:p-8 h-full overflow-y-auto">
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-6">Dashboard</h1>

        <div className="flex flex-wrap items-center gap-1 bg-white p-1 rounded-xl w-fit mb-8 border border-gray-200 shadow-sm">
          <button className="px-6 py-2 bg-[#e9fbc0] text-[#1a1a1a] font-semibold rounded-lg text-sm whitespace-nowrap">
            Dashboard de ocorrências
          </button>
          <button className="px-6 py-2 text-gray-500 hover:bg-gray-50 font-medium rounded-lg text-sm whitespace-nowrap">
            Dashboard de Infratores
          </button>
        </div>

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

        <div className="grid grid-cols-12 gap-6 mb-8 lg:h-[500px] h-auto">
          <div
            className={`col-span-12 lg:col-span-7 transition-all ${mapExpanded ? "fixed inset-0 z-50 w-full h-full" : "relative h-[400px] lg:h-full"}`}
          >
            <MapWidget
              isExpanded={mapExpanded}
              onToggleExpand={() => setMapExpanded(!mapExpanded)}
            />
          </div>

          <div className="col-span-12 lg:col-span-5 flex flex-col gap-6 h-full">
            <div className="flex flex-col sm:flex-row gap-6 h-auto sm:h-32">
              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Total de ocorrências
                  </span>
                  <div
                    className="w-4 h-4 border border-gray-300 rounded-full text-[10px] flex items-center justify-center text-gray-400 cursor-help"
                    title="Total acumulado de ocorrências detectadas"
                  >
                    <Info size={12} />
                  </div>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-orange-100 flex items-center justify-center text-orange-500">
                    <AlertTriangle size={24} />
                  </div>
                  <span className="text-4xl font-bold text-[#1a1a1a]">
                    {loading ? "..." : stats?.total_occurrences || 0}
                  </span>
                </div>
              </div>

              <div className="flex-1 bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 text-xs font-medium uppercase">
                    Volume diário de resíduos
                  </span>
                  <div
                    className="w-4 h-4 border border-gray-300 rounded-full text-[10px] flex items-center justify-center text-gray-400 cursor-help"
                    title="Volume total de resíduos detectados hoje"
                  >
                    <Info size={12} />
                  </div>
                </div>
                <div className="flex items-center gap-4 mt-2 sm:mt-0">
                  <div className="w-12 h-12 rounded-full bg-[#ecfccb] flex items-center justify-center text-[#65a30d]">
                    <Trash2 size={24} />
                  </div>
                  <div className="flex items-baseline">
                    <span className="text-4xl font-bold text-[#1a1a1a]">
                      {loading ? "..." : Math.round(stats?.daily_volume_m3 || 0)}
                    </span>
                    <span className="text-sm text-gray-500 font-medium ml-1">
                      m³
                    </span>
                  </div>
                </div>
              </div>
            </div>

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

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-6">
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
              {loading ? (
                <div className="text-center py-8 text-gray-500">Carregando...</div>
              ) : recurrentLocations.length === 0 ? (
                <div className="text-center py-8 text-gray-500">Nenhum local reincidente encontrado</div>
              ) : (
                recurrentLocations.slice(0, 5).map((location, i) => {
                  const position = `${i + 1}º`;
                  const getColorClass = (count: number) => {
                    if (count >= 10) return "bg-red-200 text-red-700";
                    if (count >= 5) return "bg-orange-100 text-orange-600";
                    return "bg-yellow-100 text-yellow-600";
                  };

                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg text-sm min-w-[300px]"
                    >
                      <div className="flex items-center gap-3 text-gray-700 font-medium truncate">
                        <span className="text-gray-400 w-6">{position}</span>
                        <span className="truncate max-w-[200px]">
                          {location.logradouro}, {location.bairro}
                        </span>
                      </div>
                      <span
                        className={`px-3 py-1 rounded-md text-xs font-bold ${getColorClass(location.count)}`}
                      >
                        {location.count} ocorrências
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

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
              {loading ? (
                <div className="text-center py-8 text-gray-500">Carregando...</div>
              ) : volumeByRPA.length === 0 ? (
                <div className="text-center py-8 text-gray-500">Nenhum dado de volumetria encontrado</div>
              ) : (
                volumeByRPA.map((item, i) => {
                  const avgVolume = Math.round(item.avg_volume_m3);
                  const getColorClass = (avg: number) => {
                    if (avg >= 10) return "bg-red-200 text-red-700";
                    if (avg >= 5) return "bg-orange-100 text-orange-600";
                    return "bg-yellow-100 text-yellow-600";
                  };

                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg text-sm min-w-[200px]"
                    >
                      <span className="text-gray-700 font-medium">{item.rpa}</span>
                      <span
                        className={`px-3 py-1 rounded-md text-xs font-bold ${getColorClass(avgVolume)}`}
                      >
                        {avgVolume}m³
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};
