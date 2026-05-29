import React from "react";

// Gemini bbox format: [y_min, x_min, y_max, x_max], normalized 0-1000.
export type BBoxCoords = [number, number, number, number];

export interface BBox {
  coords: BBoxCoords;
  color: string;
  label?: string;
}

interface BBoxOverlayProps {
  boxes: BBox[];
  naturalW: number;
  naturalH: number;
  fit: "cover" | "contain";
}

function isValid(coords: BBoxCoords): boolean {
  return (
    Array.isArray(coords) &&
    coords.length === 4 &&
    coords.every((n) => typeof n === "number" && Number.isFinite(n)) &&
    coords[2] > coords[0] &&
    coords[3] > coords[1]
  );
}

/**
 * Draws bounding boxes over an <img> using an SVG whose viewBox matches the
 * image's natural pixel grid. `preserveAspectRatio` reproduces the image's
 * object-fit (slice=cover, meet=contain), so the boxes scale/crop exactly like
 * the image — no manual letterbox/crop math or ResizeObserver needed.
 */
export const BBoxOverlay: React.FC<BBoxOverlayProps> = ({
  boxes,
  naturalW,
  naturalH,
  fit,
}) => {
  if (!naturalW || !naturalH) return null;

  const valid = boxes.filter((b) => isValid(b.coords));
  if (valid.length === 0) return null;

  const preserveAspectRatio = fit === "cover" ? "xMidYMid slice" : "xMidYMid meet";
  const fontSize = Math.max(naturalH * 0.03, 10);

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      viewBox={`0 0 ${naturalW} ${naturalH}`}
      preserveAspectRatio={preserveAspectRatio}
      aria-hidden="true"
    >
      {valid.map((box, i) => {
        const [ymin, xmin, ymax, xmax] = box.coords;
        const x = (xmin / 1000) * naturalW;
        const y = (ymin / 1000) * naturalH;
        const w = ((xmax - xmin) / 1000) * naturalW;
        const h = ((ymax - ymin) / 1000) * naturalH;
        const labelY = y > fontSize * 1.2 ? y - fontSize * 0.35 : y + h + fontSize;

        return (
          <g key={i}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              fill="none"
              stroke={box.color}
              strokeWidth={3}
              vectorEffect="non-scaling-stroke"
            />
            {box.label && (
              <text
                x={x}
                y={labelY}
                fill={box.color}
                fontSize={fontSize}
                fontWeight="bold"
                style={{ paintOrder: "stroke" }}
                stroke="rgba(0,0,0,0.6)"
                strokeWidth={fontSize * 0.12}
              >
                {box.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
};
