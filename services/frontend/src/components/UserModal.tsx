import React, { useState, useEffect } from "react";
import {
  X,
  User,
  Briefcase,
  Mail,
  Phone,
  MapPin,
  ChevronDown,
} from "lucide-react";

interface UserModalProps {
  onClose: () => void;
  onSave: (data: any) => void;
  initialData?: any;
  isClosing: boolean; // Animation state
}

// Helper component for Light Mode Inputs inside the modal
const ModalInput: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
  type?: string;
  placeholder?: string;
  icon?: React.ElementType;
}> = ({ label, value, onChange, type = "text", placeholder, icon: Icon }) => (
  <div className="flex flex-col gap-1.5 w-full group">
    <label className="text-sm font-bold text-gray-700 select-none ml-1">
      {label}
    </label>
    <div className="relative">
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] placeholder-gray-400 outline-none focus:bg-white focus:border-gray-300 transition-all"
      />
      {Icon && (
        <Icon className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
      )}
    </div>
  </div>
);

export const UserModal: React.FC<UserModalProps> = ({
  onClose,
  onSave,
  initialData,
  isClosing,
}) => {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    secretaria: "",
    cargo: "",
    rpa: "",
  });

  useEffect(() => {
    if (initialData) {
      setFormData(initialData);
    }
  }, [initialData]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(formData);
  };

  return (
    <div
      className={`
        fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4
        transition-opacity duration-500
        ${isClosing ? "opacity-0" : "opacity-100"}
      `}
    >
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-2xl p-8 relative overflow-hidden"
        style={{
          animation: isClosing
            ? "modalPopExit 0.5s ease-in forwards"
            : "modalPop 0.5s ease-out forwards",
        }}
      >
        <button
          onClick={onClose}
          className="absolute top-6 right-6 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <X size={24} />
        </button>

        <h2 className="text-2xl font-bold text-[#1a1a1a] mb-1 select-none">
          {initialData ? "Editar Usuário" : "Novo Usuário"}
        </h2>
        <p className="text-gray-500 text-sm mb-8 select-none">
          Preencha as informações abaixo para{" "}
          {initialData ? "editar" : "cadastrar"} o usuário.
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ModalInput
              label="Nome Completo"
              value={formData.name}
              onChange={(val) => setFormData({ ...formData, name: val })}
              placeholder="Ex: João Silva"
              icon={User}
            />
            <ModalInput
              label="E-mail"
              type="email"
              value={formData.email}
              onChange={(val) => setFormData({ ...formData, email: val })}
              placeholder="Ex: joao@email.com"
              icon={Mail}
            />
            <ModalInput
              label="Telefone"
              value={formData.phone}
              onChange={(val) => setFormData({ ...formData, phone: val })}
              placeholder="(00) 00000-0000"
              icon={Phone}
            />
            <ModalInput
              label="Cargo"
              value={formData.cargo}
              onChange={(val) => setFormData({ ...formData, cargo: val })}
              placeholder="Ex: Analista"
              icon={Briefcase}
            />
            <ModalInput
              label="Secretaria"
              value={formData.secretaria}
              onChange={(val) => setFormData({ ...formData, secretaria: val })}
              placeholder="Ex: EMLURB"
              icon={Briefcase}
            />

            {/* Custom Select for RPA (Light Mode) */}
            <div className="flex flex-col gap-1.5 w-full group">
              <label className="text-sm font-bold text-gray-700 select-none ml-1">
                RPA
              </label>
              <div className="relative">
                <select
                  value={formData.rpa}
                  onChange={(e) =>
                    setFormData({ ...formData, rpa: e.target.value })
                  }
                  className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] outline-none focus:bg-white focus:border-gray-300 appearance-none transition-all cursor-pointer"
                >
                  <option value="">Selecione...</option>
                  <option value="RPA 1">RPA 1</option>
                  <option value="RPA 2">RPA 2</option>
                  <option value="RPA 3">RPA 3</option>
                </select>
                <MapPin className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 pointer-events-none" />
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 mt-4 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 rounded-xl font-bold text-gray-500 hover:bg-gray-100 transition-colors select-none"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="px-8 py-3 rounded-xl font-bold bg-[#ccff33] hover:bg-[#b8e62e] text-black shadow-lg shadow-[#ccff33]/20 transition-all select-none"
            >
              Salvar Usuário
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
