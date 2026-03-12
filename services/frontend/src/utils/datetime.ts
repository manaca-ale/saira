export const BRAZIL_TIME_ZONE = "America/Sao_Paulo";

const NO_TIMEZONE_PATTERN =
  /^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$/;

export function parseSairaDate(value?: string | Date | null): Date {
  if (!value) return new Date(Number.NaN);
  if (value instanceof Date) return value;

  const raw = String(value).trim();
  if (!raw) return new Date(Number.NaN);

  const normalized = raw.includes(" ") ? raw.replace(" ", "T") : raw;
  const hasTimezone = /([zZ]|[+-]\d{2}:\d{2})$/.test(normalized);
  let target = normalized;

  if (!hasTimezone && NO_TIMEZONE_PATTERN.test(normalized)) {
    target = normalized.includes("T") ? `${normalized}-03:00` : `${normalized}T00:00:00-03:00`;
  }

  return new Date(target);
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
