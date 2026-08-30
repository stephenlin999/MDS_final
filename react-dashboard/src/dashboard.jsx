import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  BatteryCharging,
  CalendarDays,
  CheckCircle2,
  CloudSun,
  ExternalLink,
  Gauge,
  Play,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import data from "@/data/ems-dashboard-data.json";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const COLORS = {
  accent: "#0052FF",
  accentSecondary: "#4D7CFF",
  foreground: "#0F172A",
  muted: "#64748B",
  border: "#E2E8F0",
  green: "#2D7D46",
  greenSoft: "#DDF5E6",
  red: "#C0392B",
  redSoft: "#FCE7E5",
  orange: "#F59E0B",
  blue: "#1B4F72",
  purple: "#6D5BD0",
};

const seriesConfig = {
  load: { label: "負載", monthlyKey: "loadPeakKw", dailyKey: "loadKw", color: COLORS.foreground, axis: "power" },
  pv: { label: "PV發電", monthlyKey: "pvPeakKw", dailyKey: "pvKw", color: COLORS.green, axis: "power" },
  grid: { label: "購電", monthlyKey: "gridPeakKw", dailyKey: "gridKw", color: COLORS.purple, axis: "power" },
  charge: { label: "充電", monthlyKey: "chargePeakKw", dailyKey: "chargeKw", color: COLORS.accentSecondary, axis: "power" },
  discharge: { label: "放電", monthlyKey: "dischargePeakKw", dailyKey: "dischargeKw", color: COLORS.orange, axis: "power" },
  soc: { label: "SOC", monthlyKey: "socPercent", dailyKey: "socPercent", color: COLORS.blue, axis: "soc" },
};

function formatCurrency(value, compact = false) {
  const number = Number(value) || 0;
  if (compact && Math.abs(number) >= 10000) {
    return `NT$ ${(number / 10000).toLocaleString("zh-TW", { maximumFractionDigits: 1 })}萬`;
  }
  return `NT$ ${Math.round(number).toLocaleString("zh-TW")}`;
}

