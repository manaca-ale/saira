import React, { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { createOffender } from "../services/offenderService";
import type { OffenderType } from "../services/offenderService";

const TYPE_OPTIONS: { value: OffenderType; label: string }[] = [
  { value: "Carroca", label: "Carroca" },
  { value: "Carro", label: "Carro" },
  { value: "Moto", label: "Moto" },
  { value: "Pessoa", label: "Pessoa" },
  { value: "Outro", label: "Outro" },
];

interface RegisterOffenderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const RegisterOffenderModal: React.FC<RegisterOffenderModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [name, setName] = useState("");
  const [type, setType] = useState<OffenderType | "">("");
  const [plate, setPlate] = useState("");
  const [vehicleColor, setVehicleColor] = useState("");
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  if (!isOpen) return null;

  const isValid = type !== "";

  const resetForm = () => {
    setName("");
    setType("");
    setPlate("");
    setVehicleColor("");
    setDescription("");
    setError("");
  };

  const handleSubmit = async () => {
    if (!isValid || isLoading) return;
    setIsLoading(true);
    setError("");
    try {
      await createOffender({
        name: name.trim() || undefined,
        type: type as OffenderType,
        plate: plate.trim() || undefined,
        vehicle_color: vehicleColor.trim() || undefined,
        description: description.trim() || undefined,
      });
      resetForm();
      onSuccess();
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Erro ao cadastrar infrator. Tente novamente."
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      resetForm();
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <h2 className="text-xl font-bold text-[#1a1a1a]">
            Cadastrar Infrator
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
        <div className="p-6 pt-2 space-y-5">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-xl p-3">
              {error}
            </div>
          )}

          {/* Nome */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Nome
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="Nome do infrator (opcional)"
              disabled={isLoading}
            />
          </div>

          {/* Tipo de infrator */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Tipo de infrator <span className="text-red-500">*</span>
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as OffenderType)}
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

          {/* Placa */}
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
              placeholder="XXX-0000 ou XXX0X00"
              disabled={isLoading}
            />
          </div>

          {/* Cor do veiculo */}
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
              placeholder="Ex: Branco, Preto, Prata"
              disabled={isLoading}
            />
          </div>

          {/* Descricao */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Descricao
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="Observacoes sobre o infrator"
              disabled={isLoading}
            />
          </div>

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
              disabled={!isValid || isLoading}
              className="px-6 py-3 bg-[#ccff33] text-[#1a1a1a] rounded-xl font-bold text-sm hover:bg-[#bef026] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading && <Loader2 size={16} className="animate-spin" />}
              Cadastrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
