import {
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
  forwardRef,
} from "react";
import { cn } from "@/shared/utils/cn";
import { surface } from "./surface";

export const IconGhostButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { isDark: boolean }
>(function IconGhostButton({ isDark, className, type = "button", ...props }, ref) {
  return <button ref={ref} type={type} className={cn(surface.iconGhost(isDark), className)} {...props} />;
});

export function SoftChipButton({
  isDark,
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { isDark: boolean }) {
  return <button type={type} className={cn(surface.softChip(isDark), className)} {...props} />;
}

export function StarterChipButton({
  isDark,
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { isDark: boolean }) {
  return <button type={type} className={cn(surface.starterChip(isDark), className)} {...props} />;
}

export function ComposerShell({
  isDark,
  variant = "default",
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  isDark: boolean;
  variant?: "default" | "accent";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "w-full rounded-2xl p-3 shadow-sm transition-all focus-within:shadow-md sm:p-4",
        variant === "accent"
          ? isDark
            ? "border-2 border-blue-500/40 bg-[#0f1d32]/80 focus-within:border-blue-400"
            : "border-2 border-blue-400 bg-white focus-within:border-blue-500"
          : isDark
            ? "border border-transparent bg-[#0f1d32]/90 shadow-lg shadow-black/30 focus-within:border-blue-500/40 focus-within:shadow-xl"
            : "border border-transparent bg-white shadow-lg shadow-slate-200/50 focus-within:border-blue-400 focus-within:shadow-xl",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
