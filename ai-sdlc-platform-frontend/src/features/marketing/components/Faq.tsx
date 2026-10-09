import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { GlassCard } from "./GlassCard";

const faqs = [
  {
    q: "What file formats do you support for SRS uploads?",
    a: "PDF, DOCX, Markdown and plain text, or typed text. The text read from a file is shown to you before it is used, and each requirement is numbered and traced through everything generated from it.",
  },
  {
    q: "How long does generation take?",
    a: "It depends on the size of the requirements and on the AI model provider. Each phase shows its stages as they finish, so you can read one while the rest are generated.",
  },
  {
    q: "Can we review before anything moves on?",
    a: "Yes. Each phase stops at a review: nothing moves to the next phase until you approve it, and you can ask for changes with a note saying what to change.",
  },
  {
    q: "Is our SRS data kept private?",
    a: "The text of your requirements is stored with your project and sent to the AI model provider the platform is configured with, to generate the design, code and tests. Tokens for GitHub, Vercel, Render and MongoDB Atlas are stored encrypted on the server and never sent back to the browser.",
  },
  {
    q: "Which stacks are supported?",
    a: "Code is generated for the MERN stack: MongoDB, Express, React and Node, in TypeScript. The architecture step may recommend another shape; code generation says so when a stack is not one it can build.",
  },
];

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-200/80 last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-4 py-5 text-left"
      >
        <span className="text-sm font-medium text-slate-900 md:text-base">{q}</span>
        <ChevronDown className={cn("h-5 w-5 shrink-0 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && <p className="pb-5 text-sm leading-relaxed text-slate-600">{a}</p>}
    </div>
  );
}

export function Faq() {
  return (
    <section id="docs" className="relative bg-slate-50/80 px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="text-center">
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-600">FAQ</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Common questions</h2>
        </div>
        <GlassCard className="mt-12 px-6 md:px-8">
          {faqs.map((faq) => (
            <FaqItem key={faq.q} q={faq.q} a={faq.a} />
          ))}
        </GlassCard>
      </div>
    </section>
  );
}
