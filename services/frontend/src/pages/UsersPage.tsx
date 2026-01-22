import React, { useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  UserPlus,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Trash2,
  Info,
  X,
} from "lucide-react";
import { UserModal } from "../components/UserModal";
import { DeleteModal } from "../components/DeleteModal";

// Mock Data based on screenshots
const INITIAL_USERS = [
  {
    id: 1,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 2,
    name: "Maria Eduarda Ferreira Lima",
    email: "maria.lima@recife.pe.gov.br",
    phone: "(81) 9 9123-7788",
    secretaria: "EMLURB",
    cargo: "Fiscal Ambiental",
    rpa: "RPA 6",
  },
  {
    id: 3,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 4,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 5,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 6,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 7,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
  {
    id: 8,
    name: "João Victor Almeida Santos",
    email: "joao.santos@recife.pe.gov.br",
    phone: "(81) 9 8765-4321",
    secretaria: "EMLURB",
    cargo: "Analista de Fiscalização Urbana",
    rpa: "RPA 1",
  },
];

export const UsersPage: React.FC = () => {
  const [users, setUsers] = useState(INITIAL_USERS);
  const [isUserModalOpen, setIsUserModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  const [showSuccessToast, setShowSuccessToast] = useState(false);

  // Handlers
  const handleOpenCreate = () => {
    setSelectedUser(null);
    setIsUserModalOpen(true);
  };

  const handleOpenEdit = (user: any) => {
    setSelectedUser(user);
    setIsUserModalOpen(true);
  };

  const handleOpenDelete = (user: any, e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent triggering the edit modal row click
    setSelectedUser(user);
    setIsDeleteModalOpen(true);
  };

  const handleSaveUser = () => {
    // Logic to add/update user would go here
    setIsUserModalOpen(false);

    // Show Success Toast
    setShowSuccessToast(true);
    setTimeout(() => setShowSuccessToast(false), 3000);
  };

  const handleDeleteUser = () => {
    if (selectedUser) {
      setUsers(users.filter((u) => u.id !== selectedUser.id));
    }
    setIsDeleteModalOpen(false);
  };

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto relative">
        {/* Success Toast */}
        {showSuccessToast && (
          <div className="absolute top-8 right-8 z-50 animate-in slide-in-from-top-5 duration-300">
            <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
              <div className="bg-green-500 rounded-full p-1 text-white">
                <Info size={12} strokeWidth={4} />
              </div>
              <span className="font-semibold text-sm">
                Usuário Cadastrado com sucesso!
              </span>
              <button
                onClick={() => setShowSuccessToast(false)}
                className="ml-4 hover:text-green-800"
              >
                <X size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">
            Usuários Cadastrados
          </h1>
        </div>

        {/* Filters Bar */}
        <div className="flex items-center gap-4 mb-8">
          <div className="flex flex-1 gap-4">
            {/* Search Inputs */}
            {["Nome", "Cargo"].map((label, idx) => (
              <div
                key={idx}
                className="flex-1 bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors group"
              >
                <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                  {label}
                </span>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-700 font-medium">
                    Pesquisar
                  </span>
                </div>
              </div>
            ))}
            {/* Select Input */}
            <div className="flex-1 bg-[#f3f4f6] rounded-lg px-4 py-2 border border-transparent hover:border-gray-300 transition-colors cursor-pointer group">
              <span className="text-[10px] uppercase text-gray-500 font-bold block mb-0.5">
                RPA
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
          </div>

          {/* Add User Button */}
          <button
            onClick={handleOpenCreate}
            className="h-full px-4 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
          >
            <UserPlus size={24} />
          </button>
        </div>

        {/* Table Card */}
        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden min-h-[600px] flex flex-col">
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100">
                  {[
                    "Nome",
                    "E-mail",
                    "Telefone",
                    "Secretaria",
                    "Cargo",
                    "RPA",
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
              <tbody>
                {users.map((row, index) => (
                  <tr
                    key={index}
                    onClick={() => handleOpenEdit(row)} // Click row to view/edit
                    className="hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-0 cursor-pointer group"
                  >
                    <td className="px-6 py-5 text-sm text-[#1a1a1a] font-medium">
                      {row.name}
                    </td>
                    <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                      {row.email}
                    </td>
                    <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                      {row.phone}
                    </td>
                    <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                      {row.secretaria}
                    </td>
                    <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                      {row.cargo}
                    </td>
                    <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                      {row.rpa}
                    </td>
                    <td className="px-6 py-5">
                      <button
                        onClick={(e) => handleOpenDelete(row, e)}
                        className="w-8 h-8 flex items-center justify-center text-[#f43f5e] hover:bg-pink-50 rounded-lg transition-colors"
                      >
                        <Trash2 size={20} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between px-6 py-6 border-t border-gray-100 mt-auto">
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

      {/* Modals */}
      <UserModal
        isOpen={isUserModalOpen}
        onClose={() => setIsUserModalOpen(false)}
        onSave={handleSaveUser}
        initialData={selectedUser}
      />

      <DeleteModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={handleDeleteUser}
      />
    </div>
  );
};
