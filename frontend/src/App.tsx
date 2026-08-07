import { Suspense, lazy, useEffect, useState } from "react";
import { Segmented } from "./components/ui";
import type { Tier } from "./types";
import { Playground } from "./views/Playground";

// Code-split the dashboard: Recharts is ~250 kB and only this view uses it, so
// the Playground (the landing view) shouldn't pay for it on first paint. Safe to
// unmount because the trace history lives in the external store in
// lib/traceStore.ts, not in this component's state.
const OpsDashboard = lazy(() =>
  import("./views/OpsDashboard").then((m) => ({ default: m.OpsDashboard })),
);

type View = "playground" | "ops";

export default function App() {
  const [view, setView] = useState<View>("playground");
  const [tier, setTier] = useState<Tier>("quality");
  const [railOpen, setRailOpen] = useState<boolean>(
    () => window.matchMedia("(min-width: 1024px)").matches,
  );

  // Collapse the document rail automatically on narrow viewports.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const handler = (e: MediaQueryListEvent) => setRailOpen(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <div className="flex h-screen flex-col">
      {/* slim header */}
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-ink-700 bg-ink-900 px-3">
        {view === "playground" && (
          <button
            type="button"
            aria-label={railOpen ? "Collapse document rail" : "Expand document rail"}
            aria-expanded={railOpen}
            onClick={() => setRailOpen((o) => !o)}
            className="rounded border border-ink-700 px-2 py-1 font-mono text-xs text-ink-300 transition-colors hover:bg-ink-800 hover:text-ink-100"
          >
            {railOpen ? "⟨" : "⟩"}
          </button>
        )}
        <h1 className="font-display text-base font-semibold tracking-tight text-ink-100">
          Glasshouse
        </h1>
        <span className="hidden font-mono text-[10px] uppercase tracking-[0.18em] text-ink-300 sm:inline">
          rag pipeline, visible
        </span>

        <div className="ml-auto flex items-center gap-2">
          <Segmented<View>
            ariaLabel="View"
            options={[
              { value: "playground", label: "Playground" },
              { value: "ops", label: "Ops" },
            ]}
            value={view}
            onChange={setView}
          />
          <Segmented<Tier>
            ariaLabel="Model tier"
            options={[
              { value: "fast", label: "Fast" },
              { value: "quality", label: "Quality" },
              { value: "deep", label: "Deep" },
            ]}
            value={tier}
            onChange={setTier}
          />
        </div>
      </header>

      {/* views — playground stays mounted so an in-flight query keeps
          streaming while the user checks the ops dashboard */}
      <div className={view === "playground" ? "flex min-h-0 flex-1" : "hidden"}>
        <Playground tier={tier} railOpen={railOpen} />
      </div>
      {view === "ops" && (
        <div className="flex min-h-0 flex-1">
          <Suspense
            fallback={
              <div className="flex flex-1 items-center justify-center">
                <p className="font-mono text-xs text-ink-300">Loading dashboard…</p>
              </div>
            }
          >
            <OpsDashboard active={view === "ops"} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