function formatNumber(value, digits = 0) {
  return (Number(value) || 0).toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function percent(value, digits = 1) {
  return `${formatNumber(value, digits)}%`;
}

function SectionLabel({ children, pulse = false }) {
  return (
    <div className="section-label">
      <span className={cn("h-2 w-2 rounded-full bg-[#0052FF]", pulse && "shadow-[0_0_0_4px_rgba(0,82,255,0.10)]")} />
      <span>{children}</span>
    </div>
  );
}

function ChartShell({ title, description, children, action, className }) {
  return (
    <Card className={cn("overflow-hidden shadow-sm hover:shadow-premium", className)}>
      <CardHeader className="flex flex-col gap-3 border-b border-border/70 pb-4 md:flex-row md:items-start md:justify-between">
        <div>
          <CardTitle className="text-base md:text-lg">{title}</CardTitle>
          {description ? <CardDescription className="mt-1">{description}</CardDescription> : null}
        </div>
        {action}
      </CardHeader>
      <CardContent className="p-4 md:p-5">{children}</CardContent>
    </Card>
  );
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border bg-white/95 p-3 text-sm shadow-premium backdrop-blur">
      <div className="mb-2 font-semibold text-foreground">{label}</div>
      <div className="space-y-1">
        {payload
          .filter((entry) => entry.value !== undefined && entry.value !== null)
          .map((entry) => (
            <div key={`${entry.name}-${entry.dataKey}`} className="flex items-center justify-between gap-5">
              <span className="flex items-center gap-2 text-muted-foreground">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
                {entry.name}
              </span>
              <span className="font-medium text-foreground">
                {typeof entry.value === "number" ? formatNumber(entry.value, entry.value % 1 ? 1 : 0) : entry.value}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}

function HeroMetricCard({ title, value, label, tone, badge, icon: Icon, children, dominant = false }) {
  const toneClasses = {
    red: "border-red-100 bg-red-50/80 text-[#C0392B]",
    green: "border-emerald-100 bg-emerald-50/90 text-[#2D7D46]",
    blue: "border-blue-100 bg-blue-50/90 text-[#0052FF]",
    dark: "border-transparent bg-gradient-to-br from-[#0F172A] to-[#1E293B] text-white shadow-premium",
  };

  return (
    <Card
      className={cn(
        "relative min-h-[178px] overflow-hidden border p-0",
        toneClasses[tone],
        dominant && "scale-[1.01] shadow-accent-lg",
      )}
    >
      <div className="absolute -right-8 -top-8 h-28 w-28 rounded-full bg-white/30 blur-2xl" />
      <CardContent className="relative flex h-full flex-col justify-between p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium opacity-80">{title}</p>
            <p className={cn("mt-3 text-3xl font-extrabold tracking-normal md:text-[2.5rem]", dominant && "md:text-[2.75rem]")}>
              {value}
            </p>
          </div>
          <div className="rounded-2xl bg-white/70 p-3 shadow-sm">
            <Icon className="h-5 w-5" />
          </div>
        </div>
        <div className="mt-4 flex items-end justify-between gap-3">
          <p className={cn("text-sm", tone === "dark" ? "text-white/70" : "text-slate-600")}>{label}</p>
          {badge ? <Badge variant={tone === "red" ? "danger" : "success"}>{badge}</Badge> : null}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

function StatCard({ title, value, detail, delta, icon: Icon, tone = "blue" }) {
  const color = tone === "green" ? COLORS.green : tone === "red" ? COLORS.red : COLORS.accent;
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="mt-2 text-2xl font-bold tracking-normal text-foreground">{value}</p>
            <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
          </div>
          <div className="rounded-2xl bg-blue-50 p-3" style={{ color }}>
            <Icon className="h-5 w-5" />
          </div>
        </div>
        {delta ? (
          <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-slate-50 px-3 py-1 text-xs text-muted-foreground">
            <span className={delta.startsWith("+") ? "text-[#C0392B]" : "text-[#2D7D46]"}>{delta}</span>
            <span>vs 上月</span>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StrategyBarLabel({ x, y, width, value }) {
  return (
    <text x={x + width + 10} y={y + 17} fill={COLORS.muted} fontSize={12}>
      {formatCurrency(value, true)}
    </text>
  );
}

function buildTouAreas(rows, xKey = "time") {
  if (!rows?.length) return [];
  const areas = [];
  let current = rows[0].tou;
  let start = rows[0][xKey];
  rows.forEach((row, index) => {
    const next = rows[index + 1];
    if (!next || next.tou !== current) {
      areas.push({ tou: current, x1: start, x2: row[xKey] });
      if (next) {
        current = next.tou;
        start = next[xKey];
      }
    }
  });
  return areas;
}

function touFill(tou) {
  if (tou === "peak") return "rgba(192, 57, 43, 0.035)";
  if (tou === "semi" || tou === "sat_semi") return "rgba(245, 158, 11, 0.035)";
  return "rgba(107, 114, 128, 0.025)";
}

function bandData(rows) {
  return rows.map((row) => ({ ...row, band: Math.max(0, row.p90 - row.p10) }));
}

function displayDate(date) {
  if (!date) return "";
  const [, month, day] = String(date).split("-");
  return month && day ? `${month}/${day}` : String(date);
}

function scenarioDayLabel(date) {
  if (!date) return "選擇情境日";
  return `未來情境 ${displayDate(date)}`;
}

function seasonMonthLabel(month) {
  if (Number(month) === 7) return "夏季尖峰情境";
  if (Number(month) === 12) return "冬季尖峰情境";
  return `${labelMonth(month)} 情境`;
}

function buildSavingsBridgeRows(waterfall) {
  return waterfall.map((entry) => {
    const isEndpoint = entry.kind === "start" || entry.kind === "end";
    const amount = isEndpoint ? entry.value : Math.abs(entry.display);
    const isSaving = !isEndpoint && entry.display < 0;
    const isIncrease = !isEndpoint && entry.display > 0;
    return {
      name: entry.name,
      amount,
      rawChange: entry.display,
      kind: entry.kind,
      note: entry.note,
      displayText: isEndpoint
        ? formatCurrency(entry.display)
        : `${isSaving ? "-" : isIncrease ? "+" : ""}${formatCurrency(amount)}`,
      fill: entry.kind === "start" ? COLORS.red : entry.kind === "end" ? COLORS.green : isSaving ? COLORS.green : isIncrease ? COLORS.red : "#CBD5E1",
    };
  });
}

function SavingsBridgeLabel({ x = 0, y = 0, width = 0, payload }) {
  if (!payload?.displayText) return null;
  return (
    <text x={x + width + 10} y={y + 17} fill={payload.fill} fontSize={12} fontWeight={700}>
      {payload.displayText}
    </text>
  );
}

function CostBarLabel({ x = 0, y = 0, width = 0, value }) {
  return (
    <text x={x + width / 2} y={y - 10} fill={COLORS.foreground} fontSize={13} fontWeight={700} textAnchor="middle">
      {formatCurrency(value)}
    </text>
  );
}

function OverviewTab({ overview, waterfall, strategyComparison, monthlySummary }) {
  const b1Cost = overview.withoutSystemCost;
  const cumulativeSavings = monthlySummary.reduce((sum, row) => sum + row.savings, 0);
  const costComparisonRows = [
    { name: "無系統", cost: overview.withoutSystemCost, fill: COLORS.red },
    { name: "有系統", cost: overview.milpCost, fill: COLORS.green },
  ];
  return (
    <div className="space-y-6">
      <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
        <ChartShell
          title="無系統 vs 有系統電費"
          description="用最直觀的雙長條比較：左邊是 B1 無電池基準，右邊是 MILP 系統成本。"
        >
          <div className="h-[360px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={costComparisonRows} margin={{ top: 34, right: 24, left: 8, bottom: 10 }}>
                <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 13 }} />
                <YAxis tickFormatter={(value) => `${Math.round(value / 10000)}萬`} tick={{ fontSize: 12 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend />
                <Bar dataKey="cost" name="每月電費" radius={[10, 10, 0, 0]} label={<CostBarLabel />} isAnimationActive={false}>
                  {costComparisonRows.map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                </Bar>
                <ReferenceLine
                  y={overview.milpCost}
                  stroke={COLORS.green}
                  strokeDasharray="6 6"
                  label={{ value: "有系統成本線", position: "insideTopRight", fill: COLORS.green, fontSize: 12 }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 rounded-xl bg-slate-50 px-4 py-3 text-sm text-muted-foreground">
            淨效果：B1 {formatCurrency(overview.withoutSystemCost)} → MILP {formatCurrency(overview.milpCost)}，每月節省{" "}
            <span className="font-semibold text-[#2D7D46]">{formatCurrency(overview.monthlySavings)}</span>。
          </div>
        </ChartShell>

        <ChartShell
          title="策略比較"
          description="依總成本由高到低排序；MILP 用深綠色，高於 B1 的方案會直接暴露風險。"
        >
          <div className="h-[360px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={strategyComparison} layout="vertical" margin={{ top: 10, right: 78, left: 16, bottom: 10 }}>
                <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} horizontal={false} />
                <XAxis type="number" tickFormatter={(value) => `${Math.round(value / 10000)}萬`} tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="label" width={118} tick={{ fontSize: 12 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend />
                <ReferenceLine
                  x={b1Cost}
                  stroke={COLORS.red}
                  strokeDasharray="6 6"
                  label={{ value: "B1 基準", position: "top", fill: COLORS.red, fontSize: 12 }}
                />
                <Bar dataKey="totalCost" name="總成本" radius={[0, 8, 8, 0]} label={<StrategyBarLabel />}>
                  {strategyComparison.map((entry) => (
                    <Cell key={entry.id} fill={entry.isMilp ? COLORS.green : "#CBD5E1"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Advanced EMS 與 B1 的節省空間：{formatCurrency(overview.monthlySavings)}。
          </div>
        </ChartShell>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_0.6fr]">
        <ChartShell
          title="月份成本拆解"
          description="7 月與 12 月使用既有 EMS output；其他月份使用 Monte Carlo 發電量縮放的抽樣情境。"
        >
          <div className="h-[360px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlySummary} margin={{ top: 20, right: 24, left: 10, bottom: 10 }}>
                <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(value) => `${Math.round(value / 10000)}萬`} tick={{ fontSize: 12 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend />
                <Bar dataKey="b1Cost" name="B1 基準" fill="#CBD5E1" radius={[8, 8, 0, 0]} />
                <Bar dataKey="cost" name="MILP 實績" fill={COLORS.green} radius={[8, 8, 0, 0]} />
                <Line type="monotone" dataKey="savings" name="節省額" stroke={COLORS.accent} strokeWidth={3} dot={{ r: 4 }} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartShell>

        <Card className="relative overflow-hidden bg-[#0F172A] text-white shadow-premium">
          <div className="absolute inset-0 dot-pattern opacity-50" />
          <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-[#0052FF]/20 blur-[90px]" />
          <CardContent className="relative p-6">
            <SectionLabel pulse>EXECUTIVE READOUT</SectionLabel>
            <h3 className="mt-8 font-display text-4xl leading-tight">
              累計已節省
              <span className="block gradient-text">{formatCurrency(cumulativeSavings)}</span>
            </h3>
            <p className="mt-4 text-sm leading-6 text-white/70">
              以既有 EMS output 校準，再用 Monte Carlo 未來年度情境補齊月份抽樣。這個區塊給 business owner 先看結論，再往下展開技術原因。
            </p>
            <div className="mt-8 grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-white/10 bg-white/10 p-4">
                <p className="font-mono text-xs uppercase tracking-[0.15em] text-white/50">Peak</p>
                <p className="mt-2 text-2xl font-bold">{formatNumber(overview.peakGridKw, 1)} kW</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/10 p-4">
                <p className="font-mono text-xs uppercase tracking-[0.15em] text-white/50">Cycles</p>
                <p className="mt-2 text-2xl font-bold">{formatNumber(overview.batteryCycles, 1)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function MonthlyExecutionTab({
  months,
  selectedMonth,
  setSelectedMonth,
  selectedDay,
  setSelectedDay,
  visibleSeries,
  setVisibleSeries,
  mcMode,
  setMcMode,
}) {
  const monthData = data.monthlyExecution[String(selectedMonth)] ?? data.monthlyExecution[String(months[0]?.month)] ?? { daily: [] };
  const monthSummary = months.find((row) => row.month === selectedMonth) ?? months[0];
  const dayRows = data.dailySchedules[String(selectedMonth)]?.[selectedDay] ?? [];
  const executionData = selectedDay ? dayRows : monthData.daily;
  const xKey = selectedDay ? "time" : "label";
  const activeMc = mcMode === "generation" ? data.mcForecast.generation : data.mcForecast.load;
  const mcLabel = mcMode === "generation" ? "發電量預測" : "用電量預測";
  const touAreas = selectedDay ? buildTouAreas(dayRows) : [];
  const previous = months[Math.max(0, months.findIndex((row) => row.month === selectedMonth) - 1)] ?? monthSummary;

  function handleChartClick(state) {
    const payload = state?.activePayload?.[0]?.payload;
    if (!selectedDay && payload?.date) setSelectedDay(payload.date);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-white p-4 shadow-sm md:flex-row md:items-center md:justify-between">
        <div>
          <SectionLabel>MONTH EXECUTION</SectionLabel>
          <h2 className="mt-3 text-xl font-semibold">月調度執行檢視</h2>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="h-11 rounded-xl border border-input bg-white px-4 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={selectedMonth}
            onChange={(event) => {
              setSelectedMonth(Number(event.target.value));
              setSelectedDay(null);
            }}
          >
            {months.map((row) => (
              <option key={row.month} value={row.month}>
                {seasonMonthLabel(row.month)}
              </option>
            ))}
          </select>
          {selectedDay ? (
            <Button variant="secondary" onClick={() => setSelectedDay(null)}>
              <RefreshCw className="h-4 w-4" />
              回到月視圖
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="本月 MILP 電費"
          value={formatCurrency(monthSummary.cost, true)}
          detail={`vs B1 基準 ${formatCurrency(monthSummary.b1Cost, true)}`}
          delta={`${monthSummary.cost - previous.cost >= 0 ? "+" : ""}${formatCurrency(monthSummary.cost - previous.cost, true)}`}
          icon={TrendingDown}
          tone="green"
        />
        <StatCard
          title="PV 利用率"
          value={percent(monthSummary.pvUtilization)}
          detail={`棄光 ${formatNumber(monthSummary.curtailmentKwh, 1)} kWh`}
          delta={`${formatNumber(monthSummary.pvUtilization - previous.pvUtilization, 1)} pt`}
          icon={CloudSun}
          tone="green"
        />
        <StatCard
          title="月峰值"
          value={`${formatNumber(monthSummary.peakGridKw, 1)} kW`}
          detail={`契約容量 ${formatNumber(monthSummary.contractKw, 0)} kW`}
          delta={`${formatNumber(monthSummary.peakGridKw - previous.peakGridKw, 1)} kW`}
          icon={Gauge}
          tone={monthSummary.peakGridKw > monthSummary.contractKw ? "red" : "blue"}
        />
        <StatCard
          title="電池循環"
          value={formatNumber(monthSummary.batteryCycles, 1)}
          detail={`vs B1 節省 ${formatCurrency(monthSummary.savings, true)}`}
          delta={`${formatNumber(monthSummary.batteryCycles - previous.batteryCycles, 1)}`}
          icon={BatteryCharging}
          tone="blue"
        />
      </div>

        <ChartShell
          title={selectedDay ? `${scenarioDayLabel(selectedDay)} 15 分鐘調度` : `${seasonMonthLabel(monthSummary.month)} 每日峰值概覽`}
        description="預設只顯示負載、PV、購電與 SOC；點擊月視圖任一天可 zoom 到 15 分鐘解析度。"
        action={
          <div className="flex max-w-full flex-wrap gap-2">
            {Object.entries(seriesConfig).map(([key, item]) => (
              <Button
                key={key}
                type="button"
                variant={visibleSeries[key] ? "default" : "secondary"}
                size="sm"
                onClick={() => setVisibleSeries((current) => ({ ...current, [key]: !current[key] }))}
                className={cn(!visibleSeries[key] && "text-muted-foreground")}
              >
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                {item.label}
              </Button>
            ))}
          </div>
        }
      >
        <div className="h-[460px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={executionData} onClick={handleChartClick} margin={{ top: 16, right: 18, left: 8, bottom: 10 }}>
              <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} />
              {touAreas.map((area) => (
                <ReferenceArea
                  key={`${area.x1}-${area.x2}-${area.tou}`}
                  x1={area.x1}
                  x2={area.x2}
                  yAxisId="power"
                  fill={touFill(area.tou)}
                  strokeOpacity={0}
                />
              ))}
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} interval={selectedDay ? 11 : 2} />
              <YAxis yAxisId="power" tick={{ fontSize: 12 }} label={{ value: "kW", angle: -90, position: "insideLeft" }} />
              <YAxis
                yAxisId="soc"
                orientation="right"
                domain={[0, 100]}
                tick={{ fontSize: 12 }}
                label={{ value: "SOC %", angle: 90, position: "insideRight" }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <ReferenceLine
                yAxisId="power"
                y={monthSummary.contractKw}
                stroke={COLORS.red}
                strokeDasharray="7 7"
                label={{ value: "契約容量上限", fill: COLORS.red, fontSize: 12, position: "insideTopRight" }}
              />
              {Object.entries(seriesConfig).map(([key, item]) => {
                if (!visibleSeries[key]) return null;
                const dataKey = selectedDay ? item.dailyKey : item.monthlyKey;
                return (
                  <Line
                    key={key}
                    type="linear"
                    yAxisId={item.axis}
                    dataKey={dataKey}
                    name={item.label}
                    stroke={item.color}
                    strokeWidth={key === "soc" ? 3 : 2.5}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                    activeDot={{ r: 5 }}
                  />
                );
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          紅色虛線為契約容量；購電功率高於該線時，會形成超約風險。點擊任一日資料點進入 15 分鐘 zoom。
        </p>
      </ChartShell>

      <ChartShell
        title="未來 7 日發電量預測區間"
        description="P10-P90 為不確定性帶，P50 是中位數；灰色虛線用昨日實績做參照。"
        action={
          <div className="flex rounded-xl border border-border bg-white p-1 shadow-sm">
            {[
              ["generation", "發電量預測"],
              ["load", "用電量預測"],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setMcMode(key)}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm font-medium transition-all",
                  mcMode === key ? "bg-[#0F172A] text-white shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        }
      >
        <div className="h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={bandData(activeMc)} margin={{ top: 16, right: 18, left: 8, bottom: 10 }}>
              <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} />
              <XAxis dataKey="label" interval={23} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Area type="linear" dataKey="p10" name="P10" stroke="transparent" fill="transparent" stackId="band" isAnimationActive={false} />
              <Area
                type="linear"
                dataKey="band"
                name="P10-P90 區間"
                stroke="transparent"
                fill={COLORS.green}
                fillOpacity={0.18}
                stackId="band"
                isAnimationActive={false}
              />
              <Line type="linear" dataKey="p50" name={`${mcLabel} P50`} stroke={COLORS.green} strokeWidth={3} dot={false} connectNulls isAnimationActive={false} />
              <Line
                type="linear"
                dataKey="actual"
                name="昨日實績"
                stroke="#94A3B8"
                strokeDasharray="5 5"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">預測區間基於歷史相似日抽樣，僅供規劃參考。</p>
      </ChartShell>
    </div>
  );
}

function DecisionTab({ selectedMonth, setSelectedMonth, selectedDay, setSelectedDay }) {
  const availableMonths = data.monthlySummary;
  const monthSummary = availableMonths.find((row) => row.month === selectedMonth) ?? availableMonths[0];
  const monthKey = String(selectedMonth);
  const availableDays = Object.keys(data.dailySchedules[monthKey] ?? {});
  const day = selectedDay && availableDays.includes(selectedDay) ? selectedDay : availableDays[0];
  const rows = data.dailySchedules[monthKey]?.[day] ?? [];
  const decisionRows = rows.map((row) => ({
    ...row,
    batteryActionKw: row.dischargeKw > 0 ? row.dischargeKw : -row.chargeKw,
  }));
  const touAreas = buildTouAreas(decisionRows);
  const objectiveTerms = data.monthlyExecution[monthKey]?.objectiveTerms ?? [];
  const energyFlows = data.monthlyExecution[monthKey]?.energyFlows ?? [];
  const tooltipRow = decisionRows.find((row) => row.time === "14:00") ?? decisionRows[Math.floor(decisionRows.length / 2)] ?? {};

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-white p-4 shadow-sm md:flex-row md:items-center md:justify-between">
        <div>
          <SectionLabel>DECISION TRACE</SectionLabel>
          <h2 className="mt-3 text-xl font-semibold">MILP 決策解釋</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {monthSummary?.source === "actual_ems" ? "完整 EMS output 調度資料" : "Monte Carlo 發電量校準的未來抽樣情境"}
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <select
            className="h-11 rounded-xl border border-input bg-white px-4 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={selectedMonth}
            onChange={(event) => {
              setSelectedMonth(Number(event.target.value));
              setSelectedDay(null);
            }}
          >
            {availableMonths.map((row) => (
              <option key={row.month} value={row.month}>
                {seasonMonthLabel(row.month)}
              </option>
            ))}
          </select>
          <select
            className="h-11 rounded-xl border border-input bg-white px-4 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={day ?? ""}
            onChange={(event) => setSelectedDay(event.target.value)}
          >
            {availableDays.map((date) => (
              <option key={date} value={date}>
                {scenarioDayLabel(date)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <ChartShell
        title={`${scenarioDayLabel(day)} 日內決策排程`}
        description="背景色代表電價時段，柱狀顯示 PV、台電與電池動作，右軸疊 SOC。"
      >
        <div className="h-[430px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={decisionRows} margin={{ top: 16, right: 18, left: 8, bottom: 10 }}>
              <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} />
              {touAreas.map((area) => (
                <ReferenceArea
                  key={`${area.x1}-${area.x2}-${area.tou}`}
                  x1={area.x1}
                  x2={area.x2}
                  yAxisId="power"
                  fill={touFill(area.tou)}
                  strokeOpacity={0}
                />
              ))}
              <XAxis dataKey="time" interval={11} tick={{ fontSize: 12 }} />
              <YAxis yAxisId="power" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="soc" orientation="right" domain={[0, 100]} tick={{ fontSize: 12 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Bar yAxisId="power" dataKey="pvKw" name="太陽能發電" fill={COLORS.green} fillOpacity={0.82} radius={[6, 6, 0, 0]} isAnimationActive={false} />
              <Bar yAxisId="power" dataKey="gridKw" name="台電取電" fill={COLORS.purple} fillOpacity={0.55} radius={[6, 6, 0, 0]} isAnimationActive={false} />
              <Bar yAxisId="power" dataKey="batteryActionKw" name="電池動作 (+放電/-充電)" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                {decisionRows.map((entry) => (
                  <Cell key={entry.datetime} fill={entry.batteryActionKw >= 0 ? COLORS.orange : COLORS.accentSecondary} />
                ))}
              </Bar>
              <Line yAxisId="soc" type="linear" dataKey="socPercent" name="SOC" stroke={COLORS.blue} strokeWidth={3} dot={false} connectNulls isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 p-4 text-sm text-[#1B4F72]">
          {tooltipRow.time ?? "--"} {tooltipRow.tou === "peak" ? "尖峰" : tooltipRow.tou === "semi" ? "半尖峰" : "離峰"}時段 - 電池
          {tooltipRow.dischargeKw > 0 ? "放電" : tooltipRow.chargeKw > 0 ? "充電" : "待機"}{" "}
          {formatNumber(Math.max(tooltipRow.dischargeKw ?? 0, tooltipRow.chargeKw ?? 0), 1)} kW，太陽能{" "}
          {formatNumber(tooltipRow.pvKw, 1)} kW，購電 {formatNumber(tooltipRow.gridKw, 1)} kW，SOC{" "}
          {formatNumber(tooltipRow.socBeforePercent, 1)}% → {formatNumber(tooltipRow.socAfterPercent, 1)}%。
        </div>
      </ChartShell>

      <div className="grid gap-5 lg:grid-cols-2">
        <ChartShell title="Objective Terms 拆解" description="用來回答這個月的 MILP 成本函數到底被哪些項目主導。">
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={objectiveTerms.slice(0, 8)} layout="vertical" margin={{ top: 10, right: 24, left: 20, bottom: 10 }}>
                <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="name" width={92} tick={{ fontSize: 12 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend />
                <Bar dataKey="value" name="Objective value" fill={COLORS.accent} radius={[0, 8, 8, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartShell>

        <ChartShell title="能源流向" description="PV、台電與電池流向拆解，協助檢查是否有不合理充放電。">
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={energyFlows} margin={{ top: 10, right: 24, left: 10, bottom: 28 }}>
                <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} interval={0} angle={-18} textAnchor="end" />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip content={<CustomTooltip />} />
                <Legend />
                <Bar dataKey="value" name="kWh" fill={COLORS.green} radius={[8, 8, 0, 0]}>
                  {energyFlows.map((entry) => (
                    <Cell key={entry.key} fill={entry.key.includes("grid") ? COLORS.purple : entry.key.includes("battery") ? COLORS.orange : COLORS.green} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartShell>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <ShapChart title="發電量預測 SHAP Top 8" rows={data.shapImportance.solar} />
        <ShapChart title="用電量預測 SHAP Top 8" rows={data.shapImportance.load} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {data.modelMetrics.map((metric) => (
          <Card key={metric.label}>
            <CardContent className="p-5">
              <Badge variant={metric.status === "good" ? "success" : "warning"}>{metric.status === "good" ? "OK" : "WATCH"}</Badge>
              <p className="mt-4 text-sm text-muted-foreground">{metric.label}</p>
              <p className="mt-2 text-3xl font-bold text-foreground">
                {metric.value}
                {metric.suffix}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">{metric.note}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function ShapChart({ title, rows }) {
  return (
    <ChartShell title={title} description="綠色代表正向影響，紅色代表負向影響；目前用現有 SHAP 報表與原型負載特徵。">
      <div className="h-[330px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 10, right: 24, left: 34, bottom: 10 }}>
            <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 12 }} />
            <YAxis type="category" dataKey="feature" width={150} tick={{ fontSize: 12 }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend />
            <ReferenceLine x={0} stroke={COLORS.border} />
            <Bar dataKey="value" name="SHAP impact" radius={[0, 8, 8, 0]}>
              {rows.map((entry) => (
                <Cell key={entry.feature} fill={entry.value >= 0 ? COLORS.green : COLORS.red} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartShell>
  );
}

function RiskScenarioTab({ selectedMonth }) {
  const [params, setParams] = useState({
    batteryCapacity: 2000,
    contractKw: 400,
    lambdaExcess: 300,
    wSoc: 1500,
    month: selectedMonth,
  });
  const [roiCost, setRoiCost] = useState(12_000_000);
  const [lastPreviewAt, setLastPreviewAt] = useState("");

  useEffect(() => {
    setLastPreviewAt(new Date().toLocaleTimeString("zh-TW", { hour12: false }));
  }, [params, roiCost]);

  useEffect(() => {
    setParams((current) => ({ ...current, month: selectedMonth }));
  }, [selectedMonth]);

  const monthSummary = data.monthlySummary.find((row) => row.month === params.month) ?? data.monthlySummary[0];
  const preview = useMemo(() => {
    const baseCost = monthSummary?.b1Cost ?? data.overview.withoutSystemCost;
    const savingsPerKwhCoefficient = 82;
    const contractPressure = Math.max(0, Math.round((500 - params.contractKw) / 18));
    const lowPenaltyRisk = Math.max(0, Math.round((280 - params.lambdaExcess) / 70));
    const overContractEvents = Math.max(0, contractPressure + lowPenaltyRisk);
    const penaltyRate = params.lambdaExcess;
    const estimatedCost = Math.max(120000, baseCost - params.batteryCapacity * savingsPerKwhCoefficient + overContractEvents * penaltyRate);
    const estimatedSavings = baseCost - estimatedCost;
    const annualSaving = estimatedSavings * 12;
    return {
      baseCost,
      savingsPerKwhCoefficient,
      overContractEvents,
      penaltyRate,
      estimatedCost,
      estimatedSavings,
      paybackYears: annualSaving > 0 ? roiCost / annualSaving : Infinity,
    };
  }, [monthSummary, params, roiCost]);

  const annualRows = bandData(data.annualProjection);
  const annualP50 = data.annualProjection.reduce((sum, row) => sum + row.p50, 0);
  const annualP90 = data.annualProjection.reduce((sum, row) => sum + row.p90, 0);
  const paybackP50 = annualP50 > 0 ? roiCost / annualP50 : 0;
  const paybackP90 = annualP90 > 0 ? roiCost / annualP90 : 0;
  const riskCards = [
    {
      title: "超約風險",
      value: monthSummary.peakGridKw > params.contractKw ? "Red" : "Green",
      detail: `峰值 ${formatNumber(monthSummary.peakGridKw, 1)} / 契約 ${formatNumber(params.contractKw, 0)} kW`,
      tone: monthSummary.peakGridKw > params.contractKw ? "danger" : "success",
      icon: ShieldAlert,
    },
    {
      title: "SOC 安全備援",
      value: params.wSoc >= 1200 ? "Green" : "Yellow",
      detail: `SOC 權重 ${formatNumber(params.wSoc, 0)}`,
      tone: params.wSoc >= 1200 ? "success" : "warning",
      icon: BatteryCharging,
    },
    {
      title: "本月最高需量",
      value: `${formatNumber(monthSummary.peakGridKw, 1)} kW`,
      detail: `目前記錄 ${monthSummary.label}`,
      tone: "accent",
      icon: Gauge,
    },
    {
      title: "預測信心度",
      value: monthSummary.pvUtilization > 95 ? "High" : "Medium",
      detail: `PV 利用率 ${percent(monthSummary.pvUtilization)}`,
      tone: monthSummary.pvUtilization > 95 ? "success" : "warning",
      icon: CloudSun,
    },
  ];

  function updateParam(key, value) {
    setParams((current) => ({ ...current, [key]: Array.isArray(value) ? value[0] : value }));
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {riskCards.map((risk) => (
          <Card key={risk.title} className="overflow-hidden">
            <CardContent className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <Badge variant={risk.tone}>{risk.value}</Badge>
                  <p className="mt-4 text-sm text-muted-foreground">{risk.title}</p>
                  <p className="mt-2 text-xl font-bold text-foreground">{risk.detail}</p>
                </div>
                <div className="rounded-2xl bg-slate-50 p-3 text-[#0052FF]">
                  <risk.icon className="h-5 w-5" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border/70">
            <SectionLabel pulse>LIVE PARAMETERS</SectionLabel>
            <CardTitle className="mt-3">即時場景參數</CardTitle>
            <CardDescription>拖曳 slider 會在右側 100ms 內更新簡化估算；不會呼叫後端或重跑 MILP。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 p-5">
            <ScenarioSlider
              label="電池容量 Q"
              value={params.batteryCapacity}
              min={100}
              max={2000}
              step={50}
              suffix="kWh"
              onChange={(value) => updateParam("batteryCapacity", value)}
            />
            <ScenarioSlider
              label="契約容量"
              value={params.contractKw}
              min={200}
              max={800}
              step={10}
              suffix="kW"
              onChange={(value) => updateParam("contractKw", value)}
            />
            <ScenarioSlider
              label="超約懲罰 λ"
              value={params.lambdaExcess}
              min={0}
              max={1000}
              step={10}
              suffix=""
              onChange={(value) => updateParam("lambdaExcess", value)}
            />
            <ScenarioSlider
              label="SOC 追蹤權重 w_soc"
              value={params.wSoc}
              min={0}
              max={3000}
              step={100}
              suffix=""
              onChange={(value) => updateParam("wSoc", value)}
            />
            <label className="block space-y-2">
              <span className="text-sm font-medium text-foreground">模擬月份</span>
              <select
                className="h-11 w-full rounded-xl border border-input bg-white px-4 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                value={params.month}
                onChange={(event) => updateParam("month", Number(event.target.value))}
              >
                {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => (
                  <option key={month} value={month}>
                    {seasonMonthLabel(month)}
                  </option>
                ))}
              </select>
            </label>
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden border-blue-100 bg-white shadow-accent">
          <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#0052FF]/10 blur-[95px]" />
          <CardHeader className="relative border-b border-border/70">
            <div className="flex items-start justify-between gap-4">
              <div>
                <SectionLabel>INSTANT PREVIEW</SectionLabel>
                <CardTitle className="mt-3">快速估算結果</CardTitle>
                <CardDescription>公式：estimated_cost = base_cost - battery_capacity × savings_per_kwh_coefficient + over_contract_events × penalty_rate</CardDescription>
              </div>
              <Badge variant="accent">Updated {lastPreviewAt}</Badge>
            </div>
          </CardHeader>
          <CardContent className="relative p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <PreviewTile title="Estimated monthly cost" value={formatCurrency(preview.estimatedCost)} icon={Zap} />
              <PreviewTile title="Estimated savings vs B1" value={formatCurrency(preview.estimatedSavings)} icon={TrendingDown} tone="green" />
              <PreviewTile title="Over-contract events" value={`${preview.overContractEvents} 次`} icon={ShieldAlert} tone={preview.overContractEvents > 0 ? "red" : "green"} />
              <PreviewTile title="Payback period estimate" value={`${formatNumber(preview.paybackYears, 1)} 年`} icon={CalendarDays} />
            </div>
            <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              快速估算，點擊執行取得精確結果。此 prototype 的完整場景按鈕只做視覺展示，不呼叫 backend。
            </div>
            <Button className="mt-5 w-full md:w-auto">
              <Play className="h-4 w-4" />
              執行完整場景
            </Button>
          </CardContent>
        </Card>
      </div>

      <ChartShell
        title="Monte Carlo 年度節省投影"
        description="以現有年度太陽能 MC 投影折算節省範圍，做為年度 ROI 的簡化前視估算。"
      >
        <div className="h-[360px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={annualRows} margin={{ top: 16, right: 18, left: 8, bottom: 10 }}>
              <CartesianGrid stroke={COLORS.border} strokeOpacity={0.5} />
              <XAxis dataKey="label" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(value) => `${Math.round(value / 10000)}萬`} tick={{ fontSize: 12 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Area type="monotone" dataKey="p10" name="P10" stroke="transparent" fill="transparent" stackId="annual" />
              <Area type="monotone" dataKey="band" name="P10-P90 區間" stroke="transparent" fill={COLORS.accent} fillOpacity={0.14} stackId="annual" />
              <Line type="monotone" dataKey="p10" name="P10 保守" stroke="#94A3B8" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="p50" name="P50 中位" stroke={COLORS.accent} strokeWidth={3} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="p90" name="P90 樂觀" stroke={COLORS.green} strokeWidth={2.5} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-[1fr_1.2fr]">
          <label className="space-y-2">
            <span className="text-sm font-medium text-foreground">電池系統建置成本</span>
            <Input type="number" value={roiCost} onChange={(event) => setRoiCost(Number(event.target.value))} />
          </label>
          <div className="rounded-2xl bg-slate-50 p-4 text-sm text-muted-foreground">
            年度預期節省 {formatCurrency(annualP50)} (P50 情境)。投資回收期約{" "}
            <span className="font-semibold text-foreground">{formatNumber(paybackP50, 1)} 年</span>，樂觀情境{" "}
            <span className="font-semibold text-foreground">{formatNumber(paybackP90, 1)} 年</span>。
          </div>
        </div>
      </ChartShell>
    </div>
  );
}

function ScenarioSlider({ label, value, min, max, step, suffix, onChange }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="font-mono text-sm text-[#0052FF]">
          {formatNumber(value, 0)}
          {suffix ? ` ${suffix}` : ""}
        </span>
      </div>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={onChange} />
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

function PreviewTile({ title, value, icon: Icon, tone = "blue" }) {
  const colors = {
    blue: "text-[#0052FF] bg-blue-50",
    green: "text-[#2D7D46] bg-emerald-50",
    red: "text-[#C0392B] bg-red-50",
  };
  return (
    <div className="rounded-2xl border border-border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{title}</p>
        <div className={cn("rounded-xl p-2", colors[tone])}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <p className="mt-3 text-2xl font-bold tracking-normal text-foreground">{value}</p>
    </div>
  );
}

function labelMonth(month) {
  return `${String(month).padStart(2, "0")}月`;
}

export default function EMSDashboard() {
  const availableMonths = data.monthlySummary;
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedMonth, setSelectedMonth] = useState(7);
  const [selectedDay, setSelectedDay] = useState(null);
  const [mcMode, setMcMode] = useState("generation");
  const [visibleSeries, setVisibleSeries] = useState({
    load: true,
    pv: true,
    grid: true,
    charge: false,
    discharge: false,
    soc: true,
  });

  const overview = data.overview;
  const generatedDate = new Date(data.generatedAt).toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#FAFAFA]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(circle_at_20%_10%,rgba(0,82,255,0.12),transparent_32%),radial-gradient(circle_at_85%_20%,rgba(77,124,255,0.10),transparent_28%)]" />
      <div className="relative mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <header className="relative mb-6">
          <div>
            <SectionLabel pulse>ENERGY MANAGEMENT OPTIMIZATION</SectionLabel>
            <h1 className="mt-5 max-w-4xl font-display text-[2.7rem] leading-[1.05] tracking-normal text-foreground md:text-6xl">
              數據分析應用於工廠用電與太陽能發電
              <span className="gradient-text"> 排程最佳化</span>
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-muted-foreground md:text-lg">
              結合負載預測、太陽能發電預測、電池儲能與契約容量限制，建立能源管理系統的最佳化調度流程，並評估節費成效、超約風險與不同情境參數的影響。
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              <Badge variant="accent">專題展示資料</Badge>
              <span>資料產生：{generatedDate}</span>
              <span className="hidden h-1 w-1 rounded-full bg-slate-300 sm:block" />
              <span className="truncate">來源：既有 EMS 輸出校準 + Monte Carlo 未來年度情境</span>
              <a
                href="./owner-full-grid-robust-comparison.html"
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-blue-200 bg-white px-4 font-medium text-[#0052FF] shadow-sm transition hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0052FF] focus-visible:ring-offset-2"
              >
                穩健最佳化比較
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
              </a>
            </div>
          </div>
        </header>

        <section className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <HeroMetricCard
            title="無系統每月電費"
            value={formatCurrency(overview.withoutSystemCost)}
            label="B1 無電池基準"
            tone="red"
            icon={Activity}
          />
          <HeroMetricCard
            title="MILP 系統電費"
            value={formatCurrency(overview.milpCost)}
            label="本系統"
            tone="green"
            icon={CheckCircle2}
          />
          <HeroMetricCard
            title="每月節省"
            value={formatCurrency(overview.monthlySavings)}
            label="Advanced EMS vs B1"
            badge={`-${percent(overview.savingsRate)}`}
            tone="dark"
            icon={ArrowDownRight}
            dominant
          />
          <HeroMetricCard title="PV 利用率" value={percent(overview.pvUtilization)} label="再生能源使用效率" tone="blue" icon={CloudSun}>
            <div className="mt-5 h-2 rounded-full bg-white/60">
              <div className="h-full rounded-full bg-gradient-to-r from-[#0052FF] to-[#4D7CFF]" style={{ width: `${overview.pvUtilization}%` }} />
            </div>
          </HeroMetricCard>
        </section>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="relative">
          <div className="sticky top-0 z-20 -mx-4 border-y border-border/70 bg-[#FAFAFA]/85 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border sm:shadow-sm">
            <TabsList className="flex w-full justify-start gap-1 overflow-x-auto">
              <TabsTrigger value="overview">總覽與節費</TabsTrigger>
              <TabsTrigger value="execution">月調度執行</TabsTrigger>
              <TabsTrigger value="decision">MILP 決策解釋</TabsTrigger>
              <TabsTrigger value="risk">風險檢查 / 場景重跑</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="overview">
            <OverviewTab
              overview={overview}
              waterfall={data.waterfall}
              strategyComparison={data.strategyComparison}
              monthlySummary={data.monthlySummary}
            />
          </TabsContent>

          <TabsContent value="execution">
            <MonthlyExecutionTab
              months={availableMonths}
              selectedMonth={selectedMonth}
              setSelectedMonth={setSelectedMonth}
              selectedDay={selectedDay}
              setSelectedDay={setSelectedDay}
              visibleSeries={visibleSeries}
              setVisibleSeries={setVisibleSeries}
              mcMode={mcMode}
              setMcMode={setMcMode}
            />
          </TabsContent>

          <TabsContent value="decision">
            <DecisionTab selectedMonth={selectedMonth} setSelectedMonth={setSelectedMonth} selectedDay={selectedDay} setSelectedDay={setSelectedDay} />
          </TabsContent>

          <TabsContent value="risk">
            <RiskScenarioTab selectedMonth={selectedMonth} />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  );
}
