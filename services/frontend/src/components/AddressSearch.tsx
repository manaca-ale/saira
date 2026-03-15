import React, { useState, useRef, useCallback } from "react";
import type { GeocodingResult } from "../types/geocoding";
import { searchAddress } from "../services/geocodingService";

interface AddressSearchProps {
  onSelect: (result: GeocodingResult) => void;
  disabled?: boolean;
}

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 3;

export const AddressSearch: React.FC<AddressSearchProps> = ({ onSelect, disabled }) => {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<GeocodingResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);
    setError(null);

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.length < MIN_QUERY_LENGTH) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setIsLoading(true);
      try {
        const results = await searchAddress(value);
        setSuggestions(results);
        setIsOpen(true);
        if (results.length === 0) setError("Endereço não encontrado.");
      } catch {
        setError("Serviço de busca indisponível. Insira as coordenadas manualmente.");
        setSuggestions([]);
        setIsOpen(false);
      } finally {
        setIsLoading(false);
      }
    }, DEBOUNCE_MS);
  }, []);

  const handleSelect = (result: GeocodingResult) => {
    setQuery(result.display_name);
    setSuggestions([]);
    setIsOpen(false);
    setError(null);
    onSelect(result);
  };

  return (
    <div className="relative col-span-2">
      <label className="text-sm font-bold text-gray-700 select-none ml-1">
        Buscar por endereço
      </label>
      <div className="relative mt-1.5">
        <input
          type="text"
          value={query}
          onChange={handleChange}
          disabled={disabled}
          placeholder="Ex: Rua das Flores, Boa Viagem, Recife"
          className="w-full bg-[#f3f4f6] border border-transparent rounded-xl py-3 pl-4 pr-10 text-[#1a1a1a] placeholder-gray-400 outline-none focus:bg-white focus:border-gray-300 transition-all"
        />
        {isLoading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
            Buscando...
          </span>
        )}
      </div>

      {error && (
        <p className="mt-1 text-xs text-red-500 ml-1">{error}</p>
      )}

      {isOpen && suggestions.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full rounded-xl border border-gray-200 bg-white shadow-lg max-h-52 overflow-y-auto text-sm">
          {suggestions.map((s, idx) => (
            <li
              key={idx}
              onClick={() => handleSelect(s)}
              className="cursor-pointer px-4 py-2.5 hover:bg-blue-50 border-b last:border-b-0"
            >
              {s.display_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
