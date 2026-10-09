import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { LogIn, Mail, Lock } from "lucide-react";
import { signIn } from "@/entities/account";
import { messageOf } from "@/lib/http";
import { Button, Field, useFieldClasses } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";

/** Sign in, then go back to the page that asked for it. */
export function LoginForm({ from }: { from: string }) {
  const navigate = useNavigate();
  const { fieldClass } = useFieldClasses();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await signIn(email, password);
      navigate(from, { replace: true });
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-5" noValidate>
      <Field label="Email">
        {(control) => (
          <div className="relative">
            <Mail className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              {...control}
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={cn(fieldClass, "pl-10 pr-3.5")}
            />
          </div>
        )}
      </Field>

      <Field label="Password">
        {(control) => (
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              {...control}
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className={cn(fieldClass, "pl-10 pr-3.5")}
            />
          </div>
        )}
      </Field>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <Button
        type="submit"
        variant="primary"
        size="lg"
        busy={pending}
        className="w-full gap-2 py-3 shadow-lg shadow-blue-600/25"
      >
        <LogIn className="h-4 w-4" />
        Log In
      </Button>
    </form>
  );
}
