import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Download,
  Loader2,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { getCameras, type Camera } from "../services/cameraService";
import {
  createImageExport,
  deleteImageExport,
  listImageExports,
  type ImageExport,
  type ImageExportStatus,
} from "../services/imageExportService";
import { formatDateTimeBrazil } from "../utils/datetime";

const MAX_DAYS = 7;
const POLL_INTERVAL_MS = 5000;

function getDefaultRange() {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const end = new Date(now);
  end.setHours(23, 59, 0, 0);
  const fmt = (d: Date) => {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const HH = String(d.getHours()).padStart(2, "0");
    const MM = String(d.getMinutes()).padStart(2, "0");
    return { date: `${yyyy}-${mm}-${dd}`, time: `${HH}:${MM}` };
  };
  return {
    startDate: fmt(start).date,
    startTime: "00:00",
    endDate: fmt(end).date,
    endTime: "23:59",
  };
}

function rangeInDays(startISO: string, endISO: string): number {
  const start = new Date(startISO).getTime();
  const end = new Date(endISO).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
  return (end - start) / (1000 * 60 * 60 * 24);
}

function buildIsoLocal(date: string, time: string): string {
  if (!date) return "";
  const hhmm = (time || "00:00").length === 5 ? `${time}:00` : time || "00:00:00";
  return `${date}T${hhmm}`;
}

