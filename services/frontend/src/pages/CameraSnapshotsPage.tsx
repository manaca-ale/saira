import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  CalendarClock,
  ImageOff,
  MapPin,
  RefreshCw,
  Search,
} from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import { CameraDetailsModal } from "../components/CameraDetailsModal";
import {
  getCameras,
  getLatestCameraImageFromFolder,
  type Camera as CameraEntity,
  type CameraLatestImage,
} from "../services/cameraService";
import { formatDateTimeBrazil } from "../utils/datetime";

const POLLING_INTERVAL_MS = 30_000;

type SnapshotMap = Record<number, CameraLatestImage | null>;

const formatTimestamp = (value?: string | null): string => {
  const formatted = formatDateTimeBrazil(value, {
    dateStyle: "short",
    timeStyle: "short",
  });
  return formatted === "—" ? "Sem registro" : formatted;
};

const formatRelativeSeconds = (seconds: number): string => {
  if (seconds < 5) return "agora há pouco";
  if (seconds < 60) return `há ${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes === 1) return "há 1 min";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return "há 1 h";
  return `há ${hours} h`;
};

const uniqueSorted = (values: (string | null | undefined)[]): string[] => {
  const set = new Set<string>();
  for (const v of values) {
    if (v && v.trim()) set.add(v.trim());
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "pt-BR"));
};

export const CameraSnapshotsPage: React.FC = () => {
  const [cameras, setCameras] = useState<CameraEntity[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotMap>({});
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);
  const [now, setNow] = useState<Date>(new Date());

  const [search, setSearch] = useState("");
  const [filterRpa, setFilterRpa] = useState<string>("");
  const [filterBairro, setFilterBairro] = useState<string>("");
  const [onlyActive, setOnlyActive] = useState(true);
  const [brokenImages, setBrokenImages] = useState<Set<number>>(new Set());

  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState(false);
  const [isDetailsModalClosing, setIsDetailsModalClosing] = useState(false);
  const [detailsCamera, setDetailsCamera] = useState<CameraEntity | null>(null);

  const camerasRef = useRef<CameraEntity[]>([]);
  camerasRef.current = cameras;

  const fetchSnapshots = async (list: CameraEntity[]): Promise<SnapshotMap> => {
    const entries = await Promise.all(
      list.map(async (camera): Promise<[number, CameraLatestImage | null]> => {
        try {
          const latest = await getLatestCameraImageFromFolder(camera.id);
          return [camera.id, latest];
        } catch (error) {
          console.error(`Failed to load snapshot for camera ${camera.id}:`, error);
          return [camera.id, null];
        }
      }),
    );
    return Object.fromEntries(entries) as SnapshotMap;
  };

  const refreshSnapshots = async (): Promise<void> => {
    const list = camerasRef.current;
    if (list.length === 0) return;
    setIsRefreshing(true);
    try {
      const next = await fetchSnapshots(list);
      setSnapshots(next);
      setBrokenImages(new Set());
      setLastRefreshAt(new Date());
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      try {
        const list = await getCameras({ limit: 100 });
        if (cancelled) return;
        setCameras(list);
        const initialSnapshots = await fetchSnapshots(list);
        if (cancelled) return;
        setSnapshots(initialSnapshots);
        setLastRefreshAt(new Date());
      } catch (error) {
        console.error("Failed to load cameras:", error);
      } finally {
        if (!cancelled) setIsInitialLoading(false);
      }
    };
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (isInitialLoading) return;
    const interval = window.setInterval(() => {
      refreshSnapshots();
    }, POLLING_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [isInitialLoading]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  const rpaOptions = useMemo(() => uniqueSorted(cameras.map((c) => c.rpa)), [cameras]);
  const bairroOptions = useMemo(
    () => uniqueSorted(cameras.map((c) => c.bairro)),
    [cameras],
  );

  const filteredCameras = useMemo(() => {
    const term = search.trim().toLowerCase();
    return cameras.filter((camera) => {
      if (onlyActive && !camera.is_active) return false;
      if (filterRpa && (camera.rpa || "") !== filterRpa) return false;
      if (filterBairro && (camera.bairro || "") !== filterBairro) return false;
      if (term) {
        const haystack = `${camera.name} ${camera.device_id || ""}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [cameras, search, filterRpa, filterBairro, onlyActive]);

  const sortedCameras = useMemo(() => {
    const withSnapshot = [...filteredCameras];
    withSnapshot.sort((a, b) => {
      const sa = snapshots[a.id]?.captured_at || null;
      const sb = snapshots[b.id]?.captured_at || null;
      if (sa && sb) return sb.localeCompare(sa);
      if (sa) return -1;
      if (sb) return 1;
      return a.name.localeCompare(b.name, "pt-BR");
    });
    return withSnapshot;
  }, [filteredCameras, snapshots]);

  const openDetailsModal = (camera: CameraEntity) => {
    setDetailsCamera(camera);
    setIsDetailsModalClosing(false);
    setIsDetailsModalOpen(true);
  };

  const closeDetailsModal = () => {
    setIsDetailsModalClosing(true);
    window.setTimeout(() => {
      setIsDetailsModalOpen(false);
      setIsDetailsModalClosing(false);
      setDetailsCamera(null);
    }, 500);
  };

  const handleManualRefresh = () => {
    if (isRefreshing) return;
    refreshSnapshots();
  };

  const lastRefreshLabel = lastRefreshAt
    ? `Atualizado ${formatRelativeSeconds(
        Math.max(0, Math.floor((now.getTime() - lastRefreshAt.getTime()) / 1000)),
      )}`
    : "Aguardando primeira atualização...";

  return (
    <div className="flex h-full bg-[#f8f9fa] font-sans relative">
      <Sidebar />

      <style>{`
        @keyframes modalPop {
          0% { opacity: 0; transform: scale(0.8) translateY(50px); }
          100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes modalPopExit {
          0% { opacity: 1; transform: scale(1) translateY(0); }
          100% { opacity: 0; transform: scale(0.8) translateY(50px); }
        }
      `}</style>

      <main className="flex-1 ml-20 p-8 h-full overflow-y-auto overflow-x-hidden relative">
        <div className="flex justify-between items-start mb-8 gap-4">
          <div>
            <p className="text-sm text-gray-500 mb-1">Monitoramento</p>
            <h1 className="text-3xl font-bold text-[#1a1a1a]">
              Painel de Câmeras
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Última imagem registrada por cada câmera. {lastRefreshLabel}.
            </p>
          </div>
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isRefreshing || isInitialLoading}
            className="h-[50px] px-5 bg-[#ccff33] rounded-xl hover:bg-[#b8e62e] disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors flex items-center gap-2 text-black shadow-sm font-semibold text-sm"
          >
            <RefreshCw
              size={18}
              className={isRefreshing ? "animate-spin" : ""}
              strokeWidth={2.5}
            />
            Atualizar agora
          </button>
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="relative">
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Buscar
              </label>
              <div className="relative mt-1">
                <Search
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Nome ou device_id"
                  className="w-full h-11 pl-9 pr-3 rounded-xl border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:border-[#ccff33] focus:bg-white transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                RPA
              </label>
              <select
                value={filterRpa}
                onChange={(e) => setFilterRpa(e.target.value)}
                aria-label="Filtrar por RPA"
                className="mt-1 w-full h-11 px-3 rounded-xl border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:border-[#ccff33] focus:bg-white transition-colors"
              >
                <option value="">Todas</option>
                {rpaOptions.map((rpa) => (
                  <option key={rpa} value={rpa}>
                    {rpa}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Bairro
              </label>
              <select
                value={filterBairro}
                onChange={(e) => setFilterBairro(e.target.value)}
                aria-label="Filtrar por bairro"
                className="mt-1 w-full h-11 px-3 rounded-xl border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:border-[#ccff33] focus:bg-white transition-colors"
              >
                <option value="">Todos</option>
                {bairroOptions.map((bairro) => (
                  <option key={bairro} value={bairro}>
                    {bairro}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col">
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Status
              </label>
              <label className="mt-1 inline-flex items-center gap-3 h-11 px-3 rounded-xl border border-gray-200 bg-gray-50 cursor-pointer hover:bg-white transition-colors">
                <input
                  type="checkbox"
                  checked={onlyActive}
                  onChange={(e) => setOnlyActive(e.target.checked)}
                  className="w-4 h-4 accent-[#a3e635] cursor-pointer"
                />
                <span className="text-sm text-gray-700">
                  Somente câmeras ativas
                </span>
              </label>
            </div>
          </div>

          <div className="mt-4 text-xs text-gray-500">
            {isInitialLoading
              ? "Carregando câmeras..."
              : `${sortedCameras.length} de ${cameras.length} câmera${
                  cameras.length === 1 ? "" : "s"
                }`}
          </div>
        </div>

        {isInitialLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden animate-pulse"
              >
                <div className="aspect-video bg-gray-100" />
                <div className="p-4 space-y-2">
                  <div className="h-4 bg-gray-100 rounded w-3/4" />
                  <div className="h-3 bg-gray-100 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : sortedCameras.length === 0 ? (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center text-gray-500">
            Nenhuma câmera encontrada com os filtros atuais.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {sortedCameras.map((camera) => {
              const snapshot = snapshots[camera.id] || null;
              const rawImageUrl = snapshot?.image_url || null;
              const imageUrl =
                rawImageUrl && !brokenImages.has(camera.id) ? rawImageUrl : null;
              const capturedAt = snapshot?.captured_at || null;

              return (
                <button
                  type="button"
                  key={camera.id}
                  onClick={() => openDetailsModal(camera)}
                  className="text-left bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-md hover:border-gray-200 transition-all group"
                >
                  <div className="aspect-video bg-gray-100 relative overflow-hidden">
                    {imageUrl ? (
                      <img
                        src={imageUrl}
                        alt={`Última foto da câmera ${camera.name}`}
                        loading="lazy"
                        onError={() =>
                          setBrokenImages((prev) => {
                            if (prev.has(camera.id)) return prev;
                            const next = new Set(prev);
                            next.add(camera.id);
                            return next;
                          })
                        }
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                    ) : (
                      <div className="w-full h-full flex flex-col items-center justify-center text-gray-400 gap-2">
                        <ImageOff size={28} />
                        <span className="text-xs font-medium">
                          Sem foto disponível
                        </span>
                      </div>
                    )}
                    <span
                      className={`absolute top-2 right-2 inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold backdrop-blur-sm ${
                        camera.is_active
                          ? "bg-emerald-100/90 text-emerald-700"
                          : "bg-gray-200/90 text-gray-600"
                      }`}
                    >
                      <Activity size={10} />
                      {camera.is_active ? "Ativa" : "Inativa"}
                    </span>
                  </div>

                  <div className="p-4">
                    <h3 className="text-sm font-bold text-[#1a1a1a] truncate">
                      {camera.name}
                    </h3>
                    {camera.device_id ? (
                      <p className="text-xs text-gray-400 truncate font-mono">
                        {camera.device_id}
                      </p>
                    ) : null}

                    <div className="mt-3 space-y-1.5 text-xs text-gray-600">
                      <div className="flex items-start gap-1.5">
                        <MapPin
                          size={12}
                          className="mt-0.5 text-gray-400 shrink-0"
                        />
                        <span className="truncate">
                          {[camera.bairro, camera.rpa]
                            .filter(Boolean)
                            .join(" · ") || "Local não informado"}
                        </span>
                      </div>
                      <div className="flex items-start gap-1.5">
                        <CalendarClock
                          size={12}
                          className="mt-0.5 text-gray-400 shrink-0"
                        />
                        <span className="truncate">
                          {capturedAt
                            ? formatTimestamp(capturedAt)
                            : "Sem captura registrada"}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {isDetailsModalOpen && detailsCamera ? (
          <CameraDetailsModal
            camera={detailsCamera}
            latestCameraImage={snapshots[detailsCamera.id] || null}
            isLoadingLatest={false}
            isClosing={isDetailsModalClosing}
            onClose={closeDetailsModal}
          />
        ) : null}
      </main>
    </div>
  );
};
