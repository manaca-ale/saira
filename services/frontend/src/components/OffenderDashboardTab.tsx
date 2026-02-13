import React, { useEffect, useState, useCallback } from "react";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  Legend,
} from "recharts";
import {
  Users,
  Repeat,
  AlertTriangle,
  Car,
  Cuboid,
  Info,
  Plus,
  Loader2,
} from "lucide-react";
import { Tooltip } from "./Tooltip";
import { RegisterOffenderModal } from "./RegisterOffenderModal";
import {
  getOffenderStats,
  getOffendersByType,
  getRecidivismByType,
  getOffenderVolumeByType,
  getWasteByOffenderType,
  getTopPlates,
  getVehicleColors,
} from "../services/offenderService";
import type {
  OffenderStats,
  OffendersByType,
  RecidivismByType,
  OffenderVolumeByType,
  WasteByOffenderType,
  TopPlate,
  VehicleColor,
  DashboardFilters,
} from "../services/offenderService";

// ── Colors ───────────────────────────────────────────────────────────

const TYPE_COLORS = ["#84cc16", "#a3e635", "#d9f99d", "#f97316", "#6b7280"];
const PIE_COLORS = ["#84cc16", "#a3e635", "#65a30d", "#d9f99d", "#ecfccb", "#f97316", "#6b7280"];

// ── Props ────────────────────────────────────────────────────────────

interface FilterState {
  dateStart: string;
  dateEnd: string;
  startTime: string;
  endTime: string;
  status: string[];
  logradouro: string;
  bairro: string;
  rpa: string[];
  tipoResiduo: string[];
  volMin: string;
  volMax: string;
  infratores: string[];
}

interface OffenderDashboardTabProps {
  filters: FilterState;
}

// ── Helpers ──────────────────────────────────────────────────────────

function buildApiFilters(f: FilterState): DashboardFilters {
  const params: DashboardFilters = {};
  if (f.dateStart) params.start_date = f.dateStart;
  if (f.dateEnd) params.end_date = f.dateEnd;
  if (f.logradouro) params.logradouro = f.logradouro;
  if (f.bairro) params.bairro = f.bairro;
  if (f.rpa.length === 1) params.rpa = f.rpa[0];
  return params;
}

// ── Component ────────────────────────────────────────────────────────

