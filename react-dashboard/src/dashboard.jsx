import { useEffect, useMemo, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import {
  AlertTriangle,
  BatteryCharging,
  CheckCircle2,
  CircleDollarSign,
  CloudSun,
  Gauge,
  ShieldCheck,
  Zap,
} from "lucide-react";

import data from "@/data/ems-dashboard-data.json";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const COLORS = {
  green: "#2D7D46",
  greenLight: "#A7D8B5",
  red: "#C0392B",
  gray: "#9CA3AF",
  graphite: "#18201C",
  blue: "#1B4F72",
  purple: "#6D5BD0",
  orange: "#D97706",
  grid: "#DDE4E0",
};
const scenarioMethodLabel = `${data.meta.drawCount} 條 7 日配對區塊抽樣路徑，縮減為 ${data.meta.optimizationScenarioCount} 個 medoid 求解情境與 ${data.meta.stressScenarioCount} 個壓力包絡`;
const decisionStructureLabel = "前 60 分鐘採跨情境共識決策；之後依首小時實測負載與 PV，選擇最接近的配對情境分支執行。";
const dataLimitationLabel = "目前缺少同年度的完整負載與 PV 聯合紀錄，因此採跨年度、同日曆位置的配對類比資料。";

const currency = (value) =>
  `NT$ ${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Number(value || 0))}`;

const number = (value, digits = 0) =>
  new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(Number(value || 0));

function tooltipValue(value, key = "") {
  if (Array.isArray(value)) return `${number(value[0], 1)} - ${number(value[1], 1)} kW`;
  if (/cost|saving/i.test(key)) return currency(value);
  if (/soc/i.test(key)) return `${number(value, 1)}%`;
  if (/utilization|coverage/i.test(key)) return `${number(value, 1)}%`;
  return number(value, 1);
}

function ChartTooltip({ active, payload, label, context }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="max-w-[280px] rounded-lg border border-[#D9E0DC] bg-white p-3 text-xs shadow-xl">
      <p className="mb-2 font-semibold text-[#18201C]">{context ? `${context} · ` : ""}{label}</p>
      <div className="space-y-1.5">
        {payload
          .filter((item) => item.value !== undefined && item.value !== null)
          .map((item) => (
            <div key={`${item.dataKey}-${item.name}`} className="flex items-center justify-between gap-5">
              <span className="flex items-center gap-2 text-[#66716B]">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color || item.fill }} />
                {item.name}
              </span>
              <strong className="tabular text-[#18201C]">{tooltipValue(item.value, String(item.dataKey))}</strong>
            </div>
          ))}
      </div>
    </div>
  );
}

