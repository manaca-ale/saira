export const BRAZIL_TIME_ZONE = "America/Sao_Paulo";

export function parseSairaDate(value?: string | Date | null): Date {
  if (!value) return new Date(Number.NaN);
  if (value instanceof Date) return value;

  const raw = String(value).trim();
  if (!raw) return new Date(Number.NaN);

  const normalized = raw.includes(" ") ? raw.replace(" ", "T") : raw;
  return new Date(normalized);
}

export function formatDateTimeBrazil(
  value?: string | Date | null,
  options?: Intl.DateTimeFormatOptions,
): string {
  const parsed = parseSairaDate(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pt-BR", {
    timeZone: BRAZIL_TIME_ZONE,
    ...options,
  });
}

export function toBrazilDateString(value?: string | Date | null): string {
  const parsed = parseSairaDate(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("sv-SE", { timeZone: BRAZIL_TIME_ZONE });
}

export function toBrazilTimeString(value?: string | Date | null): string {
  const parsed = parseSairaDate(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString("sv-SE", {
    timeZone: BRAZIL_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelativeSeconds(seconds: number): string {
  if (seconds < 5) return "agora há pouco";
  if (seconds < 60) return `há ${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes === 1) return "há 1 min";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return "há 1 h";
  return `há ${hours} h`;
}
