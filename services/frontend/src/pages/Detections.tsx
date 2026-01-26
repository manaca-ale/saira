import React, { useState, useEffect } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  Filter,
  ChevronDown,
  Download,
  Eye,
  ChevronRight,
  ChevronLeft,
  MapPin,
  X,
} from "lucide-react";
import { OccurrenceModal } from "../components/OccurrenceModal";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import api from "../services/api";

interface Detection {
  id: string;
  logradouro: string;
  bairro: string;
  rpa: string;
  timestamp: string;
  waste_type: string;
  volume_m3: number;
  offenders: string | null;
  status: string;
  latitude: number;
  longitude: number;
}

export const Detections: React.FC = () => {
  const [detections, setDetections] = useState<Detection[]>([]);
  const [selectedItem, setSelectedItem] = useState<Detection | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMapModalOpen, setIsMapModalOpen] = useState(false);
  const [selectedDetection, setSelectedDetection] = useState<Detection | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    fetchDetections();
  }, []);

  const fetchDetections = async () => {
    try {
      const response = await api.get("/detections");
      setDetections(response.data);
    } catch (error) {
      console.error("Erro ao carregar detecções:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenModal = (item: Detection) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleOpenMapModal = (detection: Detection) => {
    setSelectedDetection(detection);
    setIsMapModalOpen(true);
  };

  const getStatusStyle = (status: string) => {
    switch (status) {
      case "Pendente":
        return "bg-red-100 text-red-500";
      case "Em análise":
        return "bg-orange-100 text-orange-500";
      case "Resolvido":
        return "bg-[#dcfce7] text-[#16a34a]";
      default:
        return "bg-gray-100 text-gray-500";
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString("pt-BR");
  };

  const filteredDetections = detections.filter(
    (det) =>
      det.logradouro?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      det.bairro?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">
            Detecções de câmeras
          </h1>
        </div>

        <div className="flex items-center gap-4 mb-8">
          <div className="flex flex-1 gap-4">
            <div className="flex-1 bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors min-w-[120px]">
              <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                Logradouro
              </span>
              <input
                type="text"
                placeholder="Pesquisar"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full text-sm text-gray-700 font-medium bg-transparent outline-none"
              />
            </div>
            {["Período", "Status", "Bairro", "RPA"].map((label, idx) => (
              <div
                key={idx}
                className="flex-1 bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors cursor-pointer group min-w-[120px]"
              >
                <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                  {label}
                </span>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-700 font-medium">
                    Selecionar
                  </span>
                  <ChevronDown
                    size={14}
                    className="text-gray-400 group-hover:text-gray-600"
                  />
                </div>
              </div>
            ))}
            <button className="w-12 bg-white border border-gray-200 rounded-lg flex items-center justify-center hover:bg-gray-50 text-gray-600">
              <Filter size={20} />
            </button>
          </div>
        </div>

        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
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
                    "Ações",
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

              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={10} className="text-center py-8 text-gray-500">
                      Carregando...
                    </td>
                  </tr>
                ) : filteredDetections.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="text-center py-8 text-gray-500">
                      Nenhuma detecção encontrada
                    </td>
                  </tr>
                ) : (
                  filteredDetections.map((row, index) => (
                    <tr
                      key={row.id}
                      className={`hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-0 group ${
                        index % 2 === 0 ? "bg-white" : "bg-gray-50/50"
                      }`}
                    >
                      <td className="px-6 py-4 text-sm text-gray-500 font-medium">
                        {row.id.substring(0, 8)}
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
                        {formatDate(row.timestamp)}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        {row.waste_type}
                      </td>
                      <td className="px-6 py-4 text-sm text-[#1a1a1a]">
                        ~{row.volume_m3} m³
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {row.offenders || "Não Identificado"}
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`px-3 py-1.5 rounded-lg text-xs font-bold ${getStatusStyle(
                            row.status
                          )}`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleOpenModal(row)}
                            className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#1a1a1a] hover:border-[#1a1a1a] transition-all"
                            title="Ver detalhes"
                          >
                            <Eye size={16} />
                          </button>
                          <button
                            onClick={() => handleOpenMapModal(row)}
                            className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-blue-600 hover:border-blue-600 transition-all"
                            title="Ver no mapa"
                          >
                            <MapPin size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
            <span className="text-sm text-gray-500">
              Mostrando {filteredDetections.length} de {detections.length} linhas
            </span>
          </div>
        </div>
      </main>

      {selectedItem && (
        <OccurrenceModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          data={selectedItem}
        />
      )}

      {/* Map Modal */}
      {isMapModalOpen && selectedDetection && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-4xl h-[80vh] relative">
            <div className="absolute top-4 right-4 z-[1000]">
              <button
                onClick={() => setIsMapModalOpen(false)}
                className="bg-white p-2 rounded-lg shadow-lg hover:bg-gray-50 transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <div className="w-full h-full rounded-2xl overflow-hidden">
              <MapContainer
                center={[selectedDetection.latitude, selectedDetection.longitude]}
                zoom={16}
                style={{ width: "100%", height: "100%" }}
              >
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <Marker
                  position={[selectedDetection.latitude, selectedDetection.longitude]}
                >
                  <Popup>
                    <div className="text-sm">
                      <div className="font-bold text-base mb-2">
                        {selectedDetection.logradouro}
                      </div>
                      <div>{selectedDetection.bairro}</div>
                      <div className="text-gray-600 mt-1">
                        {selectedDetection.waste_type}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              </MapContainer>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
