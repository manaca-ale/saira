import { useCallback, useMemo, useRef, useState } from "react";
import { Hexagon, Plus, Undo2, Trash2, Eraser } from "lucide-react";

/**
 * Editor da zona de interesse (pile_zone_polygon) desenhada sobre o snapshot da
 * câmera. Inspirado em tools/polygon_marker.html: clicar adiciona vértice,
 * arrastar move vértice, clicar no 1º ponto (ou Enter / duplo-clique) fecha o
 * polígono; suporta múltiplos polígonos.
 *
 * Contrato de coordenadas: pixels absolutos no frame de referência 1280×720
 * (o worker/Pi reescalam a máscara para o frame real). O SVG usa esse viewBox,
 * então getScreenCTM().inverse() mapeia o cursor direto para 1280×720 — sem
 * matemática de letterbox. Assume snapshot em 16:9 (padrão das câmeras).
 */

const REF_W = 1280;
const REF_H = 720;
const CLOSE_HIT = 26; // raio (em px do ref) p/ clicar no 1º vértice e fechar
const VERTEX_R = 9;

// Pontos como number[] (não tupla) para casar com o tipo do serviço
// (pile_zone_polygon: number[][][]); cada ponto é [x, y].
type Point = number[];
type Poly = Point[];

interface PolygonEditorProps {
  imageUrl: string | null;
  value: Poly[];
  onChange: (polys: Poly[]) => void;
}

function shoelaceArea(poly: Poly): number {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

export default function PolygonEditor({ imageUrl, value, onChange }: PolygonEditorProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  // Índice do polígono aberto (recebendo novos pontos); null = clicar inicia um novo.
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ poly: number; pt: number } | null>(null);

  const polys = value;

  const toRef = useCallback((clientX: number, clientY: number): Point => {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const ctm = svg.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = svg.createSVGPoint();
    p.x = clientX;
    p.y = clientY;
    const local = p.matrixTransform(ctm.inverse());
    const x = Math.max(0, Math.min(REF_W, Math.round(local.x)));
    const y = Math.max(0, Math.min(REF_H, Math.round(local.y)));
    return [x, y];
  }, []);

  const finishActive = useCallback(() => setActiveIdx(null), []);

  const handleBackgroundDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (drag) return; // um arraste de vértice está em curso
      const [x, y] = toRef(e.clientX, e.clientY);
      const next = polys.map((p) => p.slice());
      if (activeIdx != null && next[activeIdx]?.length >= 3) {
        // Clicou perto do 1º vértice do polígono ativo -> fecha.
        const [fx, fy] = next[activeIdx][0];
        if (Math.hypot(fx - x, fy - y) <= CLOSE_HIT) {
          finishActive();
          return;
        }
      }
      if (activeIdx == null) {
        next.push([[x, y]]);
        setActiveIdx(next.length - 1);
      } else {
        next[activeIdx].push([x, y]);
      }
      onChange(next);
    },
    [activeIdx, drag, finishActive, onChange, polys, toRef],
  );

  const handleVertexDown = useCallback(
    (e: React.PointerEvent, poly: number, pt: number) => {
      e.stopPropagation();
      setDrag({ poly, pt });
      svgRef.current?.setPointerCapture(e.pointerId);
    },
    [],
  );

  const handleMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (!drag) return;
      const [x, y] = toRef(e.clientX, e.clientY);
      const next = polys.map((p) => p.slice());
      if (next[drag.poly]?.[drag.pt]) {
        next[drag.poly][drag.pt] = [x, y];
        onChange(next);
      }
    },
    [drag, onChange, polys, toRef],
  );

  const handleUp = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (drag) {
        svgRef.current?.releasePointerCapture(e.pointerId);
        setDrag(null);
      }
    },
    [drag],
  );

  const undoLastPoint = useCallback(() => {
    const idx = activeIdx != null ? activeIdx : polys.length - 1;
    if (idx < 0 || !polys[idx]) return;
    const next = polys.map((p) => p.slice());
    next[idx].pop();
    if (next[idx].length === 0) {
      next.splice(idx, 1);
      setActiveIdx(null);
    } else if (activeIdx == null) {
      setActiveIdx(idx); // reabre p/ continuar editando
    }
    onChange(next);
  }, [activeIdx, onChange, polys]);

  const removePoly = useCallback(
    (idx: number) => {
      const next = polys.filter((_, i) => i !== idx);
      onChange(next);
      setActiveIdx(null);
    },
    [onChange, polys],
  );

  const clearAll = useCallback(() => {
    onChange([]);
    setActiveIdx(null);
  }, [onChange]);

  const coveragePct = useMemo(() => {
    const area = polys.reduce((sum, p) => sum + (p.length >= 3 ? shoelaceArea(p) : 0), 0);
    return (area / (REF_W * REF_H)) * 100;
  }, [polys]);

  return (
    <div
      className="select-none"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") finishActive();
        else if (e.key === "Backspace") {
          e.preventDefault();
          undoLastPoint();
        }
      }}
    >
      <div className="relative aspect-video w-full rounded-xl overflow-hidden bg-gray-100">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt="Snapshot da câmera para desenhar o polígono"
            className="absolute inset-0 w-full h-full object-contain pointer-events-none"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-xs text-gray-400">
            Sem imagem — clique em "Atualizar" no painel acima
          </div>
        )}
        <svg
          ref={svgRef}
          viewBox={`0 0 ${REF_W} ${REF_H}`}
          preserveAspectRatio="xMidYMid meet"
          className="absolute inset-0 w-full h-full cursor-crosshair touch-none"
          onPointerDown={handleBackgroundDown}
          onPointerMove={handleMove}
          onPointerUp={handleUp}
          onDoubleClick={finishActive}
          onContextMenu={(e) => {
            e.preventDefault();
            finishActive();
          }}
        >
          {polys.map((poly, pi) => {
            const isActive = pi === activeIdx;
            const pointsStr = poly.map(([x, y]) => `${x},${y}`).join(" ");
            return (
              <g key={pi}>
                {poly.length >= 2 &&
                  (isActive ? (
                    <polyline
                      points={pointsStr}
                      fill="none"
                      stroke="#ccff33"
                      strokeWidth={3}
                      strokeDasharray="8 6"
                    />
                  ) : (
                    <polygon
                      points={pointsStr}
                      fill="rgba(204,255,51,0.18)"
                      stroke="#a3e635"
                      strokeWidth={3}
                    />
                  ))}
                {poly.map(([x, y], vi) => (
                  <circle
                    key={vi}
                    cx={x}
                    cy={y}
                    r={VERTEX_R}
                    fill={vi === 0 ? "#ccff33" : "#ffffff"}
                    stroke="#1a1a1a"
                    strokeWidth={2}
                    className="cursor-grab"
                    onPointerDown={(e) => handleVertexDown(e, pi, vi)}
                  />
                ))}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setActiveIdx(null)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 transition-colors"
        >
          <Plus size={14} /> Novo polígono
        </button>
        <button
          type="button"
          onClick={undoLastPoint}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 transition-colors"
        >
          <Undo2 size={14} /> Desfazer ponto
        </button>
        {activeIdx != null && (
          <button
            type="button"
            onClick={() => removePoly(activeIdx)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 transition-colors"
          >
            <Trash2 size={14} /> Excluir polígono
          </button>
        )}
        {polys.length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 transition-colors"
          >
            <Eraser size={14} /> Limpar tudo
          </button>
        )}
        <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-gray-500">
          <Hexagon size={14} />
          {polys.length} polígono(s) · {coveragePct.toFixed(1)}% do frame
        </span>
      </div>
    </div>
  );
}