function StatusBadge({ status }: { status: ImageExportStatus }) {
  const map: Record<ImageExportStatus, { label: string; cls: string; icon: React.ReactNode }> = {
    pending: {
      label: "Aguardando",
      cls: "bg-gray-100 text-gray-600",
      icon: <Clock size={12} />,
    },
    running: {
      label: "Gerando",
      cls: "bg-blue-100 text-blue-700",
      icon: <Loader2 size={12} className="animate-spin" />,
    },
    ready: {
      label: "Pronto",
      cls: "bg-green-100 text-green-700",
      icon: <CheckCircle2 size={12} />,
    },
    failed: {
      label: "Falhou",
      cls: "bg-red-100 text-red-700",
      icon: <XCircle size={12} />,
    },
    expired: {
      label: "Expirado",
      cls: "bg-yellow-100 text-yellow-700",
      icon: <AlertCircle size={12} />,
    },
  };
  const info = map[status] ?? map.pending;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold ${info.cls}`}
    >
      {info.icon}
      {info.label}
    </span>
  );
}

export const ImageExportTab: React.FC = () => {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(true);
  const [cameraId, setCameraId] = useState<number | "">("");
  const defaults = useMemo(() => getDefaultRange(), []);
  const [startDate, setStartDate] = useState(defaults.startDate);
  const [startTime, setStartTime] = useState(defaults.startTime);
  const [endDate, setEndDate] = useState(defaults.endDate);
  const [endTime, setEndTime] = useState(defaults.endTime);
  const [includeOcc, setIncludeOcc] = useState(true);
  const [includeNonOcc, setIncludeNonOcc] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [exports, setExports] = useState<ImageExport[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setCamerasLoading(true);
      try {
        const data = await getCameras({ limit: 500 });
        if (!cancelled) {
          const sorted = [...data].sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
          setCameras(sorted);
        }
      } catch (e) {
        console.error("Falha ao listar câmeras", e);
      } finally {
        if (!cancelled) setCamerasLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const data = await listImageExports(50);
      setExports(data);
    } catch (e) {
      console.error("Falha ao listar exportações", e);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setListLoading(true);
      await refreshList();
      if (!cancelled) setListLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshList]);

  // Polling while any export is pending/running.
  useEffect(() => {
    const hasActive = exports.some(
      (e) => e.status === "pending" || e.status === "running",
    );
    if (!hasActive) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current !== null) return;
    pollRef.current = window.setInterval(() => {
      refreshList();
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [exports, refreshList]);

  const startIso = buildIsoLocal(startDate, startTime);
  const endIso = buildIsoLocal(endDate, endTime);
  const days = rangeInDays(startIso, endIso);
  const rangeError = (() => {
    if (!startDate || !endDate) return "Selecione data e hora de início e fim";
    if (days <= 0) return "Fim deve ser posterior ao início";
    if (days > MAX_DAYS) return `Intervalo máximo de ${MAX_DAYS} dias por exportação`;
    if (!includeOcc && !includeNonOcc)
      return "Selecione pelo menos um tipo de imagem";
    return null;
  })();

  const canSubmit = cameraId !== "" && !rangeError && !submitting;

  const handleSubmit = async () => {
    if (cameraId === "" || rangeError) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createImageExport({
        camera_id: Number(cameraId),
        start_at: new Date(startIso).toISOString(),
        end_at: new Date(endIso).toISOString(),
        include_occurrences: includeOcc,
        include_non_occurrences: includeNonOcc,
      });
      await refreshList();
    } catch (e) {
      const detail =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (e as any)?.response?.data?.detail || "Erro ao criar exportação";
      setSubmitError(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Remover esta exportação? O ZIP será apagado do S3.")) return;
    try {
      await deleteImageExport(id);
      await refreshList();
    } catch (e) {
      console.error("Falha ao remover exportação", e);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-6 mb-8">
      <h2 className="text-lg font-bold text-gray-800 mb-1">
        Exportar Imagens da Câmera
      </h2>
      <p className="text-sm text-gray-500 mb-6">
        Solicite o ZIP com todas as imagens capturadas (com e sem ocorrência) por uma câmera em um intervalo de até {MAX_DAYS} dias.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <label className="flex flex-col">
          <span className="text-xs font-semibold text-gray-600 mb-1">Câmera</span>
          <select
            className="h-11 border border-gray-200 rounded-lg px-3 text-sm bg-white"
            value={cameraId}
            onChange={(e) =>
              setCameraId(e.target.value === "" ? "" : Number(e.target.value))
            }
            disabled={camerasLoading}
          >
            <option value="">
              {camerasLoading ? "Carregando câmeras..." : "Selecione uma câmera"}
            </option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id} disabled={!c.device_id}>
                {c.name}
                {c.device_id ? ` (${c.device_id})` : " (sem device_id)"}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-end gap-6">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeOcc}
              onChange={(e) => setIncludeOcc(e.target.checked)}
            />
            Com ocorrência
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeNonOcc}
              onChange={(e) => setIncludeNonOcc(e.target.checked)}
            />
            Sem ocorrência
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
        <label className="flex flex-col">
          <span className="text-xs font-semibold text-gray-600 mb-1">Data início</span>
          <input
            type="date"
            className="h-11 border border-gray-200 rounded-lg px-3 text-sm"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </label>
        <label className="flex flex-col">
          <span className="text-xs font-semibold text-gray-600 mb-1">Hora início</span>
          <input
            type="time"
            className="h-11 border border-gray-200 rounded-lg px-3 text-sm"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
          />
        </label>
        <label className="flex flex-col">
          <span className="text-xs font-semibold text-gray-600 mb-1">Data fim</span>
          <input
            type="date"
            className="h-11 border border-gray-200 rounded-lg px-3 text-sm"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </label>
        <label className="flex flex-col">
          <span className="text-xs font-semibold text-gray-600 mb-1">Hora fim</span>
          <input
            type="time"
            className="h-11 border border-gray-200 rounded-lg px-3 text-sm"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
          />
        </label>
      </div>

      {rangeError && (
        <p className="text-xs text-amber-700 mb-3">{rangeError}</p>
      )}
      {submitError && (
        <p className="text-xs text-red-700 mb-3">{submitError}</p>
      )}

      <div className="flex items-center justify-between gap-3 mb-8">
        <span className="text-xs text-gray-500">
          {days > 0 ? `Intervalo selecionado: ~${days.toFixed(1)} dia(s)` : ""}
        </span>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={`h-11 px-5 rounded-lg font-semibold text-sm flex items-center gap-2 transition-colors ${
            canSubmit
              ? "bg-[#1a1a1a] text-white hover:bg-black"
              : "bg-gray-200 text-gray-400 cursor-not-allowed"
          }`}
        >
          {submitting && <Loader2 size={14} className="animate-spin" />}
          Solicitar exportação
        </button>
      </div>

      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-gray-800 text-sm">Exportações recentes</h3>
        <button
          onClick={() => refreshList()}
          className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-800"
        >
          <RefreshCw size={12} />
          Atualizar
        </button>
      </div>

      <div className="overflow-x-auto border border-gray-100 rounded-xl">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs text-gray-600 uppercase">
            <tr>
              <th className="px-4 py-3 font-semibold">Câmera</th>
              <th className="px-4 py-3 font-semibold">Período</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Progresso</th>
              <th className="px-4 py-3 font-semibold">Imagens</th>
              <th className="px-4 py-3 font-semibold text-right">Ação</th>
            </tr>
          </thead>
          <tbody>
            {listLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                  Carregando...
                </td>
              </tr>
            ) : exports.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                  Nenhuma exportação solicitada ainda.
                </td>
              </tr>
            ) : (
              exports.map((exp) => (
                <tr key={exp.id} className="border-t border-gray-100">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-800">
                      {exp.camera_name || `Câmera ${exp.camera_id}`}
                    </div>
                    {exp.camera_device_id && (
                      <div className="text-xs text-gray-500">{exp.camera_device_id}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    <div>{formatDateTimeBrazil(exp.start_at)}</div>
                    <div className="text-xs text-gray-500">
                      até {formatDateTimeBrazil(exp.end_at)}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={exp.status} />
                    {exp.status === "failed" && exp.error_message && (
                      <div className="text-xs text-red-700 mt-1 max-w-xs truncate" title={exp.error_message}>
                        {exp.error_message}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-700 min-w-[120px]">
                    <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                      <div
                        className="h-2 bg-[#65a30d] transition-all"
                        style={{ width: `${exp.progress}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500">{exp.progress}%</span>
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {exp.total_images ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {exp.status === "ready" && exp.download_url ? (
                      <a
                        href={exp.download_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-[#e9fbc0] text-[#1a1a1a] text-xs font-semibold hover:bg-[#d6f48a]"
                      >
                        <Download size={12} />
                        Baixar
                      </a>
                    ) : (
                      <button
                        onClick={() => handleDelete(exp.id)}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-gray-100 text-gray-600 text-xs font-semibold hover:bg-gray-200"
                        title="Remover"
                      >
                        <Trash2 size={12} />
                        Remover
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
