import { cn } from "@/shared/utils/cn";
import { nexusLogo, nexusLogoLight } from "@/assets/img";

type NexusWordmarkProps = {
  className?: string;
  /** Use light logo variant on dark backgrounds (e.g. footer) */
  dark?: boolean;
  compact?: boolean;
};

/** Official NEXUS logo lockup (icon plus wordmark), a transparent PNG. */
export function NexusWordmark({ className, dark = false, compact = false }: NexusWordmarkProps) {
  // Compact always uses the colorful mark (left side of the lockup)
  const src = compact ? nexusLogo : dark ? nexusLogoLight : nexusLogo;

  if (compact) {
    return (
      <img
        src={src}
        alt="Nexus"
        className={cn(
          "h-8 w-8 shrink-0 rounded-lg object-cover object-left",
          className
        )}
      />
    );
  }

  return (
    <img
      src={src}
      alt="Nexus"
      className={cn("h-9 w-auto max-w-full bg-transparent object-contain object-left", className)}
    />
  );
}
