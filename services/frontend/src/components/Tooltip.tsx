import React, {
  useState,
  useRef,
  useLayoutEffect,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// --- Tooltip with Smart Positioning ---
type TooltipProps = {
  content?: string;
  text?: string;
  variant?: "default" | "danger";
  className?: string;
  spacing?: string;
  children: ReactNode;
};

type Position = {
  top: number;
  left: number;
  placement: "top" | "bottom";
};

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  text,
  variant = "default",
  className,
  spacing,
  children,
}) => {
  const tooltipText = content ?? text;
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const enterTimeout = useRef<number | undefined>(undefined);
  const leaveTimeout = useRef<number | undefined>(undefined);

  const handleMouseEnter = () => {
    if (leaveTimeout.current) {
      clearTimeout(leaveTimeout.current);
    }
    enterTimeout.current = window.setTimeout(() => {
      setIsVisible(true);
    }, 200);
  };

  const handleMouseLeave = () => {
    if (enterTimeout.current) {
      clearTimeout(enterTimeout.current);
    }
    leaveTimeout.current = window.setTimeout(() => {
      setIsVisible(false);
    }, 200);
  };

  useLayoutEffect(() => {
    if (!isVisible || !triggerRef.current || !tooltipRef.current) return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const margin = 10;
    const gap = 8;

    // Horizontal centering with collision handling
    let left =
      triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    if (left < margin) left = margin;
    if (left + tooltipRect.width > window.innerWidth - margin) {
      left = window.innerWidth - tooltipRect.width - margin;
    }

    // Vertical placement (prefer top)
    const spaceAbove = triggerRect.top;
    const spaceBelow = window.innerHeight - triggerRect.bottom;
    let placement: "top" | "bottom" = "top";
    let top = triggerRect.top - tooltipRect.height - gap;

    if (spaceAbove < tooltipRect.height + gap && spaceBelow > spaceAbove) {
      placement = "bottom";
      top = triggerRect.bottom + gap;
    }

    if (top < margin) top = margin;
    if (top + tooltipRect.height > window.innerHeight - margin) {
      top = Math.max(margin, window.innerHeight - tooltipRect.height - margin);
    }

    setPosition({ top, left, placement });
  }, [isVisible]);

  if (!tooltipText) {
    return <span className={className}>{children}</span>;
  }

  const variantClass = variant === "danger" ? "bg-red-600" : "bg-gray-900";

  return (
    <>
      <span
        ref={triggerRef}
        className={`inline-flex items-center ${className ?? ""}`.trim()}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </span>
      {isVisible &&
        createPortal(
          <div
            ref={tooltipRef}
            className={`fixed ${variantClass} text-white text-xs rounded-md shadow-lg px-3 py-2 w-max max-w-xs whitespace-normal break-words pointer-events-none transition-opacity duration-200 z-[99999] ${spacing ?? ""} ${position ? "opacity-100" : "opacity-0"}`.trim()}
            style={
              position
                ? {
                    top: `${position.top}px`,
                    left: `${position.left}px`,
                  }
                : undefined
            }
          >
            {tooltipText}
          </div>,
          document.body,
        )}
    </>
  );
};
