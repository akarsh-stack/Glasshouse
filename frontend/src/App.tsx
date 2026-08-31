import { Suspense, lazy, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Spinner } from "./components/icons";
import { Wordmark } from "./components/Logo";
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
    // dvh rather than vh: on mobile browsers 100vh includes the retractable
    // URL bar, so the header would sit under it until the user scrolls.
    <div className="flex h-dvh flex-col">
      {/* slim header */}
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-ink-700 bg-ink-900 px-3">
        {view === "playground" && (
          <button
            type="button"
            aria-label={railOpen ? "Collapse document rail" : "Expand document rail"}
            aria-expanded={railOpen}
            onClick={() => setRailOpen((o) => !o)}
            // 32px square: below the 44px ideal, but this is a pointer-first
            // desktop instrument panel and the rail auto-collapses on touch
            // widths, where this control isn't rendered at all.
            className="grid h-8 w-8 place-items-center rounded border border-ink-700 text-ink-300 transition-colors duration-120 hover:bg-ink-800 hover:text-ink-100"
          >
            {railOpen ? <ChevronLeft /> : <ChevronRight />}
          </button>
        )}

        <h1 className="contents">
          <Wordmark />
        </h1>

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
              // Matches the dashboard's own loading language rather than a bare
              // line of text, so the swap doesn't flash a different treatment.
              <div className="flex flex-1 items-center justify-center gap-2 text-ink-300">
                <Spinner />
                <p className="font-mono text-xs">Loading dashboard…</p>
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
