import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, Mail, User, UserPlus } from "lucide-react";
import { register } from "@/entities/account";
import { messageOf } from "@/lib/http";
import { Button, Field, useFieldClasses } from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import { useUiStore } from "@/store/ui";
import { registrationProblem } from "../model/registration";

/** Create an account, signed in at once. */
export function RegisterForm() {
  const navigate = useNavigate();
  const addToast = useUiStore((s) => s.addToast);
  const { fieldClass } = useFieldClasses();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const problem = registrationProblem(name, email, password);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const { adopted } = await register(name, email, password);
      if (adopted) {
        addToast({
          type: "info",
          title: "Your account holds your earlier work",
          message: "The projects made before sign-in are now this account's.",
        });
      }
      navigate("/workspace", { replace: true });
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-5" noValidate>
      <Field label="Name">
        {(control) => (
          <div className="relative">
            <User className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              {...control}
              required
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ada Lovelace"
              className={cn(fieldClass, "pl-10 pr-3.5")}
            />
          </div>
        )}
      </Field>

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

      <Field label="Password" hint="At least 8 characters. A passphrase of a few words is easy to remember and hard to guess.">
        {(control) => (
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              {...control}
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
        <UserPlus className="h-4 w-4" />
        Create account
      </Button>
    </form>
  );
}
