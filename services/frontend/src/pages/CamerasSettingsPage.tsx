import React, { useEffect, useMemo, useState } from "react";
import {
  Camera,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  Info,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import { Tooltip } from "../components/Tooltip";
import {
  FilterAutocomplete,
  FilterMultiSelect,
} from "../components/SharedFilters";
import { DeleteModal } from "../components/DeleteModal";
import { CameraModal } from "../components/CameraModal";
import type { CameraFormData } from "../components/CameraModal";
import { CameraDetailsModal } from "../components/CameraDetailsModal";
import {
  createCamera,
  deleteCamera,
  getCameras,
  getLatestCameraImageFromFolder,
  updateCamera,
  type Camera as CameraEntity,
  type CameraLatestImage,
  type CameraPayload,
} from "../services/cameraService";
import { formatDateTimeBrazil } from "../utils/datetime";

const formatDateTime = (value?: string | null): string => {
  const formatted = formatDateTimeBrazil(value, {
    dateStyle: "short",
    timeStyle: "short",
  });
  return formatted === "—" ? "Sem comunicação" : formatted;
};

const cameraStatusLabel = (camera: CameraEntity): string =>
  camera.is_active ? "Ativa" : "Inativa";

const toOptionalString = (value: string): string | undefined => {
  const normalized = value.trim();
  return normalized ? normalized : undefined;
};

export const CamerasSettingsPage: React.FC = () => {
  const [cameras, setCameras] = useState<CameraEntity[]>([]);
  const [loading, setLoading] = useState(true);

  const [filterName, setFilterName] = useState("");
  const [filterDeviceId, setFilterDeviceId] = useState("");
  const [filterStatus, setFilterStatus] = useState<string[]>([]);

  const [itemsPerPage, setItemsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showItemsMenu, setShowItemsMenu] = useState(false);

  const [showSuccessToast, setShowSuccessToast] = useState(false);
  const [successMessage, setSuccessMessage] = useState("Câmera salva com sucesso!");

  const [isCameraModalOpen, setIsCameraModalOpen] = useState(false);
  const [isCameraModalClosing, setIsCameraModalClosing] = useState(false);
  const [selectedCamera, setSelectedCamera] = useState<CameraEntity | null>(null);

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleteModalClosing, setIsDeleteModalClosing] = useState(false);

  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false);
  const [isDetailsModalClosing, setIsDetailsModalClosing] = useState(false);
  const [detailsCamera, setDetailsCamera] = useState<CameraEntity | null>(null);
  const [latestCameraImage, setLatestCameraImage] = useState<CameraLatestImage | null>(
    null,
  );
  const [isLoadingLatestImage, setIsLoadingLatestImage] = useState(false);

  const loadCameras = async () => {
    try {
      const data = await getCameras({ limit: 100 });
      setCameras(data);
    } catch (error) {
      console.error("Failed to load cameras:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCameras();
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [filterName, filterDeviceId, filterStatus, itemsPerPage]);

  const matchesFilters = (
    camera: CameraEntity,
    exclude?: "name" | "device" | "status",
  ): boolean => {
    if (exclude !== "name" && filterName) {
      if (!camera.name.toLowerCase().includes(filterName.toLowerCase())) {
        return false;
      }
    }
    if (exclude !== "device" && filterDeviceId) {
      const deviceId = (camera.device_id || "").toLowerCase();
      if (!deviceId.includes(filterDeviceId.toLowerCase())) {
        return false;
      }
    }
    if (exclude !== "status" && filterStatus.length > 0) {
      if (!filterStatus.includes(cameraStatusLabel(camera))) {
        return false;
      }
    }
    return true;
  };

  const nameOptions = useMemo(() => {
    const filtered = cameras.filter((camera) => matchesFilters(camera, "name"));
    return Array.from(new Set(filtered.map((camera) => camera.name))).sort();
  }, [cameras, filterDeviceId, filterName, filterStatus]);

  const deviceOptions = useMemo(() => {
    const filtered = cameras.filter((camera) => matchesFilters(camera, "device"));
    return Array.from(
      new Set(
        filtered
          .map((camera) => camera.device_id)
          .filter((value): value is string => Boolean(value)),
      ),
    ).sort();
  }, [cameras, filterDeviceId, filterName, filterStatus]);

  const statusOptions = useMemo(() => {
    const filtered = cameras.filter((camera) => matchesFilters(camera, "status"));
    return Array.from(new Set(filtered.map((camera) => cameraStatusLabel(camera))));
  }, [cameras, filterDeviceId, filterName, filterStatus]);

  const filteredCameras = useMemo(
    () => cameras.filter((camera) => matchesFilters(camera)),
    [cameras, filterDeviceId, filterName, filterStatus],
  );

  const totalPages = Math.ceil(filteredCameras.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const visibleCameras = filteredCameras.slice(startIndex, endIndex);

  const closeCameraModal = () => {
    setIsCameraModalClosing(true);
    setTimeout(() => {
      setIsCameraModalOpen(false);
      setIsCameraModalClosing(false);
      setSelectedCamera(null);
    }, 500);
  };

  const closeDeleteModal = () => {
    setIsDeleteModalClosing(true);
    setTimeout(() => {
      setIsDeleteModalOpen(false);
      setIsDeleteModalClosing(false);
      setSelectedCamera(null);
    }, 500);
  };

  const closeDetailsModal = () => {
    setIsDetailsModalClosing(true);
    setTimeout(() => {
      setIsDetailsModalOpen(false);
      setIsDetailsModalClosing(false);
      setDetailsCamera(null);
      setLatestCameraImage(null);
    }, 500);
  };

  const openCreateModal = () => {
    setSelectedCamera(null);
    setIsCameraModalClosing(false);
    setIsCameraModalOpen(true);
  };

  const openEditModal = (camera: CameraEntity) => {
    setSelectedCamera(camera);
    setIsCameraModalClosing(false);
    setIsCameraModalOpen(true);
  };

  const openDeleteModal = (camera: CameraEntity) => {
    setSelectedCamera(camera);
    setIsDeleteModalClosing(false);
    setIsDeleteModalOpen(true);
  };

  const openDetailsModal = async (camera: CameraEntity) => {
    setDetailsCamera(camera);
    setLatestCameraImage(null);
    setIsLoadingLatestImage(true);
    setIsDetailsModalClosing(false);
    setIsDetailsModalOpen(true);

    try {
      const latest = await getLatestCameraImageFromFolder(camera.id);
      setLatestCameraImage(latest);
    } catch (error) {
      console.error("Failed to load latest camera image from folder:", error);
      setLatestCameraImage(null);
    } finally {
      setIsLoadingLatestImage(false);
    }
  };

  const parseCameraFormData = (formData: CameraFormData): CameraPayload => {
    const latitude = Number(formData.latitude);
    const longitude = Number(formData.longitude);
    const captureInterval = Number(formData.capture_interval_seconds);

    return {
      name: formData.name.trim(),
      device_id: toOptionalString(formData.device_id),
      logradouro: toOptionalString(formData.logradouro),
      bairro: toOptionalString(formData.bairro),
      rpa: toOptionalString(formData.rpa),
      latitude,
      longitude,
      rtsp_url: toOptionalString(formData.rtsp_url),
      capture_interval_seconds: captureInterval,
      is_active: formData.is_active,
    };
  };

  const handleSaveCamera = async (formData: CameraFormData) => {
    const payload = parseCameraFormData(formData);

    try {
      if (selectedCamera) {
        await updateCamera(selectedCamera.id, payload);
        setSuccessMessage("Câmera atualizada com sucesso!");
      } else {
        await createCamera(payload);
        setSuccessMessage("Câmera cadastrada com sucesso!");
      }

      await loadCameras();
      closeCameraModal();
      setShowSuccessToast(true);
      setTimeout(() => setShowSuccessToast(false), 3000);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      if (typeof detail === "string") {
        if (detail === "device_id already registered") {
          throw new Error("Este Device ID já está cadastrado.");
        }
        throw new Error(detail);
      }
      throw new Error("Não foi possível salvar a câmera.");
    }
  };

  const handleDeleteCamera = async () => {
    if (!selectedCamera) return;

    try {
      await deleteCamera(selectedCamera.id);
      setCameras((prev) => prev.filter((camera) => camera.id !== selectedCamera.id));
      setSuccessMessage("Câmera removida com sucesso!");
      setShowSuccessToast(true);
      setTimeout(() => setShowSuccessToast(false), 3000);
    } catch (error) {
      console.error("Failed to delete camera:", error);
    } finally {
      closeDeleteModal();
    }
  };

  const getPageNumbers = (): number[] => {
    const pages: number[] = [];
    for (let page = 1; page <= totalPages; page += 1) pages.push(page);
    return pages;
  };

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

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

      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto overflow-x-hidden relative">
        {showSuccessToast ? (
          <div className="absolute top-8 right-8 z-50 animate-in slide-in-from-top-5 duration-300">
            <div className="bg-[#dcfce7] border border-green-200 text-[#166534] px-4 py-3 rounded-xl shadow-lg flex items-center gap-3">
              <div className="bg-green-500 rounded-full p-1 text-white">
                <Info size={12} strokeWidth={4} />
              </div>
              <span className="font-semibold text-sm">{successMessage}</span>
              <button
                onClick={() => setShowSuccessToast(false)}
                className="ml-4 hover:text-green-800"
              >
                <X size={16} />
              </button>
            </div>
          </div>
        ) : null}

        <div className="flex justify-between items-center mb-8">
          <div>
            <p className="text-sm text-gray-500 mb-1">Configurações</p>
            <h1 className="text-3xl font-bold text-[#1a1a1a]">Câmeras Cadastradas</h1>
          </div>
        </div>

        <div className="flex items-start gap-4 mb-8">
          <div className="flex-1">
            <div className="grid grid-cols-4 gap-4">
              <FilterAutocomplete
                label="Nome"
                value={filterName}
                options={nameOptions}
                onChange={setFilterName}
              />
              <FilterAutocomplete
                label="Device ID"
                value={filterDeviceId}
                options={deviceOptions}
                onChange={setFilterDeviceId}
              />
              <FilterMultiSelect
                label="Status"
                value={filterStatus}
                options={statusOptions}
                onChange={setFilterStatus}
              />
            </div>
          </div>
          <div className="pt-[25px]">
            <Tooltip text="Cadastrar nova câmera" className="w-fit" spacing="mb-2">
              <button
                onClick={openCreateModal}
                className="h-[50px] px-6 py-2 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors flex items-center justify-center text-black shadow-sm"
              >
                <Plus size={24} />
              </button>
            </Tooltip>
          </div>
        </div>

        <div className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden min-h-[600px] flex flex-col">
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100">
                  {[
                    "Nome",
                    "Device ID",
                    "Local",
                    "Status",
                    "Última comunicação",
                    "Ações",
                  ].map((head) => (
                    <th
                      key={head}
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
                    <td colSpan={6} className="px-6 py-10 text-center text-gray-500">
                      Carregando câmeras...
                    </td>
                  </tr>
                ) : visibleCameras.length > 0 ? (
                  visibleCameras.map((camera, index) => (
                    <tr
                      key={camera.id}
                      className={`transition-colors border-b border-gray-50 last:border-0 ${index % 2 === 0 ? "bg-gray-50" : "bg-white"} hover:bg-gray-100`}
                    >
                      <td className="px-6 py-5 text-sm text-[#1a1a1a] font-medium">
                        <Tooltip text={camera.name}>
                          <span className="truncate max-w-[220px] block">{camera.name}</span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        {camera.device_id || "-"}
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a]">
                        <Tooltip
                          text={
                            [camera.logradouro, camera.bairro, camera.rpa]
                              .filter(Boolean)
                              .join(" - ") || "Não informado"
                          }
                        >
                          <span className="truncate max-w-[280px] block">
                            {[camera.logradouro, camera.bairro, camera.rpa]
                              .filter(Boolean)
                              .join(" - ") || "Não informado"}
                          </span>
                        </Tooltip>
                      </td>
                      <td className="px-6 py-5 text-sm">
                        <span
                          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${
                            camera.is_active
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-gray-200 text-gray-600"
                          }`}
                        >
                          {cameraStatusLabel(camera)}
                        </span>
                      </td>
                      <td className="px-6 py-5 text-sm text-[#1a1a1a] whitespace-nowrap">
                        {formatDateTime(camera.last_capture_at)}
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-1">
                          <Tooltip text="Ver detalhes">
                            <button
                              onClick={() => openDetailsModal(camera)}
                              className="w-8 h-8 flex items-center justify-center text-sky-600 hover:bg-sky-50 rounded-lg transition-colors bg-transparent"
                            >
                              <Eye size={18} />
                            </button>
                          </Tooltip>
                          <Tooltip text="Editar câmera">
                            <button
                              onClick={() => openEditModal(camera)}
                              className="w-8 h-8 flex items-center justify-center text-gray-600 hover:bg-gray-100 rounded-lg transition-colors bg-transparent"
                            >
                              <Pencil size={18} />
                            </button>
                          </Tooltip>
                          <Tooltip text="Excluir câmera" variant="danger">
                            <button
                              onClick={() => openDeleteModal(camera)}
                              className="w-8 h-8 flex items-center justify-center text-[#f43f5e] hover:bg-pink-50 rounded-lg transition-colors bg-transparent"
                            >
                              <Trash2 size={18} />
                            </button>
                          </Tooltip>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="px-6 py-10 text-center text-gray-500">
                      Nenhuma câmera encontrada.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between px-6 py-6 border-t border-gray-100 mt-auto bg-white">
            <span className="text-sm text-gray-500">
              Mostrando {visibleCameras.length > 0 ? startIndex + 1 : 0} -{" "}
              {Math.min(endIndex, filteredCameras.length)} de {filteredCameras.length}{" "}
              registros
            </span>

            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">Itens</span>
              <div className="relative">
                <div
                  onClick={() => setShowItemsMenu((prev) => !prev)}
                  className="flex items-center gap-2 bg-gray-200 rounded-lg px-3 py-1 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-300 transition-colors select-none min-w-[60px] justify-between"
                >
                  {itemsPerPage}
                  <ChevronDown
                    size={14}
                    className={`transition-transform duration-200 ${showItemsMenu ? "rotate-180" : ""}`}
                  />
                </div>

                {showItemsMenu ? (
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
                ) : null}
              </div>

              <div className="flex items-center gap-2 ml-4">
                <button
                  onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                  disabled={currentPage === 1}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === 1
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronLeft size={16} />
                </button>

                {getPageNumbers().map((page) => (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold transition-all shadow-sm ${
                      currentPage === page
                        ? "bg-[#ccff33] text-black"
                        : "text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    {page}
                  </button>
                ))}

                <button
                  onClick={() =>
                    setCurrentPage((prev) => Math.min(totalPages || 1, prev + 1))
                  }
                  disabled={currentPage === totalPages || totalPages === 0}
                  className={`w-6 h-6 flex items-center justify-center transition-colors ${
                    currentPage === totalPages || totalPages === 0
                      ? "text-gray-300 cursor-not-allowed"
                      : "text-gray-400 hover:text-gray-600"
                  }`}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {isCameraModalOpen ? (
        <CameraModal
          onClose={closeCameraModal}
          onSave={handleSaveCamera}
          initialData={selectedCamera}
          isClosing={isCameraModalClosing}
        />
      ) : null}

      {isDeleteModalOpen ? (
        <DeleteModal
          onClose={closeDeleteModal}
          onConfirm={handleDeleteCamera}
          isClosing={isDeleteModalClosing}
          title="Excluir Câmera?"
          description="Essa ação remove a câmera cadastrada do sistema. Esta ação não pode ser desfeita."
          confirmLabel="Excluir câmera"
        />
      ) : null}

      {isDetailsModalOpen && detailsCamera ? (
        <CameraDetailsModal
          camera={detailsCamera}
          latestCameraImage={latestCameraImage}
          isLoadingLatest={isLoadingLatestImage}
          isClosing={isDetailsModalClosing}
          onClose={closeDetailsModal}
        />
      ) : null}
    </div>
  );
};
