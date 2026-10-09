import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";
import { Progress } from "@/shared/ui/primitives";

export function Metric({
  label,
  value,
  denominator,
  note,
  tone,
  size = "md",
  source,
}: {
  label: string;
  value: ReactNode;
  denominator?: ReactNode;
  note?: ReactNode;
  tone?: "pass" | "fail" | "caution" | "muted";
  size?: "sm" | "md" | "lg";
  /**
   * Where the number comes from and over what: "test report, test version 3".
   * Required, because every metric tile names its source and window or does
   * not ship, and 39 of 47 named neither.
   */
  source: string;
}) {
  const color =
    tone === "pass"
      ? "var(--tp-pass)"
      : tone === "fail"
      ? "var(--tp-fail)"
      : tone === "caution"
      ? "var(--tp-caution)"
      : tone === "muted"
      ? "var(--tp-muted)"
      : undefined;

  return (
    <div className="min-w-0">
      <p className="tp-label">{label}</p>
      <p className="mt-1 flex items-baseline gap-1.5">
        <span
          className={cn("tp-num", size === "lg" ? "text-3xl" : size === "sm" ? "text-xl" : "text-2xl")}
          style={color ? { color } : undefined}
        >
          {value}
        </span>
        {denominator && <span className="tp-den">{denominator}</span>}
      </p>
      {note && <p className="tp-den mt-1 leading-relaxed">{note}</p>}
      <p className="tp-den mt-1 text-[11px] leading-snug" data-metric-source>
        {source}
      </p>
    </div>
  );
}

const barColor: Record<string, string> = {
  ink: "#2563eb",
  pass: "#10b981",
  caution: "#f59e0b",
  fail: "#ef4444",
  muted: "#94a3b8",
};

export function Bar({
  value,
  tone = "ink",
  className,
}: {
  value: number;
  tone?: "ink" | "pass" | "caution" | "fail" | "muted";
  className?: string;
}) {
  return <Progress value={value} color={barColor[tone]} className={className} />;
}
