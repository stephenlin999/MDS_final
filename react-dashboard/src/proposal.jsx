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
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";

import data from "@/data/ems-dashboard-data.json";

const C = {
  green: "#2D7D46",
  greenLight: "#83C395",
  red: "#D36A5D",
  gray: "#89958E",
  text: "#F2F6F3",
  muted: "#9EAAA3",
  blue: "#6E9FBD",
  orange: "#D59B4B",
  grid: "rgba(232, 240, 235, 0.1)",
};

const chartTick = { fill: C.muted, fontSize: 11 };
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
    <div className="proposal-tooltip">
      <p className="proposal-tooltip-title">{prefix}{label}</p>
      <div className="proposal-tooltip-list">
        {payload.filter((item) => item.value !== undefined).map((item) => (
          <div key={`${item.dataKey}-${item.name}`} className="proposal-tooltip-row">
            <span>{item.name}</span>
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
    <div className="proposal-tooltip proposal-tooltip-wide">
      <p className="proposal-tooltip-title">{label}，{touName(row.tou)}</p>
      <dl className="proposal-tooltip-grid">
        <dt>負載</dt><dd>{num(row.loadKw, 1)} kW</dd>
        <dt>PV</dt><dd>{num(row.pvKw, 1)} kW</dd>
        <dt>購電</dt><dd>{num(row[`${key}GridKw`], 1)} kW</dd>
        <dt>充電 / 放電</dt><dd>{num(charge, 1)} / {num(discharge, 1)} kW</dd>
        <dt>SOC</dt><dd>{num(row[`${key}Soc`], 1)}%</dd>
      </dl>
      <p className="proposal-tooltip-reason">{reason}</p>
    </div>
  );
}

function touName(value) {
  return ({ peak: "尖峰", semi: "半尖峰", sat_semi: "週六半尖峰", off: "離峰" })[value] || value;
}

function SectionIntro({ title, copy }) {
  return (
    <header className="proposal-section-intro">
      <h2>{title}</h2>
      <p>{copy}</p>
    </header>
  );
}

function ProposalMetric({ label, value, note, emphasis = false, alert = false }) {
  return (
    <div className={`proposal-metric${emphasis ? " is-emphasis" : ""}${alert ? " is-alert" : ""}`}>
      <p className="proposal-metric-label">{label}</p>
      <p className="proposal-metric-value">{value}</p>
      <p className="proposal-metric-note">{note}</p>
    </div>
  );
}

function ChartPanel({ title, copy, children, className = "" }) {
  return (
    <div className={`proposal-panel ${className}`}>
      <div className="proposal-panel-heading">
        <h3>{title}</h3>
        {copy && <p>{copy}</p>}
      </div>
      <div className="proposal-panel-body">{children}</div>
    </div>
  );
}

function Evidence({ label, value }) {
  return (
    <div className="proposal-evidence-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
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
  const deterministic = data.strategyComparison.find((row) => row.key === "deterministic");
  const robust = data.strategyComparison.find((row) => row.key === "robust");

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
    <main className="proposal-shell">
      <nav className="proposal-nav">
        <div className="proposal-nav-inner">
          <a href="#top" className="proposal-brand">工廠能源決策系統</a>
          <div className="proposal-nav-links" aria-label="提案內容">
            <a href="#comparison">年度比較</a>
            <a href="#robust">穩健價值</a>
            <a href="#dispatch">日內決策</a>
            <a href="#preference">風險偏好</a>
            <a href="#evidence">模型證據</a>
          </div>
          <div className="proposal-mode-switch" aria-label="顯示模式">
            {[{ value: false, label: "業主" }, { value: true, label: "技術" }].map((item) => (
              <button
                key={item.label}
                type="button"
                aria-pressed={technical === item.value}
                onClick={() => setTechnical(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      <section id="top" className="proposal-hero proposal-section">
        <div className="proposal-container proposal-hero-inner">
          <div className="proposal-hero-copy proposal-enter">
            <p className="proposal-kicker">P-Robust 工廠能源決策</p>
            <h1>數據分析應用於工廠用電與太陽能發電排程最佳化</h1>
            <p className="proposal-hero-summary">比較完全買電、確定性 MILP 與 P-Robust，量化年度節費與不利情境風險。</p>
            <a href="#comparison" className="proposal-primary-action">
              查看年度比較 <ArrowRight aria-hidden="true" />
            </a>

            <div className="proposal-hero-outcome" aria-label="年度核心成果">
              <div className="proposal-hero-saving">
                <span>相對完全買電，年度節省</span>
                <strong>{money(executive.robustSavings)}</strong>
                <small>{num(executive.robustSavingsRate, 1)}% 年度成本改善</small>
              </div>
              <dl className="proposal-hero-costs">
                <div><dt>完全買電</dt><dd>{money(executive.allGridAnnualCost)}</dd></div>
                <div><dt>P-Robust</dt><dd>{money(executive.robustAnnualCost)}</dd></div>
                <div><dt>穩健參數</dt><dd>p = {num(executive.selectedP * 100)}%</dd></div>
              </dl>
            </div>
          </div>

          <div className="proposal-hero-visual proposal-enter-delayed">
            <div className="proposal-visual-heading">
              <div>
                <span>代表日能源流</span>
                <strong>調度結果直接來自年度模擬</strong>
              </div>
              <ShieldCheck aria-hidden="true" />
            </div>
            <div className="proposal-hero-chart">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 320 }}>
                <ComposedChart data={heroRows} margin={{ top: 16, right: 10, left: -14, bottom: 8 }}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                  <XAxis dataKey="time" interval={15} tick={chartTick} axisLine={{ stroke: C.grid }} tickLine={false} />
                  <YAxis tick={chartTick} axisLine={false} tickLine={false} />
                  <Tooltip content={<FloatingTooltip prefix="24 小時，" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                  <Legend wrapperStyle={{ color: C.muted, fontSize: 12 }} />
                  <Area type="monotone" dataKey="loadKw" name="工廠負載" fill="rgba(242,246,243,.06)" stroke={C.text} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="pvKw" name="PV" stroke={C.greenLight} strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="robustGridKw" name="P-Robust 購電" stroke={C.blue} strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </section>

      <section id="comparison" className="proposal-section proposal-container">
        <SectionIntro
          title="先比較一年要付多少電費"
          copy="四種策略使用同一計費契約與全年結算路徑。節費、超約事件和尖峰需量放在同一個決策畫面。"
        />
        <div className="proposal-comparison-layout">
          <ChartPanel title="四策略年度成本" copy="長條越短，年度總電費越低。P-Robust 同時考慮不利情境。">
            <div className="proposal-chart proposal-chart-tall">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 700, height: 380 }}>
                <BarChart data={data.strategyComparison} layout="vertical" margin={{ top: 8, right: 44, left: 24, bottom: 8 }}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => `${num(v / 10000)}萬`} tick={chartTick} axisLine={{ stroke: C.grid }} tickLine={false} />
                  <YAxis type="category" dataKey="label" width={118} tick={chartTick} axisLine={false} tickLine={false} />
                  <Tooltip content={<FloatingTooltip prefix="年度，" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                  <Legend wrapperStyle={{ color: C.muted, fontSize: 12 }} />
                  <Bar dataKey="annualCost" name="年度電費" radius={[0, 4, 4, 0]}>
                    {data.strategyComparison.map((row) => (
                      <Cell key={row.key} fill={row.key === "robust" ? C.green : row.key === "allGrid" ? C.red : C.gray} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartPanel>

          <aside className="proposal-outcome-ledger" aria-label="P-Robust 成果摘要">
            <ProposalMetric emphasis label="年度節省" value={money(executive.robustSavings)} note={`相對完全買電，改善 ${num(executive.robustSavingsRate, 1)}%`} />
            <ProposalMetric label="P90 downside 改善" value={money(executive.downsideReduction)} note="P-Robust 相對確定性策略" />
            <ProposalMetric label="超約事件" value={`${num(deterministic?.overContractEvents)} → ${num(robust?.overContractEvents)}`} note="確定性 MILP 與 P-Robust 比較" />
            <ProposalMetric label="PV 利用率" value={`${num(executive.pvUtilization, 1)}%`} note="降低棄光並保留尖峰調度能力" />
          </aside>
        </div>
      </section>

      <section id="robust" className="proposal-section proposal-container">
        <SectionIntro
          title="穩健成本換來什麼"
          copy="確定性 MILP 對單一路徑最佳。P-Robust 用可量化的穩健成本，降低不利天氣下的成本與超約暴露。"
        />
        <div className="proposal-robust-layout">
          <div className="proposal-robust-statement">
            <span>年度穩健成本</span>
            <strong>{money(executive.robustPremium)}</strong>
            <p>換取 {money(executive.downsideReduction)} 的 P90 downside 改善，超約事件減少 {num((deterministic?.overContractEvents || 0) - (robust?.overContractEvents || 0))} 次。</p>
            <div className="proposal-proof-strip">
              <div><span>情境內 Regret 上限</span><strong>{num(executive.selectedP * 100)}%</strong></div>
              <div><span>建置期包絡</span><strong>{num(data.scenarioCoverage.net_load_pointwise_envelope_coverage * 100, 1)}%</strong></div>
              <div><span>求解情境</span><strong>{data.meta.optimizationScenarioCount} 組</strong></div>
            </div>
          </div>

          <ChartPanel title="一般與不利情境成本" copy="P50 代表一般情境，P90 代表較不利情境。">
            <div className="proposal-chart proposal-chart-medium">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 340 }}>
                <BarChart data={riskRows} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={chartTick} axisLine={{ stroke: C.grid }} tickLine={false} />
                  <YAxis tickFormatter={(v) => `${num(v / 10000)}萬`} width={58} tick={chartTick} axisLine={false} tickLine={false} />
                  <Tooltip content={<FloatingTooltip />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                  <Legend wrapperStyle={{ color: C.muted, fontSize: 12 }} />
                  <Bar dataKey="p50Cost" name="一般情境 P50" fill={C.gray} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="p90Cost" name="不利情境 P90" fill={C.red} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartPanel>
        </div>
        <div className="proposal-method-warning" role="note">
          <AlertTriangle aria-hidden="true" />
          <p>樣本外 regret coverage 目前為 {num(data.scenarioCoverage.exPostRegretCoverage, 1)}%，未達 {num(data.scenarioCoverage.exPostRegretTarget)}% 研究門檻。提案不得宣稱已具有事後遺憾保證。</p>
        </div>
      </section>

      <section id="dispatch" className="proposal-section proposal-container">
        <SectionIntro
          title="看懂一天內的調度決策"
          copy="選擇月份與代表日，比較確定性和 P-Robust 排程。滑鼠停留可查看能源狀態、電價時段與決策原因。"
        />
        <ChartPanel title={`${month}月 ${selectedDay?.label || "代表日"}，${dispatchMode === "robust" ? "P-Robust" : "確定性 MILP"}`} copy="預設只顯示負載、PV、購電與 SOC。契約容量以紅色虛線標示。">
          <div className="proposal-controls">
            <label>
              <span>月份</span>
              <select value={month} onChange={(event) => changeMonth(event.target.value)}>
                {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}月</option>)}
              </select>
            </label>
            <label>
              <span>代表日</span>
              <select value={selectedDay?.day || day} onChange={(event) => setDay(Number(event.target.value))}>
                {days.map((item) => <option key={item.day} value={item.day}>{item.label}</option>)}
              </select>
            </label>
            <div className="proposal-segmented" aria-label="策略">
              {[{ key: "deterministic", label: "確定性" }, { key: "robust", label: "P-Robust" }].map((item) => (
                <button key={item.key} type="button" aria-pressed={dispatchMode === item.key} onClick={() => setDispatchMode(item.key)}>{item.label}</button>
              ))}
            </div>
          </div>
          <div className="proposal-chart proposal-chart-dispatch">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 900, height: 460 }}>
              <ComposedChart data={rows} margin={{ top: 12, right: 24, left: 8, bottom: 10 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                <XAxis dataKey="time" interval={11} tick={chartTick} axisLine={{ stroke: C.grid }} tickLine={false} />
                <YAxis yAxisId="power" unit=" kW" width={65} tick={chartTick} axisLine={false} tickLine={false} />
                <YAxis yAxisId="soc" orientation="right" domain={[0, 100]} unit="%" width={48} tick={chartTick} axisLine={false} tickLine={false} />
                <Tooltip content={<DispatchTooltip mode={dispatchMode} />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                <Legend wrapperStyle={{ color: C.muted, fontSize: 12 }} />
                <Line yAxisId="power" type="monotone" dataKey="loadKw" name="負載" stroke={C.text} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="power" type="monotone" dataKey="pvKw" name="PV" stroke={C.greenLight} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="power" type="monotone" dataKey={`${key}GridKw`} name="購電" stroke={C.orange} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="power" type="stepAfter" dataKey="contractKw" name="契約容量" stroke={C.red} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                <Line yAxisId="soc" type="monotone" dataKey={`${key}Soc`} name="SOC" stroke={C.blue} strokeWidth={2.5} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </ChartPanel>
      </section>

      <section id="preference" className="proposal-section proposal-container">
        <SectionIntro
          title="讓業主選擇可接受的風險"
          copy="p 滑桿只切換已完成求解的結果。ROI 使用建置成本除以年度節省，不在前端假裝重新求解 MILP。"
        />
        <div className="proposal-preference-layout">
          <div className="proposal-preference-control">
            <div className="proposal-slider-heading"><span>容許遺憾 p</span><strong>{num((pPoint?.p || 0) * 100)}%</strong></div>
            <input
              type="range"
              min="0"
              max={Math.max(0, frontier.length - 1)}
              step="1"
              value={pIndex}
              onInput={(event) => setPIndex(Number(event.currentTarget.value))}
              onChange={(event) => setPIndex(Number(event.currentTarget.value))}
              aria-label="P-Robust solved point"
            />
            <div className="proposal-slider-labels">{frontier.map((row) => <span key={row.p}>{num(row.p * 100)}%</span>)}</div>

            <div className="proposal-solved-values">
              <ProposalMetric label="期望成本" value={money(pPoint?.expectedCost)} note="代表日" />
              <ProposalMetric label="最差成本" value={money(pPoint?.worstCost)} note="代表日" />
              <ProposalMetric label="超約事件" value={`${num(pPoint?.overContractEvents, 1)} 次`} note="機率加權" />
              <ProposalMetric label="情境內 Regret 覆蓋" value={`${num(pPoint?.regretCoverage, 1)}%`} note="已求解情境" />
            </div>

            <div className="proposal-roi">
              <label htmlFor="capex">電池系統建置成本</label>
              <input id="capex" type="number" min="0" step="100000" value={capex} onChange={(event) => setCapex(Math.max(0, Number(event.target.value)))} />
              <p>預估回收期 <strong>{payback ? `${num(payback, 1)} 年` : "目前節省不足"}</strong></p>
            </div>
          </div>

          <ChartPanel title="已求解穩健前緣" copy="橫軸為期望成本，縱軸為最差情境成本。紅點是目前選擇。">
            <div className="proposal-chart proposal-chart-frontier">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 700, height: 460 }}>
                <ScatterChart margin={{ top: 20, right: 25, left: 10, bottom: 15 }}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="expectedCost" name="期望成本" domain={["dataMin - 100", "dataMax + 100"]} tick={chartTick} axisLine={{ stroke: C.grid }} tickLine={false} />
                  <YAxis type="number" dataKey="worstCost" name="最差成本" width={72} domain={["dataMin - 100", "dataMax + 100"]} tick={chartTick} axisLine={false} tickLine={false} />
                  <ZAxis range={[100, 100]} />
                  <Tooltip content={<FloatingTooltip prefix="前緣，" />} allowEscapeViewBox={{ x: true, y: true }} wrapperStyle={{ zIndex: 60 }} />
                  <Legend wrapperStyle={{ color: C.muted, fontSize: 12 }} />
                  <Scatter data={frontier} name="已求解 p 值" fill={C.green} line={{ stroke: C.green, strokeWidth: 2 }}>
                    {frontier.map((row, index) => <Cell key={row.p} fill={index === pIndex ? C.red : C.green} />)}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </ChartPanel>
        </div>
      </section>

      <section id="evidence" className="proposal-section proposal-container proposal-evidence">
        <SectionIntro
          title="模型結果可以被追溯"
          copy="正式資料缺漏或狀態 invalid 時，提案版會停止建置，不會以 mock data 取代。"
        />

        <div className="proposal-evidence-grid">
          <ProposalMetric label="情境路徑" value={`${data.meta.optimizationScenarioCount} + ${data.meta.stressScenarioCount}`} note={`${num(data.meta.drawCount)} 條 bootstrap 路徑縮減`} />
          <ProposalMetric label="建置期包絡" value={`${num(data.scenarioCoverage.net_load_pointwise_envelope_coverage * 100, 1)}%`} note={`門檻 ${num(data.scenarioCoverage.coverage_target * 100)}%`} />
          <ProposalMetric alert label="樣本外 Regret 覆蓋" value={`${num(data.scenarioCoverage.exPostRegretCoverage, 1)}%`} note={`未通過 ${num(data.scenarioCoverage.exPostRegretTarget)}% 門檻`} />
          <ProposalMetric label="每日求解中位數" value={`${num(data.scenarioCoverage.dailyMedianSolveSeconds, 3)} 秒`} note={`P95 ${num(data.scenarioCoverage.dailyP95SolveSeconds, 3)} 秒`} />
          <ProposalMetric label="Solver 狀態" value={data.meta.status.toUpperCase()} note={`${data.meta.solver}，seed ${data.meta.seed}`} />
        </div>

        {technical ? (
          <div className="proposal-technical-grid">
            <ChartPanel title="模型與計費設定">
              <dl className="proposal-evidence-list">
                <Evidence label="Tariff" value={data.meta.tariffVersion} />
                <Evidence label="Scenario" value={scenarioMethodLabel} />
                <Evidence label="Decision" value={decisionStructureLabel} />
                <Evidence label="SOC" value={`${num(data.modelAssumptions.battery.soc_min * 100)}% - ${num(data.modelAssumptions.battery.soc_max * 100)}%`} />
                <Evidence label="Run ID" value={data.meta.runId} />
              </dl>
            </ChartPanel>
            <ChartPanel title="資料限制">
              <div className="proposal-technical-copy">
                <p>{dataLimitationLabel}</p>
                <p>建置期淨負載包絡是規劃路徑內檢查，獨立的日別 ex-post regret 另行呈現。</p>
                <strong>{data.meta.simulationLabel}</strong>
              </div>
            </ChartPanel>
          </div>
        ) : (
          <div className="proposal-status-note">
            <CheckCircle2 aria-hidden="true" />
            <div><strong>正式結果已通過建置檢查</strong><p>切換右上角「技術」可查看 tariff、情境方法、SOC 邊界、Run ID 與資料限制。</p></div>
          </div>
        )}
      </section>

      <footer className="proposal-footer">
        <div className="proposal-container"><span>{data.meta.simulationLabel}</span><span>P-Robust EMS</span></div>
      </footer>
    </main>
  );
}