function SectionHeading({ eyebrow, title, description, action }) {
  return (
    <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
      <div>
        <p className="eyebrow mb-2">{eyebrow}</p>
        <h2 className="text-xl font-semibold text-[#18201C]">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-sm leading-6 text-[#66716B]">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function ChartCard({ title, description, children, className = "" }) {
  return (
    <Card className={`min-w-0 overflow-visible ${className}`}>
      <CardHeader className="border-b border-border p-5">
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <p className="text-sm leading-5 text-[#66716B]">{description}</p>}
      </CardHeader>
      <CardContent className="overflow-visible p-4 pt-5 sm:p-5">{children}</CardContent>
    </Card>
  );
}

function MetricCard({ label, value, note, icon: Icon, tone = "neutral" }) {
  const tones = {
    red: "border-red-200 bg-red-50 text-[#C0392B]",
    green: "border-green-200 bg-green-50 text-[#2D7D46]",
    dark: "border-[#18201C] bg-[#18201C] text-white",
    neutral: "border-border bg-white text-[#18201C]",
  };
  return (
    <Card className={`${tones[tone]} min-h-[164px] shadow-sm`}>
      <CardContent className="flex h-full flex-col justify-between p-5">
        <div className="flex items-start justify-between gap-4">
          <p className={`text-sm font-medium ${tone === "dark" ? "text-white/70" : "opacity-75"}`}>{label}</p>
          <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
        </div>
        <div>
          <p className="tabular mt-4 text-2xl font-bold leading-none 2xl:text-3xl">{value}</p>
          <p className={`mt-3 text-xs leading-5 ${tone === "dark" ? "text-white/65" : "opacity-70"}`}>{note}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function OverviewTab({ onSelectMonth }) {
  const executive = data.executiveSummary;
  const riskData = data.strategyComparison
    .filter((row) => ["deterministic", "robust"].includes(row.key))
    .map((row) => ({ name: row.label, P50: row.p50Cost, P90: row.p90Cost }));

  return (
    <div className="space-y-7">
      <section>
        <SectionHeading
          eyebrow="年度決策總覽"
          title="年度成本與風險，一次看清楚"
          description="所有金額來自同一批全年 P-Robust 規劃模擬；比較完全買電、PV 自用、確定性 MILP 與 P-Robust。"
        />
        <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
          <ChartCard title="四策略年度電費" description="長條越短代表年度結算成本越低；滑鼠停留可檢查成本與風險指標。">
            <div className="h-[350px] min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <BarChart data={data.strategyComparison} margin={{ top: 12, right: 18, left: 10, bottom: 16 }}>
                  <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} interval={0} />
                  <YAxis tickFormatter={(v) => `${number(v / 10000)}萬`} width={58} />
                  <Tooltip content={<ChartTooltip context="年度電費" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 40 }} />
                  <Legend />
                  <Bar dataKey="annualCost" name="年度電費" radius={[4, 4, 0, 0]}>
                    {data.strategyComparison.map((row) => (
                      <Cell key={row.key} fill={row.key === "robust" ? COLORS.green : row.key === "allGrid" ? COLORS.red : COLORS.gray} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="一般情境與不利情境" description="P50 代表一般結算；P90 代表較不利但仍具代表性的年度成本。">
            <div className="h-[350px] min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <BarChart data={riskData} margin={{ top: 12, right: 18, left: 10, bottom: 16 }}>
                  <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tickFormatter={(v) => `${number(v / 10000)}萬`} width={58} />
                  <Tooltip content={<ChartTooltip context="情境成本" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 40 }} />
                  <Legend />
                  <Bar dataKey="P50" name="一般情境 P50" fill={COLORS.gray} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="P90" name="不利情境 P90" fill={COLORS.green} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>
      </section>

      <ChartCard title="12 個月成本走勢" description="點選月份會同步切換日調度頁的代表日；P-Robust 不一定每月最低，但目標是限制不利情境的相對損失。">
        <div className="h-[380px] min-w-0">
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
            <BarChart
              data={data.monthlyComparison}
              margin={{ top: 12, right: 18, left: 10, bottom: 10 }}
              onClick={(event) => {
                const row = event?.activePayload?.[0]?.payload;
                if (row?.month) onSelectMonth(row.month);
              }}
            >
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={(v) => `${number(v / 10000)}萬`} width={58} />
              <Tooltip content={<ChartTooltip context="月結算" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 40 }} />
              <Legend />
              <Bar dataKey="allGridCost" name="完全買電" fill={COLORS.red} radius={[3, 3, 0, 0]} />
              <Bar dataKey="deterministicCost" name="確定性 MILP" fill={COLORS.gray} radius={[3, 3, 0, 0]} />
              <Bar dataKey="robustCost" name="P-Robust" fill={COLORS.green} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 border-t border-border pt-4 text-sm text-[#66716B]">
          <span>年度節省 <strong className="text-[#2D7D46]">{currency(executive.robustSavings)}</strong></span>
          <span>相對完全買電 <strong className="text-[#2D7D46]">{number(executive.robustSavingsRate, 1)}%</strong></span>
          <span>不利情境改善 <strong className="text-[#2D7D46]">{currency(executive.downsideReduction)}</strong></span>
        </div>
      </ChartCard>
    </div>
  );
}

function RobustTab() {
  const solved = data.robustnessFrontier.filter((row) => row.status === "solved");
  const initial = Math.max(0, solved.findIndex((row) => row.selected));
  const [pointIndex, setPointIndex] = useState(initial);
  const point = solved[pointIndex] || solved[0];
  const strategies = data.strategyComparison.filter((row) => ["deterministic", "robust"].includes(row.key));

  return (
    <div className="space-y-7">
      <section>
        <SectionHeading
          eyebrow="穩健策略權衡"
          title="用已求解的 p 值選擇成本與風險平衡"
          description="滑桿只切換已完成求解的結果，不做內插，也不在瀏覽器裡假裝重跑 MILP。"
        />
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">容許遺憾 p</span>
                <Badge variant="success">{number((point?.p || 0) * 100)}%</Badge>
              </div>
              <Slider
                className="my-7"
                min={0}
                max={Math.max(0, solved.length - 1)}
                step={1}
                value={[pointIndex]}
                onValueChange={([value]) => setPointIndex(value)}
                aria-label="P-Robust solved point"
              />
              <div className="flex justify-between text-xs text-[#66716B]">
                {solved.map((row) => <span key={row.p}>{number(row.p * 100)}%</span>)}
              </div>
              <div className="mt-7 grid grid-cols-2 gap-3">
                <SmallStat label="期望成本" value={currency(point?.expectedCost)} />
                <SmallStat label="最差成本" value={currency(point?.worstCost)} />
                <SmallStat label="超約事件" value={`${number(point?.overContractEvents, 1)} 次`} />
                <SmallStat label="Regret 覆蓋" value={`${number(point?.regretCoverage, 1)}%`} />
              </div>
              <p className="mt-5 border-t border-border pt-4 text-xs leading-5 text-[#66716B]">
                前緣數據範圍為代表日 {point?.month}月{point?.day}日；年度成果使用選定 p 值逐日求解。
              </p>
            </CardContent>
          </Card>

          <ChartCard title="成本與風險前緣" description="越靠左下越好；點位顯示各個已求解 p 值的期望成本與最差情境成本。">
            <div className="h-[360px] min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <ScatterChart margin={{ top: 18, right: 28, left: 12, bottom: 14 }}>
                  <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="expectedCost" name="期望成本" tickFormatter={(v) => number(v)} domain={["dataMin - 100", "dataMax + 100"]} />
                  <YAxis type="number" dataKey="worstCost" name="最差成本" tickFormatter={(v) => number(v)} width={70} domain={["dataMin - 100", "dataMax + 100"]} />
                  <ZAxis range={[90, 90]} />
                  <Tooltip content={<ChartTooltip context="穩健前緣" />} cursor={{ strokeDasharray: "3 3" }} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 40 }} />
                  <Legend />
                  <Scatter
                    name="已求解 p 值"
                    data={solved}
                    fill={COLORS.green}
                    line={{ stroke: COLORS.green, strokeWidth: 2 }}
                    onClick={(row) => setPointIndex(Math.max(0, solved.findIndex((item) => item.p === row.p)))}
                  >
                    {solved.map((row, index) => <Cell key={row.p} fill={index === pointIndex ? COLORS.red : COLORS.green} />)}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard title="Downside 成本比較" description="比較確定性與 P-Robust 在一般情境 P50 與不利情境 P90 的結算成本。">
          <div className="h-[330px] min-w-0">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
              <BarChart data={strategies} margin={{ top: 10, right: 18, left: 10, bottom: 8 }}>
                <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" />
                <YAxis tickFormatter={(v) => `${number(v / 10000)}萬`} width={58} />
                <Tooltip content={<ChartTooltip />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 40 }} />
                <Legend />
                <Bar dataKey="p50Cost" name="P50 成本" fill={COLORS.gray} radius={[3, 3, 0, 0]} />
                <Bar dataKey="p90Cost" name="P90 成本" fill={COLORS.green} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <Card className="bg-[#18201C] text-white">
          <CardContent className="p-6">
            <p className="eyebrow !text-[#A7D8B5]">Owner readout</p>
            <h3 className="mt-3 text-2xl font-semibold">穩健成本換到了什麼</h3>
            <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-white/15">
              <DarkStat label="穩健成本" value={currency(data.executiveSummary.robustPremium)} />
              <DarkStat label="P90 downside 改善" value={currency(data.executiveSummary.downsideReduction)} />
              <DarkStat label="確定性超約" value={`${number(strategies[0]?.overContractEvents)} 次`} />
              <DarkStat label="穩健超約" value={`${number(strategies[1]?.overContractEvents)} 次`} />
            </div>
            <p className="mt-6 text-sm leading-6 text-white/70">{data.executiveSummary.businessConclusion}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SmallStat({ label, value }) {
  return <div className="rounded-lg bg-[#F4F7F5] p-3"><p className="text-xs text-[#66716B]">{label}</p><p className="tabular mt-1 text-sm font-semibold">{value}</p></div>;
}

function DarkStat({ label, value }) {
  return <div className="bg-[#18201C] p-4"><p className="text-xs text-white/55">{label}</p><p className="tabular mt-2 text-lg font-semibold">{value}</p></div>;
}

const SERIES = {
  load: { name: "負載", color: COLORS.graphite },
  pv: { name: "PV", color: COLORS.green },
  grid: { name: "購電", color: COLORS.purple },
  soc: { name: "SOC", color: COLORS.blue },
  charge: { name: "充電", color: "#4F7DF3" },
  discharge: { name: "放電", color: COLORS.orange },
  contract: { name: "契約容量", color: COLORS.red },
};

function DispatchTab({ month, setMonth }) {
  const [day, setDay] = useState(15);
  const [mode, setMode] = useState("robust");
  const [selectedTime, setSelectedTime] = useState("14:00");
  const [visible, setVisible] = useState({ load: true, pv: true, grid: true, soc: true, charge: false, discharge: false, contract: false });
  const days = data.dailyDispatch[String(month)] || [];

  useEffect(() => {
    if (!days.some((item) => item.day === day)) setDay(days[0]?.day || 1);
  }, [month, day, days]);

  const selectedDay = days.find((item) => item.day === day) || days[0];
  const rows = useMemo(
    () => (selectedDay?.rows || []).map((row) => ({ ...row, actualNetKw: row.loadKw - row.pvKw })),
    [selectedDay],
  );
  const selectedRow = rows.find((row) => row.time === selectedTime) || rows[Math.min(56, rows.length - 1)];
  const prefix = mode === "robust" ? "robust" : "deterministic";
  const gridKey = `${prefix}GridKw`;
  const chargeKey = `${prefix}ChargeKw`;
  const dischargeKey = `${prefix}DischargeKw`;
  const socKey = `${prefix}Soc`;

  const reason = (() => {
    if (!selectedRow) return "尚無代表日資料。";
    if (selectedRow[dischargeKey] > 1) return `${selectedRow.time} ${touLabel(selectedRow.tou)}，電池放電 ${number(selectedRow[dischargeKey], 1)} kW，優先壓低購電與超約風險。`;
    if (selectedRow[chargeKey] > 1 && selectedRow.pvKw > 1) return `${selectedRow.time} PV 出力充足，電池吸收 ${number(selectedRow[chargeKey], 1)} kW，保留後續尖峰時段的放電能力。`;
    return `${selectedRow.time} 維持待機，SOC ${number(selectedRow[socKey], 1)}%，目前沒有足以抵銷退化成本的充放電誘因。`;
  })();

  return (
    <div className="space-y-7">
      <section>
        <SectionHeading
          eyebrow="日內調度"
          title="跨月份抽查日內調度"
          description="每月提供 8、15、22 日三個正式求解代表日。切換確定性與 P-Robust，可直接比較購電、SOC 與充放電行為。"
          action={<DispatchSelectors month={month} setMonth={setMonth} days={days} day={day} setDay={setDay} mode={mode} setMode={setMode} />}
        />
        <ChartCard title={`${month}月 ${selectedDay?.label || "代表日"}排程`} description="預設只顯示負載、PV、購電與 SOC；按鈕可加入充電、放電與契約容量。">
          <div className="mb-4 flex flex-wrap gap-2">
            {Object.entries(SERIES).map(([key, series]) => (
              <button
                key={key}
                type="button"
                onClick={() => setVisible((current) => ({ ...current, [key]: !current[key] }))}
                className={`min-h-11 rounded-lg border px-3 text-sm font-medium transition-colors ${visible[key] ? "border-[#18201C] bg-[#18201C] text-white" : "border-border bg-white text-[#66716B] hover:border-[#2D7D46]"}`}
                aria-pressed={visible[key]}
              >
                <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: series.color }} />{series.name}
              </button>
            ))}
          </div>
          <div className="h-[420px] min-w-0">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
              <ComposedChart
                data={rows}
                margin={{ top: 10, right: 22, left: 8, bottom: 12 }}
                onClick={(event) => event?.activeLabel && setSelectedTime(event.activeLabel)}
              >
                <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
                <XAxis dataKey="time" interval={11} />
                <YAxis yAxisId="power" unit=" kW" width={66} />
                <YAxis yAxisId="soc" orientation="right" domain={[0, 100]} unit="%" width={50} />
                <Tooltip content={<ChartTooltip context={`${mode === "robust" ? "P-Robust" : "確定性"} · ${month}月${day}日`} />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 50 }} />
                <Legend />
                {visible.load && <Line yAxisId="power" type="monotone" dataKey="loadKw" name="負載" stroke={SERIES.load.color} strokeWidth={2} dot={false} isAnimationActive={false} />}
                {visible.pv && <Line yAxisId="power" type="monotone" dataKey="pvKw" name="PV" stroke={SERIES.pv.color} strokeWidth={2} dot={false} isAnimationActive={false} />}
                {visible.grid && <Line yAxisId="power" type="monotone" dataKey={gridKey} name="購電" stroke={SERIES.grid.color} strokeWidth={2} dot={false} isAnimationActive={false} />}
                {visible.charge && <Line yAxisId="power" type="stepAfter" dataKey={chargeKey} name="充電" stroke={SERIES.charge.color} dot={false} isAnimationActive={false} />}
                {visible.discharge && <Line yAxisId="power" type="stepAfter" dataKey={dischargeKey} name="放電" stroke={SERIES.discharge.color} dot={false} isAnimationActive={false} />}
                {visible.contract && <Line yAxisId="power" type="stepAfter" dataKey="contractKw" name="契約容量" stroke={SERIES.contract.color} strokeDasharray="6 4" dot={false} isAnimationActive={false} />}
                {visible.soc && <Line yAxisId="soc" type="monotone" dataKey={socKey} name="SOC" stroke={SERIES.soc.color} strokeWidth={2.5} dot={false} isAnimationActive={false} />}
                <ReferenceLine yAxisId="power" x={selectedRow?.time} stroke="#7B8781" strokeDasharray="2 4" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm leading-6 text-[#245F36]">
            <strong>決策解釋：</strong>{reason}
          </div>
        </ChartCard>
      </section>

      <ChartCard title="Scenario envelope" description="P10-P90 為配對情境的淨負載包絡；實際結算路徑用當日負載減 PV 計算。">
        <div className="h-[340px] min-w-0">
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
            <ComposedChart data={rows} margin={{ top: 10, right: 22, left: 8, bottom: 10 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
              <XAxis dataKey="time" interval={11} />
              <YAxis unit=" kW" width={66} />
              <Tooltip content={<ChartTooltip context="淨負載情境" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 50 }} />
              <Legend />
              <Area type="monotone" dataKey={(row) => [row.netP10Kw, row.netP90Kw]} name="P10-P90 區間" fill={COLORS.greenLight} stroke="none" fillOpacity={0.45} isAnimationActive={false} />
              <Line type="monotone" dataKey="netP50Kw" name="P50" stroke={COLORS.green} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="actualNetKw" name="實際結算" stroke={COLORS.graphite} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>
    </div>
  );
}

function touLabel(value) {
  return ({ peak: "尖峰時段", semi: "半尖峰時段", sat_semi: "週六半尖峰", off: "離峰時段" })[value] || value;
}

function DispatchSelectors({ month, setMonth, days, day, setDay, mode, setMode }) {
  const selectClass = "h-11 rounded-lg border border-border bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#2D7D46]";
  return (
    <div className="flex flex-wrap gap-2">
      <select className={selectClass} value={month} onChange={(event) => setMonth(Number(event.target.value))} aria-label="月份">
        {Array.from({ length: 12 }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}月</option>)}
      </select>
      <select className={selectClass} value={day} onChange={(event) => setDay(Number(event.target.value))} aria-label="代表日">
        {days.map((item) => <option key={item.day} value={item.day}>{item.label}</option>)}
      </select>
      <div className="flex rounded-lg border border-border bg-white p-1">
        {[{ key: "deterministic", label: "確定性" }, { key: "robust", label: "P-Robust" }].map((item) => (
          <button key={item.key} type="button" onClick={() => setMode(item.key)} className={`min-h-9 rounded-md px-3 text-sm ${mode === item.key ? "bg-[#18201C] text-white" : "text-[#66716B]"}`}>{item.label}</button>
        ))}
      </div>
    </div>
  );
}

