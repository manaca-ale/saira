import React, { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Eye, EyeOff } from "lucide-react";

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
  isPassword?: boolean;
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
  isPassword = false,
}) => {
  // --- State for password visibility ---
  const [showPassword, setShowPassword] = useState(false);

  // --- Dynamic Style Calculations ---
  const labelColor = error ? "text-[#ff3366]" : "text-[#d9f99d]";
  const borderColor = error
    ? "border-[#ff3366]"
    : "border-zinc-600 focus:border-[#ccff33]";
  const iconColor = error ? "text-[#ff3366]" : "text-zinc-500";

  // Determine actual input type
  const inputType = isPassword ? (showPassword ? "text" : "password") : type;

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
          type={inputType}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className={`
            w-full bg-transparent border-[1px] rounded-2xl py-4 pl-5 ${isPassword ? 'pr-20' : 'pr-12'}
            text-white placeholder-zinc-600 outline-none transition-all duration-300
            hover:border-zinc-500
            ${borderColor}
          `}
        />
        {isPassword ? (
          <>
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className={`absolute right-12 top-1/2 -translate-y-1/2 transition-colors duration-200 hover:text-[#d9f99d] ${iconColor}`}
            >
              {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
            <Icon
              className={`absolute right-5 top-1/2 -translate-y-1/2 w-5 h-5 transition-colors duration-200 ${iconColor}`}
            />
          </>
        ) : (
          <Icon
            className={`absolute right-5 top-1/2 -translate-y-1/2 w-5 h-5 transition-colors duration-200 ${iconColor}`}
          />
        )}
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
