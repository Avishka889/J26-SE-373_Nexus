import { useNavigate } from "react-router-dom";
import { Upload } from "lucide-react";
import { NexusWordmark } from "@/shared/ui/brand/NexusWordmark";
import { CtaVisual } from "./LandingVisuals";
import { GlassCard } from "./GlassCard";

export function FooterCta() {
  const navigate = useNavigate();

  return (
    <>
      <section className="relative px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
        <GlassCard className="relative mx-auto max-w-4xl overflow-hidden border-0 bg-gradient-to-br from-blue-600 to-[#1e3a8a] p-12 text-center">
          <CtaVisual />
          <h2 className="text-3xl font-semibold text-white md:text-4xl">Ready to transform your delivery pipeline?</h2>
          <p className="mx-auto mt-4 max-w-xl text-blue-100">
            Upload your first SRS and follow it through design, code, tests and release, approving each step.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <button
              onClick={() => navigate("/projects/new")}
              className="inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3.5 text-sm font-semibold text-blue-600 shadow-lg transition-all hover:bg-blue-50"
            >
              <Upload className="h-4 w-4" />
              Upload SRS
            </button>
            <button
              onClick={() => navigate("/login")}
              className="inline-flex items-center gap-2 rounded-xl border border-white/30 px-6 py-3.5 text-sm font-semibold text-white transition-all hover:bg-white/10"
            >
              Log In
            </button>
          </div>
        </GlassCard>
      </section>

      <footer id="contact" className="border-t border-slate-200 bg-slate-900 px-4 py-12 text-slate-400 sm:px-6 sm:py-16 lg:px-8">
        <div className="mx-auto grid max-w-7xl gap-10 sm:grid-cols-2 md:grid-cols-4 md:gap-12">
          <div className="sm:col-span-2 md:col-span-1">
            <div className="flex items-center">
              <NexusWordmark dark className="h-8 max-w-[160px] sm:h-9 sm:max-w-[180px]" />
            </div>
            <p className="mt-4 text-sm leading-relaxed">
              AI-assisted software delivery, from requirements to a release a person approved.
            </p>
          </div>
          <div>
            <h4 className="mb-4 text-sm font-semibold text-white">Product</h4>
            <ul className="space-y-2 text-sm">
              {[
                ["Features", "#features"],
                ["Solutions", "#solutions"],
                ["Availability", "#pricing"],
                ["Questions", "#docs"],
              ].map(([label, href]) => (
                <li key={label}>
                  <a href={href} className="hover:text-white">
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mb-4 text-sm font-semibold text-white">Your data</h4>
            <ul className="space-y-2 text-sm">
              <li>
                <a href="#privacy" className="hover:text-white">
                  Privacy
                </a>
              </li>
            </ul>
          </div>
          <div>
            <h4 className="mb-4 text-sm font-semibold text-white">About</h4>
            <p className="text-sm leading-relaxed">
              A final-year research project at the Sri Lanka Institute of Information Technology (SLIIT).
            </p>
          </div>
        </div>
        <div className="mx-auto mt-12 max-w-7xl border-t border-slate-800 pt-8 text-center text-sm">
          © {new Date().getFullYear()} Nexus. All rights reserved.
        </div>
      </footer>
    </>
  );
}
