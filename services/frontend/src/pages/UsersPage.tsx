import React, { useState, useEffect, useMemo } from "react";
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
import { Tooltip } from "../components/Tooltip";
import {
  FilterAutocomplete,
  FilterMultiSelect,
} from "../components/SharedFilters";
import { getUsers, deleteUser, createUser, updateUser } from "../services/userService";
import type { User, CreateUserData } from "../services/userService";
import type { UserFormData } from "../components/UserModal";

interface UserWithStatus extends User {
  status: string;
  cargo?: string;
}

export const UsersPage: React.FC = () => {
  const [users, setUsers] = useState<UserWithStatus[]>([]);
  const [loading, setLoading] = useState(true);

  // --- Load users from API ---
  const loadUsers = async () => {
    try {
      const data = await getUsers({ limit: 100 });
      setUsers(data as UserWithStatus[]);
    } catch (e) {
      console.error("Failed to load users:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  // --- Filter States ---
  const [filterName, setFilterName] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [filterRoles, setFilterRoles] = useState<string[]>([]);
  const [filterStatus, setFilterStatus] = useState<string[]>([]);

  // --- Pagination States ---
  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);

  // --- Modal States ---
  const [isUserModalOpen, setIsUserModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  const [showSuccessToast, setShowSuccessToast] = useState(false);
  const [isUserModalClosing, setIsUserModalClosing] = useState(false);
  const [isDeleteModalClosing, setIsDeleteModalClosing] = useState(false);

  // --- Filtering Logic ---
  const matchesFilters = (user: any, exclude?: "name" | "email" | "role" | "status") => {
    if (exclude !== "name" && filterName) {
      if (!user.name.toLowerCase().includes(filterName.toLowerCase())) return false;
    }
    if (exclude !== "email" && filterEmail) {
      if (!user.email.toLowerCase().includes(filterEmail.toLowerCase())) return false;
    }
    if (exclude !== "role" && filterRoles.length > 0) {
      if (!filterRoles.includes(user.cargo)) return false;
    }
    if (exclude !== "status" && filterStatus.length > 0) {
      if (!filterStatus.includes(user.status)) return false;
    }
    return true;
  };

  const nameOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "name"));
    return Array.from(new Set(filtered.map((user) => user.name))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const emailOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "email"));
    return Array.from(new Set(filtered.map((user) => user.email))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const roleOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "role"));
    return Array.from(
      new Set(
        filtered
          .map((user) => user.cargo)
          .filter((cargo): cargo is string => Boolean(cargo)),
      ),
    ).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const statusOptions = useMemo(() => {
    const filtered = users.filter((user) => matchesFilters(user, "status"));
    return Array.from(new Set(filtered.map((user) => user.status))).sort();
  }, [filterEmail, filterName, filterRoles, filterStatus, users]);

  const filteredUsers = users.filter((user) => matchesFilters(user));

  // --- Pagination Logic ---
  const totalPages = Math.ceil(filteredUsers.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const visibleUsers = filteredUsers.slice(startIndex, endIndex);

  // Reset page when filters or items per page change
  useEffect(() => {
    setCurrentPage(1);
  }, [filterEmail, filterName, filterRoles, filterStatus, itemsPerPage]);

  // --- Handlers ---
  const handleOpenCreate = () => {
    setSelectedUser(null);
    setIsUserModalClosing(false);
    setIsUserModalOpen(true);
  };

  const handleOpenEdit = (user: any) => {
    setSelectedUser(user);
    setIsUserModalClosing(false);
    setIsUserModalOpen(true);
  };

  const handleOpenDelete = (user: any, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedUser(user);
    setIsDeleteModalClosing(false);
    setIsDeleteModalOpen(true);
  };

  const handleCloseUserModal = () => {
    setIsUserModalClosing(true);
    setTimeout(() => {
      setIsUserModalOpen(false);
      setIsUserModalClosing(false);
    }, 500);
  };

  const handleCloseDeleteModal = () => {
    setIsDeleteModalClosing(true);
    setTimeout(() => {
      setIsDeleteModalOpen(false);
      setIsDeleteModalClosing(false);
    }, 500);
  };

  const handleSaveUser = async (data: UserFormData) => {
    const payload: Partial<CreateUserData> = {
      name: data.name.trim(),
      email: data.email.trim(),
      phone: data.phone.trim() || undefined,
      secretaria: data.secretaria.trim() || undefined,
      cargo: data.cargo.trim() || undefined,
      rpa: data.rpa.trim() || undefined,
    };

    if (selectedUser) {
      if (data.password.trim()) {
        payload.password = data.password.trim();
      }

      try {
        await updateUser(selectedUser.id, payload);
        await loadUsers();
        handleCloseUserModal();
        setShowSuccessToast(true);
        setTimeout(() => setShowSuccessToast(false), 3000);
      } catch (e) {
        const detail = (e as any)?.response?.data?.detail;
        if (typeof detail === "string") {
          throw new Error(detail === "Email already registered" ? "E-mail já cadastrado." : detail);
        }
        throw new Error("Não foi possível atualizar o usuário.");
      }
      return;
    }

    if (!data.password || data.password.trim().length < 8) {
      throw new Error("A senha deve ter pelo menos 8 caracteres.");
    }

    try {
      await createUser({
        name: payload.name || "",
        email: payload.email || "",
        password: data.password.trim(),
        phone: payload.phone,
        secretaria: payload.secretaria,
        cargo: payload.cargo,
        rpa: payload.rpa,
        is_active: true,
      });
      await loadUsers();
      handleCloseUserModal();
      setShowSuccessToast(true);
      setTimeout(() => setShowSuccessToast(false), 3000);
    } catch (e) {
      const detail = (e as any)?.response?.data?.detail;
      if (typeof detail === "string") {
        throw new Error(detail === "Email already registered" ? "E-mail já cadastrado." : detail);
      }
      throw new Error("Não foi possível criar o usuário.");
    }
  };

  const handleDeleteUser = async () => {
    if (selectedUser) {
      try {
        await deleteUser(selectedUser.id);
        setUsers(users.filter((u) => u.id !== selectedUser.id));
      } catch (e) {
        console.error("Failed to delete user:", e);
      }
    }
    handleCloseDeleteModal();
  };

  // Helper to generate page numbers
  const getPageNumbers = () => {
    const pages = [];
    for (let i = 1; i <= totalPages; i++) {
      pages.push(i);
    }
    return pages;
  };

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      {/* Global Animation Styles */}
      <style>{`
        @keyframes modalPop {
          0% { opacity: 0; transform: scale(0.8) translateY(50px); }
          100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes modalPopExit {
          0% { opacity: 1; transform: scale(1) translateY(0); }
          100% { opacity: 0; transform: scale(0.8) translateY(50px); }
        }
      `}</style>

      {/* FIX: Added overflow-x-hidden to main to prevent horizontal scrollbar */}
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto overflow-x-hidden relative">
        {/* Success Toast */}
        {showSuccessToast && (
          <div className="absolute top-8 right-8 z-50 animate-in slide-in-from-top-5 duration-300">
            <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
              <div className="bg-green-500 rounded-full p-1 text-white">
                <Info size={12} strokeWidth={4} />
              </div>
              <span className="font-semibold text-sm">
                Usuário salvo com sucesso!
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

        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">
            Usuários Cadastrados
          </h1>
        </div>

        {/* Filters Bar */}
        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-5 gap-4">
              <FilterAutocomplete
                label="Nome"
                value={filterName}
                options={nameOptions}
                onChange={setFilterName}
              />
              <FilterAutocomplete
                label="E-mail"
                value={filterEmail}
                options={emailOptions}
                onChange={setFilterEmail}
              />
              <FilterMultiSelect
                label="Cargo"
                value={filterRoles}
                options={roleOptions}
                onChange={(v) => setFilterRoles(v)}
              />
              <FilterMultiSelect
                label="Status"
                value={filterStatus}
                options={statusOptions}
                onChange={(v) => setFilterStatus(v)}
              />
              <div className="hidden md:block"></div>
              <div className="hidden md:block"></div>
            </div>
          </div>
          <div className="pt-[25px]">
            <Tooltip
              text="Adicionar novo usuário"
              className="w-fit"
              spacing="mb-2"
            >
              <button
                onClick={handleOpenCreate}
                className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
              >
                <UserPlus size={24} />
              </button>
            </Tooltip>
          </div>
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
                {visibleUsers.length > 0 ? (
                  visibleUsers.map((row, index) => (
                    <tr
                      key={row.id}
                      onClick={() => handleOpenEdit(row)}
                      className={`transition-colors border-b border-gray-50 last:border-0 cursor-pointer group ${index % 2 === 0 ? "bg-gray-50" : "bg-white"} hover:bg-gray-200`}
                    >
                      <td className="px-6 py-5 text-sm text-[#1a1a1a] font-medium">
                        <Tooltip text={row.name}>
                          <span className="truncate max-w-[200px] block">
                            {row.name}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.email}>
                          <span className="truncate max-w-[240px] block">
                            {row.email}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        {row.phone}
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.secretaria}>
                          <span className="truncate max-w-[200px] block">
                            {row.secretaria}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip text={row.cargo}>
                          <span className="truncate max-w-[220px] block">
                            {row.cargo}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        {row.rpa}
                      </td>
                      <td className="px-6 py-5">
                        <Tooltip
                          text="Deletar usuário"
                          variant="danger"
                          className="w-fit"
                          spacing="mb-2"
                        >
                          <button
                            onClick={(e) => handleOpenDelete(row, e)}
                            className="w-8 h-8 flex items-center justify-center text-[#f43f5e] hover:bg-pink-50 rounded-lg transition-colors bg-transparent"
                          >
                            <Trash2 size={20} />
                          </button>
                        </Tooltip>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-6 py-10 text-center text-gray-500"
                    >
                      Nenhum usuário encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Dynamic Pagination Footer */}
          <div className="flex items-center justify-between px-6 py-6 border-t border-gray-100 mt-auto bg-white">
            <span className="text-sm text-gray-500">
              Mostrando {visibleUsers.length > 0 ? startIndex + 1 : 0} -{" "}
              {Math.min(endIndex, filteredUsers.length)} de{" "}
              {filteredUsers.length} registros
            </span>

            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>

              {/* Items Per Page Dropdown */}
              <div className="relative">
                <div
                  onClick={() => setShowItemsMenu(!showItemsMenu)}
                  className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-300 transition-colors select-none min-w-[60px] justify-between"
                >
                  {itemsPerPage}
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${showItemsMenu ? "rotate-180" : ""}`}
                  />
                </div>

                {showItemsMenu && (
                  <div className="absolute bottom-full left-0 mb-1 w-full bg-white border border-gray-200 rounded-lg shadow-xl overflow-hidden z-30 animate-in fade-in zoom-in-95 slide-in-from-bottom-2 duration-200 ease-out origin-bottom">
                    {[10, 20, 30].map((num) => (
                      <div
                        key={num}
                        onClick={() => {
                          setItemsPerPage(num);
                          setShowItemsMenu(false);
                        }}
                        className={`px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 flex justify-center ${itemsPerPage === num ? "font-bold bg-gray-50 text-[#1a1a1a]" : "text-gray-600"}`}
                      >
                        {num}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Page Numbers */}
              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${currentPage === 1 ? "text-gray-300 cursor-not-allowed" : "text-gray-400 hover:text-gray-600"}`}
                >
                  <ChevronLeft size={16} />
                </button>

                {getPageNumbers().map((pageNum) => (
                  <button
                    key={pageNum}
                    onClick={() => setCurrentPage(pageNum)}
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold transition-all shadow-sm
                            ${currentPage === pageNum ? "bg-[#ccff33] text-black" : "text-gray-500 hover:bg-gray-100"}`}
                  >
                    {pageNum}
                  </button>
                ))}

                <button
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages || totalPages === 0}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${currentPage === totalPages || totalPages === 0 ? "text-gray-300 cursor-not-allowed" : "text-gray-400 hover:text-gray-600"}`}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Modals */}
      {isUserModalOpen && (
        <UserModal
          onClose={handleCloseUserModal}
          onSave={handleSaveUser}
          initialData={selectedUser}
          isClosing={isUserModalClosing}
        />
      )}

      {isDeleteModalOpen && (
        <DeleteModal
          onClose={handleCloseDeleteModal}
          onConfirm={handleDeleteUser}
          isClosing={isDeleteModalClosing}
        />
      )}
    </div>
  );
};
