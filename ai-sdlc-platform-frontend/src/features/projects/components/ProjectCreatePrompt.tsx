import { useRef, useState } from "react";
import {
  ArrowUp,
  Paperclip,
  Monitor,
  Smartphone,
  Layers,
  FileText,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { messageOf } from "@/lib/http";
import { composeRequirementText, useAttachments } from "@/entities/document";
import { useRunsOn } from "@/entities/settings";
import {
  AttachmentChips,
  AttachmentPreview,
  ComposerShell,
  IconGhostButton,
  RunsOnLine,
  SoftChipButton,
  StarterChipButton,
  composerTextareaClass,
  surface,
} from "@/shared/ui";
import { cn } from "@/shared/utils/cn";
import { Spinner } from "@/shared/ui/Spinner";
import { nexusLogo } from "@/assets/img";

const examples = [
  "Payment gateway with KYC verification",
  "Inventory management API",
  "Real-time notification service",
];

const starters: { icon: LucideIcon; label: string; prompt: string; attach?: boolean }[] = [
  { icon: Monitor, label: "Web app", prompt: "Build a web app for " },
  { icon: Smartphone, label: "Mobile API", prompt: "Build a mobile API for " },
  { icon: Layers, label: "Microservices", prompt: "Build a microservices system for " },
  { icon: FileText, label: "From SRS", prompt: "", attach: true },
];

export function ProjectCreatePrompt({
  firstName,
  isDark,
  onSubmit,
  autoFocus = false,
}: {
  firstName: string;
  isDark: boolean;
  /** Awaited, so the control can stay disabled until the project exists. */
  onSubmit: (text: string, files: string[], typed: string) => void | Promise<void>;
  autoFocus?: boolean;
}) {
  const [prompt, setPrompt] = useState("");
  const { slots, documents, readingCount, add, remove } = useAttachments();
  const [showPreview, setShowPreview] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const composed = composeRequirementText(prompt, documents);
  // A file being read is not in `documents` yet, so `composed` is the typed
  // text alone while it is in flight. Submitting there created the project,
  // started the run on the typed sentence, and unmounted this composer with the
  // read still going: the document was dropped and nothing said so. Enter
  // submits, so that window is one keystroke wide.
  // Creating a project is a round trip, and until it returns this component is
  // still mounted and still listening. Enter submits, so a reader who presses it
  // twice used to create two projects. `canSubmit` is what both the handler and
  // the button read, so guarding here guards the keyboard path too.
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = composed.trim().length > 0 && readingCount === 0 && !submitting;
  const waitingLabel = `Waiting for the ${readingCount === 1 ? "document" : "documents"} to finish reading`;

  // Why the last attempt failed, said under the composer. It said "the caller
  // shows the error" and neither caller did: a refused create left the reader
  // looking at their text with nothing to say nothing had happened.
  const [failure, setFailure] = useState<string | null>(null);
  // What the run this starts runs on: a project's first run is its design's.
  const runsOn = useRunsOn("design", null);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setFailure(null);
    try {
      await onSubmit(composed, documents.map((d) => d.name), prompt);
    } catch (error) {
      // The text stays, and the control is released, so the reader can retry.
      setFailure(messageOf(error, "The server did not answer."));
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="mx-auto max-w-2xl text-center">
        <div
          className={cn(
            "mb-4 inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-medium sm:mb-5 sm:text-xs",
            isDark ? "border-white/10 bg-white/[0.04] text-slate-300" : "border-slate-200 bg-white text-slate-600 shadow-sm"
          )}
        >
          <img src={nexusLogo} alt="" className="h-4 w-4 shrink-0 object-cover object-left" />
          <span className="truncate">
            <span className="sm:hidden">AI-assisted SDLC</span>
            <span className="hidden sm:inline">AI-assisted SDLC from requirements to release</span>
          </span>
        </div>
        <h1 className={cn("text-[1.65rem] font-semibold leading-tight tracking-tight sm:text-3xl md:text-4xl", surface.heading(isDark))}>
          Hi {firstName}, what do you want to build?
        </h1>
        <p className={cn("mx-auto mt-3 max-w-md text-sm md:text-base", surface.muted(isDark))}>
          Describe a product or paste requirements. We’ll generate design, code, tests, and deployment plans.
        </p>
      </div>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (e.dataTransfer.files.length) add(e.dataTransfer.files);
        }}
      >
        <ComposerShell isDark={isDark} className="mx-auto mt-6 max-w-2xl sm:mt-8">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            rows={3}
            autoFocus={autoFocus}
            aria-label="Describe what you want to build"
            placeholder="Describe a product, paste requirements, or outline a system to build..."
            className={composerTextareaClass(isDark)}
          />

          <AttachmentChips slots={slots} isDark={isDark} onRemove={remove} onInspect={() => setShowPreview(true)} />

          <div className="mt-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1">
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                multiple
                // No .doc: the picker offers exactly the formats SUPPORTED
                // reads, rather than letting a reader choose one the next step
                // refuses.
                accept=".pdf,.docx,.txt,.md"
                onChange={(e) => {
                  if (e.target.files?.length) add(e.target.files);
                  // Cleared so re-picking the same file fires change again.
                  e.target.value = "";
                }}
              />
              <IconGhostButton
                isDark={isDark}
                title="Attach a requirements document"
                onClick={() => fileRef.current?.click()}
              >
                <Paperclip className="h-4 w-4" />
              </IconGhostButton>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                // A real disabled attribute, not only the muted styling it used
                // to have: the guard in the handler was invisible, so the
                // control looked inert and still fired.
                disabled={!canSubmit}
                // The only place this button can say anything, since it carries
                // an icon and no text. A reader who presses it and sees nothing
                // happen is told what it is waiting for rather than left to
                // guess, on the tooltip and in the accessibility tree alike.
                aria-label={
                  submitting
                    ? "Creating the project"
                    : readingCount > 0
                      ? waitingLabel
                      : "Analyze requirements"
                }
                title={readingCount > 0 ? waitingLabel : undefined}
                onClick={handleSubmit}
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-xl text-white transition-all",
                  canSubmit
                    ? "bg-blue-500 shadow-md shadow-blue-500/25 hover:bg-blue-400"
                    : isDark
                      ? "bg-white/10 text-slate-400"
                      : "bg-slate-200 text-slate-500"
                )}
              >
                {submitting ? (
                  <Spinner size="sm" decorative />
                ) : (
                  <ArrowUp className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        </ComposerShell>
        {runsOn && (
          <RunsOnLine
            runsOn={runsOn}
            className={cn("mx-auto mt-2 max-w-2xl px-1 text-xs", surface.muted(isDark))}
          />
        )}
        {failure && (
          <p role="alert" className={cn("mt-2 text-left text-sm", isDark ? "text-red-300" : "text-red-700")}>
            The project was not created. {failure}
          </p>
        )}
      </div>

      <div className="mx-auto mt-5 max-w-2xl sm:mt-6">
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 scrollbar-none sm:flex-wrap sm:justify-center sm:overflow-visible">
          {starters.map((s) => {
            const Icon = s.icon;
            return (
              <StarterChipButton
                key={s.label}
                isDark={isDark}
                onClick={() => (s.attach ? fileRef.current?.click() : setPrompt(s.prompt))}
              >
                <Icon className="h-3.5 w-3.5 opacity-70" />
                {s.label}
              </StarterChipButton>
            );
          })}
        </div>
      </div>

      <div className="mx-auto mt-4 flex max-w-2xl flex-col items-center gap-2.5 sm:mt-5">
        <button
          type="button"
          className={cn("flex items-center gap-1.5 text-xs", isDark ? "text-slate-400 hover:text-slate-300" : "text-slate-500 hover:text-slate-600")}
          onClick={() => setPrompt(examples[Math.floor(Math.random() * examples.length)])}
        >
          Try an example prompt <RefreshCw className="h-3 w-3" />
        </button>
        <div className="-mx-1 flex w-full gap-2 overflow-x-auto px-1 pb-1 scrollbar-none sm:flex-wrap sm:justify-center sm:overflow-visible">
          {examples.map((ex) => (
            <SoftChipButton key={ex} isDark={isDark} onClick={() => setPrompt(ex)}>
              {ex}
            </SoftChipButton>
          ))}
        </div>
      </div>

      {showPreview && (
        <AttachmentPreview
          composed={composed}
          sources={documents.map((d) => d.name)}
          isDark={isDark}
          hasTypedText={prompt.trim().length > 0}
          onClose={() => setShowPreview(false)}
        />
      )}
    </>
  );
}
