import React, { useState, useRef, useEffect } from "react";
import { X, Download, MapPin } from "lucide-react";

interface OccurrenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
}

export const OccurrenceModal: React.FC<OccurrenceModalProps> = ({
  isOpen,
  onClose,
  data,
}) => {
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setShowDownloadMenu(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!isOpen) return null;

  // Status color mapping for the modal
  const getStatusColor = (status: string) => {
    switch (status) {
      case "Pendente":
        return "text-red-500";
      case "Em análise":
        return "text-orange-500";
      case "Resolvido":
        return "text-green-500";
      default:
        return "text-gray-500";
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <h2 className="text-xl font-bold text-[#1a1a1a]">
            Informações da ocorrência
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pt-2 space-y-5">
          {/* Image Placeholder with Bounding Boxes */}
          <div className="relative w-full h-48 bg-gray-200 rounded-xl overflow-hidden group">
            <img
              src="https://images.unsplash.com/photo-1605218427368-35b80b7e42d7?auto=format&fit=crop&q=80&w=800"
              alt="Evidence"
              className="w-full h-full object-cover"
            />
            {/* Simulated Bounding Boxes */}
            <div className="absolute top-10 left-12 w-16 h-32 border-2 border-red-500 bg-red-500/10 flex items-start justify-center">
              <span className="bg-red-500 text-white text-[8px] px-1">
                Infrator (Pessoa)
              </span>
            </div>
            <div className="absolute top-16 left-32 w-24 h-24 border-2 border-red-500 bg-red-500/10 flex items-start justify-center">
              <span className="bg-red-500 text-white text-[8px] px-1">
                Plástico (98%)
              </span>
            </div>
          </div>

          {/* Info Grid */}
          <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-sm">
            <div>
              <span className="block text-gray-400 text-xs mb-1">Status</span>
              <span className={`font-bold ${getStatusColor(data.status)}`}>
                {data.status}
              </span>
            </div>
            <div>
              <span className="block text-gray-400 text-xs mb-1">ID</span>
              <span className="font-bold text-gray-700">000000</span>
            </div>
            <div className="col-span-2">
              <span className="block text-gray-400 text-xs mb-1">
                Data e Hora
              </span>
              <span className="font-bold text-gray-700">07/08/2025, 15:45</span>
            </div>

            <div className="col-span-2 grid grid-cols-3 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Logradouro
                </span>
                <span className="font-bold text-gray-700 block truncate">
                  Rua da Aurora
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">Bairro</span>
                <span className="font-bold text-gray-700 block truncate">
                  Santo Amaro
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">RPA</span>
                <span className="font-bold text-gray-700">RPA 1</span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-2 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Latitude
                </span>
                <span className="font-bold text-gray-700">099982</span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Longitude
                </span>
                <span className="font-bold text-gray-700">099982</span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-3 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Tipo de resíduo
                </span>
                <span className="font-bold text-gray-700">Lixo domiciliar</span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Tipo de material
                </span>
                <span className="font-bold text-gray-700">Plástico</span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Volumetria aprox.
                </span>
                <span className="font-bold text-gray-700">300m³</span>
              </div>
            </div>

            <div className="col-span-2 bg-gray-50 p-2 rounded-lg border border-gray-100">
              <span className="block text-gray-400 text-xs mb-1">
                Infratores
              </span>
              <span className="font-bold text-[#1a1a1a]">
                Identificados: Pessoa
              </span>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 mt-4">
            {/* Download Button with Dropdown */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setShowDownloadMenu(!showDownloadMenu)}
                className="w-12 h-12 flex items-center justify-center bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors text-black"
              >
                <Download size={20} />
              </button>

              {/* Dropdown Menu */}
              {showDownloadMenu && (
                <div className="absolute bottom-full left-0 mb-2 w-40 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden py-1 z-50">
                  <button className="w-full text-left px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                    Baixar em PNG
                  </button>
                  <button className="w-full text-left px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors border-t border-gray-50">
                    Baixar em PDF
                  </button>
                </div>
              )}
            </div>

            {/* Map Button */}
            <button className="flex-1 bg-[#e9fbc0] text-[#4d7c0f] font-bold rounded-xl flex items-center justify-center gap-2 hover:bg-[#d9f99d] transition-colors">
              Ver localização no mapa
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
