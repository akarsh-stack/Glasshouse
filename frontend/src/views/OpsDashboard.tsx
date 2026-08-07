import { motion } from "framer-motion";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button, Segmented, Skeleton } from "../components/ui";
import { useLoadTest } from "../hooks/useLoadTest";
import type { MetricsWindow } from "../hooks/useMetrics";
import { useMetrics } from "../hooks/useMetrics";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { fmtCost, fmtMs, fmtNum, fmtPct } from "../lib/format";
import { INK, STAGE_COLOR } from "../lib/stages";
import { getTraces, subscribeTraces } from "../lib/traceStore";

/* ------------------------------------------------------- animated number */

function AnimatedNumber({
  value,
  format,
}: {
  value: number;
  format: (n: number) => string;
}) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);

  useEffect(() => {
    const from = prevRef.current;
    prevRef.current = value;
    if (reduced || from === value) {
      setDisplay(value);
      return;
    }
    const t0 = performance.now();
    const dur = 450;
    let raf = 0;
    const tick = () => {
      const p = Math.min(1, (performance.now() - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(from + (value - from) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, reduced]);

  return <>{format(display)}</>;
}

/* -------------------------------------------------------------- readouts */

interface ReadoutDef {
  label: string;
  value: number | null;
  format: (n: number) => string;
}

function ReadoutRow({ readouts, loading }: { readouts: ReadoutDef[]; loading: boolean }) {
  const reduced = useReducedMotion();
  return (
    <div className="tilt-scene grid grid-cols-3 overflow-hidden rounded-md border border-ink-700 bg-ink-900 shadow-raised surface-edge md:grid-cols-6">
      {readouts.map((r, i) => (
        <motion.div
          key={r.label}
          // Cells resolve left to right like an instrument powering on. The
          // stagger is short (40ms) — this is six numbers on one row, not a
          // list, so it should read as a single sweep rather than six events.
          initial={reduced ? false : { opacity: 0, y: 8, rotateX: -10 }}
          animate={{ opacity: 1, y: 0, rotateX: 0 }}
          transition={
            reduced
              ? { duration: 0 }
              : { duration: 0.36, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }
          }
          className={`px-4 py-3.5 transition-colors duration-120 hover:bg-ink-800/40 ${
            i % 3 !== 0 ? "border-l border-ink-700" : ""
          } ${i >= 3 ? "border-t border-ink-700 md:border-t-0" : ""} ${
            i % 3 === 0 && i > 0 ? "md:border-l md:border-ink-700" : ""
          }`}
        >
          <p className="label-caps">{r.label}</p>
          {loading ? (
            <Skeleton className="mt-2 h-8 w-20" />
          ) : (
            // The jump from text-2xl to 30px with negative tracking is the
            // hierarchy fix: these numerals are the reason the view exists and
            // were previously only one step above the caption. tabular-nums
            // stops the width jitter as digits tick during a load test.
            <p className="mt-1 font-mono text-[30px] font-medium leading-none tracking-[-0.02em] tabular-nums text-ink-100">
              {r.value === null ? (
                <span className="text-2xl text-ink-300">—</span>
              ) : (
                <AnimatedNumber value={r.value} format={r.format} />
              )}
            </p>
          )}
        </motion.div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- charts */

const MODEL_COLORS = [
  STAGE_COLOR.generate,
  STAGE_COLOR.retrieve,
  STAGE_COLOR.cache,
  STAGE_COLOR.embed,
];

const tooltipStyle = {
  backgroundColor: INK[800],
  border: `1px solid ${INK[700]}`,
  borderRadius: 5,
  fontSize: 11,
  fontFamily: '"JetBrains Mono", monospace',
  color: INK[100],
  // A tooltip floats above everything, so it takes the top of the depth scale.
  // Recharts renders it inline, so this mirrors `shadow-lift` by hand rather
  // than reaching for the Tailwind class.
  boxShadow:
    "0 2px 4px rgba(3,7,18,0.55), 0 8px 18px -4px rgba(3,7,18,0.55), 0 22px 48px -16px rgba(3,7,18,0.66)",
  padding: "6px 10px",
} as const;

const axisTick = {
  fill: INK[300],
  fontSize: 10,
  fontFamily: '"JetBrains Mono", monospace',
} as const;

function ModelBreakdownChart({ breakdown }: { breakdown: Record<string, number> }) {
  const data = Object.entries(breakdown)
    .map(([model, count]) => ({ model, count }))
    .sort((a, b) => b.count - a.count);

  if (data.length === 0) {
    return <EmptyChartNote text="No model calls in this window." />;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 44)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, bottom: 0, left: 8 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="model"
          width={170}
          tickLine={false}
          axisLine={{ stroke: INK[700] }}
          tick={axisTick}
        />
        <Tooltip
          cursor={{ fill: `${INK[700]}44` }}
          contentStyle={tooltipStyle}
          itemStyle={{ color: INK[100] }}
          labelStyle={{ color: INK[300] }}
        />
        <Bar dataKey="count" name="requests" barSize={16} radius={[0, 2, 2, 0]}>
          {data.map((entry, i) => (
            <Cell key={entry.model} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function RecentLatencyChart() {
  const traces = useSyncExternalStore(subscribeTraces, getTraces);
  const data = traces.slice(-20).map((entry, i) => {
    const stages = entry.trace.stages_ms ?? {};
    return {
      name: `#${i + 1}`,
      Retrieval: Math.round(stages.retrieval_ms ?? 0),
      Cache: Math.round(entry.client_cache_ms ?? 0),
      Generate: Math.round(stages.llm_ms ?? 0),
    };
  });

  if (data.length === 0) {
    return (
      <EmptyChartNote text="No queries traced yet this session — run a query in the playground or start a load test." />
    );
  }

  return (
    <ResponsiveContainer width="100%" height={190}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <XAxis
          dataKey="name"
          tickLine={false}
          axisLine={{ stroke: INK[700] }}
          tick={axisTick}
        />
        <YAxis
          tickLine={false}
          axisLine={{ stroke: INK[700] }}
          tick={axisTick}
          width={52}
          tickFormatter={(v: number) => `${v}ms`}
        />
        <Tooltip
          cursor={{ fill: `${INK[700]}44` }}
          contentStyle={tooltipStyle}
          itemStyle={{ color: INK[100] }}
          labelStyle={{ color: INK[300] }}
          formatter={(value: number | string) => `${value}ms`}
        />
        <Bar dataKey="Retrieval" stackId="lat" fill={STAGE_COLOR.retrieve} barSize={14} />
        <Bar dataKey="Cache" stackId="lat" fill={STAGE_COLOR.cache} barSize={14} />
        <Bar
          dataKey="Generate"
          stackId="lat"
          fill={STAGE_COLOR.generate}
          barSize={14}
          radius={[2, 2, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

function EmptyChartNote({ text }: { text: string }) {
  return (
    <div className="flex h-[190px] items-center justify-center px-6">
      <p className="max-w-xs text-center text-xs leading-relaxed text-ink-300">{text}</p>
    </div>
  );
}

function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-[2px]"
            style={{ backgroundColor: it.color }}
          />
          <span className="text-[11px] text-ink-300">{it.label}</span>
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- dashboard */

export function OpsDashboard({ active }: { active: boolean }) {
  const [window_, setWindow] = useState<MetricsWindow>("1h");
  const loadTest = useLoadTest();
  const pollMs = loadTest.running ? 1000 : 5000;
  const { metrics, error } = useMetrics(window_, pollMs, active);
  const reduced = useReducedMotion();

  const loading = metrics === null && !error;
  const empty = metrics !== null && metrics.total_requests === 0;

  const readouts: ReadoutDef[] = [
    {
      label: "req / sec",
      value: metrics?.req_per_sec ?? null,
      format: (n) => fmtNum(n, 2),
    },
    {
      label: "p50",
      value: metrics?.latency_p50_ms ?? null,
      format: (n) => fmtMs(n),
    },
    {
      label: "p95",
      value: metrics?.latency_p95_ms ?? null,
      format: (n) => fmtMs(n),
    },
    {
      label: "p99",
      value: metrics?.latency_p99_ms ?? null,
      format: (n) => fmtMs(n),
    },
    {
      label: "cache hit",
      value: metrics?.cache_hit_rate ?? null,
      format: (n) => fmtPct(n),
    },
    {
      label: "error rate",
      value: metrics?.error_rate ?? null,
      format: (n) => fmtPct(n),
    },
  ];

  return (
    <motion.main
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="min-w-0 flex-1 overflow-y-auto p-5"
    >
      {/* controls */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented<MetricsWindow>
          ariaLabel="Metrics window"
          options={[
            { value: "1h", label: "1h" },
            { value: "24h", label: "24h" },
            { value: "7d", label: "7d" },
          ]}
          value={window_}
          onChange={setWindow}
        />
        <div className="ml-auto flex items-center gap-3">
          {loadTest.running && (
            <span className="font-mono text-xs text-ink-300" aria-live="polite">
              {loadTest.completed}/{loadTest.total} complete
            </span>
          )}
          <Button onClick={loadTest.start} disabled={loadTest.running}>
            {loadTest.running ? "Load test running…" : "Run load test"}
          </Button>
        </div>
      </div>

      {loadTest.running && (
        <div className="mb-4 h-1 w-full overflow-hidden rounded-full bg-ink-950/70 shadow-[inset_0_1px_2px_rgba(3,7,18,0.65)]">
          <div
            className="h-full rounded-full transition-[width] duration-300"
            style={{
              width: `${(loadTest.completed / loadTest.total) * 100}%`,
              backgroundColor: STAGE_COLOR.generate,
              boxShadow: `0 0 8px ${STAGE_COLOR.generate}88`,
            }}
          />
        </div>
      )}

      {/* instrument readout row */}
      <ReadoutRow readouts={readouts} loading={loading} />

      <div className="mt-2 flex items-baseline justify-between px-1">
        <p className="font-mono text-[11px] text-ink-300">
          {metrics
            ? `${metrics.total_requests} requests · ${fmtCost(metrics.total_cost_usd ?? 0)} total cost · window ${metrics.window}`
            : " "}
          {/* Deliberately not folded into "error rate": a 429 means the limiter
              did its job, not that the system failed. Shown beside the error
              readout so the distinction is visible, not just argued in a doc.
              The "served" count is spelled out alongside it because every rate
              above is over admitted requests, not arrivals — without it the
              cache and error percentages look like they disagree with the
              request total. */}
          {metrics && (metrics.rate_limited_count ?? 0) > 0 && (
            <span className="text-warn">
              {` · ${metrics.rate_limited_count} rate-limited (429) · rates over ${metrics.served_requests ?? metrics.total_requests} served`}
            </span>
          )}
        </p>
        {error && <p className="text-xs text-warn">{error}</p>}
      </div>

      {empty && (
        <p className="mt-4 text-sm text-ink-300">
          No traffic in this window yet — run a query in the playground or
          start a load test.
        </p>
      )}

      {/* charts */}
      <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-ink-700 bg-ink-900 p-4 shadow-panel surface-edge transition-shadow duration-120 hover:shadow-raised">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="font-display text-sm font-medium tracking-[0.01em] text-ink-100">
              Model usage
            </h2>
            <span className="label-caps">window {window_}</span>
          </div>
          {loading ? (
            <div className="space-y-3 py-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-4 w-3/5" />
            </div>
          ) : (
            <ModelBreakdownChart breakdown={metrics?.model_breakdown ?? {}} />
          )}
        </section>

        <section className="rounded-md border border-ink-700 bg-ink-900 p-4 shadow-panel surface-edge transition-shadow duration-120 hover:shadow-raised">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="font-display text-sm font-medium tracking-[0.01em] text-ink-100">
              Recent query latency by stage
            </h2>
            <ChartLegend
              items={[
                { label: "Retrieval", color: STAGE_COLOR.retrieve },
                { label: "Cache", color: STAGE_COLOR.cache },
                { label: "Generate", color: STAGE_COLOR.generate },
              ]}
            />
          </div>
          <RecentLatencyChart />
        </section>
      </div>
    </motion.main>
  );
}
