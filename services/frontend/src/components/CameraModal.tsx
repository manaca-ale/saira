import React, { useEffect, useState } from "react";
import { AlertCircle, Camera, Clock3, MapPin, Radio, X } from "lucide-react";
import type { Camera as CameraEntity } from "../services/cameraService";
import type { GeocodingResult } from "../types/geocoding";
import { AddressSearch } from "./AddressSearch";
import { CameraMapPicker } from "./CameraMapPicker";

interface CameraModalProps {
  onClose: () => void;
  onSave: (data: CameraFormData) => void | Promise<void>;
  initialData?: CameraEntity | null;
  isClosing: boolean;
}

export interface CameraFormData {
  name: string;
  device_id: string;
  logradouro: string;
  bairro: string;
  rpa: string;
  latitude: string;
  longitude: string;
  rtsp_url: string;
  capture_interval_seconds: string;
  is_active: boolean;
}

const Field: React.FC<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  icon?: React.ElementType;
  type?: string;
  required?: boolean;
}> = ({
  label,
  value,
  onChange,
  placeholder,
  icon: Icon,
  type = "text",
  required = false,
}) => (
  <div className="flex flex-col gap-1.5 w-full">
    <label className="text-sm font-bold text-gray-700 select-none ml-1">
      {label}
      {required ? " *" : ""}
    </label>
    <div className="relative">
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] placeholder-gray-400 outline-none focus:bg-white focus:border-gray-300 transition-all"
      />
      {Icon ? (
        <Icon className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
      ) : null}
    </div>
  </div>
);

export const CameraModal: React.FC<CameraModalProps> = ({
  onClose,
  onSave,
  initialData,
  isClosing,
}) => {
  const [formData, setFormData] = useState<CameraFormData>({
    name: "",
    device_id: "",
    logradouro: "",
    bairro: "",
    rpa: "",
    latitude: "",
    longitude: "",
    rtsp_url: "",
    capture_interval_seconds: "30",
    is_active: true,
  });
  const [formError, setFormError] = useState("");

  useEffect(() => {
    if (!initialData) {
      setFormData({
        name: "",
        device_id: "",
        logradouro: "",
        bairro: "",
        rpa: "",
        latitude: "",
        longitude: "",
        rtsp_url: "",
        capture_interval_seconds: "30",
        is_active: true,
      });
      setFormError("");
      return;
    }

    setFormData({
      name: initialData.name || "",
      device_id: initialData.device_id || "",
      logradouro: initialData.logradouro || "",
      bairro: initialData.bairro || "",
      rpa: initialData.rpa || "",
      latitude: String(initialData.latitude ?? ""),
      longitude: String(initialData.longitude ?? ""),
      rtsp_url: initialData.rtsp_url || "",
      capture_interval_seconds: String(initialData.capture_interval_seconds ?? 30),
      is_active: Boolean(initialData.is_active),
    });
    setFormError("");
  }, [initialData]);

  const handleAddressSelect = (result: GeocodingResult) => {
    setFormData((prev) => ({
      ...prev,
      latitude: result.latitude.toFixed(8),
      longitude: result.longitude.toFixed(8),
      logradouro: result.logradouro ?? prev.logradouro,
      bairro: result.bairro ?? prev.bairro,
    }));
    setFormError("");
  };

  const handleMapPositionChange = (lat: number, lng: number) => {
    setFormData((prev) => ({
      ...prev,
      latitude: lat.toFixed(8),
      longitude: lng.toFixed(8),
    }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError("");

    const latitude = Number(formData.latitude);
    const longitude = Number(formData.longitude);
    const captureInterval = Number(formData.capture_interval_seconds);

    if (!formData.name.trim()) {
      setFormError("O nome da câmera é obrigatório.");
      return;
    }
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
      setFormError("Latitude inválida. Use um valor entre -90 e 90.");
      return;
    }
    if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
      setFormError("Longitude inválida. Use um valor entre -180 e 180.");
      return;
    }
    if (!Number.isInteger(captureInterval) || captureInterval < 1) {
      setFormError("Intervalo de captura deve ser um número inteiro maior que 0.");
      return;
    }

    try {
      await onSave(formData);
    } catch (error: any) {
      setFormError(error?.message || "Não foi possível salvar a câmera.");
    }
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
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-3xl p-8 relative overflow-y-auto max-h-[90vh]"
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
          {initialData ? "Editar Câmera" : "Nova Câmera"}
        </h2>
        <p className="text-gray-500 text-sm mb-8 select-none">
          Preencha os dados da câmera para cadastro e monitoramento.
        </p>

        {formError ? (
          <div className="mb-5 flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl">
            <AlertCircle size={18} className="text-red-500 shrink-0" />
            <span className="text-sm text-red-700">{formError}</span>
          </div>
        ) : null}

        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Field
              label="Nome"
              value={formData.name}
              onChange={(value) => setFormData((prev) => ({ ...prev, name: value }))}
              placeholder="Ex: Câmera Ponte da Madalena"
              icon={Camera}
              required
            />
            <Field
              label="Device ID"
              value={formData.device_id}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, device_id: value }))
              }
              placeholder="Ex: esp32_002"
              icon={Radio}
            />

            <AddressSearch
              value={formData.logradouro}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, logradouro: value }))
              }
              onSelect={handleAddressSelect}
            />
            <Field
              label="Bairro"
              value={formData.bairro}
              onChange={(value) => setFormData((prev) => ({ ...prev, bairro: value }))}
              placeholder="Ex: Boa Vista"
              icon={MapPin}
            />
            <Field
              label="RPA"
              value={formData.rpa}
              onChange={(value) => setFormData((prev) => ({ ...prev, rpa: value }))}
              placeholder="Ex: RPA-1"
              icon={MapPin}
            />
            <Field
              label="URL RTSP"
              value={formData.rtsp_url}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, rtsp_url: value }))
              }
              placeholder="rtsp://..."
            />
            <Field
              label="Latitude"
              value={formData.latitude}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, latitude: value }))
              }
              placeholder="-8.05389"
              type="number"
              required
            />
            <Field
              label="Longitude"
              value={formData.longitude}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, longitude: value }))
              }
              placeholder="-34.88111"
              type="number"
              required
            />
            <Field
              label="Intervalo de captura (segundos)"
              value={formData.capture_interval_seconds}
              onChange={(value) =>
                setFormData((prev) => ({
                  ...prev,
                  capture_interval_seconds: value,
                }))
              }
              placeholder="30"
              type="number"
              icon={Clock3}
              required
            />
            <div className="flex flex-col gap-1.5 w-full">
              <label className="text-sm font-bold text-gray-700 select-none ml-1">
                Status
              </label>
              <button
                type="button"
                onClick={() =>
                  setFormData((prev) => ({ ...prev, is_active: !prev.is_active }))
                }
                className={`h-[50px] rounded-xl font-semibold transition-colors ${
                  formData.is_active
                    ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                    : "bg-gray-200 text-gray-600 hover:bg-gray-300"
                }`}
              >
                {formData.is_active ? "Ativa" : "Inativa"}
              </button>
            </div>
          </div>

          <CameraMapPicker
            latitude={formData.latitude ? parseFloat(formData.latitude) : null}
            longitude={formData.longitude ? parseFloat(formData.longitude) : null}
            onPositionChange={handleMapPositionChange}
          />

          <div className="flex justify-end gap-3 mt-2 pt-4 border-t border-gray-100">
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
              Salvar Câmera
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
