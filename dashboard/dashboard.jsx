import React, { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Label,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  ArrowDownRight,
  CheckCircle2,
  Clock3,
  DollarSign,
  Gauge,
  Leaf,
  ShieldCheck,
  TrendingDown,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const COLORS = {
  primaryGreen: "#2D7D46",
  alertRed: "#C0392B",
  neutralGray: "#6B7280",
  background: "#F8FAF9",
  socBlue: "#1B4F72",
  warningOrange: "#D97706",
  softGreen: "#E6F4EA",
  softRed: "#FDECEC",
  softBlue: "#EAF2F8",
  grid: "rgba(107, 114, 128, 0.3)",
};

const baselineCost = 914738;
const milpCost = 686947;
const monthlySavings = baselineCost - milpCost;
const savingsRate = monthlySavings / baselineCost;

const monthNames = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const heroMetrics = [
  {
    title: "無系統每月電費",
    value: baselineCost,
    label: "B1 無電池基準",
    tone: "red",
    icon: DollarSign,
  },
  {
    title: "MILP 系統電費",
    value: milpCost,
    label: "本系統",
    tone: "green",
    icon: CheckCircle2,
  },
  {
    title: "每月節省",
    value: monthlySavings,
    label: "相較 B1 基準",
    tone: "dominant",
    icon: ArrowDownRight,
    badge: `-${(savingsRate * 100).toFixed(1)}%`,
  },
  {
    title: "PV 利用率",
    value: 0.915,
    label: "太陽能有效利用",
    tone: "blue",
    icon: Leaf,
    progress: 91.5,
  },
];

const waterfallData = [
  {
    name: "無系統",
    base: 0,
    amount: baselineCost,
    display: baselineCost,
    fill: COLORS.alertRed,
    type: "start",
  },
  {
    name: "購電電費節省",
    base: baselineCost - 144000,
    amount: 144000,
    display: -144000,
    fill: COLORS.primaryGreen,
    type: "saving",
  },
  {
    name: "需量費節省",
    base: baselineCost - 144000 - 63000,
    amount: 63000,
    display: -63000,
    fill: COLORS.primaryGreen,
    type: "saving",
  },
  {
    name: "超約罰款差異",
    base: milpCost,
    amount: 20791,
    display: -20791,
    fill: COLORS.primaryGreen,
    type: "saving",
  },
  {
    name: "MILP 系統",
    base: 0,
    amount: milpCost,
    display: milpCost,
    fill: "#1F6B3B",
    type: "end",
  },
];

const strategyComparison = [
  { id: "B5", name: "B5 保守 SOC", cost: 2630131, color: COLORS.neutralGray },
  { id: "B3", name: "B3 負載門檻", cost: 1399217, color: COLORS.neutralGray },
  { id: "B2", name: "B2 TOU 規則", cost: 1266444, color: COLORS.neutralGray },
  { id: "B1", name: "B1 無電池", cost: baselineCost, color: COLORS.neutralGray },
  { id: "B4", name: "B4 再生能源優先", cost: 815081, color: COLORS.neutralGray },
  { id: "MILP", name: "Advanced EMS (MILP)", cost: milpCost, color: COLORS.primaryGreen },
].sort((a, b) => b.cost - a.cost);

const monthlySummary = monthNames.map((month, index) => {
  const seasonal = index >= 5 && index <= 8 ? 1.08 : index >= 10 || index <= 1 ? 0.86 : 0.98;
  const b1 = Math.round(baselineCost * seasonal * (0.97 + (index % 4) * 0.018));
  const milp = Math.round(b1 * (0.72 + (index % 3) * 0.018));
  return {
    month,
    b1,
    milp,
    savings: b1 - milp,
    pvUtilization: Math.min(96, 84 + index * 1.1),
    peak: Math.round(460 + seasonal * 65 + (index % 3) * 24),
    excessEvents: Math.max(0, 9 - index + (index % 2)),
    socReserve: Math.round(55 + (index % 5) * 6),
  };
});

const monthlyExecution = Array.from({ length: 31 }, (_, index) => {
  const day = index + 1;
  const pv = Math.max(0, 95 + Math.sin(index / 3) * 75 + (index % 6) * 8);
  const load = 250 + Math.cos(index / 4) * 45 + (index % 5) * 16;
  const charge = pv > 130 ? Math.round((pv - 95) * 0.72) : 12;
  const discharge = day % 6 === 0 || day % 7 === 0 ? 86 : 34 + (index % 4) * 10;
  const grid = Math.max(40, load - pv * 0.54 - discharge * 0.35 + charge * 0.22);
  return {
    date: `2018-07-${String(day).padStart(2, "0")}`,
    label: `${day}`,
    load: Math.round(load),
    pv: Math.round(pv),
    grid: Math.round(grid),
    charge: Math.round(charge),
    discharge: Math.round(discharge),
    soc: Math.round(42 + Math.sin(index / 2.6) * 18 + (index % 4) * 3),
    contractCapacity: 400,
  };
});

const dailySchedule = Array.from({ length: 96 }, (_, index) => {
  const hour = Math.floor(index / 4);
  const minute = (index % 4) * 15;
  const time = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  const daylight = hour >= 6 && hour <= 18 ? Math.sin(((hour - 6) / 12) * Math.PI) : 0;
  const pv = Math.max(0, daylight * 195 + Math.sin(index / 5) * 10);
  const load = 210 + (hour >= 8 && hour <= 20 ? 85 : 28) + Math.sin(index / 8) * 22;
  const pricePeriod = hour >= 16 && hour < 22 ? "尖峰" : hour >= 9 && hour < 16 ? "半尖峰" : "離峰";
  const charge = pv > 130 && pricePeriod !== "尖峰" ? Math.min(130, (pv - 110) * 0.75) : 0;
  const discharge = pricePeriod === "尖峰" ? 85 + Math.sin(index / 3) * 20 : hour >= 7 && hour < 9 ? 38 : 0;
  const grid = Math.max(0, load - pv * 0.58 - discharge + charge * 0.18);
  const socBefore = 72 - Math.max(0, hour - 15) * 2 + (charge > 0 ? 8 : 0);
  const soc = Math.max(20, Math.min(90, socBefore + charge * 0.04 - discharge * 0.08));
  const batteryAction = charge > 5 ? "充電" : discharge > 5 ? "放電" : "待機";
  return {
    date: "2018-07-15",
    time,
    hour,
    load: Math.round(load),
    pv: Math.round(pv),
    grid: Math.round(grid),
    charge: Math.round(charge),
    discharge: Math.round(discharge),
    soc: Math.round(soc),
    socBefore: Math.round(Math.max(20, Math.min(90, soc + discharge * 0.05 - charge * 0.03))),
    contractCapacity: 400,
    pricePeriod,
    batteryAction,
    priceRange: [3.18, 3.82],
    solarRange: [2.08, 2.08 + Math.min(0.72, pv / 260)],
    chargeRange: charge > 0 ? [1.5, 1.5 + Math.min(0.35, charge / 360)] : [1.5, 1.5],
    dischargeRange: discharge > 0 ? [1.5 - Math.min(0.35, discharge / 300), 1.5] : [1.5, 1.5],
    standbyRange: batteryAction === "待機" ? [1.43, 1.57] : [1.5, 1.5],
    gridRange: [0.12, 0.12 + Math.min(0.72, grid / 380)],
  };
});

const mcForecast = Array.from({ length: 7 * 24 }, (_, index) => {
  const day = Math.floor(index / 24) + 1;
  const hour = index % 24;
  const daylight = hour >= 6 && hour <= 18 ? Math.sin(((hour - 6) / 12) * Math.PI) : 0;
  const genMedian = Math.max(0, daylight * (165 + day * 4));
  const loadMedian = 245 + (hour >= 8 && hour <= 20 ? 72 : 18) + Math.sin(index / 9) * 18;
  return {
    label: `D+${day} ${String(hour).padStart(2, "0")}:00`,
    generationP10: Math.round(genMedian * 0.62),
    generationBand: Math.round(genMedian * 0.7),
    generationP50: Math.round(genMedian),
    generationP90: Math.round(genMedian * 1.32),
    generationActual: Math.round(Math.max(0, genMedian * (0.82 + Math.sin(hour / 4) * 0.1))),
    loadP10: Math.round(loadMedian * 0.88),
    loadBand: Math.round(loadMedian * 0.24),
    loadP50: Math.round(loadMedian),
    loadP90: Math.round(loadMedian * 1.12),
    loadActual: Math.round(loadMedian * (0.96 + Math.cos(hour / 5) * 0.05)),
  };
});

const shapImportance = {
  solar: [
    { feature: "雲量", value: -0.34 },
    { feature: "太陽高度角", value: 0.29 },
    { feature: "前 1 小時發電", value: 0.22 },
    { feature: "濕度", value: -0.18 },
    { feature: "季節", value: 0.15 },
    { feature: "溫度", value: -0.13 },
    { feature: "風速", value: -0.09 },
    { feature: "前日均值", value: 0.08 },
  ],
  load: [
    { feature: "前 1 小時用電", value: 0.31 },
    { feature: "工作日", value: 0.25 },
    { feature: "氣溫", value: 0.18 },
    { feature: "尖峰時段", value: 0.16 },
    { feature: "前日同時段", value: 0.14 },
    { feature: "濕度", value: 0.09 },
    { feature: "週末", value: -0.08 },
    { feature: "夜間", value: -0.07 },
  ],
};

const modelMetrics = [
  { label: "發電預測 MAPE", value: "36.1%", note: "高發電段僅 14.7%" },
  { label: "發電預測 R²", value: "0.86", note: "日內型態穩定" },
  { label: "用電預測 MAPE", value: "15.0%", note: "可支援短期 MPC" },
  { label: "Q10 覆蓋率", value: "89.1%", note: "target 90%" },
];

const annualProjection = monthNames.map((month, index) => {
  const p50 = Math.round(175000 + Math.sin(index / 2) * 36000 + (index % 4) * 9000);
  return {
    month,
    p10: Math.round(p50 * 0.72),
    p50,
    p90: Math.round(p50 * 1.25),
    band: Math.round(p50 * 0.53),
  };
});

const seriesConfig = [
  { key: "load", label: "負載", color: "#374151" },
  { key: "pv", label: "PV發電", color: COLORS.primaryGreen },
  { key: "grid", label: "購電", color: "#7C3AED" },
  { key: "charge", label: "充電", color: "#2563EB" },
  { key: "discharge", label: "放電", color: COLORS.warningOrange },
  { key: "soc", label: "SOC", color: COLORS.socBlue, yAxisId: "right" },
  { key: "contractCapacity", label: "契約容量", color: COLORS.alertRed, dashed: true },
];

const defaultVisibleSeries = {
  load: true,
  pv: true,
  grid: true,
  charge: false,
  discharge: false,
  soc: true,
  contractCapacity: false,
};

function formatCurrency(value) {
  return `NT$ ${Math.round(value).toLocaleString("zh-TW")}`;
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function sectionTitle(title, description) {
  return (
    <div className="mb-4">
      <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
      {description ? <p className="mt-1 text-sm text-gray-500">{description}</p> : null}
    </div>
  );
}

function CurrencyTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-lg">
      <p className="font-semibold text-gray-900">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="mt-1" style={{ color: entry.color }}>
          {entry.name}: {formatCurrency(entry.value)}
        </p>
      ))}
    </div>
  );
}

function WaterfallTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-lg">
      <p className="font-semibold text-gray-900">{label}</p>
      <p className={row.display < 0 ? "text-[#2D7D46]" : "text-[#C0392B]"}>
        {row.type === "saving" ? "節省" : "成本"}: {formatCurrency(Math.abs(row.display))}
      </p>
    </div>
  );
}

function ExecutionTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-lg">
      <p className="font-semibold text-gray-900">{row.date || row.time || label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="mt-1" style={{ color: entry.color }}>
          {entry.name}: {entry.dataKey === "soc" ? `${entry.value}%` : `${entry.value} kW`}
        </p>
      ))}
      {row.grid > row.contractCapacity ? (
        <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs font-medium text-[#C0392B]">
          超約 {Math.round(row.grid - row.contractCapacity)} kW
        </p>
      ) : null}
    </div>
  );
}

function GanttTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const batteryText =
    row.batteryAction === "充電"
      ? `電池充電 ${row.charge}kW`
      : row.batteryAction === "放電"
        ? `電池放電 ${row.discharge}kW`
        : "電池待機";
  return (
    <div className="max-w-xs rounded-lg border border-gray-200 bg-white p-3 text-sm shadow-lg">
      <p className="font-semibold text-gray-900">
        {row.time} {row.pricePeriod}時段
      </p>
      <p className="mt-1 text-gray-700">
        {batteryText}，太陽能 {row.pv}kW，購電 {row.grid}kW，SOC 從 {row.socBefore}% → {row.soc}%
      </p>
    </div>
  );
}

