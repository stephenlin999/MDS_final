import { useMemo, useState } from "react";
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
import { ArrowRight, CheckCircle2, ChevronDown, ShieldCheck } from "lucide-react";

import data from "@/data/ems-dashboard-data.json";

const C = {
  green: "#2D7D46",
  pale: "#A7D8B5",
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

const money = (value) => `NT$ ${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(Number(value || 0))}`;
const num = (value, digits = 0) => new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(Number(value || 0));

function valueLabel(value, key = "") {
  if (Array.isArray(value)) return `${num(value[0], 1)} - ${num(value[1], 1)} kW`;
  if (/cost|saving/i.test(key)) return money(value);
  if (/soc/i.test(key)) return `${num(value, 1)}%`;
  return num(value, 1);
}

function FloatingTooltip({ active, payload, label, prefix = "" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="max-w-[290px] rounded-lg border border-[#D9E0DC] bg-white p-3 text-xs text-[#18201C] shadow-2xl">
      <p className="mb-2 font-semibold">{prefix}{label}</p>
      <div className="space-y-1.5">
        {payload.filter((item) => item.value !== undefined).map((item) => (
          <div key={`${item.dataKey}-${item.name}`} className="flex justify-between gap-6">
            <span className="text-[#66716B]">{item.name}</span>
            <strong>{valueLabel(item.value, String(item.dataKey))}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function DispatchTooltip({ active, payload, label, mode }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const key = mode === "robust" ? "robust" : "deterministic";
  const charge = row[`${key}ChargeKw`];
  const discharge = row[`${key}DischargeKw`];
  const reason = discharge > 1
    ? "為降低尖峰購電與超約風險而放電"
    : charge > 1
      ? "吸收 PV 或離峰電力，保留後續調度空間"
      : "維持 SOC 備援，當下不進行無效循環";
  return (
    <div className="max-w-[310px] rounded-lg border border-[#D9E0DC] bg-white p-4 text-xs text-[#18201C] shadow-2xl">
      <p className="font-semibold">{label} · {touName(row.tou)}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-1.5">
        <dt className="text-[#66716B]">負載</dt><dd className="text-right font-semibold">{num(row.loadKw, 1)} kW</dd>
        <dt className="text-[#66716B]">PV</dt><dd className="text-right font-semibold">{num(row.pvKw, 1)} kW</dd>
        <dt className="text-[#66716B]">購電</dt><dd className="text-right font-semibold">{num(row[`${key}GridKw`], 1)} kW</dd>
        <dt className="text-[#66716B]">充電 / 放電</dt><dd className="text-right font-semibold">{num(charge, 1)} / {num(discharge, 1)} kW</dd>
        <dt className="text-[#66716B]">SOC</dt><dd className="text-right font-semibold">{num(row[`${key}Soc`], 1)}%</dd>
      </dl>
      <p className="mt-3 border-t border-border pt-3 leading-5 text-[#2D7D46]">{reason}</p>
    </div>
  );
}

function touName(value) {
  return ({ peak: "尖峰", semi: "半尖峰", sat_semi: "週六半尖峰", off: "離峰" })[value] || value;
}

function StoryHeader({ index, kicker, title, copy }) {
  return (
    <div className="mb-8 grid gap-4 lg:grid-cols-[90px_minmax(0,1fr)]">
      <div className="text-sm font-semibold text-[#2D7D46]">0{index} / 06</div>
      <div>
        <p className="mb-2 text-xs font-semibold uppercase text-[#66716B]">{kicker}</p>
        <h2 className="text-2xl font-bold leading-tight sm:text-3xl">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-[#66716B]">{copy}</p>
      </div>
    </div>
  );
}

function ProposalMetric({ label, value, note, tone = "light" }) {
  const dark = tone === "dark";
  return (
    <div className={`rounded-lg border p-5 ${dark ? "border-white/15 bg-white/5 text-white" : "border-border bg-white text-[#18201C]"}`}>
      <p className={`text-xs ${dark ? "text-white/60" : "text-[#66716B]"}`}>{label}</p>
      <p className="mt-3 text-2xl font-bold tabular sm:text-3xl">{value}</p>
      <p className={`mt-2 text-xs leading-5 ${dark ? "text-white/55" : "text-[#7B8781]"}`}>{note}</p>
    </div>
  );
}

function ChartPanel({ title, copy, children, dark = false }) {
  return (
    <div className={`min-w-0 overflow-visible rounded-lg border ${dark ? "border-white/15 bg-white/[.03]" : "border-border bg-white"}`}>
      <div className={`border-b p-5 ${dark ? "border-white/10" : "border-border"}`}><h3 className="font-semibold">{title}</h3>{copy && <p className={`mt-1 text-sm ${dark ? "text-white/55" : "text-[#66716B]"}`}>{copy}</p>}</div>
      <div className="overflow-visible p-4 sm:p-5">{children}</div>
    </div>
  );
}

export default function Proposal() {
  const executive = data.executiveSummary;
  const [technical, setTechnical] = useState(false);
  const [month, setMonth] = useState(7);
  const [day, setDay] = useState(15);
  const [dispatchMode, setDispatchMode] = useState("robust");
  const frontier = data.robustnessFrontier.filter((row) => row.status === "solved");
  const defaultP = Math.max(0, frontier.findIndex((row) => row.selected));
  const [pIndex, setPIndex] = useState(defaultP);
  const [capex, setCapex] = useState(6000000);
  const pPoint = frontier[pIndex] || frontier[0];
  const days = data.dailyDispatch[String(month)] || [];
  const selectedDay = days.find((item) => item.day === day) || days[0];
  const rows = selectedDay?.rows || [];
  const key = dispatchMode === "robust" ? "robust" : "deterministic";
  const payback = executive.robustSavings > 0 ? capex / executive.robustSavings : null;
  const firstDay = data.dailyDispatch["7"]?.[1] || data.dailyDispatch["7"]?.[0];
  const heroRows = firstDay?.rows || [];

  const riskRows = useMemo(
    () => data.strategyComparison.filter((row) => ["deterministic", "robust"].includes(row.key)),
    [],
  );

  const changeMonth = (value) => {
    const next = Number(value);
    setMonth(next);
    setDay(data.dailyDispatch[String(next)]?.[0]?.day || 1);
  };

  return (
    <main className="proposal-shell min-h-screen">
      <nav className="proposal-nav sticky top-0 z-40 border-b border-[#D9E0DC] bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <a href="#top" className="text-sm font-bold">P-Robust EMS</a>
          <div className="hidden items-center gap-5 text-xs text-[#66716B] lg:flex">
            <a href="#comparison" className="hover:text-[#18201C]">策略比較</a><a href="#robust" className="hover:text-[#18201C]">穩健價值</a><a href="#dispatch" className="hover:text-[#18201C]">日內決策</a><a href="#preference" className="hover:text-[#18201C]">風險偏好</a><a href="#evidence" className="hover:text-[#18201C]">技術證據</a>
          </div>
          <div className="flex rounded-lg border border-border bg-[#F4F7F5] p-1">
            {[{ value: false, label: "Executive" }, { value: true, label: "Technical" }].map((item) => (
              <button key={item.label} type="button" onClick={() => setTechnical(item.value)} className={`min-h-9 rounded-md px-3 text-xs font-medium ${technical === item.value ? "bg-[#18201C] text-white" : "text-[#66716B]"}`}>{item.label}</button>
            ))}
          </div>
        </div>
      </nav>

      <section id="top" className="proposal-hero proposal-section overflow-hidden">
        <div className="mx-auto max-w-[1320px] px-4 py-12 sm:px-6 sm:py-16 lg:py-20">
          <div className="grid gap-10 lg:grid-cols-[1.02fr_.98fr] lg:items-center">
            <div>
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/15 px-3 py-1.5 text-xs text-white/70"><ShieldCheck className="h-4 w-4 text-[#A7D8B5]" />全年 P-Robust 規劃模擬</div>
              <h1 className="max-w-3xl text-4xl font-bold leading-[1.12] sm:text-5xl lg:text-6xl">數據分析應用於工廠用電與太陽能發電排程最佳化</h1>
              <p className="mt-6 max-w-2xl text-base leading-8 text-white/65">在同一組負載、太陽能、契約容量與電價假設下，量化「完全買電」到「穩健調度」的年度成本與不利情境風險。</p>
              <div className="mt-8 grid gap-3 sm:grid-cols-3">
                <ProposalMetric tone="dark" label="完全買電" value={money(executive.allGridAnnualCost)} note="年度成本基準" />
                <ProposalMetric tone="dark" label="P-Robust" value={money(executive.robustAnnualCost)} note={`p = ${num(executive.selectedP * 100)}%`} />
                <ProposalMetric tone="dark" label="年度節省" value={money(executive.robustSavings)} note={`${num(executive.robustSavingsRate, 1)}% 改善`} />
              </div>
            </div>
            <div className="proposal-chart h-[430px] min-w-0 border-l border-white/10 pl-0 lg:pl-6">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <ComposedChart data={heroRows} margin={{ top: 24, right: 10, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,.1)" strokeDasharray="3 3" />
                  <XAxis dataKey="time" interval={15} tick={{ fill: "rgba(255,255,255,.55)", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,.2)" }} />
                  <YAxis tick={{ fill: "rgba(255,255,255,.55)", fontSize: 11 }} axisLine={false} />
                  <Tooltip content={<FloatingTooltip prefix="24 小時 · " />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                  <Legend wrapperStyle={{ color: "white", fontSize: 12 }} />
                  <Area type="monotone" dataKey="loadKw" name="工廠負載" fill="rgba(255,255,255,.06)" stroke="white" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="pvKw" name="PV" stroke="#A7D8B5" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="robustGridKw" name="P-Robust 購電" stroke="#7DA4FF" strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="mt-10 flex items-center gap-2 text-xs text-white/50"><ChevronDown className="h-4 w-4" />往下查看節省來源與模型證據</div>
        </div>
      </section>

      <section id="comparison" className="proposal-section py-16 sm:py-20">
        <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
          <StoryHeader index="2" kicker="Strategy comparison" title="從完全買電，到可承受不確定性的穩健調度" copy="先以業主最熟悉的年度電費比較四個策略，再補上節省率、超約事件與尖峰需量，避免只用單一成本數字宣稱策略較好。" />
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_.75fr]">
            <ChartPanel title="四策略年度成本" copy="同一計費契約與同一組全年結算路徑。">
              <div className="h-[380px] min-w-0">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                  <BarChart data={data.strategyComparison} layout="vertical" margin={{ top: 8, right: 34, left: 16, bottom: 8 }}>
                    <CartesianGrid stroke={C.grid} strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tickFormatter={(v) => `${num(v / 10000)}萬`} />
                    <YAxis type="category" dataKey="label" width={112} tick={{ fontSize: 12 }} />
                    <Tooltip content={<FloatingTooltip prefix="年度 · " />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                    <Legend />
                    <Bar dataKey="annualCost" name="年度電費" radius={[0, 4, 4, 0]}>
                      {data.strategyComparison.map((row) => <Cell key={row.key} fill={row.key === "robust" ? C.green : row.key === "allGrid" ? C.red : C.gray} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ChartPanel>
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              <ProposalMetric label="相對完全買電節省" value={money(executive.robustSavings)} note={`${num(executive.robustSavingsRate, 1)}% 年度改善`} />
              <ProposalMetric label="P90 downside 改善" value={money(executive.downsideReduction)} note="P-Robust 相對確定性策略" />
              <ProposalMetric label="PV 利用率" value={`${num(executive.pvUtilization, 1)}%`} note="降低棄光並保留尖峰調度能力" />
            </div>
          </div>
        </div>
      </section>

      <section id="robust" className="proposal-section bg-white py-16 sm:py-20">
        <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
          <StoryHeader index="3" kicker="Robust value" title="穩健最佳化不是追求最便宜，而是控制不利情境" copy="確定性 MILP 對單一路徑最佳；P-Robust 則限制每個代表情境相對其事後最優解的遺憾，讓風險偏好可被量化。" />
          <div className="grid gap-5 lg:grid-cols-2">
            <ChartPanel title="一般與不利情境成本" copy="P50 是一般情境，P90 是較不利情境。">
              <div className="h-[340px] min-w-0">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                  <BarChart data={riskRows} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                    <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" /><YAxis tickFormatter={(v) => `${num(v / 10000)}萬`} width={58} />
                    <Tooltip content={<FloatingTooltip />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} /><Legend />
                    <Bar dataKey="p50Cost" name="一般情境 P50" fill={C.gray} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="p90Cost" name="不利情境 P90" fill={C.green} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ChartPanel>
            <div className="rounded-lg bg-[#18201C] p-6 text-white">
              <p className="text-xs font-semibold uppercase text-[#A7D8B5]">Trade-off</p>
              <h3 className="mt-3 text-2xl font-bold">用 {money(executive.robustPremium)} 的穩健成本，換取 downside 控制</h3>
              <div className="mt-7 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-white/15">
                <div className="bg-[#18201C] p-4"><p className="text-xs text-white/55">不利情境改善</p><p className="mt-2 text-xl font-semibold">{money(executive.downsideReduction)}</p></div>
                <div className="bg-[#18201C] p-4"><p className="text-xs text-white/55">情境內 Regret 上限</p><p className="mt-2 text-xl font-semibold">{num(executive.selectedP * 100)}%</p></div>
                <div className="bg-[#18201C] p-4"><p className="text-xs text-white/55">建置期包絡</p><p className="mt-2 text-xl font-semibold">{num(data.scenarioCoverage.net_load_pointwise_envelope_coverage * 100, 1)}%</p></div>
                <div className="bg-[#18201C] p-4"><p className="text-xs text-white/55">求解情境</p><p className="mt-2 text-xl font-semibold">{data.meta.optimizationScenarioCount} 組</p></div>
              </div>
              <p className="mt-6 text-sm leading-7 text-white/65">{executive.businessConclusion}</p>
            </div>
          </div>
        </div>
      </section>

      <section id="dispatch" className="proposal-section py-16 sm:py-20">
        <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
          <StoryHeader index="4" kicker="Decision trace" title="一天內，系統如何決定充電、放電與保留備援" copy="可切換每個月份的三個代表日，並在確定性與 P-Robust 排程之間比較。滑鼠停留會顯示完整能源狀態與決策原因。" />
          <ChartPanel title={`${month}月 ${selectedDay?.label || "代表日"} · ${dispatchMode === "robust" ? "P-Robust" : "確定性 MILP"}`} copy="背景資料為 15 分鐘解析度；紅色虛線為各時段契約容量。">
            <div className="mb-5 flex flex-wrap gap-2">
              <select className="h-11 rounded-lg border border-border bg-white px-3 text-sm" value={month} onChange={(event) => changeMonth(event.target.value)} aria-label="月份">{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}月</option>)}</select>
              <select className="h-11 rounded-lg border border-border bg-white px-3 text-sm" value={selectedDay?.day || day} onChange={(event) => setDay(Number(event.target.value))} aria-label="代表日">{days.map((item) => <option key={item.day} value={item.day}>{item.label}</option>)}</select>
              <div className="flex rounded-lg border border-border bg-white p-1">{[{ key: "deterministic", label: "確定性" }, { key: "robust", label: "P-Robust" }].map((item) => <button key={item.key} type="button" onClick={() => setDispatchMode(item.key)} className={`min-h-9 rounded-md px-3 text-sm ${dispatchMode === item.key ? "bg-[#18201C] text-white" : "text-[#66716B]"}`}>{item.label}</button>)}</div>
            </div>
            <div className="h-[460px] min-w-0">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <ComposedChart data={rows} margin={{ top: 12, right: 24, left: 8, bottom: 10 }}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                  <XAxis dataKey="time" interval={11} /><YAxis yAxisId="power" unit=" kW" width={65} /><YAxis yAxisId="soc" orientation="right" domain={[0, 100]} unit="%" width={48} />
                  <Tooltip content={<DispatchTooltip mode={dispatchMode} />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} /><Legend />
                  <Bar yAxisId="power" dataKey={`${key}ChargeKw`} name="充電" fill="#7DA4FF" opacity={0.55} />
                  <Bar yAxisId="power" dataKey={`${key}DischargeKw`} name="放電" fill={C.orange} opacity={0.7} />
                  <Line yAxisId="power" type="monotone" dataKey="loadKw" name="負載" stroke={C.graphite} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line yAxisId="power" type="monotone" dataKey="pvKw" name="PV" stroke={C.green} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line yAxisId="power" type="monotone" dataKey={`${key}GridKw`} name="購電" stroke={C.purple} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line yAxisId="power" type="stepAfter" dataKey="contractKw" name="契約容量" stroke={C.red} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                  <Line yAxisId="soc" type="monotone" dataKey={`${key}Soc`} name="SOC" stroke={C.blue} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </ChartPanel>
        </div>
      </section>

      <section id="preference" className="proposal-section bg-white py-16 sm:py-20">
        <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
          <StoryHeader index="5" kicker="Risk preference" title="讓決策者選擇可接受的風險，不在前端捏造求解結果" copy="p 滑桿只跳到已完成的求解點。ROI 則使用透明公式：建置成本除以 P-Robust 相對完全買電的年度節省。" />
          <div className="grid gap-5 lg:grid-cols-[.78fr_1.22fr]">
            <div className="rounded-lg border border-border bg-[#F8FAF9] p-5">
              <div className="flex items-center justify-between"><span className="text-sm font-semibold">容許遺憾 p</span><strong className="text-[#2D7D46]">{num((pPoint?.p || 0) * 100)}%</strong></div>
              <input className="mt-6 w-full accent-[#2D7D46]" type="range" min="0" max={Math.max(0, frontier.length - 1)} step="1" value={pIndex} onInput={(event) => setPIndex(Number(event.currentTarget.value))} onChange={(event) => setPIndex(Number(event.currentTarget.value))} aria-label="P-Robust solved point" />
              <div className="mt-2 flex justify-between text-[10px] text-[#66716B]">{frontier.map((row) => <span key={row.p}>{num(row.p * 100)}%</span>)}</div>
              <div className="mt-6 grid grid-cols-2 gap-3"><ProposalMetric label="期望成本" value={money(pPoint?.expectedCost)} note="代表日" /><ProposalMetric label="最差成本" value={money(pPoint?.worstCost)} note="代表日" /><ProposalMetric label="超約事件" value={`${num(pPoint?.overContractEvents, 1)} 次`} note="機率加權" /><ProposalMetric label="情境內 Regret 覆蓋" value={`${num(pPoint?.regretCoverage, 1)}%`} note="已求解情境" /></div>
              <div className="mt-6 border-t border-border pt-5"><label className="text-sm font-semibold" htmlFor="capex">電池系統建置成本</label><input id="capex" className="mt-2 h-11 w-full rounded-lg border border-border bg-white px-3" type="number" min="0" step="100000" value={capex} onChange={(event) => setCapex(Math.max(0, Number(event.target.value)))} /><p className="mt-3 text-sm">預估回收期：<strong className="text-[#2D7D46]">{payback ? `${num(payback, 1)} 年` : "目前節省不足"}</strong></p></div>
            </div>
            <ChartPanel title="已求解穩健前緣" copy="橫軸期望成本、縱軸最差情境成本；紅點為目前選擇。">
              <div className="h-[480px] min-w-0">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                  <ScatterChart margin={{ top: 20, right: 25, left: 10, bottom: 15 }}>
                    <CartesianGrid stroke={C.grid} strokeDasharray="3 3" /><XAxis type="number" dataKey="expectedCost" name="期望成本" domain={["dataMin - 100", "dataMax + 100"]} /><YAxis type="number" dataKey="worstCost" name="最差成本" width={72} domain={["dataMin - 100", "dataMax + 100"]} /><ZAxis range={[100, 100]} />
                    <Tooltip content={<FloatingTooltip prefix="前緣 · " />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} /><Legend />
                    <Scatter data={frontier} name="已求解 p 值" fill={C.green} line={{ stroke: C.green, strokeWidth: 2 }}>{frontier.map((row, index) => <Cell key={row.p} fill={index === pIndex ? C.red : C.green} />)}</Scatter>
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </ChartPanel>
          </div>
        </div>
      </section>

      <section id="evidence" className="proposal-section bg-[#18201C] py-16 text-white sm:py-20">
        <div className="mx-auto max-w-[1320px] px-4 sm:px-6">
          <div className="mb-8 grid gap-4 lg:grid-cols-[90px_minmax(0,1fr)]"><div className="text-sm font-semibold text-[#A7D8B5]">06 / 06</div><div><p className="mb-2 text-xs font-semibold uppercase text-white/45">Technical evidence</p><h2 className="text-2xl font-bold sm:text-3xl">成果能展示，也能被工程端追溯</h2><p className="mt-3 max-w-3xl text-sm leading-7 text-white/60">正式資料缺漏或狀態 invalid 時，這份提案版會停止建置，不會改用 mock data。</p></div></div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <ProposalMetric tone="dark" label="情境路徑" value={`${data.meta.optimizationScenarioCount} + ${data.meta.stressScenarioCount}`} note={`${num(data.meta.drawCount)} 條 bootstrap 路徑縮減`} />
            <ProposalMetric tone="dark" label="建置期包絡" value={`${num(data.scenarioCoverage.net_load_pointwise_envelope_coverage * 100, 1)}%`} note={`門檻 ${num(data.scenarioCoverage.coverage_target * 100)}%`} />
            <ProposalMetric tone="dark" label="樣本外 regret 覆蓋" value={`${num(data.scenarioCoverage.exPostRegretCoverage, 1)}%`} note={`${data.scenarioCoverage.exPostRegretPassed ? "通過" : "未通過"} ${num(data.scenarioCoverage.exPostRegretTarget)}% 門檻`} />
            <ProposalMetric tone="dark" label="每日求解中位數" value={`${num(data.scenarioCoverage.dailyMedianSolveSeconds, 3)} 秒`} note={`P95 ${num(data.scenarioCoverage.dailyP95SolveSeconds, 3)} 秒`} />
            <ProposalMetric tone="dark" label="Solver 狀態" value={data.meta.status.toUpperCase()} note={`${data.meta.solver} · seed ${data.meta.seed}`} />
          </div>
          {technical ? (
            <div className="mt-6 grid gap-5 lg:grid-cols-2">
              <ChartPanel dark title="模型與計費設定"><dl className="space-y-3 text-sm"><Evidence label="Tariff" value={data.meta.tariffVersion} /><Evidence label="Scenario" value={scenarioMethodLabel} /><Evidence label="Decision" value={decisionStructureLabel} /><Evidence label="SOC" value={`${num(data.modelAssumptions.battery.soc_min * 100)}% - ${num(data.modelAssumptions.battery.soc_max * 100)}%`} /></dl></ChartPanel>
              <ChartPanel dark title="資料限制"><p className="text-sm leading-7 text-white/65">{dataLimitationLabel}</p><p className="mt-4 text-sm leading-7 text-white/65">建置期淨負載包絡是規劃路徑內檢查，獨立的日別 ex-post regret 另行呈現。</p><p className="mt-5 border-t border-white/10 pt-5 text-sm font-semibold text-[#A7D8B5]">{data.meta.simulationLabel}</p></ChartPanel>
            </div>
          ) : (
            <div className="mt-6 flex flex-col justify-between gap-4 rounded-lg border border-white/15 bg-white/[.03] p-6 sm:flex-row sm:items-center"><div><div className="flex items-center gap-2 font-semibold"><CheckCircle2 className="h-5 w-5 text-[#A7D8B5]" />正式結果已通過建置檢查</div><p className="mt-2 text-sm text-white/55">切換右上角 Technical 可查看 tariff、情境方法、SOC 邊界與資料限制。</p></div><a href="#top" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#2D7D46] px-4 text-sm font-semibold">回到成果總覽 <ArrowRight className="h-4 w-4" /></a></div>
          )}
          <p className="mt-8 text-xs text-white/40">{data.meta.simulationLabel} · Run ID: {data.meta.runId}</p>
        </div>
      </section>
    </main>
  );
}

function Evidence({ label, value }) {
  return <div className="grid grid-cols-[90px_1fr] gap-3 border-b border-white/10 pb-3 last:border-0"><dt className="text-white/45">{label}</dt><dd className="break-words leading-6 text-white/80">{value}</dd></div>;
}
