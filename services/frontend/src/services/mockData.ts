export type WasteType = "Entulho" | "Lixo domiciliar" | "Poda" | "Plástico";

export type DetectionValidityStatus =
  | "Pendente"
  | "Confirmado"
  | "Rejeitado"
  | "Indeterminado";

export type PoiData = {
  id: string;
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
  timestamp: string;
  wasteType: WasteType;
  volume: number; // Volume in m³
  status: DetectionValidityStatus;
  photoUrl: string;
  hasOffender: boolean;
  validityComment?: string;
};

type SeedLocation = {
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
};

const seedLocations: SeedLocation[] = [
  {
    bairro: "Imbiribeira",
    logradouro: "Rua Visconde de Suassuna",
    latitude: -8.1122,
    longitude: -34.9026,
  },
  {
    bairro: "Brasília Teimosa",
    logradouro: "Av. Brasília Formosa",
    latitude: -8.0848,
    longitude: -34.8876,
  },
  {
    bairro: "Santo Amaro",
    logradouro: "Rua do Pombal",
    latitude: -8.0435,
    longitude: -34.8906,
  },
  {
    bairro: "Prado",
    logradouro: "Rua Abdias de Carvalho",
    latitude: -8.0617,
    longitude: -34.9123,
  },
  {
    bairro: "Porto da Madeira",
    logradouro: "Av. Beberibe",
    latitude: -8.0163,
    longitude: -34.8856,
  },
  {
    bairro: "Ilha de Deus",
    logradouro: "Ponte Paulo Guerra",
    latitude: -8.0934,
    longitude: -34.9073,
  },
  {
    bairro: "Torrões",
    logradouro: "Rua Onze de Fevereiro",
    latitude: -8.0673,
    longitude: -34.9318,
  },
  {
    bairro: "Várzea",
    logradouro: "Praça da Várzea",
    latitude: -8.0531,
    longitude: -34.9545,
  },
  {
    bairro: "Jiquiá",
    logradouro: "Rua João Teixeira",
    latitude: -8.0825,
    longitude: -34.9213,
  },
];

const WASTE_TYPES: WasteType[] = [
  "Entulho",
  "Lixo domiciliar",
  "Poda",
  "Plástico",
];

const PHOTO_URLS = [
  "https://placehold.co/600x400/ef4444/FFFFFF?text=Foto+1",
  "https://placehold.co/600x400/3b82f6/FFFFFF?text=Foto+2",
  "https://placehold.co/600x400/f97316/FFFFFF?text=Foto+3",
  "https://placehold.co/600x400/22c55e/FFFFFF?text=Foto+4",
  "https://placehold.co/600x400/8b5cf6/FFFFFF?text=Foto+5",
  "https://placehold.co/600x400/0ea5e9/FFFFFF?text=Foto+6",
  "https://placehold.co/600x400/facc15/1f2937?text=Foto+7",
  "https://placehold.co/600x400/14b8a6/FFFFFF?text=Foto+8",
  "https://placehold.co/600x400/64748b/FFFFFF?text=Foto+9",
];

const randomInt = (min: number, max: number) =>
  Math.floor(Math.random() * (max - min + 1)) + min;

const randomItem = <T,>(items: T[]) => items[randomInt(0, items.length - 1)];

const buildRandomTimestamp = (year: number, monthIndex: number) => {
  const start = new Date(Date.UTC(year, monthIndex, 1, 0, 0, 0));
  const end = new Date(Date.UTC(year, monthIndex + 1, 0, 23, 59, 59));
  const range = end.getTime() - start.getTime();
  const offset = randomInt(0, range);
  return new Date(start.getTime() + offset).toISOString();
};

const getStatusForDate = (year: number, monthIndex: number): DetectionValidityStatus => {
  if (year === 2025) return "Confirmado";
  if (year === 2026 && monthIndex === 0) {
    return randomItem([
      "Pendente",
      "Confirmado",
      "Rejeitado",
      "Indeterminado",
    ] as const);
  }
  return "Confirmado";
};

const generateMockData = (): PoiData[] => {
  const results: PoiData[] = [];
  let counter = 1;

  for (const location of seedLocations) {
    for (let year = 2025; year <= 2026; year += 1) {
      const startMonth = year === 2025 ? 0 : 0;
      const endMonth = year === 2025 ? 11 : 0;

      for (let month = startMonth; month <= endMonth; month += 1) {
        for (let i = 0; i < 10; i += 1) {
          results.push({
            id: `SAIRA-${String(counter).padStart(4, "0")}`,
            bairro: location.bairro,
            logradouro: location.logradouro,
            latitude: location.latitude,
            longitude: location.longitude,
            timestamp: buildRandomTimestamp(year, month),
            wasteType: randomItem(WASTE_TYPES),
            volume: randomInt(10, 100),
            status: getStatusForDate(year, month),
            photoUrl: randomItem(PHOTO_URLS),
            hasOffender: Math.random() < 0.5,
          });
          counter += 1;
        }
      }
    }
  }

  return results;
};

export const masterPois: PoiData[] = generateMockData();
