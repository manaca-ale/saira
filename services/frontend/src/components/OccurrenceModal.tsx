import React, { useState, useRef, useEffect } from "react";
import { jsPDF } from "jspdf";
import { X, Download, Image as ImageIcon, FileText, Loader2, MapPin, CheckCircle, Clock, UserPlus, Trash2 as UnlinkIcon } from "lucide-react";
import imgLixo from "../assets/lixo_exemplo.png";
import imgInfrator from "../assets/infrator_exemplo.png";
import { getDetectionOffenders, deleteDetectionOffender } from "../services/offenderService";
import type { DetectionOffenderLink } from "../services/offenderService";
import { AddDetectionOffenderModal } from "./AddDetectionOffenderModal";

interface OccurrenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
  onResolve?: () => void;
  onStartAnalysis?: () => void;
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

  const occurrenceDate = data?.timestamp ? new Date(data.timestamp) : null;
  const formattedDate = occurrenceDate ? occurrenceDate.toLocaleString("pt-BR") : "—";
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

// --- Component ---

export const OccurrenceModal: React.FC<OccurrenceModalProps> = ({
  isOpen,
  onClose,
  data,
  onResolve,
  onStartAnalysis,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [offenderLinks, setOffenderLinks] = useState<DetectionOffenderLink[]>([]);
  const [loadingOffenders, setLoadingOffenders] = useState(false);
  const [isAddOffenderOpen, setIsAddOffenderOpen] = useState(false);

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

  const handleUnlink = async (linkId: string) => {
    try {
      await deleteDetectionOffender(linkId);
      setOffenderLinks((prev) => prev.filter((l) => l.id !== linkId));
    } catch (e) {
      console.error("Erro ao desvincular infrator:", e);
    }
  };

  if (!isOpen) return null;

  const occurrenceDate = data?.timestamp ? new Date(data.timestamp) : null;
  const formattedDate = occurrenceDate
    ? occurrenceDate.toLocaleString("pt-BR")
    : "—";
  const photoSrc = data?.image_url || (data?.hasOffender ? imgInfrator : imgLixo);
  const volumeValue = data?.volume ?? data?.volume_m3;

  const handleExportPng = async () => {
    setIsExportMenuOpen(false);
    setIsCapturing(true);
    try {
      const canvas = await renderExportCanvas(data);
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
      const canvas = await renderExportCanvas(data);
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

  return (
    <>
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        ref={modalRef}
        data-export-root="occurrence-modal"
        className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <h2 className="text-xl font-bold text-[#1a1a1a]">
            Informações da ocorrência
          </h2>
          <button
            onClick={onClose}
            className={`text-gray-400 hover:text-gray-600 ${isCapturing ? "opacity-0 pointer-events-none" : ""}`}
          >
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pt-2 space-y-5">
          {/* Image */}
          <div className="relative w-full h-48 bg-gray-200 rounded-xl overflow-hidden group">
            <img
              src={photoSrc}
              alt="Evidência"
              className="w-full h-full object-cover"
            />
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

            <div className="col-span-2 grid grid-cols-3 gap-2">
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
                  Tipo de material
                </span>
                <span className="font-bold text-gray-700">
                  {data?.material_type || "—"}
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
    </>
  );
};
