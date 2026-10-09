import { useNavigate } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { GlassCard } from "./GlassCard";

/**
 * What it costs and what it includes: a research preview, free.
 *
 * The section offered $499 and $1,499 monthly plans, SSO, SAML, an on-premise
 * option and a sales team, none of which exist. What a person gets is listed
 * from what the platform does.
 */
const included = [
  "Requirements analysis, design, code, tests and release, each approved by you",
  "Code generated for the MERN stack, in TypeScript",
  "Releases to Vercel and Render on your own accounts",
  "Repositories pushed to your own GitHub account",
  "An audit log of every decision",
];

export function Pricing() {
  const navigate = useNavigate();

  return (
    <section id="pricing" className="relative px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-700">Availability</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">A research preview, free to use</h2>
        </div>
        <GlassCard className="mx-auto mt-14 flex max-w-xl flex-col p-8">
          <h3 className="text-lg font-semibold text-slate-900">Research preview</h3>
          <p className="mt-1 text-sm text-slate-600">
            Built as final-year research. The AI model and cloud accounts it works with are the ones it is configured
            with, and the releases are made with your own accounts.
          </p>
          <ul className="mt-8 flex-1 space-y-3">
            {included.map((line) => (
              <li key={line} className="flex items-start gap-2 text-sm text-slate-600">
                <CheckCircle2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                {line}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => navigate("/register")}
            className="mt-8 w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/25 transition-all hover:bg-blue-500"
          >
            Create an account
          </button>
        </GlassCard>
      </div>
    </section>
  );
}
