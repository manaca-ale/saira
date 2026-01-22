import React from "react";

interface DeleteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export const DeleteModal: React.FC<DeleteModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-md shadow-2xl p-8 text-center animate-in fade-in zoom-in duration-200">
        <h3 className="text-xl font-bold text-[#1a1a1a] mb-2">
          Tem certeza que deseja excluir este usuário?
        </h3>
        <p className="text-gray-500 mb-8">
          Essa ação removerá o acesso ao sistema.
        </p>

        <div className="flex justify-center gap-3">
          <button
            onClick={onClose}
            className="px-6 py-2 rounded-lg bg-gray-200 text-gray-600 font-bold hover:bg-gray-300 transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="px-6 py-2 rounded-lg bg-[#f43f5e] text-white font-bold hover:bg-[#e11d48] transition-colors shadow-lg shadow-red-200"
          >
            Excluir usuário
          </button>
        </div>
      </div>
    </div>
  );
};
