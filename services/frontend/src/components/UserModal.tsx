import React from "react";
import { X } from "lucide-react";

interface UserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  initialData?: any; // To populate if editing
}

export const UserModal: React.FC<UserModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initialData,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-3xl shadow-2xl relative animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-8 pb-4">
          <h2 className="text-2xl font-bold text-[#1a1a1a]">
            {initialData ? "Editar usuário" : "Novo usuário"}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <X size={24} />
          </button>
        </div>

        {/* Form Content */}
        <div className="p-8 pt-4 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Nome Completo */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                Nome completo <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                defaultValue={initialData?.name}
                placeholder="Ex.: Luiz Marinho da Silva"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] transition-all"
              />
            </div>

            {/* Email */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                Email <span className="text-red-500">*</span>
              </label>
              <input
                type="email"
                defaultValue={initialData?.email}
                placeholder="Ex.: luiz-marinho@gmail.com"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] transition-all"
              />
            </div>

            {/* Contato */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                Contato <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                defaultValue={initialData?.phone}
                placeholder="(XX) 9 9122-3344"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] transition-all"
              />
            </div>

            {/* Cargo */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                Cargo <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                defaultValue={initialData?.cargo}
                placeholder="Ex.: EMLURB"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] transition-all"
              />
            </div>

            {/* Secretaria */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                Secretaria <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                defaultValue={initialData?.secretaria}
                placeholder="Ex.: EMLURB"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] transition-all"
              />
            </div>

            {/* RPA */}
            <div className="space-y-1">
              <label className="text-sm text-gray-600 font-medium">
                RPA <span className="text-red-500">*</span>
              </label>
              <select
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-gray-700 focus:outline-none focus:border-[#ccff33] focus:ring-1 focus:ring-[#ccff33] bg-white transition-all"
                defaultValue={initialData?.rpa || ""}
              >
                <option value="" disabled>
                  Selecione
                </option>
                <option value="RPA 1">RPA 1</option>
                <option value="RPA 2">RPA 2</option>
                <option value="RPA 3">RPA 3</option>
              </select>
            </div>
          </div>

          {/* Buttons */}
          <div className="flex justify-end gap-3 mt-8 pt-4">
            <button
              onClick={onClose}
              className="px-6 py-2 rounded-lg bg-pink-100 text-pink-600 font-bold hover:bg-pink-200 transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={onSave}
              className="px-6 py-2 rounded-lg bg-[#10b981] text-white font-bold hover:bg-[#059669] transition-colors shadow-lg shadow-green-200"
            >
              Salvar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
