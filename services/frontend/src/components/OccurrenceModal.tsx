import React, { useState, useRef, useEffect } from "react";
import { jsPDF } from "jspdf";
import { X, Download, Image as ImageIcon, FileText, Loader2, MapPin, CheckCircle, Clock, UserPlus, Trash2 as UnlinkIcon, ChevronLeft, ChevronRight, Maximize2 } from "lucide-react";
import JSZip from "jszip";
import imgLixo from "../assets/lixo_exemplo.png";
import imgInfrator from "../assets/infrator_exemplo.png";
import { getDetectionOffenders, deleteDetectionOffender } from "../services/offenderService";
import type { DetectionOffenderLink } from "../services/offenderService";
import { getDetectionAnalyzedFrames, updateDetectionImage } from "../services/detectionService";
import type { DetectionAnalyzedFrame } from "../services/detectionService";
import { AddDetectionOffenderModal } from "./AddDetectionOffenderModal";
import { formatDateTimeBrazil } from "../utils/datetime";

interface OccurrenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
  onResolve?: () => void;
  onStartAnalysis?: () => void;
  onPhotoUpdated?: (imageUrl: string) => void;
}

// --- Programmatic Canvas export (bypasses html2canvas + oklch issues) ---

const EXPORT_WIDTH = 480;
const SCALE = 2; // retina quality
const PADDING = 32;
const IMG_HEIGHT = 200;
const COLORS = {
  bg: "#ffffff",
  title: "#1a1a1a",
  label: "#9ca3af",
  value: "#374151",
  statusPendente: "#ef4444",
  statusAnalise: "#f97316",
  statusResolvido: "#22c55e",
  statusDefault: "#6b7280",
  divider: "#f3f4f6",
  infoBg: "#f9fafb",
  infoBorder: "#f3f4f6",
  accent: "#ccff33",
};

