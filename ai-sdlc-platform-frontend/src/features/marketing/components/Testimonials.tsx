import { TestimonialsPattern } from "./LandingVisuals";

const testimonials = [
  {
    quote: "We cut our initial scaffolding phase from three weeks to two days. The architecture output alone saved our architects dozens of hours.",
    name: "Sarah Mitchell",
    role: "VP Engineering",
    company: "Nexus Financial",
  },
  {
    quote: "Uploading an SRS and getting a full project structure with traceability back to requirements changed how we pitch and deliver client work.",
    name: "James Okonkwo",
    role: "CTO",
    company: "Vertex Software Labs",
  },
  {
    quote: "Enterprise security was non-negotiable. Nexus met our compliance review while delivering faster than any internal tool we've built.",
    name: "Elena Vasquez",
    role: "Director of Platform",
    company: "Meridian Health Systems",
  },
];

export function Testimonials() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-b from-blue-600 to-[#1e3a8a] px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <TestimonialsPattern />
      <div className="mx-auto max-w-7xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight text-white md:text-4xl">
            Trusted by engineering leaders
          </h2>
        </div>
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {testimonials.map((t) => (
            <div
              key={t.name}
              className="rounded-2xl border border-white/20 bg-white/10 p-8 backdrop-blur-xl"
            >
              <p className="text-sm leading-relaxed text-blue-50">&ldquo;{t.quote}&rdquo;</p>
              <div className="mt-6 border-t border-white/20 pt-6">
                <p className="font-semibold text-white">{t.name}</p>
                <p className="text-sm text-blue-200">
                  {t.role}, {t.company}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
