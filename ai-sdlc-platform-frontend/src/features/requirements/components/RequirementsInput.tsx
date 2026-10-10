import { useRef, useState } from "react";
import { ArrowUp, FileText, Mic, Paperclip } from "lucide-react";
import type { Project } from "@/types/project";
import { useUiStore } from "@/store/ui";
import { composeRequirementText, useAttachments } from "@/entities/document";
import { useRunsOn } from "@/entities/settings";
import {
  AttachmentChips,
  AttachmentPreview,
  ComposerShell,
  IconGhostButton,
  RunsOnLine,
  SoftChipButton,
  composerTextareaClass,
  surface,
} from "@/shared/ui";
import { cn } from "@/shared/utils/cn";

export function RequirementsInput({
  project,
  onSubmit,
  isStarting = false,
}: {
  project: Project;
  onSubmit: (text: string, files: string[], typed: string) => void;
  /** Blocks a second submit while the first is in flight. */
  isStarting?: boolean;
}) {
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";
  const [text, setText] = useState(project.requirementText);
  const fileRef = useRef<HTMLInputElement>(null);
  const { slots, documents, readingCount, add, remove } = useAttachments();
  const [showPreview, setShowPreview] = useState(false);
  const composed = composeRequirementText(text, documents);
  // A file being read is not in `documents` yet, so `composed` is the typed
  // text alone while it is in flight. Submitting there started the run on the
  // typed text and unmounted this composer with the read still going: the
  // document was dropped and nothing said so.
  const canSubmit = composed.trim().length > 0 && !isStarting && readingCount === 0;
  // What the design run this starts runs on.
  const runsOn = useRunsOn("design", null);
  const submit = () =>
    canSubmit && onSubmit(composed, documents.map((d) => d.name), text);

  const examples = [
    "Build a digital banking platform with payments, KYC, and transaction history.",
    "Create an inventory API with stock levels, suppliers, and low-stock alerts.",
    "Design a notification service supporting email, SMS, and push channels.",
  ];

  return (
    <div className="flex min-h-[70vh] w-full flex-col items-center justify-center px-6 py-12">
      <div className="mb-8 text-center">
        <div
          className={cn(
            "mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl",
            isDark ? "bg-blue-500/15 text-blue-300" : "bg-blue-50 text-blue-600"
          )}
        >
          <FileText className="h-6 w-6" />
        </div>
        <h3 className={cn("text-2xl font-semibold tracking-tight", surface.heading(isDark))}>
          What should {project.name} do?
        </h3>
        <p className={cn("mt-2 text-sm", surface.muted(isDark))}>
          Paste natural language requirements, user stories, or upload an SRS. We’ll generate design artifacts automatically.
        </p>
      </div>

      <ComposerShell isDark={isDark} variant="accent">
        <textarea
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          rows={5}
          placeholder="Describe features, actors, constraints, integrations..."
          className={composerTextareaClass(isDark)}
        />

        <AttachmentChips slots={slots} isDark={isDark} onRemove={remove} onInspect={() => setShowPreview(true)} />

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              multiple
              // No .doc: the picker offers exactly the formats SUPPORTED reads,
              // rather than letting a reader choose one the next step refuses.
              accept=".pdf,.docx,.txt,.md"
              onChange={(e) => {
                if (e.target.files?.length) add(e.target.files);
                // Cleared so re-picking the same file fires change again.
                e.target.value = "";
              }}
            />
            <IconGhostButton isDark={isDark} title="Attach SRS documents" onClick={() => fileRef.current?.click()}>
              <Paperclip className="h-4 w-4" />
            </IconGhostButton>
            <IconGhostButton isDark={isDark}>
              <Mic className="h-4 w-4" />
            </IconGhostButton>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("hidden text-[11px] sm:inline", surface.faint(isDark))}>⌘ + Enter</span>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={submit}
              className={cn(
                "flex h-9 items-center gap-2 rounded-xl px-4 text-sm font-medium text-white transition-colors disabled:opacity-40",
                "bg-blue-500 hover:bg-blue-400"
              )}
            >
              {/*
                The label says why the button is doing nothing. Disabling it
                alone would leave a reader pressing a dead control with the
                cause sitting in a chip they may not connect to it.
              */}
              {readingCount > 0
                ? `Reading the ${readingCount === 1 ? "document" : "documents"}`
                : "Analyze"}
              <ArrowUp className="h-4 w-4" />
            </button>
          </div>
        </div>
      </ComposerShell>
      {runsOn && (
        <RunsOnLine
          runsOn={runsOn}
          className={cn("mt-2 w-full px-1 text-xs", surface.muted(isDark))}
        />
      )}

      <div
        className={cn("mt-4 w-full rounded-xl border border-dashed p-4 text-center text-xs", surface.dashed(isDark))}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (e.dataTransfer.files.length) add(e.dataTransfer.files);
        }}
      >
        {/*
          All four formats, not the two binary ones. TXT and MD are the formats
          the browser reads itself, so they are the ones that work with no
          orchestrator running, and naming only PDF and DOCX hid that.
        */}
        Drop a PDF, DOCX, TXT or MD file here, or use the paperclip to attach
      </div>

      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {examples.map((ex) => (
          <SoftChipButton key={ex} isDark={isDark} className="max-w-xs text-left" onClick={() => setText(ex)}>
            {ex}
          </SoftChipButton>
        ))}
      </div>

      {showPreview && (
        <AttachmentPreview
          composed={composed}
          sources={documents.map((d) => d.name)}
          hasTypedText={text.trim().length > 0}
          isDark={isDark}
          onClose={() => setShowPreview(false)}
        />
      )}
    </div>
  );
}
