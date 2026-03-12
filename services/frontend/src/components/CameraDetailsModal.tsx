import React from "react";
import { Activity, CalendarClock, Camera, ImageOff, MapPin, Radio, X } from "lucide-react";
import type { Camera as CameraEntity, CameraLatestImage } from "../services/cameraService";
import { formatDateTimeBrazil } from "../utils/datetime";

interface CameraDetailsModalProps {
  camera: CameraEntity;
  latestCameraImage: CameraLatestImage | null;
  isLoadingLatest: boolean;
  isClosing: boolean;
  onClose: () => void;
}

const formatDateTime = (value?: string | null): string => {
  const formatted = formatDateTimeBrazil(value, {
    dateStyle: "short",
    timeStyle: "short",
  });
  return formatted === "—" ? "Sem registro" : formatted;
};

export const CameraDetailsModal: React.FC<CameraDetailsModalProps> = ({
  camera,
  latestCameraImage,
  isLoadingLatest,
  isClosing,
  onClose,
}) => {
  const lastCommunication =
    camera.last_capture_at || latestCameraImage?.captured_at || camera.updated_at;

  return (
    <div
      className={`
        fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4
        transition-opacity duration-500
        ${isClosing ? "opacity-0" : "opacity-100"}
      `}
    >
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-4xl p-8 relative overflow-hidden"
        style={{
          animation: isClosing
            ? "modalPopExit 0.5s ease-in forwards"
            : "modalPop 0.5s ease-out forwards",
        }}
      >
        <button
          onClick={onClose}
          className="absolute top-6 right-6 text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Fechar"
        >
          <X size={24} />
        </button>

        <h2 className="text-2xl font-bold text-[#1a1a1a] mb-1 select-none">
          Detalhes da Câmera
        </h2>
        <p className="text-gray-500 text-sm mb-8 select-none">
          Visualize status operacional, última comunicação e última foto recebida.
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-2xl border border-gray-200 bg-gray-50 overflow-hidden min-h-[280px]">
            {isLoadingLatest ? (
              <div className="w-full h-full min-h-[280px] flex items-center justify-center text-gray-500 gap-2">
                <Activity size={16} className="animate-spin" />
                Carregando última imagem...
              </div>
            ) : latestCameraImage?.image_url ? (
              <img
                src={latestCameraImage.image_url}
                alt={`Última foto da câmera ${camera.name}`}
                className="w-full h-full min-h-[280px] object-cover"
              />
            ) : (
              <div className="w-full h-full min-h-[280px] flex flex-col items-center justify-center text-gray-500 gap-2">
                <ImageOff size={22} />
                <span>Sem foto disponível para esta câmera</span>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xl font-bold text-[#1a1a1a]">{camera.name}</h3>
                <p className="text-sm text-gray-500">ID #{camera.id}</p>
              </div>
              <span
                className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold ${
                  camera.is_active
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-gray-200 text-gray-600"
                }`}
              >
                <Activity size={14} />
                {camera.is_active ? "Ativa" : "Inativa"}
              </span>
            </div>

            <div className="space-y-3 text-sm text-gray-700">
              <div className="flex items-start gap-2">
                <Radio size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Device ID:</span>{" "}
                  {camera.device_id || "Não informado"}
                </div>
              </div>
              <div className="flex items-start gap-2">
                <CalendarClock size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Última comunicação:</span>{" "}
                  {formatDateTime(lastCommunication)}
                </div>
              </div>
              <div className="flex items-start gap-2">
                <Camera size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Última captura:</span>{" "}
                  {formatDateTime(camera.last_capture_at)}
                </div>
              </div>
              <div className="flex items-start gap-2">
                <MapPin size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Local:</span>{" "}
                  {[camera.logradouro, camera.bairro, camera.rpa]
                    .filter(Boolean)
                    .join(" - ") || "Não informado"}
                </div>
              </div>
              <div className="flex items-start gap-2">
                <MapPin size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Coordenadas:</span>{" "}
                  {camera.latitude}, {camera.longitude}
                </div>
              </div>
              <div className="flex items-start gap-2">
                <Activity size={16} className="mt-0.5 text-gray-500 shrink-0" />
                <div>
                  <span className="font-semibold">Intervalo de captura:</span>{" "}
                  {camera.capture_interval_seconds}s
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
