import { CheckCircle2, FileText, Sparkles } from "lucide-react";

const pipelineItems = [
  { label: "Architecture diagram", progress: 100 },
  { label: "API layer · 42 endpoints", progress: 100 },
  { label: "Database schema · 18 tables", progress: 100 },
  { label: "React frontend scaffold", progress: 87 },
];

export function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-xl lg:max-w-none">
      {/* Glow behind */}
      <div className="absolute inset-4 rounded-3xl bg-blue-600/20 blur-3xl" />

      {/* Architecture diagram layer */}
      <div className="absolute -right-4 top-8 z-0 hidden w-48 opacity-90 xl:block">
        <svg viewBox="0 0 200 160" className="w-full drop-shadow-lg">
          <defs>
            <linearGradient id="hero-node" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#2563eb" />
              <stop offset="100%" stopColor="#1d4ed8" />
            </linearGradient>
          </defs>
          <rect x="70" y="10" width="60" height="28" rx="8" fill="url(#hero-node)" opacity="0.9" />
          <text x="100" y="28" textAnchor="middle" fill="white" fontSize="9" fontWeight="600">
            API Gateway
          </text>
          <rect x="10" y="70" width="52" height="24" rx="6" fill="#f8fafc" stroke="#e2e8f0" strokeWidth="1" />
          <rect x="74" y="70" width="52" height="24" rx="6" fill="#f8fafc" stroke="#e2e8f0" strokeWidth="1" />
          <rect x="138" y="70" width="52" height="24" rx="6" fill="#f8fafc" stroke="#e2e8f0" strokeWidth="1" />
          <rect x="40" y="120" width="120" height="28" rx="8" fill="#1e293b" opacity="0.9" />
          <path d="M100 38 L100 70 M36 82 L70 82 M130 82 L164 82 M100 94 L100 120" stroke="#2563eb" strokeWidth="1.5" opacity="0.4" className="landing-flow-line" />
          <circle cx="100" cy="70" r="3" fill="#2563eb" className="landing-pulse-dot" />
        </svg>
      </div>

      {/* Main dashboard card */}
      <div className="relative z-10 overflow-hidden rounded-2xl border border-white/70 bg-white/75 shadow-2xl shadow-blue-900/10 backdrop-blur-xl">
        <div className="flex items-center justify-between border-b border-slate-100/80 bg-slate-50/50 px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-2.5 rounded-full bg-red-400" />
            <div className="h-2.5 w-2.5 rounded-full bg-amber-400" />
            <div className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
          </div>
          <span className="text-[11px] font-medium tracking-wide text-slate-400">AI GENERATION PIPELINE</span>
          <Sparkles className="h-4 w-4 text-blue-500 landing-sparkle" />
        </div>

        <div className="grid gap-4 p-5 md:grid-cols-5">
          {/* Code panel */}
          <div className="overflow-hidden rounded-xl border border-slate-200/80 bg-[#1e293b] md:col-span-2">
            <div className="border-b border-white/5 px-3 py-2 text-[10px] font-medium text-slate-400">generated/api/routes.ts</div>
            <pre className="overflow-hidden p-3 text-[10px] leading-relaxed text-slate-300">
              <code>
                <span className="text-blue-400">export</span>{" "}
                <span className="text-cyan-300">async</span>{" "}
                <span className="text-amber-200">function</span> createPayment() {"{"}
                {"\n"}  <span className="text-slate-400">{"// REQ-847 → auto-linked"}</span>
                {"\n"}  <span className="text-blue-400">return</span> await db.transaction(
                {"\n"}    validateKYC(userId),
                {"\n"}    processStripe(payload)
                {"\n"}  );
                {"\n"}{"}"}
              </code>
            </pre>
            <div className="h-1 bg-slate-800">
              <div className="landing-scan-bar h-full w-1/3 bg-gradient-to-r from-transparent via-blue-500 to-transparent" />
            </div>
          </div>

          {/* Pipeline status */}
          <div className="space-y-3 md:col-span-3">
            <div className="flex items-center gap-3 rounded-xl border border-blue-100 bg-gradient-to-r from-blue-50 to-white p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 shadow-md shadow-blue-600/30">
                <FileText className="h-5 w-5 text-white" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-900">payment-gateway-srs.pdf</p>
                <p className="text-xs text-slate-500">847 requirements · semantic analysis active</p>
              </div>
              <span className="relative flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60" />
                <span className="relative inline-flex h-3 w-3 rounded-full bg-blue-600" />
              </span>
            </div>

            {pipelineItems.map((item, i) => (
              <div
                key={item.label}
                className="rounded-xl border border-slate-100 bg-white/90 px-4 py-3 landing-fade-up"
                style={{ animationDelay: `${i * 120}ms` }}
              >
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                    <span className="text-xs font-medium text-slate-700">{item.label}</span>
                  </div>
                  <span className="text-[10px] tabular-nums text-slate-400">{item.progress}%</span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-blue-600 to-cyan-500 transition-all"
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Data flow footer */}
        <div className="relative border-t border-slate-100 bg-slate-50/40 px-5 py-3">
          <svg className="absolute inset-x-5 top-0 h-8 -translate-y-1/2" preserveAspectRatio="none">
            <path
              d="M0 16 Q120 0 240 16 T480 16"
              fill="none"
              stroke="#2563eb"
              strokeWidth="1.5"
              strokeDasharray="6 8"
              opacity="0.35"
              className="landing-flow-line"
            />
          </svg>
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>SRS → Architecture → Code → Deploy</span>
            <span className="font-medium text-blue-600">Live generation</span>
          </div>
        </div>
      </div>

      {/* Floating stat cards */}
      <div className="absolute -bottom-5 -left-4 z-20 rounded-2xl border border-white/80 bg-white/90 px-5 py-3.5 shadow-xl backdrop-blur-xl landing-float">
        <p className="text-2xl font-bold tabular-nums text-blue-600">4 gates</p>
        <p className="text-xs text-slate-500">each approved by a person</p>
      </div>
      <div className="absolute -right-2 top-1/2 z-20 hidden rounded-2xl border border-white/80 bg-[#1e293b]/95 px-4 py-3 shadow-xl backdrop-blur-xl landing-float-delay sm:block">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-blue-600/30 flex items-center justify-center">
            <Sparkles className="h-4 w-4 text-blue-400" />
          </div>
          <div>
            <p className="text-xs font-semibold text-white">Every artefact</p>
            <p className="text-lg font-bold text-blue-400">traced</p>
          </div>
        </div>
      </div>

      {/* Cloud accent */}
      <svg className="absolute -left-8 bottom-16 z-0 w-24 opacity-60 landing-float" viewBox="0 0 80 50">
        <ellipse cx="40" cy="30" rx="35" ry="18" fill="#eff6ff" stroke="#bfdbfe" strokeWidth="1" />
        <ellipse cx="25" cy="28" rx="18" ry="12" fill="white" />
        <ellipse cx="52" cy="26" rx="14" ry="10" fill="white" />
      </svg>
    </div>
  );
}
