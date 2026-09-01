import type { ReactNode } from "react";
import { Bot, ShieldCheck } from "lucide-react";
import { Badge } from "@/shared/ui/primitives";

export type ChipTone = "neutral" | "pass" | "fail" | "caution" | "info";

const toneVariant: Record<ChipTone, "default" | "success" | "error" | "warning" | "info"> = {
  neutral: "default",
  pass: "success",
  fail: "error",
  caution: "warning",
  info: "info",
};

/** A label with a tone. Every phase-specific chip is built on this one. */
export function Chip({
  tone = "neutral",
  icon,
  children,
  className,
  title,
}: {
  tone?: ChipTone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <Badge variant={toneVariant[tone]} className={className} title={title}>
      {icon}
      {children}
    </Badge>
  );
}

/** Who did a thing: a person gets initials, anything automated gets an icon. */
export function ActorMark({ actor, kind }: { actor: string; kind: "human" | "agent" | "guard" }) {
  if (kind === "human") {
    const initials = actor
      .split(" ")
      .map((p) => p[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-blue-400 text-[8px] font-bold text-white">
          {initials}
        </span>
        {actor}
      </span>
    );
  }
  const Icon = kind === "guard" ? ShieldCheck : Bot;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 text-blue-400" />
      {actor}
    </span>
  );
}