function getStatusExportColor(status: string): string {
  switch (status) {
    case "Pendente": return COLORS.statusPendente;
    case "Em análise": return COLORS.statusAnalise;
    case "Resolvido": return COLORS.statusResolvido;
    default: return COLORS.statusDefault;
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawLabel(ctx: CanvasRenderingContext2D, text: string, x: number, y: number) {
  ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.fillStyle = COLORS.label;
  ctx.fillText(text, x, y);
}

function drawValue(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color = COLORS.value, maxWidth?: number) {
  ctx.font = "bold 13px Inter, system-ui, sans-serif";
  ctx.fillStyle = color;
  if (maxWidth) {
    let display = text;
    while (ctx.measureText(display).width > maxWidth && display.length > 1) {
      display = display.slice(0, -1);
    }
    if (display !== text) display += "…";
    ctx.fillText(display, x, y);
  } else {
    ctx.fillText(text, x, y);
  }
}

async function renderExportCanvas(data: any): Promise<HTMLCanvasElement> {
  const w = EXPORT_WIDTH;
  const p = PADDING;
  const colW = (w - p * 2) / 2;

  const formattedDate = formatDateTimeBrazil(data?.timestamp);
  const photoSrc = data?.image_url || (data?.hasOffender ? imgInfrator : imgLixo);
  const volumeValue = data?.volume ?? data?.volume_m3;
  const status = data?.status || "—";

  // Pre-calculate height
  const rowH = 38;
  const rows = 6; // status+id, date, logradouro/bairro/rpa, lat/lng, tipo/vol, infratores
  const totalH = p + 30 + 12 + IMG_HEIGHT + 16 + rows * rowH + 16 + p;

  const canvas = document.createElement("canvas");
  canvas.width = w * SCALE;
  canvas.height = totalH * SCALE;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(SCALE, SCALE);

  // Background
  ctx.fillStyle = COLORS.bg;
  roundRect(ctx, 0, 0, w, totalH, 20);
  ctx.fill();
  ctx.save();
  roundRect(ctx, 0, 0, w, totalH, 20);
  ctx.clip();

  // Title
  let y = p;
  ctx.font = "bold 18px Inter, system-ui, sans-serif";
  ctx.fillStyle = COLORS.title;
  ctx.fillText("Informações da ocorrência", p, y + 18);
  y += 38;

  // Evidence image
  try {
    const img = await loadImage(photoSrc);
    const imgW = w - p * 2;
    // Draw rounded rect clip for image
    ctx.save();
    roundRect(ctx, p, y, imgW, IMG_HEIGHT, 12);
    ctx.clip();
    // Cover-fit
    const imgAspect = img.width / img.height;
    const boxAspect = imgW / IMG_HEIGHT;
    let sx = 0, sy = 0, sw = img.width, sh = img.height;
    if (imgAspect > boxAspect) {
      sw = img.height * boxAspect;
      sx = (img.width - sw) / 2;
    } else {
      sh = img.width / boxAspect;
      sy = (img.height - sh) / 2;
    }
    ctx.drawImage(img, sx, sy, sw, sh, p, y, imgW, IMG_HEIGHT);
    ctx.restore();
  } catch {
    // fallback: gray box
    ctx.fillStyle = "#e5e7eb";
    roundRect(ctx, p, y, w - p * 2, IMG_HEIGHT, 12);
    ctx.fill();
  }
  y += IMG_HEIGHT + 20;

  // Row 1: Status + ID
  drawLabel(ctx, "Status", p, y);
  drawValue(ctx, status, p, y + 16, getStatusExportColor(status));
  drawLabel(ctx, "ID", p + colW, y);
  drawValue(ctx, data?.id ?? "—", p + colW, y + 16);
  y += rowH;

  // Row 2: Data e Hora (full width)
  drawLabel(ctx, "Data e Hora", p, y);
  drawValue(ctx, formattedDate, p, y + 16);
  y += rowH;

  // Row 3: Logradouro, Bairro, RPA (3 cols)
  const col3W = (w - p * 2) / 3;
  drawLabel(ctx, "Logradouro", p, y);
  drawValue(ctx, data?.logradouro || "—", p, y + 16, COLORS.value, col3W - 8);
  drawLabel(ctx, "Bairro", p + col3W, y);
  drawValue(ctx, data?.bairro || "—", p + col3W, y + 16, COLORS.value, col3W - 8);
  drawLabel(ctx, "RPA", p + col3W * 2, y);
  drawValue(ctx, data?.rpa || "—", p + col3W * 2, y + 16);
  y += rowH;

  // Row 4: Latitude, Longitude
  drawLabel(ctx, "Latitude", p, y);
  drawValue(ctx, String(data?.latitude ?? "—"), p, y + 16);
  drawLabel(ctx, "Longitude", p + colW, y);
  drawValue(ctx, String(data?.longitude ?? "—"), p + colW, y + 16);
  y += rowH;

  // Row 5: Tipo de resíduo, Volumetria
  drawLabel(ctx, "Tipo de resíduo", p, y);
  drawValue(ctx, data?.tipo || data?.tipoResiduo || "—", p, y + 16);
  drawLabel(ctx, "Volumetria aprox.", p + colW, y);
  drawValue(ctx, `${volumeValue ?? "—"} m³`, p + colW, y + 16);
  y += rowH;

  // Row 6: Infratores (boxed)
  ctx.fillStyle = COLORS.infoBg;
  roundRect(ctx, p, y - 4, w - p * 2, rowH + 4, 8);
  ctx.fill();
  ctx.strokeStyle = COLORS.infoBorder;
  ctx.lineWidth = 1;
  roundRect(ctx, p, y - 4, w - p * 2, rowH + 4, 8);
  ctx.stroke();
  drawLabel(ctx, "Infratores", p + 10, y + 8);
  drawValue(
    ctx,
    data?.hasOffender ? "Identificados: Pessoa" : "Não identificado",
    p + 10, y + 24, COLORS.title,
  );

  ctx.restore();
  return canvas;
}

// --- Frame timestamp helpers ---
// Filenames follow the worker convention `YYYY-MM-DD_HH-MM-SS.jpg` in BRT.
function parseFrameDate(frameName?: string | null): Date | null {
  if (!frameName) return null;
  const stem = String(frameName).replace(/\.[^.]+$/, "");
  const m = stem.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  // Construct an ISO string with BRT offset (-03:00) so toLocaleString
  // renders consistently regardless of the viewer's timezone.
  const iso = `${y}-${mo}-${d}T${h}:${mi}:${s}-03:00`;
  const dt = new Date(iso);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatFrameTimestamp(frameName?: string | null): string {
  const dt = parseFrameDate(frameName);
  if (!dt) return frameName || "";
  return dt.toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatFrameTimeShort(frameName?: string | null): string {
  const dt = parseFrameDate(frameName);
  if (!dt) return "";
  return dt.toLocaleTimeString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// --- Component ---

export const OccurrenceModal: React.FC<OccurrenceModalProps> = ({
  isOpen,
  onClose,
  data,
  onResolve,
  onStartAnalysis,
  onPhotoUpdated,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [offenderLinks, setOffenderLinks] = useState<DetectionOffenderLink[]>([]);
  const [loadingOffenders, setLoadingOffenders] = useState(false);
  const [isAddOffenderOpen, setIsAddOffenderOpen] = useState(false);
  const [isFramesModalOpen, setIsFramesModalOpen] = useState(false);
  const [isConfirmFrameChangeOpen, setIsConfirmFrameChangeOpen] = useState(false);
  const [loadingFrames, setLoadingFrames] = useState(false);
  const [savingFrame, setSavingFrame] = useState(false);
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [analyzedFrames, setAnalyzedFrames] = useState<DetectionAnalyzedFrame[]>([]);
  const [selectedPhotoSrc, setSelectedPhotoSrc] = useState<string>("");
  const [pendingPhotoSrc, setPendingPhotoSrc] = useState<string>("");
  const [candidatePhotoSrc, setCandidatePhotoSrc] = useState<string>("");
  const [photoPositionX, setPhotoPositionX] = useState(50);
  const [photoPositionY, setPhotoPositionY] = useState(50);
  const [lightboxMode, setLightboxMode] = useState<"view" | "select">("select");
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const stripRef = useRef<HTMLDivElement>(null);
  const activeThumbRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen && data?.id) {
      setLoadingOffenders(true);
      getDetectionOffenders(data.id)
        .then(setOffenderLinks)
        .catch(() => setOffenderLinks([]))
        .finally(() => setLoadingOffenders(false));
    } else {
      setOffenderLinks([]);
    }
  }, [isOpen, data?.id]);

  useEffect(() => {
    if (!isOpen) {
      setIsFramesModalOpen(false);
      setIsConfirmFrameChangeOpen(false);
      return;
    }

    const fallbackPhoto = data?.image_url || (data?.hasOffender ? imgInfrator : imgLixo);
    setSelectedPhotoSrc(fallbackPhoto);
    setPendingPhotoSrc(fallbackPhoto);
    setLoadingFrames(true);

    if (!data?.id) {
      setAnalyzedFrames([]);
      setLoadingFrames(false);
      return;
    }

    getDetectionAnalyzedFrames(data.id)
      .then((response) => {
        const frames = response.frames || [];
        setAnalyzedFrames(frames);
        const persistedImage = (data?.image_url || "").trim();
        const persistedFrame = persistedImage
          ? frames.find((frame) => frame.image_url === persistedImage)?.image_url
          : undefined;
        const defaultFrame =
          persistedFrame ||
          frames.find((frame) => frame.is_default)?.image_url ||
          frames.find((frame) => frame.frame_name === response.selected_frame_name)?.image_url ||
          fallbackPhoto;
        setSelectedPhotoSrc(defaultFrame);
        setPendingPhotoSrc(defaultFrame);
      })
      .catch(() => {
        setAnalyzedFrames([]);
        setSelectedPhotoSrc(fallbackPhoto);
        setPendingPhotoSrc(fallbackPhoto);
      })
      .finally(() => setLoadingFrames(false));
  }, [isOpen, data?.id, data?.image_url, data?.hasOffender]);

  useEffect(() => {
    if (!isOpen || !data?.id) return;
    const key = `occurrence:crop:${data.id}`;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) {
        setPhotoPositionX(50);
        setPhotoPositionY(50);
        return;
      }
      const parsed = JSON.parse(raw) as { x?: number; y?: number };
      const x = Number(parsed?.x);
      const y = Number(parsed?.y);
      setPhotoPositionX(Number.isFinite(x) ? Math.min(100, Math.max(0, x)) : 50);
      setPhotoPositionY(Number.isFinite(y) ? Math.min(100, Math.max(0, y)) : 50);
    } catch {
      setPhotoPositionX(50);
      setPhotoPositionY(50);
    }
  }, [isOpen, data?.id]);

  useEffect(() => {
    if (!isOpen || !data?.id) return;
    const key = `occurrence:crop:${data.id}`;
    localStorage.setItem(key, JSON.stringify({ x: photoPositionX, y: photoPositionY }));
  }, [isOpen, data?.id, photoPositionX, photoPositionY]);

  const handleUnlink = async (linkId: string) => {
    try {
      await deleteDetectionOffender(linkId);
      setOffenderLinks((prev) => prev.filter((l) => l.id !== linkId));
    } catch (e) {
      console.error("Erro ao desvincular infrator:", e);
    }
  };

  if (!isOpen) return null;

  const formattedDate = formatDateTimeBrazil(data?.timestamp);
  const photoSrc = selectedPhotoSrc || data?.image_url || (data?.hasOffender ? imgInfrator : imgLixo);
  const volumeValue = data?.volume ?? data?.volume_m3;

  const handleExportPng = async () => {
    setIsExportMenuOpen(false);
    setIsCapturing(true);
    try {
      const canvas = await renderExportCanvas({ ...data, image_url: photoSrc });
      const dataUrl = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `ocorrencia_${data?.id ?? "detalhes"}.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      setIsCapturing(false);
    }
  };

  const handleExportPdf = async () => {
    setIsExportMenuOpen(false);
    setIsCapturing(true);
    try {
      const canvas = await renderExportCanvas({ ...data, image_url: photoSrc });
      const imgData = canvas.toDataURL("image/png");
      const pxW = canvas.width;
      const pxH = canvas.height;
      const orientation = pxW > pxH ? "landscape" : "portrait";
      const pdf = new jsPDF({ orientation, unit: "px", format: [pxW, pxH] });
      pdf.addImage(imgData, "PNG", 0, 0, pxW, pxH);
      pdf.save(`ocorrencia_${data?.id ?? "detalhes"}.pdf`);
    } finally {
      setIsCapturing(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Pendente":
        return "text-red-500";
      case "Em an\u00E1lise":
        return "text-orange-500";
      case "Resolvido":
        return "text-green-500";
      default:
        return "text-gray-500";
    }
  };

  const openFramesModal = (mode: "view" | "select" = "select") => {
    setPendingPhotoSrc(photoSrc);
    setCandidatePhotoSrc("");
    setIsConfirmFrameChangeOpen(false);
    setLightboxMode(mode);
    const startIdx = analyzedFrames.findIndex((f) => f.image_url === photoSrc);
    setLightboxIndex(startIdx >= 0 ? startIdx : 0);
    setIsFramesModalOpen(true);
  };

  const currentFrame = analyzedFrames[lightboxIndex];
  const hasFrames = analyzedFrames.length > 0;
  const canGoPrev = hasFrames && lightboxIndex > 0;
  const canGoNext = hasFrames && lightboxIndex < analyzedFrames.length - 1;

  const goToFrame = (idx: number) => {
    if (!hasFrames) return;
    const clamped = Math.max(0, Math.min(analyzedFrames.length - 1, idx));
    setLightboxIndex(clamped);
    setPendingPhotoSrc(analyzedFrames[clamped].image_url);
  };

  useEffect(() => {
    if (!isFramesModalOpen || !hasFrames) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goToFrame(lightboxIndex - 1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goToFrame(lightboxIndex + 1);
      } else if (e.key === "Escape") {
        setIsFramesModalOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isFramesModalOpen, hasFrames, lightboxIndex, analyzedFrames]);

  useEffect(() => {
    if (!isFramesModalOpen) return;
    activeThumbRef.current?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [lightboxIndex, isFramesModalOpen]);

  const handleRequestApplySelectedFrame = () => {
    if (!pendingPhotoSrc || pendingPhotoSrc === photoSrc) {
      setIsConfirmFrameChangeOpen(false);
      setIsFramesModalOpen(false);
      return;
    }
    setCandidatePhotoSrc(pendingPhotoSrc);
    setIsConfirmFrameChangeOpen(true);
  };

  const handleConfirmApplySelectedFrame = async () => {
    if (!data?.id || !candidatePhotoSrc) {
      setIsConfirmFrameChangeOpen(false);
      return;
    }
    setSavingFrame(true);
    try {
      await updateDetectionImage(data.id, candidatePhotoSrc);
      setSelectedPhotoSrc(candidatePhotoSrc);
      setPendingPhotoSrc(candidatePhotoSrc);
      setAnalyzedFrames((prev) =>
        prev.map((frame) => ({ ...frame, is_default: frame.image_url === candidatePhotoSrc })),
      );
      onPhotoUpdated?.(candidatePhotoSrc);
      setCandidatePhotoSrc("");
      setIsConfirmFrameChangeOpen(false);
      setIsFramesModalOpen(false);
    } catch (error) {
      console.error("Erro ao atualizar foto da ocorrência:", error);
    } finally {
      setSavingFrame(false);
    }
  };

  const handleDownloadFramesZip = async () => {
    if (!data?.id || analyzedFrames.length === 0) return;
    setDownloadingZip(true);
    try {
      const zip = new JSZip();
      const folder = zip.folder(`ocorrencia_${data.id}_frames`);
      if (!folder) throw new Error("Falha ao criar pasta no ZIP");

      await Promise.all(
        analyzedFrames.map(async (frame, index) => {
          const response = await fetch(frame.image_url);
          if (!response.ok) return;
          const blob = await response.blob();
          const fallbackName = `frame_${String(index + 1).padStart(2, "0")}.jpg`;
          const filename = (frame.frame_name || fallbackName).trim();
          folder.file(filename, blob);
        }),
      );

      const zipBlob = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(zipBlob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `ocorrencia_${data.id}_frames.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Erro ao baixar ZIP dos frames:", error);
    } finally {
      setDownloadingZip(false);
    }
  };

  return (
    <>
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        ref={modalRef}
        data-export-root="occurrence-modal"
        className="bg-white rounded-3xl w-full max-w-lg max-h-[calc(100vh-2rem)] shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200 flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-[#1a1a1a]">
              Informações da ocorrência
            </h2>
            <button
              type="button"
              onClick={() => openFramesModal("select")}
              className="h-8 px-3 rounded-lg border border-gray-200 hover:bg-gray-50 text-xs font-bold text-gray-700 flex items-center gap-1"
            >
              <ImageIcon size={14} />
              Escolher foto
            </button>
          </div>
          <button
            onClick={onClose}
            className={`text-gray-400 hover:text-gray-600 ${isCapturing ? "opacity-0 pointer-events-none" : ""}`}
          >
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pt-2 space-y-5 overflow-y-auto flex-1 min-h-0">
          {/* Image */}
          <button
            type="button"
            onClick={() => openFramesModal("view")}
            disabled={!hasFrames && !photoSrc}
            aria-label="Ampliar foto e navegar pelos frames"
            className="relative w-full h-72 md:h-80 bg-gray-200 rounded-xl overflow-hidden group block cursor-zoom-in disabled:cursor-default"
          >
            <img
              src={photoSrc}
              alt="Evidência"
              className="w-full h-full object-cover"
              style={{ objectPosition: `${photoPositionX}% ${photoPositionY}%` }}
            />
            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors pointer-events-none" />
            <div className="absolute top-2 right-2 bg-black/55 text-white rounded-lg p-1.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
              <Maximize2 size={16} />
            </div>
            {hasFrames && analyzedFrames.length > 1 && (
              <div className="absolute bottom-2 left-2 bg-black/55 text-white text-[11px] font-medium rounded-md px-2 py-0.5 pointer-events-none">
                {analyzedFrames.length} frames
              </div>
            )}
          </button>

          <div className="bg-gray-50 border border-gray-100 rounded-xl p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-600">Ajustar enquadramento da foto</span>
              <button
                type="button"
                onClick={() => {
                  setPhotoPositionX(50);
                  setPhotoPositionY(50);
                }}
                className="text-[11px] font-medium text-gray-500 hover:text-gray-700"
              >
                Centralizar
              </button>
            </div>
            <div>
              <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
                <span>Horizontal</span>
                <span>{Math.round(photoPositionX)}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={photoPositionX}
                onChange={(event) => setPhotoPositionX(Number(event.target.value))}
                className="w-full accent-lime-500"
              />
            </div>
            <div>
              <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
                <span>Vertical</span>
                <span>{Math.round(photoPositionY)}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={photoPositionY}
                onChange={(event) => setPhotoPositionY(Number(event.target.value))}
                className="w-full accent-lime-500"
              />
            </div>
          </div>

          {/* Info Grid */}
          <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-sm">
            <div>
              <span className="block text-gray-400 text-xs mb-1">Status</span>
              <span className={`font-bold ${getStatusColor(data?.status)}`}>
                {data?.status || "—"}
              </span>
            </div>
            <div>
              <span className="block text-gray-400 text-xs mb-1">ID</span>
              <span className="font-bold text-gray-700">{data?.id ?? "—"}</span>
            </div>
            <div className="col-span-2">
              <span className="block text-gray-400 text-xs mb-1">
                Data e Hora
              </span>
              <span className="font-bold text-gray-700">{formattedDate}</span>
            </div>

            <div className="col-span-2 grid grid-cols-3 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Logradouro
                </span>
                <span className="font-bold text-gray-700 block truncate">
                  {data?.logradouro || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">Bairro</span>
                <span className="font-bold text-gray-700 block truncate">
                  {data?.bairro || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">RPA</span>
                <span className="font-bold text-gray-700">{data?.rpa || "—"}</span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-2 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Latitude
                </span>
                <span className="font-bold text-gray-700">
                  {data?.latitude ?? "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Longitude
                </span>
                <span className="font-bold text-gray-700">
                  {data?.longitude ?? "—"}
                </span>
              </div>
            </div>

            <div className="col-span-2 grid grid-cols-2 gap-2">
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Tipo de resíduo
                </span>
                <span className="font-bold text-gray-700">
                  {data?.tipo || data?.tipoResiduo || "—"}
                </span>
              </div>
              <div>
                <span className="block text-gray-400 text-xs mb-1">
                  Volumetria aprox.
                </span>
                <span className="font-bold text-gray-700">
                  {volumeValue ?? "—"} m³
                </span>
              </div>
            </div>

            <div className="col-span-2 bg-gray-50 p-3 rounded-lg border border-gray-100">
              <div className="flex items-center justify-between mb-2">
                <span className="text-gray-400 text-xs">Infratores vinculados</span>
                <button
                  onClick={() => setIsAddOffenderOpen(true)}
                  className="text-xs text-lime-600 hover:text-lime-700 font-bold flex items-center gap-1"
                >
                  <UserPlus size={14} /> Vincular
                </button>
              </div>
              {loadingOffenders ? (
                <span className="text-xs text-gray-400">Carregando...</span>
              ) : offenderLinks.length === 0 ? (
                <span className="font-bold text-gray-500 text-sm">
                  {data?.hasOffender ? "Identificados: Pessoa" : "Nenhum infrator vinculado"}
                </span>
              ) : (
                <div className="space-y-2">
                  {offenderLinks.map((link) => (
                    <div key={link.id} className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-gray-100">
                      <div>
                        <span className="font-bold text-sm text-[#1a1a1a]">
                          {link.offender?.name || link.offender_type}
                        </span>
                        <span className="text-xs text-gray-400 ml-2">{link.offender_type}</span>
                        {link.plate && <span className="text-xs text-gray-400 ml-2">{link.plate}</span>}
                        {link.source === "ai" && (
                          <span className="ml-2 px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-[10px] font-bold">IA</span>
                        )}
                      </div>
                      <button onClick={() => handleUnlink(link.id)} className="text-red-400 hover:text-red-600">
                        <UnlinkIcon size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="flex gap-3 mt-4">
            {/* Download Button with Dropdown */}
            <div className="relative">
              <button
                onClick={() => setIsExportMenuOpen((prev) => !prev)}
                className="w-12 h-12 flex items-center justify-center bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] transition-colors text-black disabled:opacity-60 disabled:pointer-events-none"
                disabled={isCapturing}
                aria-label={isCapturing ? "Gerando exportação" : "Abrir opções de exportação"}
                title={isCapturing ? "Gerando..." : "Exportar"}
              >
                {isCapturing ? <Loader2 size={20} className="animate-spin" /> : <Download size={20} />}
              </button>
              {isExportMenuOpen && (
                <div className="absolute left-0 bottom-14 w-56 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-10">
                  <button
                    type="button"
                    onClick={handleExportPng}
                    className="w-full px-4 py-3 text-sm text-gray-700 flex items-center gap-2 hover:bg-gray-50 transition-colors"
                  >
                    <ImageIcon size={16} />
                    Exportar como PNG
                  </button>
                  <button
                    type="button"
                    onClick={handleExportPdf}
                    className="w-full px-4 py-3 text-sm text-gray-700 flex items-center gap-2 hover:bg-gray-50 transition-colors"
                  >
                    <FileText size={16} />
                    Exportar como PDF
                  </button>
                </div>
              )}
            </div>

            {/* Ver localização no mapa */}
            {data?.latitude && data?.longitude && (
              <a
                href={`https://www.google.com/maps?q=${data.latitude},${data.longitude}`}
                target="_blank"
                rel="noopener noreferrer"
                className="h-12 px-4 flex items-center gap-2 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors text-sm font-medium text-gray-700"
              >
                <MapPin size={18} />
                Ver no mapa
              </a>
            )}

            {/* Marcar como resolvido */}
            {onResolve && data?.status !== "Resolvido" && (
              <button
                onClick={onResolve}
                className="h-12 px-4 flex items-center gap-2 bg-green-500 text-white rounded-xl hover:bg-green-600 transition-colors text-sm font-bold"
              >
                <CheckCircle size={18} />
                Marcar como resolvido
              </button>
            )}

            {/* Marcar em análise */}
            {onStartAnalysis && data?.status === "Pendente" && (
              <button
                onClick={onStartAnalysis}
                className="h-12 px-4 flex items-center gap-2 bg-orange-500 text-white rounded-xl hover:bg-orange-600 transition-colors text-sm font-bold"
              >
                <Clock size={18} />
                Marcar em análise
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
    {isAddOffenderOpen && data?.id && (
      <AddDetectionOffenderModal
        isOpen={isAddOffenderOpen}
        onClose={() => setIsAddOffenderOpen(false)}
        detectionId={data.id}
        onSuccess={() => {
          setIsAddOffenderOpen(false);
          getDetectionOffenders(data.id)
            .then(setOffenderLinks)
            .catch(() => {});
        }}
      />
    )}
    {isFramesModalOpen && (
      <div
        className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 p-4"
        onClick={(e) => { if (e.target === e.currentTarget) setIsFramesModalOpen(false); }}
      >
        <div className="w-full max-w-5xl max-h-[calc(100vh-2rem)] bg-white rounded-2xl shadow-2xl border border-gray-100 overflow-hidden flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
            <div className="flex items-center gap-3">
              <h3 className="text-lg font-bold text-[#1a1a1a]">Frames analisados</h3>
              {hasFrames && (
                <span className="text-sm text-gray-500 tabular-nums">
                  {lightboxIndex + 1} / {analyzedFrames.length}
                </span>
              )}
              {currentFrame?.is_default && (
                <span className="text-[10px] font-bold text-lime-600 bg-lime-50 border border-lime-200 rounded-full px-2 py-0.5">
                  Padrão da IA
                </span>
              )}
            </div>
            <button
              onClick={() => setIsFramesModalOpen(false)}
              className="text-gray-400 hover:text-gray-600"
              aria-label="Fechar"
            >
              <X size={22} />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 min-h-0 flex flex-col">
            {loadingFrames ? (
              <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
                <Loader2 size={18} className="animate-spin mr-2" />
                Carregando frames...
              </div>
            ) : !hasFrames ? (
              <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
                Nenhum frame de análise disponível para esta ocorrência.
              </div>
            ) : (
              <>
                {/* Main image area */}
                <div className="relative flex-1 min-h-0 bg-black/95 flex items-center justify-center select-none">
                  <img
                    src={currentFrame.image_url}
                    alt={currentFrame.frame_name}
                    className="max-h-full max-w-full object-contain"
                  />
                  {/* Preload neighbors */}
                  {analyzedFrames[lightboxIndex - 1] && (
                    <img src={analyzedFrames[lightboxIndex - 1].image_url} alt="" className="hidden" />
                  )}
                  {analyzedFrames[lightboxIndex + 1] && (
                    <img src={analyzedFrames[lightboxIndex + 1].image_url} alt="" className="hidden" />
                  )}
                  {/* Nav buttons */}
                  <button
                    type="button"
                    onClick={() => goToFrame(lightboxIndex - 1)}
                    disabled={!canGoPrev}
                    aria-label="Frame anterior"
                    className="absolute left-3 top-1/2 -translate-y-1/2 h-11 w-11 rounded-full bg-black/60 hover:bg-black/80 disabled:opacity-30 disabled:hover:bg-black/60 text-white flex items-center justify-center transition-colors"
                  >
                    <ChevronLeft size={28} />
                  </button>
                  <button
                    type="button"
                    onClick={() => goToFrame(lightboxIndex + 1)}
                    disabled={!canGoNext}
                    aria-label="Próximo frame"
                    className="absolute right-3 top-1/2 -translate-y-1/2 h-11 w-11 rounded-full bg-black/60 hover:bg-black/80 disabled:opacity-30 disabled:hover:bg-black/60 text-white flex items-center justify-center transition-colors"
                  >
                    <ChevronRight size={28} />
                  </button>
                  {/* Timestamp caption */}
                  <div className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-black/65 text-white text-sm font-medium rounded-md px-3 py-1 tabular-nums">
                    {formatFrameTimestamp(currentFrame.frame_name)}
                  </div>
                </div>

                {/* Thumbnails strip */}
                <div
                  ref={stripRef}
                  className="flex-shrink-0 flex gap-2 overflow-x-auto overflow-y-hidden px-4 py-3 border-t border-gray-100 bg-white"
                >
                  {analyzedFrames.map((frame, idx) => {
                    const isActive = idx === lightboxIndex;
                    return (
                      <button
                        key={`${frame.frame_name}-${frame.image_url}`}
                        ref={isActive ? activeThumbRef : undefined}
                        type="button"
                        onClick={() => goToFrame(idx)}
                        aria-label={`Ir para frame ${idx + 1}`}
                        className={`flex-shrink-0 w-[88px] rounded-md overflow-hidden border-2 transition-colors ${
                          isActive
                            ? "border-[#84cc16] ring-2 ring-lime-200"
                            : "border-gray-200 hover:border-gray-400"
                        }`}
                      >
                        <div className="h-[56px] bg-gray-100">
                          <img src={frame.image_url} alt={frame.frame_name} className="w-full h-full object-cover" />
                        </div>
                        <div className="px-1.5 py-1 bg-white">
                          <div className="text-[10px] text-gray-500 tabular-nums truncate">
                            {formatFrameTimeShort(frame.frame_name)}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-between gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50">
            <button
              onClick={handleDownloadFramesZip}
              disabled={downloadingZip || analyzedFrames.length === 0}
              className="h-10 px-4 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-60 text-sm font-medium text-gray-700 flex items-center gap-2"
            >
              {downloadingZip ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              Baixar ZIP
            </button>
            <div className="flex gap-2">
              <button
                onClick={() => setIsFramesModalOpen(false)}
                className="h-10 px-4 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-sm font-medium text-gray-700"
              >
                {lightboxMode === "select" ? "Cancelar" : "Fechar"}
              </button>
              {lightboxMode === "select" && (
                <button
                  onClick={handleRequestApplySelectedFrame}
                  disabled={savingFrame || !pendingPhotoSrc || pendingPhotoSrc === photoSrc}
                  className="h-10 px-4 rounded-lg bg-lime-500 hover:bg-lime-600 disabled:opacity-60 text-sm font-bold text-white flex items-center gap-2"
                >
                  {savingFrame ? <Loader2 size={14} className="animate-spin" /> : null}
                  Aplicar foto
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    )}
    {isConfirmFrameChangeOpen && (
      <div className="fixed inset-0 z-[10010] flex items-center justify-center bg-black/55 p-4">
        <div className="w-full max-w-md bg-white rounded-2xl border border-gray-100 shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h3 className="text-base font-bold text-[#1a1a1a]">Confirmar troca da foto</h3>
            <p className="text-sm text-gray-600 mt-1">
              A foto desta ocorrência será atualizada e ficará salva como padrão.
            </p>
          </div>
          <div className="px-5 py-4">
            <div className="text-xs text-gray-500">
              Nova foto selecionada:
            </div>
            <div className="mt-1 text-sm font-medium text-gray-800 truncate">
              {analyzedFrames.find((frame) => frame.image_url === candidatePhotoSrc)?.frame_name || "Frame selecionado"}
            </div>
          </div>
          <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-100 bg-gray-50">
            <button
              onClick={() => {
                setCandidatePhotoSrc("");
                setIsConfirmFrameChangeOpen(false);
              }}
              className="h-10 px-4 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-sm font-medium text-gray-700"
            >
              Cancelar
            </button>
            <button
              onClick={handleConfirmApplySelectedFrame}
              disabled={savingFrame}
              className="h-10 px-4 rounded-lg bg-lime-500 hover:bg-lime-600 disabled:opacity-60 text-sm font-bold text-white flex items-center gap-2"
            >
              {savingFrame ? <Loader2 size={14} className="animate-spin" /> : null}
              Confirmar
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
};
