import React, { useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Tooltip } from "../components/Tooltip";
import { Info, ArrowUpRight, ArrowDownRight, Loader2, Lock } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  Cell,
} from "recharts";
import {
  getIndicatorsSummary,
  getSurveillanceReliability,
  getAlertSpeed,
  getDetectionAccuracy,
  getDossierCompleteness,
  getIdentificationQuality,
} from "../services/indicatorService";
import type {
  IndicatorsSummary,
  IndicatorCard,
  SurveillanceReliability,
  AlertSpeed,
  DetectionAccuracy,
  DossierCompleteness,
  IdentificationQuality,
} from "../services/indicatorService";
import { toBrazilDateString } from "../utils/datetime";

// Descrição oficial de cada indicador (Anexo II — aba INDICADORES AJUSTADO).
const DESCRIPTIONS: Record<string, string> = {
  I1: "% do tempo em que cada ponto crítico está efetivamente sob vigilância (transmitindo dados). Média dos pontos e pior ponto do período.",
  I2: "Tempo, em segundos, entre o flagrante do descarte e o alerta. Reportado como mediana (p50) e p95.",
  I3: "% de ocorrências em que o sistema extraiu imagem do infrator (pessoa e/ou veículo), quando presentes no frame.",
  I4: "Taxa de ocorrências confirmadas sobre o total avaliado. Leitura do modelo (cascata de duas análises) e da confirmação humana (fiscal).",
  I5: "De cada 100 ocorrências, quantas têm todos os campos do dossiê: foto, local, data/hora, tipo e volume estimado.",
  I6: "Percentual de ações realizadas sobre as detecções. Depende de ação externa do fiscal — não rastreável pela plataforma.",
};

const fmtValue = (v: number | null | undefined, unit: string): string => {
  if (v === null || v === undefined) return "—";
  if (unit === "%") return `${v.toFixed(1)}%`;
  if (unit === "s") return `${v.toFixed(0)}s`;
  return `${v}`;
};

const daysAgo = (n: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toBrazilDateString(d);
};

