import React, { useState, useEffect } from "react";
import { X, Loader2, Search, Plus } from "lucide-react";
import {
  getOffenders,
  addDetectionOffender,
  linkOffenderToDetection,
  OFFENDER_TYPE_OPTIONS as TYPE_OPTIONS,
} from "../services/offenderService";
import type { Offender, OffenderType } from "../services/offenderService";
import { RegisterOffenderModal } from "./RegisterOffenderModal";

interface AddDetectionOffenderModalProps {
  isOpen: boolean;
  onClose: () => void;
  detectionId: string;
  onSuccess: () => void;
}

type Mode = "link" | "new";

export const AddDetectionOffenderModal: React.FC<
  AddDetectionOffenderModalProps
> = ({ isOpen, onClose, detectionId, onSuccess }) => {
  const [mode, setMode] = useState<Mode>("new");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  // Link mode state
  const [searchQuery, setSearchQuery] = useState("");
  const [offenders, setOffenders] = useState<Offender[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedOffender, setSelectedOffender] = useState<Offender | null>(null);

  // New sighting state
  const [offenderType, setOffenderType] = useState<OffenderType | "">("");
  const [plate, setPlate] = useState("");
  const [vehicleColor, setVehicleColor] = useState("");
  const [wasteType, setWasteType] = useState("");
  const [estimatedVolume, setEstimatedVolume] = useState("");
  const [notes, setNotes] = useState("");

  // Register sub-modal
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);

  if (!isOpen) return null;

  const resetForm = () => {
    setMode("new");
    setSearchQuery("");
    setOffenders([]);
    setSelectedOffender(null);
    setOffenderType("");
    setPlate("");
    setVehicleColor("");
    setWasteType("");
    setEstimatedVolume("");
    setNotes("");
    setError("");
  };

  const handleSearch = async (query: string) => {
    setSearchQuery(query);
    if (query.length < 2) {
      setOffenders([]);
      return;
    }
    setSearchLoading(true);
    try {
      const results = await getOffenders({
        name: query,
        is_active: true,
        limit: 10,
      });
      // Also search by plate
      const plateResults = await getOffenders({
        plate: query,
        is_active: true,
        limit: 10,
      });
      // Merge and deduplicate
      const all = [...results, ...plateResults];
      const unique = all.filter(
        (o, i, arr) => arr.findIndex((x) => x.id === o.id) === i
      );
      setOffenders(unique);
    } catch {
      setOffenders([]);
    } finally {
      setSearchLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (isLoading) return;
    setIsLoading(true);
    setError("");
    try {
      if (mode === "link" && selectedOffender) {
        await linkOffenderToDetection(detectionId, selectedOffender.id);
      } else if (mode === "new" && offenderType) {
        await addDetectionOffender(detectionId, {
          offender_type: offenderType as OffenderType,
          plate: plate.trim() || undefined,
          vehicle_color: vehicleColor.trim() || undefined,
          waste_type: wasteType.trim() || undefined,
          estimated_volume_m3: estimatedVolume
            ? parseFloat(estimatedVolume)
            : undefined,
          notes: notes.trim() || undefined,
        });
      }
      resetForm();
      onSuccess();
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Erro ao vincular infrator. Tente novamente."
      );
    } finally {
      setIsLoading(false);
    }
  };

  const canSubmit =
    mode === "link" ? !!selectedOffender : offenderType !== "";

  const handleClose = () => {
    if (!isLoading) {
      resetForm();
      onClose();
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200 max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 pb-2">
            <h2 className="text-xl font-bold text-[#1a1a1a]">
              Adicionar Infrator
            </h2>
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-gray-600"
              disabled={isLoading}
            >
              <X size={24} />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 pt-2 space-y-5 overflow-y-auto flex-1">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-xl p-3">
                {error}
              </div>
            )}

            {/* Mode toggle */}
            <div className="flex gap-2">
              <button
                onClick={() => setMode("new")}
                className={`flex-1 py-2 rounded-xl text-sm font-semibold transition-colors ${
                  mode === "new"
                    ? "bg-[#e9fbc0] text-[#1a1a1a]"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                }`}
              >
                Novo avistamento
              </button>
              <button
                onClick={() => setMode("link")}
                className={`flex-1 py-2 rounded-xl text-sm font-semibold transition-colors ${
                  mode === "link"
                    ? "bg-[#e9fbc0] text-[#1a1a1a]"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                }`}
              >
                Vincular perfil existente
              </button>
            </div>

            {mode === "link" ? (
              <>
                {/* Search */}
                <div className="relative">
                  <Search
                    size={16}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                  />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => handleSearch(e.target.value)}
                    className="w-full border border-gray-300 rounded-xl p-3 pl-9 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
                    placeholder="Buscar por nome ou placa..."
                  />
                  {searchLoading && (
                    <Loader2
                      size={16}
                      className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-gray-400"
                    />
                  )}
                </div>

                {/* Search results */}
                {offenders.length > 0 && (
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {offenders.map((o) => (
                      <button
                        key={o.id}
                        onClick={() => setSelectedOffender(o)}
                        className={`w-full text-left p-3 rounded-xl text-sm transition-colors ${
                          selectedOffender?.id === o.id
                            ? "bg-lime-50 border-2 border-lime-400"
                            : "bg-gray-50 hover:bg-gray-100 border border-gray-100"
                        }`}
                      >
                        <div className="font-bold text-[#1a1a1a]">
                          {o.name || "Sem nome"}
                        </div>
                        <div className="text-xs text-gray-500">
                          {o.type}
                          {o.plate && ` | ${o.plate}`}
                          {o.vehicle_color && ` | ${o.vehicle_color}`}
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {searchQuery.length >= 2 &&
                  offenders.length === 0 &&
                  !searchLoading && (
                    <div className="text-center py-4">
                      <p className="text-sm text-gray-400 mb-2">
                        Nenhum perfil encontrado
                      </p>
                      <button
                        onClick={() => setIsRegisterOpen(true)}
                        className="text-sm text-lime-600 font-bold hover:text-lime-700 flex items-center gap-1 mx-auto"
                      >
                        <Plus size={14} />
                        Cadastrar novo infrator
                      </button>
                    </div>
                  )}
              </>
            ) : (
              <>
                {/* New sighting form */}
                <div>
                  <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                    Tipo de infrator <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={offenderType}
                    onChange={(e) =>
                      setOffenderType(e.target.value as OffenderType)
                    }
                    className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400 bg-white"
                    disabled={isLoading}
                  >
                    <option value="" disabled>
                      Selecione o tipo
                    </option>
                    {TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                      Placa
                    </label>
                    <input
                      type="text"
                      value={plate}
                      onChange={(e) => setPlate(e.target.value.toUpperCase())}
                      maxLength={20}
                      className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400 uppercase"
                      placeholder="XXX-0000"
                      disabled={isLoading}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                      Cor do veiculo
                    </label>
                    <input
                      type="text"
                      value={vehicleColor}
                      onChange={(e) => setVehicleColor(e.target.value)}
                      maxLength={50}
                      className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
                      placeholder="Ex: Branco"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                      Tipo de residuo
                    </label>
                    <input
                      type="text"
                      value={wasteType}
                      onChange={(e) => setWasteType(e.target.value)}
                      maxLength={100}
                      className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
                      placeholder="Ex: Entulho"
                      disabled={isLoading}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                      Volume estimado (m3)
                    </label>
                    <input
                      type="number"
                      value={estimatedVolume}
                      onChange={(e) => setEstimatedVolume(e.target.value)}
                      min={0}
                      step={0.1}
                      className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
                      placeholder="0.0"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                    Observacoes
                  </label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                    className="w-full border border-gray-300 rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-green-400"
                    placeholder="Notas adicionais"
                    disabled={isLoading}
                  />
                </div>
              </>
            )}

            {/* Actions */}
            <div className="flex gap-3 justify-end">
              <button
                onClick={handleClose}
                disabled={isLoading}
                className="px-6 py-3 border-2 border-red-500 text-red-500 rounded-xl font-bold text-sm hover:bg-red-50 transition-colors disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleSubmit}
                disabled={!canSubmit || isLoading}
                className="px-6 py-3 bg-[#ccff33] text-[#1a1a1a] rounded-xl font-bold text-sm hover:bg-[#bef026] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isLoading && <Loader2 size={16} className="animate-spin" />}
                Adicionar
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Sub-modal for registering new offender */}
      <RegisterOffenderModal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        onSuccess={() => {
          setIsRegisterOpen(false);
          // Switch to link mode to let user search for the newly created offender
          setMode("link");
          setSearchQuery("");
        }}
      />
    </>
  );
};
