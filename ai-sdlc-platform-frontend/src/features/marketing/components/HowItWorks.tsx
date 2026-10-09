import { CheckCircle2, Sparkles, Upload } from "lucide-react";
import { WorkflowPipeline } from "./LandingVisuals";

const steps = [
  {
    step: "01",
    title: "Upload SRS",
    description: "Drop your Software Requirements Specification - PDF, Word, or Markdown supported.",
    icon: Upload,
  },
  {
    step: "02",
    title: "AI generates solution",
    description: "The design, the code, its tests and the deployment pipeline are generated, each phase stopping for your review.",
    icon: Sparkles,
  },
  {
    step: "03",
    title: "Review and release",
    description: "Approve each phase or ask for changes; the release goes to Vercel and Render once you approve it.",
    icon: CheckCircle2,
  },
];

export function HowItWorks() {
  return (
    <section className="relative px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-600">How it works</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Three steps to a complete solution</h2>
        </div>
        <WorkflowPipeline />
        <div className="relative mt-16 grid gap-8 md:grid-cols-3">
          <div className="absolute left-0 right-0 top-16 hidden h-px bg-gradient-to-r from-transparent via-blue-200 to-transparent md:block" />
          {steps.map((s) => (
            <div key={s.step} className="relative text-center">
              <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-blue-100 bg-white shadow-lg shadow-blue-900/5">
                <s.icon className="h-7 w-7 text-blue-600" />
              </div>
              <span className="text-xs font-bold uppercase tracking-widest text-blue-600">Step {s.step}</span>
              <h3 className="mt-2 text-xl font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">{s.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
