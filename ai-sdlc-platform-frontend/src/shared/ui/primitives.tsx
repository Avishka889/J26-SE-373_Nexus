import {
  type ReactNode,
  type HTMLAttributes,
  type ButtonHTMLAttributes,
  type ThHTMLAttributes,
  type TdHTMLAttributes,
  forwardRef,
  useRef,
  useState,
} from "react";
import { useIsDark } from "@/shared/theme";
import { cn } from "@/shared/utils/cn";
import { Spinner } from "./Spinner";

// ===== Card =====
export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  const isDark = useIsDark();
  return (
    <div
      className={cn(
        "rounded-2xl border transition-colors",
        isDark
          ? "border-white/[0.06] bg-[#0f1d32]/80"
          : "border-slate-200/80 bg-white shadow-sm shadow-slate-200/40",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  const isDark = useIsDark();
  return (
    <div className={cn("border-b px-5 py-4", isDark ? "border-white/[0.05]" : "border-slate-100", className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  const isDark = useIsDark();
  return (
    <h3 className={cn("text-sm font-semibold tracking-tight", isDark ? "text-white" : "text-slate-900", className)} {...props}>
      {children}
    </h3>
  );
}

export function CardContent({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("p-5", className)} {...props}>
      {children}
    </div>
  );
}

// ===== Badge =====
type BadgeVariant = "default" | "success" | "warning" | "error" | "info" | "c1" | "c2" | "c3" | "c4";

const badgeVariants: Record<BadgeVariant, string> = {
  default: "bg-slate-100 text-slate-600 border-slate-200/80 dark:bg-white/5 dark:text-slate-300 dark:border-white/10",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20",
  warning: "bg-amber-50 text-amber-700 border-amber-200/80 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20",
  error: "bg-red-50 text-red-700 border-red-200/80 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20",
  info: "bg-blue-50 text-blue-700 border-blue-200/80 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20",
  c1: "bg-green-50 text-green-700 border-green-200/80 dark:bg-green-500/10 dark:text-green-400 dark:border-green-500/20",
  c2: "bg-blue-50 text-blue-700 border-blue-200/80 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20",
  c3: "bg-blue-50 text-blue-700 border-blue-200/80 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20",
  c4: "bg-orange-50 text-orange-700 border-orange-200/80 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500/20",
};

export function Badge({
  variant = "default",
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        badgeVariants[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

// ===== Button =====
type ButtonVariant = "default" | "outline" | "ghost" | "c1" | "c2" | "c3" | "c4" | "error" | "success" | "primary";
type ButtonSize = "sm" | "md" | "lg" | "icon";

const buttonVariants: Record<ButtonVariant, string> = {
  default: "bg-slate-100 text-slate-700 hover:bg-slate-200 border-slate-200 dark:bg-white/5 dark:text-slate-100 dark:hover:bg-white/10 dark:border-white/10",
  outline: "bg-transparent text-slate-600 hover:bg-slate-100 border-slate-200 dark:text-slate-300 dark:hover:bg-white/5 dark:border-white/10",
  ghost: "bg-transparent text-slate-600 hover:bg-slate-100 border-transparent dark:text-slate-300 dark:hover:bg-white/5 dark:border-transparent",
  primary: "bg-blue-600 text-white hover:bg-blue-500 border-blue-600 shadow-lg shadow-blue-500/20",
  c1: "bg-green-600 text-white hover:bg-green-500 border-green-600",
  c2: "bg-blue-600 text-white hover:bg-blue-500 border-blue-600",
  c3: "bg-blue-600 text-white hover:bg-blue-500 border-blue-600",
  c4: "bg-orange-600 text-white hover:bg-orange-500 border-orange-600",
  error: "bg-red-600 text-white hover:bg-red-500 border-red-600",
  success: "bg-emerald-600 text-white hover:bg-emerald-500 border-emerald-600",
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-10 px-5 text-sm",
  icon: "h-9 w-9 p-0",
};

/**
 * `busy` is the guard against a second click on work already in flight.
 *
 * Every action here goes to a server that takes a moment, and until it answers
 * the page still shows the button that started it. A second click sends a
 * second request: at best the server refuses it and the reader gets an error
 * toast for doing nothing wrong, at worst two runs start. Disabling on the
 * pending flag of the mutation is one prop rather than a state variable per
 * button, and the spinner says why it is disabled.
 *
 * A handler that returns its request needs no flag at all: the button is busy
 * until the request settles, answered or refused. Only some buttons had been
 * given `busy`, and Run tests stayed clickable, with nothing on it, until the
 * server answered. A handler that returns nothing is left as it was.
 */
export function Button({
  variant = "default",
  size = "md",
  className,
  children,
  disabled,
  busy = false,
  type = "button",
  onClick,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  busy?: boolean;
}) {
  const [waiting, setWaiting] = useState(false);
  // Read in the handler rather than from state, so a second click in the same
  // frame finds the first request still in flight.
  const inFlight = useRef(false);
  const shown = busy || waiting;
  return (
    <button
      type={type}
      disabled={disabled || shown}
      aria-busy={shown || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl border font-medium transition-all focus:outline-none focus:ring-2 focus:ring-blue-500/30 disabled:pointer-events-none disabled:opacity-50",
        buttonVariants[variant],
        buttonSizes[size],
        className
      )}
      onClick={(event) => {
        if (inFlight.current) return;
        const result: unknown = onClick?.(event);
        if (typeof (result as PromiseLike<unknown> | undefined)?.then !== "function") return;
        inFlight.current = true;
        setWaiting(true);
        const settle = () => {
          inFlight.current = false;
          setWaiting(false);
        };
        // A refusal frees the button too: it is reported where the request is made.
        void Promise.resolve(result).then(settle, settle);
      }}
      {...props}
    >
      {busy && <Spinner size="xs" decorative />}
      {children}
    </button>
  );
}

// ===== Progress =====
export function Progress({ value, className, color = "#2563eb" }: { value: number; className?: string; color?: string }) {
  const isDark = useIsDark();
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full", isDark ? "bg-white/10" : "bg-slate-100", className)}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%`, backgroundColor: color }}
      />
    </div>
  );
}

// ===== Code Block =====
export const CodeBlock = forwardRef<HTMLPreElement, { code: string; language?: string; className?: string }>(
  ({ code, language, className }, ref) => {
    const isDark = useIsDark();
    return (
      <pre
        ref={ref}
        className={cn(
          "overflow-auto rounded-xl p-4 text-xs leading-relaxed font-mono border",
          isDark
            ? "bg-[#0a0e17] text-slate-300 border-white/5"
            : "bg-slate-50 text-slate-700 border-slate-200",
          className
        )}
      >
        <code className={`language-${language}`}>{code}</code>
      </pre>
    );
  }
);
CodeBlock.displayName = "CodeBlock";

// ===== Table =====
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("w-full overflow-auto", className)}>
      <table className="w-full text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  const isDark = useIsDark();
  return (
    <th
      className={cn(
        "border-b px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider",
        isDark ? "border-white/5 text-slate-400" : "border-slate-100 text-slate-500",
        className
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function Td({ children, className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  const isDark = useIsDark();
  return (
    <td
      className={cn(
        "border-b px-3 py-2.5",
        isDark ? "border-white/[0.04] text-slate-300" : "border-slate-50 text-slate-600",
        className
      )}
      {...props}
    >
      {children}
    </td>
  );
}
