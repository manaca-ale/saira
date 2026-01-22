import React from "react";
import type { LucideIcon } from "lucide-react";

// --- Type Definitions ---
interface InputFieldProps {
  id: string;
  label: string;
  type: string;
  placeholder: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  icon: LucideIcon;
  error?: boolean;
  errorMessage?: string;
}

export const InputField: React.FC<InputFieldProps> = ({
  id,
  label,
  type,
  placeholder,
  value,
  onChange,
  icon: Icon,
  error,
  errorMessage,
}) => {
  // --- Dynamic Style Calculations ---
  const labelColor = error ? "text-[#ff3366]" : "text-[#d9f99d]";
  const borderColor = error
    ? "border-[#ff3366]"
    : "border-zinc-600 focus:border-[#ccff33]";
  const iconColor = error ? "text-[#ff3366]" : "text-zinc-500";

  return (
    // --- Component Container ---
    <div className="flex flex-col gap-2 w-full group">
      {/* --- Label Section --- */}
      <label
        htmlFor={id}
        className={`text-base font-normal tracking-wide transition-colors duration-200 ${labelColor}`}
      >
        {label}
      </label>

      {/* --- Input Field Wrapper --- */}
      <div className="relative">
        <input
          id={id}
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className={`
            w-full bg-transparent border-[1px] rounded-2xl py-4 pl-5 pr-12 
            text-white placeholder-zinc-600 outline-none transition-all duration-300
            hover:border-zinc-500
            ${borderColor}
          `}
        />
        <Icon
          className={`absolute right-5 top-1/2 -translate-y-1/2 w-5 h-5 transition-colors duration-200 ${iconColor}`}
        />
      </div>

      {/* --- Error Feedback --- */}
      {error && errorMessage && (
        <span className="text-sm text-[#ff3366] font-medium mt-1 pl-1">
          {errorMessage}
        </span>
      )}
    </div>
  );
};
