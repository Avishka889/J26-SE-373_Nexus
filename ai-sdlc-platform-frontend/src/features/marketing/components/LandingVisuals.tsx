import { Brain, Cloud, Code2, Database, GitBranch, Layers, Shield, Upload } from "lucide-react";

export function FeaturesBanner() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200/80 bg-gradient-to-br from-slate-900 via-[#1e293b] to-slate-900 p-8 shadow-2xl md:p-10">
      <div className="absolute inset-0 opacity-30">
        <svg className="h-full w-full" viewBox="0 0 800 400" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id="feat-glow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#2563eb" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.2" />
            </linearGradient>
          </defs>
          <circle cx="400" cy="200" r="180" fill="url(#feat-glow)" className="landing-pulse-glow" />
          {/* Architecture nodes */}
          {[
            [400, 80, "API"],
            [250, 180, "Auth"],
            [550, 180, "DB"],
            [320, 300, "Cache"],
            [480, 300, "Queue"],
          ].map(([x, y, label]) => (
            <g key={String(label)}>
              <rect x={Number(x) - 36} y={Number(y) - 14} width="72" height="28" rx="8" fill="#334155" stroke="#475569" strokeWidth="1" />
              <text x={Number(x)} y={Number(y) + 4} textAnchor="middle" fill="#e2e8f0" fontSize="11" fontWeight="500">
                {label}
              </text>
            </g>
          ))}
          <path d="M400 108 L400 166 M250 194 L364 194 M436 194 L550 194 M320 266 L380 220 M420 220 L480 266" stroke="#2563eb" strokeWidth="1.5" opacity="0.5" className="landing-flow-line" />
        </svg>
      </div>

      <div className="relative grid items-center gap-8 lg:grid-cols-2">
        <div>
          <p className="text-sm font-medium text-blue-400">Intelligent automation</p>
          <h3 className="mt-2 text-2xl font-semibold text-white md:text-3xl">
            Full-stack architecture generated from your requirements
          </h3>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">
            Our AI maps every requirement to services, data models, and deployment targets - with full traceability from SRS to production artifacts.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            {[
              { icon: Brain, label: "NLP Analysis" },
              { icon: Layers, label: "System Design" },
              { icon: Shield, label: "Secure Processing" },
            ].map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300"
              >
                <Icon className="h-3.5 w-3.5 text-blue-400" />
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {[
            // Facts about the platform, not figures nobody measured.
            { icon: Code2, value: "4", label: "Phases, each reviewed" },
            { icon: Database, value: "1", label: "Stack, validated" },
            { icon: GitBranch, value: "Every", label: "Endpoint traced to a requirement" },
            { icon: Cloud, value: "2", label: "Release targets: Vercel, Render" },
          ].map(({ icon: Icon, value, label }) => (
            <div key={label} className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm">
              <Icon className="mb-2 h-5 w-5 text-blue-400" />
              <p className="text-xl font-bold text-white">{value}</p>
              <p className="text-[11px] text-slate-400">{label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function WorkflowPipeline() {
  const steps = [
    { icon: Upload, title: "Upload SRS", color: "#2563eb" },
    { icon: Brain, title: "AI Analysis", color: "#3b82f6" },
    { icon: Layers, title: "Architecture", color: "#1d4ed8" },
    { icon: Code2, title: "Code Gen", color: "#2563eb" },
    { icon: Cloud, title: "Deploy Ready", color: "#06b6d4" },
  ];

  return (
    <div className="relative mx-auto mt-12 max-w-4xl overflow-hidden rounded-2xl border border-slate-200/80 bg-white/60 p-6 backdrop-blur-xl md:p-8">
      <svg className="absolute inset-0 h-full w-full opacity-20" viewBox="0 0 800 120">
        <path d="M80 60 H720" stroke="#2563eb" strokeWidth="2" strokeDasharray="8 12" className="landing-flow-line" />
      </svg>
      <div className="relative flex flex-wrap items-center justify-between gap-4">
        {steps.map((step, i) => (
          <div key={step.title} className="flex flex-col items-center gap-2 landing-fade-up" style={{ animationDelay: `${i * 100}ms` }}>
            <div
              className="flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-100 bg-white shadow-lg shadow-blue-900/5"
              style={{ boxShadow: `0 8px 24px ${step.color}20` }}
            >
              <step.icon className="h-6 w-6" style={{ color: step.color }} />
            </div>
            <span className="text-xs font-medium text-slate-600">{step.title}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SolutionsVisual() {
  return (
    <div className="relative mx-auto mt-12 max-w-5xl">
      <div className="overflow-hidden rounded-3xl border border-slate-200/80 bg-gradient-to-r from-blue-50 via-white to-slate-50 p-1">
        <div className="grid items-center gap-6 rounded-[22px] bg-white/80 p-6 backdrop-blur-sm md:grid-cols-3 md:p-8">
          {/* Collaboration abstract */}
          <div className="flex justify-center md:col-span-1">
            <svg viewBox="0 0 200 180" className="h-40 w-full max-w-[200px]">
              <circle cx="100" cy="60" r="28" fill="#2563eb" opacity="0.15" />
              <circle cx="100" cy="60" r="20" fill="#2563eb" />
              <text x="100" y="65" textAnchor="middle" fill="white" fontSize="14" fontWeight="600">
                AI
              </text>
              <circle cx="45" cy="130" r="16" fill="#1e293b" opacity="0.8" />
              <circle cx="100" cy="145" r="16" fill="#334155" />
              <circle cx="155" cy="130" r="16" fill="#1e293b" opacity="0.8" />
              <path d="M100 80 L45 114 M100 80 L100 129 M100 80 L155 114" stroke="#2563eb" strokeWidth="1.5" opacity="0.4" strokeDasharray="4 4" className="landing-flow-line" />
              <rect x="30" y="155" width="140" height="8" rx="4" fill="#e2e8f0" />
              <rect x="30" y="155" width="90" height="8" rx="4" fill="#2563eb" className="landing-progress-grow" />
            </svg>
          </div>
          <div className="md:col-span-2">
            <p className="text-sm font-semibold text-blue-600">Collaborative delivery</p>
            <p className="mt-2 text-lg font-medium text-slate-800">
              Enterprise teams, agencies, and product squads ship faster with AI-assisted workflows
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {["Audit log of every decision", "A person approves each phase", "Encrypted provider tokens", "Rollback only on approval"].map((tag) => (
                <span key={tag} className="rounded-lg bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TestimonialsPattern() {
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]" viewBox="0 0 400 400">
      <defs>
        <pattern id="testimonial-dots" x="0" y="0" width="20" height="20" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1" fill="white" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#testimonial-dots)" />
    </svg>
  );
}

export function CtaVisual() {
  return (
    <div className="pointer-events-none absolute -right-8 -top-8 hidden opacity-40 lg:block">
      <svg width="200" height="200" viewBox="0 0 200 200">
        <circle cx="100" cy="100" r="80" fill="none" stroke="white" strokeWidth="0.5" opacity="0.3" />
        <circle cx="100" cy="100" r="60" fill="none" stroke="white" strokeWidth="0.5" opacity="0.2" className="landing-pulse-glow" />
        <path d="M100 20 L100 180 M20 100 L180 100" stroke="white" strokeWidth="0.5" opacity="0.15" />
      </svg>
    </div>
  );
}
