import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  CheckCircle2,
  SkipForward,
  HelpCircle,
  MapPin,
  Camera as CameraIcon,
  Clock,
} from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import {
  getDetectionAnalyzedFrames,
  searchDetections,
} from "../services/detectionService";
import type {
  DetectionAnalyzedFrame,
  PoiData,
} from "../services/detectionService";
import {
  addDetectionOffender,
  getDetectionOffenders,
  offenderTypeLabel,
  OFFENDER_TYPE_OPTIONS,
} from "../services/offenderService";
import type { OffenderType } from "../services/offenderService";
import { formatDateTimeBrazil } from "../utils/datetime";

// Atalhos 1..6 seguem a ordem canônica de OFFENDER_TYPE_OPTIONS.
const TYPE_SHORTCUTS = OFFENDER_TYPE_OPTIONS.map((opt, i) => ({
  ...opt,
  key: String(i + 1),
}));

const UNIDENTIFIABLE_NOTE = "[rotulagem] não identificável";
const QUEUE_PAGE_SIZE = 20;

interface QueueItem extends PoiData {
  aiTypes: string[];
  frames: DetectionAnalyzedFrame[];
}

export const LabelingPage: React.FC = () => {
  const navigate = useNavigate();

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<OffenderType[]>([]);
  const [plate, setPlate] = useState("");
  const [notes, setNotes] = useState("");
  const [frameIndex, setFrameIndex] = useState(0);
  const [progress, setProgress] = useState({ labeled: 0, total: 0 });

  // Itens pulados nesta sessão continuam na fila do servidor; o set evita
  // que voltem a aparecer antes de um reload da página.
  const skippedRef = useRef<Set<string>>(new Set());

  const current = queue[0] ?? null;
  const frames = current?.frames ?? [];
  const hasFrames = frames.length > 0;

  const loadProgress = useCallback(async () => {
    try {
      const [all, labeled] = await Promise.all([
        searchDetections({ status: "Confirmado", limit: 1 }),
        searchDetections({
          status: "Confirmado",
          has_manual_offender: true,
          limit: 1,
        }),
      ]);
      setProgress({ labeled: labeled.total, total: all.total });
    } catch (e) {
      console.error("Erro ao carregar progresso:", e);
    }
  }, []);

  /** Busca a próxima página da fila e hidrata frames + sugestão da IA. */
  const fetchQueue = useCallback(async (): Promise<QueueItem[]> => {
    const page = await searchDetections({
      status: "Confirmado",
      has_manual_offender: false,
      limit: QUEUE_PAGE_SIZE,
      sort_by: "timestamp",
      sort_order: "asc",
    });

    const pending = page.items.filter((d) => !skippedRef.current.has(d.id));

    return Promise.all(
      pending.map(async (item) => {
        const [framesResponse, links] = await Promise.all([
          getDetectionAnalyzedFrames(item.id).catch(() => null),
          getDetectionOffenders(item.id).catch(() => []),
        ]);
        return {
          ...item,
          aiTypes: Array.from(
            new Set(
              links.filter((l) => l.source === "ai").map((l) => l.offender_type),
            ),
          ),
          frames: framesResponse?.frames?.length
            ? framesResponse.frames
            : item.photoUrl
              ? [{ frame_name: "", image_url: item.photoUrl, is_default: true }]
              : [],
        };
      }),
    );
  }, []);

  const refillQueue = useCallback(async () => {
    setLoading(true);
    try {
      setQueue(await fetchQueue());
      setError(null);
    } catch (e) {
      console.error("Erro ao carregar fila:", e);
      setError("Não foi possível carregar a fila de rotulagem.");
    } finally {
      setLoading(false);
    }
  }, [fetchQueue]);

  useEffect(() => {
    refillQueue();
    loadProgress();
  }, [refillQueue, loadProgress]);

  // Sugestão da IA pré-selecionada + reset do formulário a cada item.
  useEffect(() => {
    if (!current) return;
    setSelected(current.aiTypes as OffenderType[]);
    setPlate("");
    setNotes("");
    const defaultIdx = current.frames.findIndex((f) => f.is_default);
    setFrameIndex(defaultIdx >= 0 ? defaultIdx : 0);
  }, [current]);

  // Pré-carrega o frame default do próximo item enquanto o atual é rotulado.
  useEffect(() => {
    const next = queue[1];
    if (!next) return;
    const frame = next.frames.find((f) => f.is_default) ?? next.frames[0];
    if (frame) new Image().src = frame.image_url;
  }, [queue]);

  const advance = useCallback(() => {
    setQueue((prev) => {
      const rest = prev.slice(1);
      if (rest.length === 0) {
        // Fila local esgotada: busca a próxima página do servidor.
        fetchQueue()
          .then(setQueue)
          .catch((e) => console.error("Erro ao recarregar fila:", e));
      }
      return rest;
    });
  }, [fetchQueue]);

  const toggleType = useCallback((type: OffenderType) => {
    setSelected((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }, []);

  const saveLabels = useCallback(
    async (types: OffenderType[], noteOverride?: string) => {
      if (!current || types.length === 0) return;
      const detectionId = current.id;
      setSaving(true);
      try {
        // Placa/observações só na primeira linha — as demais são o mesmo evento.
        await Promise.all(
          types.map((type, i) =>
            addDetectionOffender(detectionId, {
              offender_type: type,
              ...(i === 0 && plate.trim() ? { plate: plate.trim() } : {}),
              ...(i === 0 && (noteOverride ?? notes.trim())
                ? { notes: noteOverride ?? notes.trim() }
                : {}),
            }),
          ),
        );
        setProgress((p) => ({ ...p, labeled: p.labeled + 1 }));
        setError(null);
        advance();
      } catch (e) {
        console.error("Erro ao salvar rótulo:", e);
        setError("Falha ao salvar o rótulo. Tente novamente.");
      } finally {
        setSaving(false);
      }
    },
    [current, plate, notes, advance],
  );

  const handleSkip = useCallback(() => {
    if (!current) return;
    skippedRef.current.add(current.id);
    advance();
  }, [current, advance]);

  const handleUnidentifiable = useCallback(() => {
    saveLabels(["Outro"], UNIDENTIFIABLE_NOTE);
  }, [saveLabels]);

  const goToFrame = useCallback(
    (idx: number) => {
      if (!hasFrames) return;
      setFrameIndex(Math.max(0, Math.min(frames.length - 1, idx)));
    },
    [hasFrames, frames.length],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (!current || saving) return;

      const shortcut = TYPE_SHORTCUTS.find((s) => s.key === e.key);
      if (shortcut) {
        e.preventDefault();
        toggleType(shortcut.value);
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goToFrame(frameIndex - 1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goToFrame(frameIndex + 1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        saveLabels(selected);
      } else if (e.key.toLowerCase() === "s") {
        e.preventDefault();
        handleSkip();
      } else if (e.key === "0") {
        e.preventDefault();
        handleUnidentifiable();
      } else if (e.key === "Escape") {
        navigate("/detections");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    current,
    saving,
    selected,
    frameIndex,
    toggleType,
    goToFrame,
    saveLabels,
    handleSkip,
    handleUnidentifiable,
    navigate,
  ]);

  const progressPct = useMemo(
    () =>
      progress.total > 0
        ? Math.round((progress.labeled / progress.total) * 100)
        : 0,
    [progress],
  );

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans">
      <Sidebar />
      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto">
        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-3xl font-bold text-[#1a1a1a]">
              Rotulagem de tipo de descarte
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Ocorrências confirmadas sem rótulo humano. Use o teclado para
              rotular rápido.
            </p>
          </div>
          <div className="w-64">
            <div className="flex justify-between text-xs text-gray-500 font-bold mb-1">
              <span>Progresso</span>
              <span>
                {progress.labeled} de {progress.total}
              </span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-[#ccff33] transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-96">
            <Loader2 size={32} className="animate-spin text-lime-500" />
          </div>
        ) : !current ? (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-12 flex flex-col items-center justify-center text-center">
            <CheckCircle2 size={48} className="text-lime-500 mb-4" />
            <h2 className="text-xl font-bold text-[#1a1a1a] mb-2">
              Fila vazia
            </h2>
            <p className="text-gray-500 text-sm max-w-md">
              Todas as ocorrências confirmadas já têm rótulo humano de tipo de
              descarte.
            </p>
            <button
              onClick={() => navigate("/detections")}
              className="mt-6 h-10 px-5 bg-[#ccff33] hover:bg-[#bef026] text-[#1a1a1a] font-bold rounded-xl text-sm transition-colors"
            >
              Voltar para Detecções
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            {/* Painel de frames */}
            <div className="lg:col-span-3 bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
              <div className="relative bg-[#1a1a1a] rounded-xl overflow-hidden flex items-center justify-center h-[420px]">
                {hasFrames ? (
                  <>
                    <img
                      src={frames[frameIndex]?.image_url}
                      alt={`Frame ${frameIndex + 1}`}
                      className="max-h-full max-w-full object-contain"
                    />
                    {frames.length > 1 && (
                      <>
                        <button
                          onClick={() => goToFrame(frameIndex - 1)}
                          disabled={frameIndex === 0}
                          className="absolute left-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 text-white flex items-center justify-center hover:bg-black/70 disabled:opacity-30 transition-colors"
                          aria-label="Frame anterior"
                        >
                          <ChevronLeft size={20} />
                        </button>
                        <button
                          onClick={() => goToFrame(frameIndex + 1)}
                          disabled={frameIndex === frames.length - 1}
                          className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 text-white flex items-center justify-center hover:bg-black/70 disabled:opacity-30 transition-colors"
                          aria-label="Próximo frame"
                        >
                          <ChevronRight size={20} />
                        </button>
                        <span className="absolute bottom-3 right-3 px-2 py-1 rounded-md bg-black/60 text-white text-xs font-bold">
                          {frameIndex + 1} / {frames.length}
                        </span>
                      </>
                    )}
                  </>
                ) : (
                  <span className="text-gray-400 text-sm">
                    Sem imagem disponível
                  </span>
                )}
              </div>

              {frames.length > 1 && (
                <div className="flex gap-2 mt-3 overflow-x-auto pb-1">
                  {frames.map((frame, i) => (
                    <button
                      key={`${frame.frame_name}-${i}`}
                      onClick={() => goToFrame(i)}
                      className={`flex-shrink-0 w-20 h-14 rounded-lg overflow-hidden border-2 transition-all ${
                        i === frameIndex
                          ? "border-[#ccff33]"
                          : "border-transparent opacity-60 hover:opacity-100"
                      }`}
                    >
                      <img
                        src={frame.image_url}
                        alt={`Miniatura ${i + 1}`}
                        className="w-full h-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Painel de rotulagem */}
            <div className="lg:col-span-2 bg-white rounded-2xl border border-gray-100 shadow-sm p-5 flex flex-col gap-5">
              <div className="space-y-2 text-sm">
                <div className="flex items-start gap-2 text-gray-700">
                  <MapPin size={15} className="text-gray-400 mt-0.5 flex-shrink-0" />
                  <span className="font-bold">
                    {current.logradouro || "—"}
                    {current.bairro ? ` · ${current.bairro}` : ""}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-gray-500">
                  <CameraIcon size={15} className="text-gray-400 flex-shrink-0" />
                  <span>{current.cameraName || current.cameraDeviceId || "—"}</span>
                </div>
                <div className="flex items-center gap-2 text-gray-500">
                  <Clock size={15} className="text-gray-400 flex-shrink-0" />
                  <span>{formatDateTimeBrazil(current.timestamp)}</span>
                </div>
              </div>

              <div>
                <span className="block text-gray-400 text-xs mb-2">
                  Sugestão da IA
                </span>
                {current.aiTypes.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {current.aiTypes.map((type) => (
                      <span
                        key={type}
                        className="px-2 py-0.5 rounded-full bg-purple-100 text-purple-600 text-xs font-bold"
                      >
                        {offenderTypeLabel(type)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-gray-400">Nenhuma</span>
                )}
              </div>

              <div>
                <span className="block text-gray-400 text-xs mb-2">
                  Tipo de descarte
                </span>
                <div className="grid grid-cols-2 gap-2">
                  {TYPE_SHORTCUTS.map((opt) => {
                    const isSelected = selected.includes(opt.value);
                    return (
                      <button
                        key={opt.value}
                        onClick={() => toggleType(opt.value)}
                        className={`h-11 px-3 rounded-xl border text-sm font-bold flex items-center justify-between transition-colors ${
                          isSelected
                            ? "bg-[#ccff33] border-[#ccff33] text-[#1a1a1a]"
                            : "bg-white border-gray-200 text-gray-600 hover:border-gray-300"
                        }`}
                      >
                        {opt.label}
                        <kbd
                          className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                            isSelected
                              ? "bg-[#1a1a1a]/10 text-[#1a1a1a]"
                              : "bg-gray-100 text-gray-400"
                          }`}
                        >
                          {opt.key}
                        </kbd>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3">
                <div>
                  <label className="block text-gray-400 text-xs mb-1">
                    Placa (opcional)
                  </label>
                  <input
                    type="text"
                    value={plate}
                    onChange={(e) => setPlate(e.target.value.toUpperCase())}
                    placeholder="ABC-1234"
                    maxLength={20}
                    className="w-full h-10 px-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-lime-400"
                  />
                </div>
                <div>
                  <label className="block text-gray-400 text-xs mb-1">
                    Observações (opcional)
                  </label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                    className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm resize-none focus:outline-none focus:ring-2 focus:ring-lime-400"
                  />
                </div>
              </div>

              <div className="mt-auto space-y-2">
                <button
                  onClick={() => saveLabels(selected)}
                  disabled={selected.length === 0 || saving}
                  className="w-full h-11 bg-[#ccff33] hover:bg-[#bef026] disabled:bg-gray-100 disabled:text-gray-400 text-[#1a1a1a] font-bold rounded-xl text-sm flex items-center justify-center gap-2 transition-colors"
                >
                  {saving ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={16} />
                  )}
                  Salvar e próxima
                  <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-[#1a1a1a]/10 font-mono">
                    ⏎
                  </kbd>
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={handleSkip}
                    disabled={saving}
                    className="flex-1 h-10 border border-gray-200 text-gray-600 hover:bg-gray-50 font-bold rounded-xl text-sm flex items-center justify-center gap-2 transition-colors"
                  >
                    <SkipForward size={14} />
                    Pular
                    <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 font-mono">
                      S
                    </kbd>
                  </button>
                  <button
                    onClick={handleUnidentifiable}
                    disabled={saving}
                    className="flex-1 h-10 border border-gray-200 text-gray-600 hover:bg-gray-50 font-bold rounded-xl text-sm flex items-center justify-center gap-2 transition-colors"
                  >
                    <HelpCircle size={14} />
                    Não identificável
                    <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 font-mono">
                      0
                    </kbd>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
