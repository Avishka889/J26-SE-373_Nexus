export function LandingBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden">
      {/* Gradient orbs */}
      <div className="landing-orb absolute -left-32 top-0 h-[640px] w-[640px] rounded-full bg-blue-500/25 blur-[120px]" />
      <div className="landing-orb-delay absolute -right-24 top-32 h-[520px] w-[520px] rounded-full bg-cyan-400/15 blur-[100px]" />
      <div className="landing-orb absolute bottom-0 left-1/4 h-[480px] w-[480px] rounded-full bg-blue-700/10 blur-[110px]" />
      <div className="absolute right-1/3 top-1/2 h-[300px] w-[300px] rounded-full bg-slate-400/10 blur-[80px]" />

      {/* Subtle grid */}
      <svg className="absolute inset-0 h-full w-full opacity-[0.35]" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="landing-grid" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="#2563eb" strokeWidth="0.5" opacity="0.08" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#landing-grid)" />
      </svg>

      {/* Floating nodes */}
      <svg className="absolute inset-0 h-full w-full opacity-40" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
        <circle cx="200" cy="180" r="3" fill="#2563eb" className="landing-node" />
        <circle cx="1200" cy="220" r="2.5" fill="#3b82f6" className="landing-node-delay" />
        <circle cx="900" cy="650" r="3" fill="#2563eb" className="landing-node" />
        <circle cx="350" cy="700" r="2" fill="#64748b" className="landing-node-delay" />
        <line x1="200" y1="180" x2="350" y2="700" stroke="#2563eb" strokeWidth="0.5" opacity="0.15" strokeDasharray="4 6" className="landing-flow-line" />
        <line x1="900" y1="650" x2="1200" y2="220" stroke="#3b82f6" strokeWidth="0.5" opacity="0.12" strokeDasharray="4 6" className="landing-flow-line-reverse" />
      </svg>
    </div>
  );
}
