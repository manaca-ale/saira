import React, { useState, useRef, useEffect } from "react";
import { ChevronDown, X, Check } from "lucide-react";

// --- REUSABLE FILTER COMPONENTS ---
export const FilterPopover: React.FC<{
  label: string;
  active: boolean;
  hasValue: boolean;
  onClear: () => void;
  children: React.ReactNode;
  onClose: () => void;
  onClick: () => void;
}> = ({ label, active, hasValue, onClear, children, onClose, onClick }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onClose();
      }
    }
    if (active) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [active, onClose]);

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={onClick}
        className={`flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer ${
          active ? "border-gray-400 bg-gray-200" : ""
        }`}
      >
        <span
          className={`text-sm font-medium truncate ${
            hasValue ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {hasValue ? "Definido" : "Selecionar"}
        </span>
        {hasValue ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {active && (
        <div className="absolute top-full left-0 mt-2 bg-white border border-gray-200 rounded-xl shadow-xl z-50 p-4 min-w-[280px] animate-in fade-in zoom-in-95 duration-200">
          {children}
        </div>
      )}
    </div>
  );
};

export const FilterSelect: React.FC<{
  label: string;
  value: string;
  options: string[];
  onChange: (val: string) => void;
}> = ({ label, value, options, onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node))
        setIsOpen(false);
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer"
      >
        <span
          className={`text-sm font-medium truncate ${
            value ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {value || "Selecionar"}
        </span>
        {value ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onChange("");
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {options.map((opt) => (
            <div
              key={opt}
              onClick={(e) => {
                e.stopPropagation();
                onChange(opt);
                setIsOpen(false);
              }}
              className="px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer border-b border-gray-50 last:border-0"
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const formatMultiValue = (value: string[]) => {
  if (value.length === 0) return "Selecionar";
  if (value.length <= 2) return value.join(", ");
  return `${value.length} selecionados`;
};

export const FilterMultiSelect: React.FC<{
  label: string;
  value: string[];
  options: string[];
  onChange: (val: string[]) => void;
}> = ({ label, value, options, onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node))
        setIsOpen(false);
    }
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const toggleValue = (opt: string) => {
    if (value.includes(opt)) {
      onChange(value.filter((item) => item !== opt));
    } else {
      onChange([...value, opt]);
    }
  };

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 transition-colors cursor-pointer"
      >
        <span
          className={`text-sm font-medium truncate ${
            value.length ? "text-[#1a1a1a]" : "text-gray-700"
          }`}
        >
          {formatMultiValue(value)}
        </span>
        {value.length ? (
          <div
            onClick={(e) => {
              e.stopPropagation();
              onChange([]);
            }}
            className="p-0.5 rounded-full hover:bg-gray-300"
          >
            <X size={14} className="text-gray-500 hover:text-red-500" />
          </div>
        ) : (
          <ChevronDown size={16} className="text-gray-400" />
        )}
      </div>
      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {options.map((opt) => {
            const selected = value.includes(opt);
            return (
              <div
                key={opt}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleValue(opt);
                }}
                className={`px-4 py-3 text-sm cursor-pointer border-b border-gray-50 last:border-0 flex items-center justify-between ${
                  selected
                    ? "bg-lime-50 text-gray-900"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
              >
                <span className="truncate">{opt}</span>
                <span
                  className={`w-4 h-4 rounded border flex items-center justify-center ${
                    selected
                      ? "bg-lime-500 border-lime-500"
                      : "border-gray-300"
                  }`}
                >
                  {selected && <Check size={12} className="text-white" />}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const FilterAutocomplete: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
  options: string[];
}> = ({ label, value, onChange, options }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const normalizedValue = value.trim().toLowerCase();
  const filteredOptions = normalizedValue
    ? options.filter((opt) => opt.toLowerCase().includes(normalizedValue))
    : options;

  return (
    <div ref={ref} className="w-full relative">
      <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
        {label}
      </span>
      <div className="bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 focus-within:border-gray-400 focus-within:bg-white flex items-center group">
        <input
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder="Pesquisar"
          className="bg-transparent border-none outline-none text-sm w-full text-gray-700 placeholder-gray-500"
        />
        {value && (
          <button
            onClick={() => onChange("")}
            className="ml-2 text-gray-400 hover:text-red-500"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {isOpen && filteredOptions.length > 0 && (
        <div className="absolute top-full left-0 mt-2 w-full bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-hidden max-h-60 overflow-y-auto">
          {filteredOptions.map((opt) => (
            <div
              key={opt}
              onClick={() => {
                onChange(opt);
                setIsOpen(false);
              }}
              className="px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 cursor-pointer border-b border-gray-50 last:border-0"
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export const FilterInput: React.FC<{
  label: string;
  value: string;
  onChange: (val: string) => void;
}> = ({ label, value, onChange }) => (
  <div className="w-full">
    <span className="text-sm text-gray-700 font-bold block mb-1.5 ml-2">
      {label}
    </span>
    <div className="bg-[#f3f4f6] rounded-xl px-4 py-3 border border-transparent hover:border-gray-300 focus-within:border-gray-400 focus-within:bg-white flex items-center group">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Pesquisar"
        className="bg-transparent border-none outline-none text-sm w-full text-gray-700 placeholder-gray-500"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          className="ml-2 text-gray-400 hover:text-red-500"
        >
          <X size={14} />
        </button>
      )}
    </div>
  </div>
);
