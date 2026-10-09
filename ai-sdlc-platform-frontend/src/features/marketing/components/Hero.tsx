import { useNavigate } from "react-router-dom";
import { ArrowRight, LogIn, Sparkles, Upload } from "lucide-react";
import { HeroVisual } from "./HeroVisual";

export function Hero() {
  const navigate = useNavigate();

  return (
    <section id="home" className="relative px-4 pb-16 pt-24 sm:px-6 sm:pb-24 sm:pt-32 lg:px-8 lg:pt-40">
      <div className="mx-auto grid max-w-7xl items-center gap-10 lg:grid-cols-2 lg:gap-16">
        <div>
          <div className="mb-5 inline-flex max-w-full items-center gap-2 rounded-full border border-blue-200/80 bg-blue-50/80 px-3 py-1.5 text-[11px] font-medium text-blue-700 backdrop-blur-sm sm:mb-6 sm:px-4 sm:text-xs">
            <Sparkles className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">AI-Powered Software Development</span>
          </div>
          <h1 className="text-[1.85rem] font-semibold leading-[1.15] tracking-tight text-slate-900 sm:text-4xl md:text-5xl lg:text-[3.25rem]">
            From SRS document to{" "}
            <span className="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
              tested, deployed software
            </span>
            , reviewed at every step
          </h1>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-slate-600 sm:mt-6 sm:text-lg">
            Upload your Software Requirements Specification and AI analyses it, designs the system, generates the
            code and its tests, and prepares the release, stopping at each phase for your approval.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:mt-10 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
            <button
              onClick={() => navigate("/projects/new")}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-6 py-3.5 text-sm font-semibold text-white shadow-xl shadow-blue-600/30 transition-all hover:bg-blue-500 hover:shadow-blue-500/30 sm:w-auto"
            >
              <Upload className="h-4 w-4" />
              Upload SRS
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              onClick={() => navigate("/login")}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-6 py-3.5 text-sm font-semibold text-slate-800 shadow-sm backdrop-blur-sm transition-all hover:border-blue-200 hover:bg-blue-50/50 sm:w-auto"
            >
              <LogIn className="h-4 w-4" />
              Log In to Workspace
            </button>
          </div>
          <p className="mt-5 text-xs text-slate-500 sm:mt-6 sm:text-sm">
            A research preview, built as final-year research at the Sri Lanka Institute of Information Technology.
          </p>
        </div>

        <div className="relative mt-8 lg:mt-0">
          <HeroVisual />
        </div>
      </div>
    </section>
  );
}
