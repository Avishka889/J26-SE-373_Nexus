import { GlassCard } from "./GlassCard";

/**
 * What happens to what a person gives the platform.
 *
 * There was no privacy statement at all, while the FAQ promised encryption and
 * dedicated tenants that were not built. This says what the code does.
 */
const facts = [
  {
    title: "Your account",
    text: "Your name, your email and a hash of your password. The password itself is never stored.",
  },
  {
    title: "Your requirements",
    text: "The text you type or the text read from a file you attach is stored with your project and sent to the AI model provider the platform is configured with, to generate the design, the code and the tests.",
  },
  {
    title: "Your provider tokens",
    text: "Tokens for GitHub, Vercel, Render and MongoDB Atlas are stored encrypted on the server, used only for your projects, and never sent back to the browser. You can remove each one in Settings.",
  },
  {
    title: "Your projects",
    text: "Deleting a project deletes its versions and records here. Its GitHub repository and its Vercel and Render deployments are yours, and stay until you delete them there. The audit log keeps what was done.",
  },
];

export function Privacy() {
  return (
    <section id="privacy" className="relative px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-700">Privacy</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">What happens to your data</h2>
        </div>
        <div className="mt-12 grid gap-6 sm:grid-cols-2">
          {facts.map((fact) => (
            <GlassCard key={fact.title} className="p-6">
              <h3 className="text-base font-semibold text-slate-900">{fact.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{fact.text}</p>
            </GlassCard>
          ))}
        </div>
      </div>
    </section>
  );
}