const KpiCard: React.FC<{ card: IndicatorCard }> = ({ card }) => {
  const disabled = !card.trackable;
  const Polarity = card.polarity === "higher_better" ? ArrowUpRight : ArrowDownRight;
  return (
    <div
      className={`bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[150px] ${
        disabled ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-[#65a30d] bg-[#ecfccb] px-2 py-0.5 rounded">
            {card.id}
          </span>
          <span className="text-gray-600 text-xs font-semibold uppercase leading-tight">
            {card.name}
          </span>
        </div>
        <Tooltip content={DESCRIPTIONS[card.id] || ""}>
          <Info size={14} className="text-gray-400 cursor-pointer shrink-0" />
        </Tooltip>
      </div>

      <div className="mt-3">
        {disabled ? (
          <div className="flex items-center gap-2 text-gray-400">
            <Lock size={18} />
            <span className="text-sm font-medium">{card.value_label}</span>
          </div>
        ) : !card.has_data ? (
          <span className="text-2xl font-bold text-gray-300">Sem dados no período</span>
        ) : (
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="text-4xl font-bold text-[#1a1a1a]">
              {fmtValue(card.value, card.unit)}
            </span>
            {card.value_label && (
              <span className="text-xs text-gray-400">{card.value_label}</span>
            )}
            {card.secondary !== null && card.secondary !== undefined && (
              <span className="text-sm text-gray-500">
                {card.secondary_label ? `${card.secondary_label}: ` : ""}
                {fmtValue(card.secondary, card.unit)}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center gap-1 text-[11px] text-gray-400">
        <Polarity size={13} />
        <span>{card.polarity === "higher_better" ? "maior é melhor" : "menor é melhor"}</span>
        <span className="ml-auto">{card.periodicity}</span>
      </div>
    </div>
  );
};

const Panel: React.FC<{ title: string; hint?: string; children: React.ReactNode }> = ({
  title,
  hint,
  children,
}) => (
  <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
    <div className="flex justify-between items-center mb-4">
      <h3 className="font-bold text-gray-800 text-sm">{title}</h3>
      {hint && (
        <Tooltip content={hint}>
          <Info size={16} className="text-gray-400 cursor-pointer" />
        </Tooltip>
      )}
    </div>
    {children}
  </div>
);

export const IndicadoresPage: React.FC = () => {
  const [start, setStart] = useState<string>(daysAgo(29));
  const [end, setEnd] = useState<string>(daysAgo(0));
  const [loading, setLoading] = useState(false);

  const [summary, setSummary] = useState<IndicatorsSummary | null>(null);
  const [i1, setI1] = useState<SurveillanceReliability | null>(null);
  const [i2, setI2] = useState<AlertSpeed | null>(null);
  const [i3, setI3] = useState<IdentificationQuality | null>(null);
  const [i4, setI4] = useState<DetectionAccuracy | null>(null);
  const [i5, setI5] = useState<DossierCompleteness | null>(null);

  const { isAuthenticated, loading: authLoading } = useAuth();

  const range = useMemo(() => ({ start, end }), [start, end]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getIndicatorsSummary(range),
      getSurveillanceReliability(range),
      getAlertSpeed(range),
      getIdentificationQuality(range),
      getDetectionAccuracy(range),
      getDossierCompleteness(range),
    ])
      .then(([s, r1, r2, r3, r4, r5]) => {
        if (cancelled) return;
        setSummary(s);
        setI1(r1);
        setI2(r2);
        setI3(r3);
        setI4(r4);
        setI5(r5);
      })
      .catch((e) => {
        // eslint-disable-next-line no-console
        console.error("Erro ao carregar indicadores", e);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, isAuthenticated]);

  const setQuickRange = (days: number) => {
    setStart(daysAgo(days - 1));
    setEnd(daysAgo(0));
  };

  const i1ChartData = (i1?.cameras || [])
    .filter((c) => c.uptime_pct !== null)
    .map((c) => ({ name: c.name || c.device_id || `cam ${c.camera_id}`, val: c.uptime_pct as number }));

  // Humano (fiscal) em destaque; modelo (cascata) em segundo plano.
  const i4ChartData =
    i4 && (i4.human.has_data || i4.model.has_data)
      ? [
          { name: "Humano (fiscal)", val: i4.human.accuracy_pct ?? 0, primary: true },
          { name: "Modelo (cascata)", val: i4.model.accuracy_pct ?? 0, primary: false },
        ]
      : [];

  const i5MissingData = i5
    ? [
        { name: "Foto", val: i5.missing_photo },
        { name: "Local", val: i5.missing_location },
        { name: "Data/hora", val: i5.missing_datetime },
        { name: "Tipo", val: i5.missing_waste_type },
        { name: "Volume", val: i5.missing_volume },
      ]
    : [];

  // Página standalone, mas restrita: exige login (sem o menu lateral do app).
  if (authLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#f8f9fa]">
        <Loader2 className="animate-spin text-gray-400" size={28} />
      </div>
    );
  }
  if (!isAuthenticated) {
    // Preserva o destino para o login retornar aqui após autenticar.
    return <Navigate to={`/login?next=${encodeURIComponent("/indicadores")}`} replace />;
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f8f9fa] font-sans">
      <main className="max-w-7xl mx-auto p-4 md:p-8">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-bold text-[#1a1a1a]">Indicadores de Resultado</h1>
          {loading && <Loader2 className="animate-spin text-gray-400" size={20} />}
        </div>
        <p className="text-sm text-gray-500 mb-6">
          Acompanhamento vivo dos indicadores do projeto (Anexo II), calculados a partir dos dados
          reais da plataforma.
        </p>

        {/* Period selector */}
        <div className="flex flex-wrap items-end gap-4 mb-8 bg-white border border-gray-200 rounded-2xl shadow-sm p-4">
          <div className="flex flex-col">
            <label className="text-xs text-gray-500 mb-1">Início</label>
            <input
              type="date"
              aria-label="Data de início"
              value={start}
              max={end}
              onChange={(e) => setStart(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col">
            <label className="text-xs text-gray-500 mb-1">Fim</label>
            <input
              type="date"
              aria-label="Data de fim"
              value={end}
              min={start}
              max={daysAgo(0)}
              onChange={(e) => setEnd(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setQuickRange(7)}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-50 hover:bg-[#e9fbc0] border border-gray-200"
            >
              7 dias
            </button>
            <button
              type="button"
              onClick={() => setQuickRange(30)}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-50 hover:bg-[#e9fbc0] border border-gray-200"
            >
              30 dias
            </button>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
          {summary?.cards.map((card) => (
            <KpiCard key={card.id} card={card} />
          ))}
        </div>

        {/* Detail panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-8">
          {/* I1 — per-camera uptime */}
          <Panel
            title="I1 — Confiabilidade por ponto (%)"
            hint="Uptime de cada câmera ativa no período. A barra mostra o % do tempo transmitindo."
          >
            {i1ChartData.length === 0 ? (
              <p className="text-sm text-gray-400 py-10 text-center">
                Sem heartbeats no período (a série começa a partir do deploy).
              </p>
            ) : (
              <div className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={i1ChartData} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e5e5e5" />
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
                    <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
                    <RechartsTooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
                    <Bar dataKey="val" radius={[0, 4, 4, 0]}>
                      {i1ChartData.map((d, i) => (
                        <Cell key={i} fill={d.val >= 90 ? "#a3e635" : d.val >= 70 ? "#fbbf24" : "#f87171"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* I2 — latency breakdown */}
          <Panel
            title="I2 — Velocidade do alerta (s)"
            hint="Latência do flagrante até o alerta. Reportada até o registro e até a notificação."
          >
            <div className="grid grid-cols-2 gap-4">
              {i2?.breakdown.map((b) => (
                <div key={b.label} className="border border-gray-100 rounded-xl p-4">
                  <p className="text-xs text-gray-500 mb-2 capitalize">{b.label}</p>
                  <div className="flex items-baseline gap-2">
                    <span className="text-3xl font-bold text-[#1a1a1a]">
                      {b.p50_seconds !== null ? `${b.p50_seconds.toFixed(0)}s` : "—"}
                    </span>
                    <span className="text-xs text-gray-400">p50</span>
                  </div>
                  <div className="flex items-baseline gap-2 mt-1">
                    <span className="text-lg font-semibold text-gray-600">
                      {b.p95_seconds !== null ? `${b.p95_seconds.toFixed(0)}s` : "—"}
                    </span>
                    <span className="text-xs text-gray-400">p95</span>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-2">{b.sample_size} amostras</p>
                </div>
              ))}
            </div>
          </Panel>

          {/* I4 — human (destaque) vs model (segundo plano) */}
          <Panel
            title="I4 — Assertividade: humano vs modelo (%)"
            hint="Humano (destaque): confirmadas/(confirmadas+rejeitadas) pelo fiscal. Modelo (referência): confirmadas/(confirmadas+rejeitadas) na cascata Agent-1+Agent-2."
          >
            {i4ChartData.length === 0 ? (
              <p className="text-sm text-gray-400 py-10 text-center">Sem avaliações no período.</p>
            ) : (
              <>
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={i4ChartData} barSize={48}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e5e5" />
                      <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
                      <RechartsTooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
                      <Bar dataKey="val" radius={[4, 4, 0, 0]}>
                        {i4ChartData.map((d, i) => (
                          <Cell key={i} fill={d.primary ? "#a3e635" : "#d1d5db"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="grid grid-cols-2 gap-4 mt-3 text-xs">
                  <span className="text-gray-700 font-semibold">
                    Humano: {i4?.human.confirmed} conf. / {i4?.human.rejected} rej.
                  </span>
                  <span className="text-gray-400">
                    Modelo: {i4?.model.confirmed} conf. / {i4?.model.rejected} rej.
                  </span>
                </div>
              </>
            )}
          </Panel>

          {/* I5 — missing dossier fields + I3 */}
          <Panel
            title="I5 — Campos faltantes no dossiê"
            hint="Quantas ocorrências confirmadas faltam cada campo. Quanto menor, mais completo o dossiê."
          >
            <div className="flex items-baseline gap-3 mb-3">
              <span className="text-3xl font-bold text-[#1a1a1a]">
                {i5?.completeness_pct !== null && i5?.completeness_pct !== undefined
                  ? `${i5.completeness_pct.toFixed(1)}%`
                  : "—"}
              </span>
              <span className="text-xs text-gray-400">
                {i5?.complete}/{i5?.total} dossiês completos
              </span>
            </div>
            <div className="h-[180px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={i5MissingData} barSize={32}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e5e5" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <RechartsTooltip />
                  <Bar dataKey="val" fill="#f87171" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-4 pt-3 border-t border-gray-100 text-xs text-gray-500">
              <span className="font-semibold text-gray-700">I3 — Identificação: </span>
              {i3?.has_data
                ? `${i3.quality_pct?.toFixed(1)}% (${i3.crops_extracted}/${i3.offenders_present} infratores com recorte extraído)`
                : "sem infratores presentes no período"}
            </div>
          </Panel>
        </div>
      </main>
    </div>
  );
};

export default IndicadoresPage;
