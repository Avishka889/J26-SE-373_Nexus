import type { ReactNode } from "react";
import { Select as BaseSelect } from "@base-ui/react/select";
import { Check, ChevronDown } from "lucide-react";
import { useIsDark } from "@/shared/theme";
import { cn } from "@/shared/utils/cn";

export interface SelectOption<Value extends string = string> {
  value: Value;
  label: string;
  /** A second line under the label: what the option is, or why it cannot be chosen. */
  note?: ReactNode;
  disabled?: boolean;
}

const SIZES = {
  sm: "h-8 gap-1.5 rounded-lg px-2.5 text-[12.5px]",
  md: "h-10 gap-2 rounded-xl px-3.5 text-sm",
} as const;

/**
 * The platform's one dropdown: a choice of one from a short list.
 *
 * Every dropdown was the browser's own `<select>`, styled four ways when
 * closed and not at all when open: the list was the operating system's, so it
 * ignored the app's type, its theme and its shape, and an option could carry
 * no more than a line of text. A release target that could not be used said
 * why only in a tooltip, which a touch screen never shows.
 *
 * The behaviour is Base UI's (arrow keys, typing to find, focus, a popup kept
 * on screen), and the look is ours. The list opens under the trigger and does
 * not lock the page. An option's `note` is read with it, and a disabled
 * option says why in the list itself. The trigger is a button with the role
 * of a combobox, named by a `<label htmlFor>` or by `aria-label`.
 *
 * Phones keep the native control where one is used only there (the stage
 * rail's "Jump to a section"): the system's picker is the better one.
 */
export function Select<Value extends string>({
  value,
  options,
  onChange,
  id,
  disabled = false,
  size = "md",
  className,
  title,
  "aria-label": ariaLabel,
  "aria-describedby": describedBy,
}: {
  value: Value;
  options: readonly SelectOption<Value>[];
  onChange: (value: Value) => void;
  id?: string;
  disabled?: boolean;
  size?: keyof typeof SIZES;
  /** For the trigger: its width, mostly. */
  className?: string;
  title?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
}) {
  const isDark = useIsDark();
  const chosen = options.find((one) => one.value === value);

  return (
    <BaseSelect.Root
      value={value}
      onValueChange={(next) => {
        if (next !== null) onChange(next as Value);
      }}
      disabled={disabled}
      modal={false}
    >
      <BaseSelect.Trigger
        id={id}
        title={title}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        className={cn(
          "inline-flex min-w-0 max-w-full select-none items-center justify-between border text-left outline-none transition-colors",
          "focus-visible:ring-2 focus-visible:ring-blue-500/40 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-60",
          SIZES[size],
          isDark
            ? "border-white/10 bg-white/[0.04] text-slate-100 hover:border-white/20 data-[popup-open]:border-blue-400/60"
            : "border-slate-200 bg-white text-slate-800 hover:border-slate-300 data-[popup-open]:border-blue-400",
          className,
        )}
      >
        <span className="min-w-0 truncate">{chosen?.label ?? value}</span>
        <BaseSelect.Icon className="shrink-0">
          <ChevronDown
            aria-hidden="true"
            className={cn("h-3.5 w-3.5", isDark ? "text-slate-400" : "text-slate-500")}
          />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner sideOffset={6} align="start" alignItemWithTrigger={false} className="z-[100] outline-none">
          <BaseSelect.Popup
            className={cn(
              "max-h-[min(20rem,var(--available-height))] min-w-[var(--anchor-width)] max-w-[min(22rem,calc(100vw-1.5rem))] overflow-y-auto overscroll-contain rounded-xl border p-1 shadow-2xl outline-none",
              "origin-[var(--transform-origin)] transition-[opacity,transform] duration-100 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0 motion-reduce:transition-none",
              isDark ? "border-white/10 bg-[#0f1d32] text-slate-200" : "border-slate-200 bg-white text-slate-800",
            )}
          >
            <BaseSelect.List>
              {options.map((option) => (
                <BaseSelect.Item
                  key={option.value}
                  value={option.value}
                  label={option.label}
                  disabled={option.disabled}
                  className={cn(
                    "flex cursor-default select-none items-start gap-2 rounded-lg py-2 pl-2 pr-3 outline-none data-[disabled]:cursor-not-allowed",
                    size === "sm" ? "text-[12.5px]" : "text-sm",
                    isDark
                      ? "data-[highlighted]:bg-white/[0.07] data-[selected]:text-white"
                      : "data-[highlighted]:bg-blue-50 data-[selected]:text-blue-900",
                  )}
                >
                  <span className="flex h-5 w-4 shrink-0 items-center">
                    <BaseSelect.ItemIndicator>
                      <Check aria-hidden="true" className={cn("h-3.5 w-3.5", isDark ? "text-blue-400" : "text-blue-600")} />
                    </BaseSelect.ItemIndicator>
                  </span>
                  <span className="min-w-0">
                    <BaseSelect.ItemText
                      className={cn("block leading-5", option.disabled && (isDark ? "text-slate-400" : "text-slate-500"))}
                    >
                      {option.label}
                    </BaseSelect.ItemText>
                    {option.note && (
                      <span className={cn("mt-0.5 block text-xs leading-snug", isDark ? "text-slate-400" : "text-slate-600")}>
                        {option.note}
                      </span>
                    )}
                  </span>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  );
}