function EvidenceTab() {
  const coverage = data.scenarioCoverage;
  const billing = Object.entries(data.billingBreakdown).map(([key, row]) => ({
    name: data.strategyComparison.find((item) => item.key === key)?.label || key,
    購電電費: row.energyCost,
    基本電費: row.basicCost,
    超約電費: row.excessCost,
    電池退化: row.degradationCost,
  }));
  return (
    <div className="space-y-7">
      <section>
        <SectionHeading eyebrow="模型證據" title="情境、求解與計費證據" description="這一頁保留模型可追溯資訊；對外提案時可切換技術模式再展開。" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <EvidenceCard icon={ShieldCheck} label="建置期包絡 coverage" value={`${number(coverage.net_load_pointwise_envelope_coverage * 100, 1)}%`} note={`目標 ${number(coverage.coverage_target * 100)}%`} />
          <EvidenceCard icon={coverage.exPostRegretPassed ? CheckCircle2 : AlertTriangle} label="樣本外 regret 覆蓋" value={`${number(coverage.exPostRegretCoverage, 1)}%`} note={`${coverage.exPostRegretPassed ? "通過" : "未通過"} ${number(coverage.exPostRegretTarget)}% 門檻`} alert={!coverage.exPostRegretPassed} />
          <EvidenceCard icon={CloudSun} label="求解 / 壓力情境" value={`${data.meta.optimizationScenarioCount} + ${data.meta.stressScenarioCount}`} note={`由 ${number(data.meta.drawCount)} 條路徑縮減`} />
          <EvidenceCard icon={Gauge} label="每日求解中位數" value={`${number(coverage.dailyMedianSolveSeconds, 3)} 秒`} note={`P95 ${number(coverage.dailyP95SolveSeconds, 3)} 秒`} />
          <EvidenceCard icon={CheckCircle2} label="Solver 狀態" value={data.meta.status === "valid" ? "VALID" : "INVALID"} note={`${data.meta.solver} · seed ${data.meta.seed}`} />
        </div>
      </section>

      <ChartCard title="年度電費組成" description="成本以同一 tariff 版本結算，電池策略另計退化成本。">
        <div className="h-[390px] min-w-0">
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
            <BarChart data={billing} margin={{ top: 10, right: 20, left: 10, bottom: 12 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" interval={0} />
              <YAxis tickFormatter={(v) => `${number(v / 10000)}萬`} width={58} />
              <Tooltip content={<ChartTooltip context="年度計費" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 50 }} />
              <Legend />
              <Bar stackId="cost" dataKey="購電電費" fill={COLORS.green} />
              <Bar stackId="cost" dataKey="基本電費" fill={COLORS.blue} />
              <Bar stackId="cost" dataKey="超約電費" fill={COLORS.red} />
              <Bar stackId="cost" dataKey="電池退化" fill={COLORS.gray} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardContent className="p-5"><h3 className="font-semibold">模型假設</h3><dl className="mt-4 space-y-3 text-sm"><EvidenceRow label="情境方法" value={scenarioMethodLabel} /><EvidenceRow label="決策結構" value={decisionStructureLabel} /><EvidenceRow label="SOC 邊界" value={`${number(data.modelAssumptions.battery.soc_min * 100)}% - ${number(data.modelAssumptions.battery.soc_max * 100)}%`} /><EvidenceRow label="時間解析度" value={`${data.modelAssumptions.timestepMinutes} 分鐘`} /></dl></CardContent></Card>
        <Card className="border-amber-200 bg-amber-50"><CardContent className="p-5"><div className="flex items-center gap-2 font-semibold text-amber-900"><AlertTriangle className="h-5 w-5" />資料限制</div><p className="mt-4 text-sm leading-6 text-amber-900/80">{dataLimitationLabel}</p><p className="mt-4 text-sm font-semibold text-amber-950">{data.meta.simulationLabel}</p><p className="mt-2 text-xs leading-5 text-amber-900/70">Tariff: {data.meta.tariffVersion}</p></CardContent></Card>
      </div>
    </div>
  );
}

function EvidenceCard({ icon: Icon, label, value, note, alert = false }) {
  return <Card className={alert ? "border-red-200 bg-red-50" : ""}><CardContent className="p-5"><Icon className={`h-5 w-5 ${alert ? "text-[#C0392B]" : "text-[#2D7D46]"}`} /><p className="mt-5 text-xs text-[#66716B]">{label}</p><p className="tabular mt-2 text-2xl font-semibold">{value}</p><p className={`mt-2 text-xs ${alert ? "text-[#C0392B]" : "text-[#7B8781]"}`}>{note}</p></CardContent></Card>;
}

function EvidenceRow({ label, value }) {
  return <div className="grid grid-cols-[110px_1fr] gap-3 border-b border-border pb-3 last:border-0"><dt className="text-[#66716B]">{label}</dt><dd className="break-words font-medium leading-6">{value}</dd></div>;
}

export default function EMSDashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedMonth, setSelectedMonth] = useState(7);
  const executive = data.executiveSummary;
  const deterministic = data.strategyComparison.find((row) => row.key === "deterministic");
  const robust = data.strategyComparison.find((row) => row.key === "robust");
  const overContractReduction = (deterministic?.overContractEvents || 0) - (robust?.overContractEvents || 0);
  const selectMonthAndDispatch = (month) => { setSelectedMonth(month); setActiveTab("dispatch"); };

  return (
    <main className="min-h-screen bg-[#F8FAF9]">
      <div className="border-b border-border bg-white">
        <div className="mx-auto max-w-[1480px] px-4 py-8 sm:px-6 lg:px-8">
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2"><Badge variant="success">P-Robust EMS</Badge><span className="text-xs text-[#66716B]">{data.meta.simulationLabel}</span></div>
            <h1 className="max-w-4xl text-3xl font-bold leading-tight text-[#18201C] sm:text-4xl">數據分析應用於工廠用電與太陽能發電排程最佳化</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[#66716B]">以年度電費、超約風險與日內調度為主軸，比較確定性 MILP 與 P-Robust 策略。</p>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1480px] px-4 py-6 sm:px-6 lg:px-8">
        <section className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="完全買電年度成本" value={currency(executive.allGridAnnualCost)} note="沒有 PV 與電池調度的成本基準" icon={Zap} tone="red" />
          <MetricCard label="確定性 MILP 年度成本" value={currency(executive.deterministicAnnualCost)} note="使用點預測的日內最佳化" icon={BatteryCharging} />
          <MetricCard label="P-Robust 年度成本" value={currency(executive.robustAnnualCost)} note={`選定 p = ${number(executive.selectedP * 100)}%`} icon={ShieldCheck} tone="green" />
          <MetricCard label="相對完全買電節省" value={currency(executive.robustSavings)} note={`${number(executive.robustSavingsRate, 1)}% 年度成本改善`} icon={CircleDollarSign} tone="dark" />
        </section>

        <div className="mb-6 rounded-lg border border-green-200 bg-green-50 px-5 py-4 text-sm font-medium leading-6 text-[#245F36]">
          以 {currency(executive.robustPremium)} 的年度穩健成本，使 P90 不利情境成本改善 {currency(executive.downsideReduction)}，並讓超約事件減少 {number(overContractReduction)} 次。
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <div className="sticky top-0 z-30 -mx-4 border-y border-border bg-[#F8FAF9]/95 px-4 py-3 backdrop-blur-sm sm:mx-0 sm:rounded-lg sm:border">
            <TabsList className="flex w-full justify-start gap-1 overflow-x-auto">
              <TabsTrigger value="overview">決策總覽</TabsTrigger>
              <TabsTrigger value="robust">穩健策略</TabsTrigger>
              <TabsTrigger value="dispatch">日調度</TabsTrigger>
              <TabsTrigger value="evidence">模型證據</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview">{activeTab === "overview" && <OverviewTab onSelectMonth={selectMonthAndDispatch} />}</TabsContent>
          <TabsContent value="robust">{activeTab === "robust" && <RobustTab />}</TabsContent>
          <TabsContent value="dispatch">{activeTab === "dispatch" && <DispatchTab month={selectedMonth} setMonth={setSelectedMonth} />}</TabsContent>
          <TabsContent value="evidence">{activeTab === "evidence" && <EvidenceTab />}</TabsContent>
        </Tabs>
      </div>
    </main>
  );
}
