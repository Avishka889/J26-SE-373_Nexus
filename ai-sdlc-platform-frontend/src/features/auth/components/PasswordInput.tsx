import { useState, type KeyboardEvent } from "react";
import { Eye, EyeOff, Lock } from "lucide-react";
import { useFieldClasses, type FieldControlProps } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";

/**
 * A password field that can be looked at before it is sent.
 *
 * The toggle is a button of its own, not a submit, and says which way it is
 * (`aria-pressed`); it keeps what was typed. Caps Lock is said when a key
 * press shows it on, which is the only moment a browser tells.
 */
export function PasswordInput({
  control,
  value,
  onChange,
  autoComplete,
  placeholder,
  minLength,
}: {
  control: FieldControlProps;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  placeholder?: string;
  minLength?: number;
}) {
  const { fieldClass } = useFieldClasses();
  const [shown, setShown] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const readCapsLock = (event: KeyboardEvent<HTMLInputElement>) =>
    setCapsLock(event.getModifierState("CapsLock"));
  const Icon = shown ? EyeOff : Eye;

  return (
    <>
      <div className="relative">
        <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          {...control}
          type={shown ? "text" : "password"}
          required
          minLength={minLength}
          autoComplete={autoComplete}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={readCapsLock}
          onKeyUp={readCapsLock}
          onBlur={() => setCapsLock(false)}
          placeholder={placeholder}
          className={cn(fieldClass, "pl-10 pr-11")}
        />
        <button
          type="button"
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          onClick={() => setShown((now) => !now)}
          className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {capsLock && (
        <p role="status" className="mt-1.5 text-xs text-amber-700">
          Caps Lock is on.
        </p>
      )}
    </>
  );
}