function HeroMetricCard({ metric }) {
  const Icon = metric.icon;
  const toneClass =
    metric.tone === "dominant"
      ? "border-[#2D7D46]/30 bg-[#2D7D46] text-white shadow-lg shadow-green-900/10"
      : metric.tone === "red"
        ? "border-red-100 bg-red-50"
        : metric.tone === "green"
          ? "border-green-100 bg-green-50"
          : "border-blue-100 bg-blue-50";
  const valueClass =
    metric.tone === "dominant"
      ? "text-white"
      : metric.tone === "red"
        ? "text-[#C0392B]"
        : metric.tone === "green"
          ? "text-[#2D7D46]"
          : "text-[#1B4F72]";
  const mutedClass = metric.tone === "dominant" ? "text-green-50" : "text-gray-500";

  return (
    <Card className={`overflow-hidden rounded-xl border shadow-sm ${toneClass}`}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className={`text-sm font-medium ${mutedClass}`}>{metric.title}</p>
            <div className={`mt-2 text-[2.5rem] font-bold leading-none tracking-normal ${valueClass}`}>
              {metric.progress ? `${metric.progress.toFixed(1)}%` : formatCurrency(metric.value)}
            </div>
            <p className={`mt-2 text-sm ${mutedClass}`}>{metric.label}</p>
          </div>
          <div className={`rounded-full p-3 ${metric.tone === "dominant" ? "bg-white/15" : "bg-white"}`}>
            <Icon className={`h-6 w-6 ${metric.tone === "dominant" ? "text-white" : valueClass}`} />
          </div>
        </div>
        {metric.badge ? (
          <Badge className="mt-5 bg-white text-[#2D7D46] hover:bg-white">
            <TrendingDown className="mr-1 h-4 w-4" />
            {metric.badge}
          </Badge>
        ) : null}
        {metric.progress ? (
          <div className="mt-5 h-2.5 overflow-hidden rounded-full bg-white">
            <div className="h-full rounded-full bg-[#2D7D46]" style={{ width: `${metric.progress}%` }} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }) {
  const map = {
    green: "border-green-200 bg-green-50 text-[#2D7D46]",
    yellow: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-[#C0392B]",
  };
  const label = status === "green" ? "正常" : status === "yellow" ? "注意" : "高風險";
  return <Badge className={map[status]}>{label}</Badge>;
}

export default function EMSDashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedMonth, setSelectedMonth] = useState("Jul");
  const [zoomDay, setZoomDay] = useState(null);
  const [mcMode, setMcMode] = useState("generation");
  const [visibleSeries, setVisibleSeries] = useState(defaultVisibleSeries);
  const [roiCost, setRoiCost] = useState(5600000);
  const [lastPreviewUpdate, setLastPreviewUpdate] = useState("");
  const [params, setParams] = useState({
    batteryCapacity: 1000,
    contractCapacity: 400,
    lambdaExcess: 300,
    wSoc: 1500,
    month: "Jul",
  });

  useEffect(() => {
    setLastPreviewUpdate(
      new Intl.DateTimeFormat("zh-TW", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date()),
    );
  }, [params]);

  const activeMonthSummary = useMemo(() => {
    return monthlySummary.find((row) => row.month === selectedMonth) || monthlySummary[6];
  }, [selectedMonth]);

  const executionData = useMemo(() => {
    return zoomDay ? dailySchedule : monthlyExecution;
  }, [zoomDay]);

  const overContractRanges = useMemo(() => {
    const ranges = [];
    for (let index = 0; index < executionData.length; index += 1) {
      const point = executionData[index];
      if (point.grid > point.contractCapacity) {
        const x1 = zoomDay ? point.time : point.label;
        const next = executionData[Math.min(index + 1, executionData.length - 1)];
        const x2 = zoomDay ? next.time : next.label;
        ranges.push({ x1, x2, key: `${x1}-${index}` });
      }
    }
    return ranges;
  }, [executionData, zoomDay]);

  const livePreview = useMemo(() => {
    const base_cost = baselineCost;
    const savings_per_kwh_coefficient = 112 + params.wSoc / 140;
    const over_contract_events = Math.max(
      0,
      Math.round((460 - params.contractCapacity) / 28 + (params.lambdaExcess < 250 ? 4 : 0)),
    );
    const penalty_rate = Math.max(800, params.lambdaExcess * 45);
    const estimated_cost =
      base_cost - params.batteryCapacity * savings_per_kwh_coefficient + over_contract_events * penalty_rate;
    const estimatedSavings = Math.max(0, base_cost - estimated_cost);
    const annualSavings = estimatedSavings * 12;
    const payback = annualSavings > 0 ? roiCost / annualSavings : Infinity;
    return {
      estimatedCost: Math.max(420000, estimated_cost),
      estimatedSavings,
      overContractEvents: over_contract_events,
      annualSavings,
      payback,
    };
  }, [params, roiCost]);

  const annualP50Savings = useMemo(() => {
    return annualProjection.reduce((sum, row) => sum + row.p50, 0);
  }, []);

  const optimisticAnnualSavings = useMemo(() => {
    return annualProjection.reduce((sum, row) => sum + row.p90, 0);
  }, []);

  const roiYears = annualP50Savings > 0 ? roiCost / annualP50Savings : Infinity;
  const optimisticRoiYears = optimisticAnnualSavings > 0 ? roiCost / optimisticAnnualSavings : Infinity;

  const updateParam = (key, value) => {
    setParams((current) => ({ ...current, [key]: value }));
  };

  const toggleSeries = (key) => {
    setVisibleSeries((current) => ({ ...current, [key]: !current[key] }));
  };

  const handleExecutionClick = (event) => {
    const payload = event?.activePayload?.[0]?.payload;
    if (!payload || zoomDay) return;
    setZoomDay(payload.date);
  };

  return (
    <div className="min-h-screen bg-[#F8FAF9] px-4 py-6 text-gray-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <Badge className="mb-3 bg-[#2D7D46]/10 text-[#2D7D46] hover:bg-[#2D7D46]/10">
              Energy Management System
            </Badge>
            <h1 className="text-3xl font-bold tracking-normal text-gray-950 md:text-4xl">EMS 節費與調度決策面板</h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-500">
              先讓經營層在 5 秒內看懂節費，再讓工程團隊往下追查 MILP 行為、預測風險與場景參數。
            </p>
          </div>
          <div className="rounded-xl border border-green-100 bg-white px-4 py-3 shadow-sm">
            <p className="text-sm text-gray-500">年度化節省估算</p>
            <p className="text-2xl font-bold text-[#2D7D46]">{formatCurrency(monthlySavings * 12)}</p>
          </div>
        </header>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {heroMetrics.map((metric) => (
            <HeroMetricCard key={metric.title} metric={metric} />
          ))}
        </section>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-5">
          <TabsList className="grid h-auto grid-cols-2 rounded-xl bg-white p-1 shadow-sm md:grid-cols-4">
            <TabsTrigger value="overview" className="rounded-lg">
              總覽與節費
            </TabsTrigger>
            <TabsTrigger value="execution" className="rounded-lg">
              月調度執行
            </TabsTrigger>
            <TabsTrigger value="decision" className="rounded-lg">
              MILP 決策解釋
            </TabsTrigger>
            <TabsTrigger value="risk" className="rounded-lg">
              風險檢查 / 場景重跑
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
              <Card className="rounded-xl border-0 bg-white shadow-sm xl:col-span-3">
                <CardHeader>
                  <CardTitle className="text-xl font-semibold">節費來源瀑布圖</CardTitle>
                  <CardDescription>從 B1 無電池基準一路拆到 MILP 系統實際電費。</CardDescription>
                </CardHeader>
                <CardContent className="h-[390px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={waterfallData} margin={{ top: 15, right: 24, bottom: 45, left: 12 }}>
                      <CartesianGrid stroke={COLORS.grid} vertical={false} />
                      <XAxis dataKey="name" tick={{ fontSize: 12 }} interval={0} angle={-12} textAnchor="end" />
                      <YAxis tickFormatter={(value) => `${Math.round(value / 1000)}k`} />
                      <Tooltip content={<WaterfallTooltip />} />
                      <Legend />
                      <Bar dataKey="base" stackId="waterfall" fill="transparent" name="累計基準" />
                      <Bar dataKey="amount" stackId="waterfall" name="成本 / 節省" radius={[8, 8, 0, 0]}>
                        {waterfallData.map((entry) => (
                          <Cell key={entry.name} fill={entry.fill} />
                        ))}
                      </Bar>
                    </ComposedChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              <Card className="rounded-xl border-0 bg-white shadow-sm xl:col-span-2">
                <CardHeader>
                  <CardTitle className="text-xl font-semibold">策略比較</CardTitle>
                  <CardDescription>由高到低排序，MILP 以深綠凸顯。</CardDescription>
                </CardHeader>
                <CardContent className="h-[390px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={strategyComparison} layout="vertical" margin={{ top: 10, right: 24, bottom: 20, left: 24 }}>
                      <CartesianGrid stroke={COLORS.grid} horizontal={false} />
                      <XAxis type="number" tickFormatter={(value) => `${Math.round(value / 1000)}k`} />
                      <YAxis dataKey="name" type="category" width={128} tick={{ fontSize: 12 }} />
                      <Tooltip content={<CurrencyTooltip />} />
                      <Legend />
                      <ReferenceLine
                        x={baselineCost}
                        stroke={COLORS.alertRed}
                        strokeDasharray="6 6"
                        label={{ value: "B1 基準", fill: COLORS.alertRed, position: "insideTopRight" }}
                      />
                      <Bar dataKey="cost" name="每月電費" radius={[0, 8, 8, 0]}>
                        {strategyComparison.map((entry) => (
                          <Cell key={entry.id} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  <p className="mt-2 text-center text-sm font-medium text-[#2D7D46]">
                    MILP 與 B1 節省空間：{formatCurrency(monthlySavings)}
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card className="rounded-xl border-0 bg-white shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl font-semibold">月成本拆解</CardTitle>
                <CardDescription>B1 基準與 MILP 並排比較，淡綠代表每月節省差額。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[420px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={monthlySummary} margin={{ top: 20, right: 28, bottom: 20, left: 12 }}>
                      <CartesianGrid stroke={COLORS.grid} vertical={false} />
                      <XAxis dataKey="month" />
                      <YAxis tickFormatter={(value) => `${Math.round(value / 1000)}k`} />
                      <Tooltip content={<CurrencyTooltip />} />
                      <Legend />
                      <Bar dataKey="b1" name="B1 baseline" fill="#9CA3AF" radius={[8, 8, 0, 0]} />
                      <Bar dataKey="milp" name="MILP actual" fill={COLORS.primaryGreen} radius={[8, 8, 0, 0]} />
                      <Bar dataKey="savings" name="節省差額" fill="#B7E4C7" opacity={0.45} radius={[8, 8, 0, 0]} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-4 rounded-xl bg-green-50 p-4 text-center">
                  <p className="text-sm text-gray-500">累計已節省</p>
                  <p className="text-[2.5rem] font-bold leading-tight text-[#2D7D46]">
                    {formatCurrency(monthlySummary.reduce((sum, row) => sum + row.savings, 0))}
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="execution" className="space-y-6">
            <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
              {sectionTitle("月調度執行", "切換月份查看 KPI，點擊月圖任一點可放大到該日 15 分鐘解析度。")}
              <select
                value={selectedMonth}
                onChange={(event) => {
                  setSelectedMonth(event.target.value);
                  updateParam("month", event.target.value);
                }}
                className="h-10 rounded-lg border border-gray-200 bg-white px-3 text-sm shadow-sm focus:border-[#2D7D46] focus:outline-none focus:ring-2 focus:ring-[#2D7D46]/20"
              >
                {monthNames.map((month) => (
                  <option key={month} value={month}>
                    {month}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  label: "月流動電費",
                  value: activeMonthSummary.milp,
                  delta: "-8.4%",
                  compare: `vs B1 省 ${formatCurrency(activeMonthSummary.savings)}`,
                  icon: DollarSign,
                },
                {
                  label: "月峰值",
                  value: `${activeMonthSummary.peak} kW`,
                  delta: "+2.1%",
                  compare: "vs B1 低 114 kW",
                  icon: Gauge,
                },
                {
                  label: "PV 利用率",
                  value: `${activeMonthSummary.pvUtilization.toFixed(1)}%`,
                  delta: "+3.2%",
                  compare: "vs B1 高 8.7pt",
                  icon: Leaf,
                },
                {
                  label: "超約事件",
                  value: `${activeMonthSummary.excessEvents}`,
                  delta: "-71%",
                  compare: "vs B1 少 18 次",
                  icon: AlertTriangle,
                },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <Card key={item.label} className="rounded-xl border-0 bg-white shadow-sm">
                    <CardContent className="p-5">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-gray-500">{item.label}</p>
                        <Icon className="h-5 w-5 text-[#2D7D46]" />
                      </div>
                      <p className="mt-3 text-[2.5rem] font-bold leading-none text-gray-950">
                        {typeof item.value === "number" ? formatCurrency(item.value) : item.value}
                      </p>
                      <p className="mt-3 text-sm font-medium text-[#2D7D46]">vs 上月 {item.delta}</p>
                      <p className="text-xs text-gray-500">{item.compare}</p>
                    </CardContent>
                  </Card>
                );
              })}
            </div>

            <Card className="rounded-xl border-0 bg-white shadow-sm">
              <CardHeader className="space-y-4">
                <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                  <div>
                    <CardTitle className="text-xl font-semibold">
                      {zoomDay ? `${zoomDay} 日調度細節` : "月調度多序列圖"}
                    </CardTitle>
                    <CardDescription>預設只顯示 4 條主序列，其餘用按鈕或圖例切換。</CardDescription>
                  </div>
                  {zoomDay ? (
                    <button
                      type="button"
                      onClick={() => setZoomDay(null)}
                      className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-[#2D7D46]/30"
                    >
                      回到月視圖
                    </button>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {seriesConfig.map((series) => (
                    <button
                      type="button"
                      key={series.key}
                      onClick={() => toggleSeries(series.key)}
                      className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
                        visibleSeries[series.key]
                          ? "border-[#2D7D46] bg-[#2D7D46] text-white shadow-sm"
                          : "border-gray-200 bg-white text-gray-600 hover:border-[#2D7D46]/50"
                      }`}
                    >
                      {series.label}
                    </button>
                  ))}
                </div>
              </CardHeader>
              <CardContent className="h-[520px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={executionData} onClick={handleExecutionClick} margin={{ top: 20, right: 28, bottom: 10, left: 8 }}>
                    <CartesianGrid stroke={COLORS.grid} vertical={false} />
                    <XAxis dataKey={zoomDay ? "time" : "label"} minTickGap={20} />
                    <YAxis yAxisId="left" tickFormatter={(value) => `${value}`} />
                    <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tickFormatter={(value) => `${value}%`} />
                    <Tooltip content={<ExecutionTooltip />} />
                    <Legend onClick={(entry) => entry?.dataKey && toggleSeries(entry.dataKey)} />
                    {overContractRanges.map((range) => (
                      <ReferenceArea
                        key={range.key}
                        yAxisId="left"
                        x1={range.x1}
                        x2={range.x2}
                        fill={COLORS.alertRed}
                        fillOpacity={0.12}
                      />
                    ))}
                    <ReferenceLine
                      yAxisId="left"
                      y={activeMonthSummary.peak > 480 ? 450 : 400}
                      stroke={COLORS.alertRed}
                      strokeDasharray="6 6"
                    >
                      <Label value="契約容量上限" position="insideTopRight" fill={COLORS.alertRed} />
                    </ReferenceLine>
                    {seriesConfig.map((series) => {
                      if (!visibleSeries[series.key]) return null;
                      if (series.key === "charge" || series.key === "discharge") {
                        return (
                          <Bar
                            key={series.key}
                            yAxisId="left"
                            dataKey={series.key}
                            name={series.label}
                            fill={series.color}
                            opacity={0.55}
                            radius={[5, 5, 0, 0]}
                          />
                        );
                      }
                      return (
                        <Line
                          key={series.key}
                          yAxisId={series.yAxisId || "left"}
                          type="monotone"
                          dataKey={series.key}
                          name={series.label}
                          stroke={series.color}
                          strokeWidth={2.5}
                          strokeDasharray={series.dashed ? "6 6" : undefined}
                          dot={false}
                          activeDot={{ r: 5 }}
                        />
                      );
                    })}
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="rounded-xl border-0 bg-white shadow-sm">
              <CardHeader>
                <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
                  <div>
                    <CardTitle className="text-xl font-semibold">未來 7 日發電量預測區間</CardTitle>
                    <CardDescription>預測區間基於歷史相似日抽樣，僅供規劃參考。</CardDescription>
                  </div>
                  <div className="flex rounded-lg border border-gray-200 bg-gray-50 p-1">
                    {[
                      ["generation", "發電量預測"],
                      ["load", "用電量預測"],
                    ].map(([key, label]) => (
                      <button
                        type="button"
                        key={key}
                        onClick={() => setMcMode(key)}
                        className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                          mcMode === key ? "bg-white text-[#2D7D46] shadow-sm" : "text-gray-500"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="h-[390px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={mcForecast} margin={{ top: 15, right: 28, bottom: 10, left: 8 }}>
                    <CartesianGrid stroke={COLORS.grid} vertical={false} />
                    <XAxis dataKey="label" minTickGap={44} />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Area
                      type="monotone"
                      dataKey={`${mcMode}P10`}
                      stackId="mc"
                      stroke="transparent"
                      fill="transparent"
                      name="P10"
                    />
                    <Area
                      type="monotone"
                      dataKey={`${mcMode}Band`}
                      stackId="mc"
                      stroke="transparent"
                      fill="#B7E4C7"
                      fillOpacity={0.55}
                      name="P10-P90 區間"
                    />
                    <Line
                      type="monotone"
                      dataKey={`${mcMode}P50`}
                      stroke={COLORS.primaryGreen}
                      strokeWidth={2.5}
                      dot={false}
                      name="P50 median"
                    />
                    <Line
                      type="monotone"
                      dataKey={`${mcMode}Actual`}
                      stroke={COLORS.neutralGray}
                      strokeDasharray="4 5"
                      dot={false}
                      name="昨日 actual"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="decision" className="space-y-6">
            <Card className="rounded-xl border-0 bg-white shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl font-semibold">Daily Schedule Gantt</CardTitle>
                <CardDescription>選定日內的電價、PV、電池、台電取電與 SOC 疊合檢視。</CardDescription>
              </CardHeader>
              <CardContent className="h-[450px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={dailySchedule} margin={{ top: 20, right: 32, bottom: 10, left: 8 }}>
                    <CartesianGrid stroke={COLORS.grid} vertical={false} />
                    <XAxis dataKey="time" minTickGap={28} />
                    <YAxis
                      yAxisId="lanes"
                      domain={[0, 4]}
                      ticks={[0.5, 1.5, 2.5, 3.5]}
                      tickFormatter={(value) =>
                        value === 3.5 ? "電價時段" : value === 2.5 ? "太陽能發電" : value === 1.5 ? "電池動作" : "台電取電"
                      }
                      width={90}
                    />
                    <YAxis yAxisId="soc" orientation="right" domain={[0, 100]} tickFormatter={(value) => `${value}%`} />
                    <Tooltip content={<GanttTooltip />} />
                    <Legend />
                    <Bar yAxisId="lanes" dataKey="priceRange" name="電價時段" barSize={11}>
                      {dailySchedule.map((entry) => (
                        <Cell
                          key={`price-${entry.time}`}
                          fill={
                            entry.pricePeriod === "尖峰"
                              ? COLORS.alertRed
                              : entry.pricePeriod === "半尖峰"
                                ? COLORS.warningOrange
                                : "#9CA3AF"
                          }
                        />
                      ))}
                    </Bar>
                    <Bar yAxisId="lanes" dataKey="solarRange" name="太陽能發電" fill={COLORS.primaryGreen} barSize={16} />
                    <Bar yAxisId="lanes" dataKey="chargeRange" name="充電" fill="#2563EB" barSize={14} />
                    <Bar yAxisId="lanes" dataKey="dischargeRange" name="放電" fill={COLORS.warningOrange} barSize={14} />
                    <Bar yAxisId="lanes" dataKey="standbyRange" name="待機" fill="#D1D5DB" barSize={8} />
                    <Bar yAxisId="lanes" dataKey="gridRange" name="台電取電" fill="#7C3AED" barSize={16} />
                    <Line yAxisId="soc" dataKey="soc" name="SOC" stroke={COLORS.socBlue} strokeWidth={2.5} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {[
                ["發電量預測 SHAP", shapImportance.solar],
                ["用電量預測 SHAP", shapImportance.load],
              ].map(([title, data]) => (
                <Card key={title} className="rounded-xl border-0 bg-white shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-xl font-semibold">{title}</CardTitle>
                    <CardDescription>正向影響為綠色，負向影響為紅色。</CardDescription>
                  </CardHeader>
                  <CardContent className="h-[330px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, bottom: 10, left: 24 }}>
                        <CartesianGrid stroke={COLORS.grid} horizontal={false} />
                        <XAxis type="number" />
                        <YAxis dataKey="feature" type="category" width={92} tick={{ fontSize: 12 }} />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="value" name="SHAP impact" radius={[0, 8, 8, 0]}>
                          {data.map((entry) => (
                            <Cell key={entry.feature} fill={entry.value >= 0 ? COLORS.primaryGreen : COLORS.alertRed} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              ))}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              {modelMetrics.map((metric) => (
                <Card key={metric.label} className="rounded-xl border-0 bg-white shadow-sm">
                  <CardContent className="p-5">
                    <p className="text-sm text-gray-500">{metric.label}</p>
                    <p className="mt-3 text-[2.5rem] font-bold leading-none text-gray-950">{metric.value}</p>
                    <p className="mt-3 text-sm text-gray-500">{metric.note}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="risk" className="space-y-6">
            {sectionTitle("風險檢查 / 場景重跑", "先看營運風險，再用即時滑桿快速估算參數影響。")}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  title: "超約風險",
                  status: "yellow",
                  value: "392 / 400 kW",
                  description: "今日預測接近契約上限",
                  icon: AlertTriangle,
                },
                {
                  title: "SOC 安全備援",
                  status: "green",
                  value: "62%",
                  description: "高於 UPS reserve 35%",
                  icon: ShieldCheck,
                },
                {
                  title: "本月最高需量",
                  status: "red",
                  value: "581 kW",
                  description: "已高於經常契約 181 kW",
                  icon: Gauge,
                },
                {
                  title: "預測信心度",
                  status: "yellow",
                  value: "中等",
                  description: "今日雲量變化偏高",
                  icon: Clock3,
                },
              ].map((risk) => {
                const Icon = risk.icon;
                return (
                  <Card key={risk.title} className="rounded-xl border-0 bg-white shadow-sm">
                    <CardContent className="p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm text-gray-500">{risk.title}</p>
                          <p className="mt-3 text-2xl font-bold text-gray-950">{risk.value}</p>
                        </div>
                        <Icon className="h-6 w-6 text-[#1B4F72]" />
                      </div>
                      <div className="mt-4 flex items-center justify-between gap-3">
                        <StatusBadge status={risk.status} />
                        <p className="text-right text-xs text-gray-500">{risk.description}</p>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              <Card className="rounded-xl border-0 bg-white shadow-sm lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-xl font-semibold">LIVE Parameter Sliders</CardTitle>
                  <CardDescription>滑動後右側快速估算會即時更新，無需重新求解。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {[
                    ["batteryCapacity", "電池容量 Q", 100, 2000, 50, "kWh"],
                    ["contractCapacity", "契約容量", 200, 800, 10, "kW"],
                    ["lambdaExcess", "超約懲罰 λ", 0, 1000, 10, ""],
                    ["wSoc", "SOC 追蹤權重 w_soc", 0, 3000, 100, ""],
                  ].map(([key, label, min, max, step, unit]) => (
                    <div key={key}>
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <label className="text-sm font-medium text-gray-700">{label}</label>
                        <span className="rounded-full bg-gray-100 px-2.5 py-1 text-sm font-semibold text-gray-700">
                          {params[key].toLocaleString("zh-TW")} {unit}
                        </span>
                      </div>
                      <Slider
                        min={min}
                        max={max}
                        step={step}
                        value={[params[key]]}
                        onValueChange={([value]) => updateParam(key, value)}
                      />
                    </div>
                  ))}

                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">模擬月份</label>
                    <select
                      value={params.month}
                      onChange={(event) => updateParam("month", event.target.value)}
                      className="h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm shadow-sm focus:border-[#2D7D46] focus:outline-none focus:ring-2 focus:ring-[#2D7D46]/20"
                    >
                      {monthNames.map((month) => (
                        <option key={month} value={month}>
                          {month}
                        </option>
                      ))}
                    </select>
                  </div>
                </CardContent>
              </Card>

              <Card className="rounded-xl border-0 bg-white shadow-sm lg:col-span-3">
                <CardHeader>
                  <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
                    <div>
                      <CardTitle className="text-xl font-semibold">Live Preview</CardTitle>
                      <CardDescription>快速估算，點擊執行取得精確結果。</CardDescription>
                    </div>
                    <Badge className="bg-[#2D7D46]/10 text-[#2D7D46] hover:bg-[#2D7D46]/10">
                      Updated {lastPreviewUpdate}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {[
                      ["Estimated monthly cost", formatCurrency(livePreview.estimatedCost), COLORS.alertRed],
                      ["Estimated savings vs B1", formatCurrency(livePreview.estimatedSavings), COLORS.primaryGreen],
                      ["Over-contract events", `${livePreview.overContractEvents} 次`, COLORS.alertRed],
                      ["Payback period estimate", `${Number.isFinite(livePreview.payback) ? livePreview.payback.toFixed(1) : "--"} 年`, COLORS.socBlue],
                    ].map(([label, value, color]) => (
                      <div key={label} className="rounded-xl border border-gray-100 bg-gray-50 p-4">
                        <p className="text-sm text-gray-500">{label}</p>
                        <p className="mt-2 text-3xl font-bold" style={{ color }}>
                          {value}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-xl border border-dashed border-[#2D7D46]/30 bg-green-50 p-4">
                    <p className="text-sm font-medium text-[#2D7D46]">快速估算公式</p>
                    <p className="mt-1 text-sm text-gray-600">
                      estimated_cost = base_cost - battery_capacity * savings_per_kwh_coefficient + over_contract_events *
                      penalty_rate
                    </p>
                  </div>

                  <button
                    type="button"
                    className="inline-flex items-center rounded-lg bg-[#2D7D46] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#25683A] focus:outline-none focus:ring-2 focus:ring-[#2D7D46]/30"
                  >
                    <Zap className="mr-2 h-4 w-4" />
                    執行完整場景
                  </button>
                </CardContent>
              </Card>
            </div>

            <Card className="rounded-xl border-0 bg-white shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl font-semibold">Monte Carlo Annual Projection</CardTitle>
                <CardDescription>12 個月節省估算，P10-P90 區間呈現不確定性。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="h-[420px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={annualProjection} margin={{ top: 15, right: 28, bottom: 10, left: 8 }}>
                      <CartesianGrid stroke={COLORS.grid} vertical={false} />
                      <XAxis dataKey="month" />
                      <YAxis tickFormatter={(value) => `${Math.round(value / 1000)}k`} />
                      <Tooltip content={<CurrencyTooltip />} />
                      <Legend />
                      <Area type="monotone" dataKey="p10" stackId="annual" stroke="transparent" fill="transparent" name="P10" />
                      <Area
                        type="monotone"
                        dataKey="band"
                        stackId="annual"
                        stroke="transparent"
                        fill="#B7E4C7"
                        fillOpacity={0.55}
                        name="P10-P90 band"
                      />
                      <Line type="monotone" dataKey="p10" stroke="#6B7280" strokeWidth={2} dot={false} name="P10 conservative" />
                      <Line type="monotone" dataKey="p50" stroke={COLORS.primaryGreen} strokeWidth={3} dot={false} name="P50 median" />
                      <Line type="monotone" dataKey="p90" stroke="#1F6B3B" strokeWidth={2} dot={false} name="P90 optimistic" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>

                <div className="grid grid-cols-1 gap-4 rounded-xl bg-green-50 p-4 md:grid-cols-3 md:items-center">
                  <div>
                    <p className="text-sm text-gray-500">年度預期節省 NT$ X (P50 情境)</p>
                    <p className="text-3xl font-bold text-[#2D7D46]">{formatCurrency(annualP50Savings)}</p>
                  </div>
                  <label className="block">
                    <span className="text-sm font-medium text-gray-700">電池系統建置成本</span>
                    <input
                      value={roiCost}
                      onChange={(event) => setRoiCost(Number(event.target.value) || 0)}
                      type="number"
                      className="mt-2 h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm shadow-sm focus:border-[#2D7D46] focus:outline-none focus:ring-2 focus:ring-[#2D7D46]/20"
                    />
                  </label>
                  <div className="rounded-xl bg-white p-4 shadow-sm">
                    <p className="text-sm text-gray-500">投資回收期</p>
                    <p className="text-2xl font-bold text-[#1B4F72]">
                      約 {Number.isFinite(roiYears) ? roiYears.toFixed(1) : "--"} 年
                    </p>
                    <p className="text-xs text-gray-500">
                      樂觀情境 {Number.isFinite(optimisticRoiYears) ? optimisticRoiYears.toFixed(1) : "--"} 年
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
