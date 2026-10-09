import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { cn } from "@/shared/utils/cn";
import { Spinner } from "@/shared/ui/Spinner";
import { fonts } from "@/shared/constants/fonts";

let mermaidTheme: "dark" | "default" = "dark";

function initMermaid(isDark: boolean) {
  const theme = isDark ? "dark" : "default";
  if (mermaidTheme === theme) return;
  mermaidTheme = theme;
  mermaid.initialize({
    startOnLoad: false,
    theme,
    themeVariables: isDark
      ? {
          darkMode: true,
          background: "#0f172a",
          primaryColor: "#1e293b",
          primaryTextColor: "#e2e8f0",
          primaryBorderColor: "#334155",
          lineColor: "#64748b",
          secondaryColor: "#1e293b",
          tertiaryColor: "#0f172a",
          fontFamily: fonts.sans.stack,
        }
      : {
          background: "#ffffff",
          primaryColor: "#f8fafc",
          primaryTextColor: "#0f172a",
          primaryBorderColor: "#cbd5e1",
          lineColor: "#64748b",
          secondaryColor: "#f1f5f9",
          tertiaryColor: "#ffffff",
          fontFamily: fonts.sans.stack,
        },
    flowchart: { curve: "basis", padding: 16, htmlLabels: true },
    sequence: { actorMargin: 40, messageMargin: 35 },
    securityLevel: "loose",
  });
}

export function MermaidDiagramImpl({
  chart,
  id,
  isDark = true,
  className,
  minHeight = 280,
  fit = false,
}: {
  chart: string;
  id: string;
  isDark?: boolean;
  className?: string;
  minHeight?: number;
  /**
   * Grow the drawing to the width it is given, rather than leaving it at the
   * size mermaid chose.
   *
   * Off in a card, where a preview at natural size sits in a row with its
   * neighbours. On when the diagram has been opened to be read, where leaving a
   * small diagram small in a large window is the opposite of what was asked for.
   */
  fit?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // One state for the outcome, tagged with the diagram it belongs to.
  //
  // The previous version reset `loading` and `error` synchronously at the top of
  // the render effect, which is the cascading-render pattern the linter flags.
  // Tagging the outcome instead means a new chart reads as loading during the
  // very first render that mentions it, with no reset pass at all: the state is
  // only ever written from the async callbacks that actually know an outcome.
  const key = `${id}|${isDark}|${chart}`;
  const [outcome, setOutcome] = useState<{ key: string; failed: boolean }>({
    key,
    failed: false,
  });
  const settled = outcome.key === key;
  const loading = !settled;
  const error = settled && outcome.failed;

  useEffect(() => {
    initMermaid(isDark);
  }, [isDark]);

  useEffect(() => {
    let cancelled = false;

    const render = async () => {
      try {
        initMermaid(isDark);
        const renderId = `mermaid-${id}-${Date.now()}`;
        const { svg } = await mermaid.render(renderId, chart);
        if (cancelled) return;
        if (ref.current) {
          ref.current.innerHTML = svg;
          const svgEl = ref.current.querySelector("svg");
          if (svgEl) {
            // maxWidth alone only caps: it stops a wide diagram overflowing but
            // never grows a narrow one, which is why an opened diagram sat small
            // in the corner of its own window.
            svgEl.style.maxWidth = "100%";
            svgEl.style.height = "auto";
            if (fit) {
              svgEl.style.width = "100%";
              svgEl.style.maxWidth = "none";
            }
          }
        }
        setOutcome({ key, failed: false });
      } catch {
        if (!cancelled) setOutcome({ key, failed: true });
      }
    };

    render();
    return () => {
      cancelled = true;
    };
  }, [chart, id, isDark, key, fit]);

  if (error) {
    return (
      <div
        className={cn(
          "flex items-center justify-center rounded-xl border p-4",
          isDark ? "border-white/10 bg-slate-950" : "border-slate-200 bg-slate-50",
          className
        )}
        style={{ minHeight }}
      >
        <p className={cn("text-xs", isDark ? "text-slate-400" : "text-slate-500")}>
          Unable to render diagram preview
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative overflow-auto rounded-xl border",
        isDark ? "border-white/10 bg-slate-950/50" : "border-slate-200 bg-slate-50/80",
        className
      )}
      style={{ minHeight }}
    >
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Spinner size="md" tone="accent" label="Drawing the diagram" />
        </div>
      )}
      <div
        ref={ref}
        className={cn("flex items-center justify-center p-4", loading && "opacity-0")}
      />
    </div>
  );
}