export const OffenderDashboardTab: React.FC<OffenderDashboardTabProps> = ({
  filters,
}) => {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<OffenderStats | null>(null);
  const [byType, setByType] = useState<OffendersByType[]>([]);
  const [recidivism, setRecidivism] = useState<RecidivismByType[]>([]);
  const [volumeByType, setVolumeByType] = useState<OffenderVolumeByType[]>([]);
  const [wasteByType, setWasteByType] = useState<WasteByOffenderType[]>([]);
  const [topPlates, setTopPlates] = useState<TopPlate[]>([]);
  const [vehicleColors, setVehicleColors] = useState<VehicleColor[]>([]);
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const apiFilters = buildApiFilters(filters);
      const [s, bt, r, v, w, tp, vc] = await Promise.all([
        getOffenderStats(apiFilters),
        getOffendersByType(apiFilters),
        getRecidivismByType(apiFilters),
        getOffenderVolumeByType(apiFilters),
        getWasteByOffenderType(apiFilters),
        getTopPlates(apiFilters),
        getVehicleColors(apiFilters),
      ]);
      setStats(s);
      setByType(bt);
      setRecidivism(r);
      setVolumeByType(v);
      setWasteByType(w);
      setTopPlates(tp);
      setVehicleColors(vc);
    } catch (err) {
      console.error("Error loading offender dashboard:", err);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Stacked bar data transform ─────────────────────────────────────
  const stackedData = React.useMemo(() => {
    const allWasteTypes = new Set<string>();
    wasteByType.forEach((item) =>
      item.waste_breakdown.forEach((wb) => allWasteTypes.add(wb.waste_type))
    );
    return wasteByType.map((item) => {
      const row: Record<string, unknown> = { name: item.offender_type };
      item.waste_breakdown.forEach((wb) => {
        row[wb.waste_type] = wb.count;
      });
      return row;
    });
  }, [wasteByType]);

  const allWasteTypes = React.useMemo(() => {
    const set = new Set<string>();
    wasteByType.forEach((item) =>
      item.waste_breakdown.forEach((wb) => set.add(wb.waste_type))
    );
    return Array.from(set);
  }, [wasteByType]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 size={32} className="animate-spin text-lime-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-[#1a1a1a]">
          Dashboard de Infratores
        </h2>
        <button
          onClick={() => setIsRegisterOpen(true)}
          className="h-10 px-4 bg-[#ccff33] hover:bg-[#bef026] text-[#1a1a1a] font-bold rounded-xl text-sm flex items-center gap-2 transition-colors"
        >
          <Plus size={16} />
          Cadastrar Infrator
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard
          label="Total de infratores"
          tooltip="Contagem de infratores unicos (por placa ou perfil)"
          value={stats?.total_offenders ?? 0}
          icon={<Users size={22} />}
          iconBg="bg-orange-100 text-orange-500"
        />
        <KpiCard
          label="Infratores reincidentes"
          tooltip="Infratores vistos em mais de 1 ocorrencia"
          value={stats?.recurrent_offenders ?? 0}
          icon={<Repeat size={22} />}
          iconBg="bg-lime-100 text-lime-600"
        />
        <KpiCard
          label="Alta reincidencia"
          tooltip="Infratores com 5 ou mais ocorrencias"
          value={stats?.high_recurrence ?? 0}
          icon={<AlertTriangle size={22} />}
          iconBg="bg-red-100 text-red-500"
        />
        <KpiCard
          label="Placas identificadas"
          tooltip="Placas unicas registradas nos avistamentos"
          value={stats?.identified_plates ?? 0}
          icon={<Car size={22} />}
          iconBg="bg-blue-100 text-blue-500"
        />
        <KpiCard
          label="Volume estimado"
          tooltip="Soma do volume estimado (m3) de todos os avistamentos"
          value={stats?.estimated_volume_m3 ?? 0}
          suffix="m3"
          icon={<Cuboid size={22} />}
          iconBg="bg-purple-100 text-purple-500"
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Donut: tipos de infratores */}
        <ChartCard title="Tipos de infratores">
          {byType.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={byType.map((d) => ({ name: d.type, value: d.count }))}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={90}
                  dataKey="value"
                  paddingAngle={2}
                >
                  {byType.map((_, i) => (
                    <Cell
                      key={i}
                      fill={TYPE_COLORS[i % TYPE_COLORS.length]}
                    />
                  ))}
                </Pie>
                <RechartsTooltip
                  contentStyle={{
                    borderRadius: "8px",
                    border: "none",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 11 }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </ChartCard>

        {/* Bar: reincidencia por tipo */}
        <ChartCard title="Reincidencia por tipo">
          {recidivism.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                data={recidivism.map((d) => ({
                  name: d.type,
                  val: d.recurrent_count,
                }))}
                barSize={24}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#e5e5e5"
                />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: "#666" }}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 12, fill: "#666" }}
                />
                <RechartsTooltip
                  cursor={{ fill: "transparent" }}
                  contentStyle={{
                    borderRadius: "8px",
                    border: "none",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  }}
                />
                <Bar dataKey="val" fill="#a3e635" radius={[4, 4, 4, 4]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </ChartCard>

        {/* Bar: volume descartado por tipo */}
        <ChartCard title="Volume descartado (m3)">
          {volumeByType.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                data={volumeByType.map((d) => ({
                  name: d.type,
                  val: d.total_volume_m3,
                }))}
                barSize={24}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#e5e5e5"
                />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: "#666" }}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 12, fill: "#666" }}
                />
                <RechartsTooltip
                  cursor={{ fill: "transparent" }}
                  contentStyle={{
                    borderRadius: "8px",
                    border: "none",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  }}
                />
                <Bar dataKey="val" fill="#84cc16" radius={[4, 4, 4, 4]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </ChartCard>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stacked Bar: tipo lixo por infrator */}
        <ChartCard title="Tipo de lixo por infrator">
          {stackedData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={stackedData} barSize={24}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#e5e5e5"
                />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 10, fill: "#666" }}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 12, fill: "#666" }}
                />
                <RechartsTooltip
                  contentStyle={{
                    borderRadius: "8px",
                    border: "none",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 11 }}
                />
                {allWasteTypes.map((wt, i) => (
                  <Bar
                    key={wt}
                    dataKey={wt}
                    stackId="a"
                    fill={PIE_COLORS[i % PIE_COLORS.length]}
                    radius={
                      i === allWasteTypes.length - 1
                        ? [4, 4, 0, 0]
                        : [0, 0, 0, 0]
                    }
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </ChartCard>

        {/* Table: placas mais reincidentes */}
        <ChartCard title="Placas mais reincidentes">
          {topPlates.length > 0 ? (
            <div className="space-y-2">
              {topPlates.map((p, i) => (
                <div
                  key={p.plate}
                  className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-50"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-lime-100 text-lime-700 text-xs font-bold flex items-center justify-center">
                      {i + 1}
                    </span>
                    <span className="font-bold text-sm text-[#1a1a1a]">
                      {p.plate}
                    </span>
                  </div>
                  <span className="text-sm font-semibold text-gray-600">
                    {p.occurrences} ocorr.
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </ChartCard>

        {/* Pie: cor dos veiculos */}
        <ChartCard title="Cor dos veiculos">
          {vehicleColors.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={vehicleColors.map((d) => ({
                    name: d.color,
                    value: d.count,
                  }))}
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  dataKey="value"
                  paddingAngle={2}
                >
                  {vehicleColors.map((_, i) => (
                    <Cell
                      key={i}
                      fill={PIE_COLORS[i % PIE_COLORS.length]}
                    />
                  ))}
                </Pie>
                <RechartsTooltip
                  contentStyle={{
                    borderRadius: "8px",
                    border: "none",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 11 }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState />
          )}
        </ChartCard>
      </div>

      {/* Register Modal */}
      <RegisterOffenderModal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        onSuccess={() => {
          setIsRegisterOpen(false);
          loadData();
        }}
      />
    </div>
  );
};

// ── Sub-components ───────────────────────────────────────────────────

const KpiCard: React.FC<{
  label: string;
  tooltip: string;
  value: number;
  suffix?: string;
  icon: React.ReactNode;
  iconBg: string;
}> = ({ label, tooltip, value, suffix, icon, iconBg }) => (
  <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 flex flex-col justify-between min-h-[120px]">
    <div className="flex items-center gap-2">
      <span className="text-gray-500 text-[10px] font-medium uppercase leading-tight">
        {label}
      </span>
      <Tooltip content={tooltip}>
        <Info size={12} className="text-gray-400 cursor-pointer" />
      </Tooltip>
    </div>
    <div className="flex items-center gap-3 mt-2">
      <div
        className={`w-10 h-10 rounded-full flex items-center justify-center ${iconBg}`}
      >
        {icon}
      </div>
      <div className="flex items-baseline">
        <span className="text-3xl font-bold text-[#1a1a1a]">
          {typeof value === "number" && !Number.isInteger(value)
            ? value.toLocaleString("pt-BR", { maximumFractionDigits: 0 })
            : value.toLocaleString("pt-BR")}
        </span>
        {suffix && (
          <span className="text-xs text-gray-500 font-medium ml-1">
            {suffix}
          </span>
        )}
      </div>
    </div>
  </div>
);

const ChartCard: React.FC<{
  title: string;
  children: React.ReactNode;
}> = ({ title, children }) => (
  <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
    <h3 className="font-bold text-gray-800 text-sm mb-4">{title}</h3>
    {children}
  </div>
);

const EmptyState: React.FC = () => (
  <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
    Sem dados para exibir
  </div>
);
