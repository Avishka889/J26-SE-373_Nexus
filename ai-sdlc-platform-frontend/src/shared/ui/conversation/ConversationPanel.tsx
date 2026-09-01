import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  ChevronDown,
  CircleDot,
  ListChecks,
  MessageSquare,
  PanelRightClose,
  PanelTop,
  Sparkles,
} from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { RunsOnLine } from "../RunsOnLine";
import { grouped } from "./grouping";
import type { ConversationComposer, ConversationMessage } from "./types";
import { formatWhen } from "@/shared/utils/time";

/**
 * The conversation beside the work.
 *
 * The product starts from a chat box and then abandons the mental model at the
 * door: inside the phase the conversation was a card buried at the bottom of one
 * stage. This is the pattern the tools people compare this to already use, chat
 * on one side and the artifact on the other, and it is the reason the phase can
 * have exactly one place to write prose.
 *
 * It reads as a document rather than a stack of cards, as the agent tools people
 * know do: what a person wrote sits in a bubble on the right, what an agent did
 * reads as a step and its prose, a stage it produced is a card to open, and what
 * the platform recorded is a quiet line. Three or more records in a row fold into
 * one line that opens, so a run's bookkeeping does not bury what was said.
 *
 * It is shared rather than owned by one feature because every phase uses it; it
 * knows about people, agents and events, and nothing about stages.
 */
export function ConversationPanel({
  title,
  subtitle,
  messages,
  composer,
  onClose,
  focusSignal,
}: {
  title: string;
  subtitle: string;
  messages: ConversationMessage[];
  composer: ConversationComposer;
  onClose: () => void;
  /**
   * Changes whenever something elsewhere asks for the panel's attention, which
   * scrolls the transcript down and focuses the box. A counter rather than a
   * boolean, so two requests in a row both land.
   */
  focusSignal?: number;
}) {
  const listRef = useRef<HTMLOListElement | null>(null);
  const boxRef = useRef<HTMLTextAreaElement | null>(null);
  // Read somewhere above the newest message, so the way back is offered.
  const [away, setAway] = useState(false);

  /**
   * Scroll the transcript, and nothing else.
   *
   * Setting the list's own scroll rather than calling `scrollIntoView` on its
   * last child: `scrollIntoView` walks up every scrollable ancestor, so with a
   * long transcript it dragged the whole page down on mount. The reader landed
   * halfway through the artifact with the phase header off screen and the stage
   * row already condensed, before touching anything.
   */
  const scrollTranscript = (behavior: ScrollBehavior) => {
    const list = listRef.current;
    if (!list) return;
    if (typeof list.scrollTo === "function") list.scrollTo({ top: list.scrollHeight, behavior });
    else list.scrollTop = list.scrollHeight;
    setAway(false);
  };

  // New messages arrive at the bottom, which is where a transcript is read from.
  useEffect(() => {
    scrollTranscript("auto");
  }, [messages.length]);

  /**
   * Only when something actually asks, and without moving the page.
   *
   * Two mistakes were in here. The effect fired on mount, because the counter
   * starts at zero and zero is not undefined, so every load focused the box; and
   * focusing scrolls an element into view, which scrolled the whole page down by
   * the height of the transcript. The reader arrived halfway through the artifact
   * with the phase header gone, having touched nothing.
   */
  const lastFocusSignal = useRef(focusSignal);
  useEffect(() => {
    if (focusSignal === undefined || focusSignal === lastFocusSignal.current) return;
    lastFocusSignal.current = focusSignal;
    scrollTranscript("smooth");
    boxRef.current?.focus({ preventScroll: true });
  }, [focusSignal]);

  const items = useMemo(() => grouped(messages), [messages]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2.5 border-b border-[color:var(--tp-line)] px-4 py-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-blue-600/10 dark:bg-blue-400/15">
          <MessageSquare className="h-3.5 w-3.5 text-blue-600 dark:text-blue-300" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-[color:var(--tp-ink)]">{title}</p>
          <p className="tp-den truncate">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Hide the conversation"
          title="Hide the conversation"
          className="rounded-lg p-1.5 text-[color:var(--tp-muted)] transition-colors hover:bg-[color:var(--tp-surface-2)] hover:text-[color:var(--tp-ink)]"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </header>

      <div className="relative min-h-0 flex-1">
        {/* overscroll-contain, so reaching the end of the transcript stops there
            rather than handing the wheel to the column beside it. */}
        <ol
          ref={listRef}
          onScroll={(event) => {
            const list = event.currentTarget;
            setAway(list.scrollHeight - list.scrollTop - list.clientHeight > 160);
          }}
          className="h-full space-y-6 overflow-y-auto overscroll-contain px-5 py-5"
        >
          {items.map((item) =>
            item.kind === "events" ? (
              <EventGroup key={item.events[0].id} events={item.events} />
            ) : (
              <Message key={item.message.id} message={item.message} />
            ),
          )}
        </ol>

        {away && (
          <button
            type="button"
            onClick={() => scrollTranscript("smooth")}
            className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-[color:var(--tp-line-strong)] bg-[color:var(--tp-surface)] px-3 py-1.5 text-[12px] font-medium text-[color:var(--tp-ink-2)] shadow-md transition-colors hover:text-[color:var(--tp-ink)]"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            Scroll to latest
          </button>
        )}
      </div>

      <Composer composer={composer} boxRef={boxRef} />
    </div>
  );
}

/* --------------------------------------------------------------- messages */

const PREVIEW_CHARS = 260;

function Message({ message }: { message: ConversationMessage }) {
  if (message.role === "user") return <UserMessage message={message} />;
  if (message.role === "agent") return <AgentMessage message={message} />;
  // A record stays a quiet line, whoever made it: a decision a person recorded
  // is still a record, and drawing it as an agent's step said otherwise.
  return (
    <li>
      <RecordLine message={message}>
        {message.footer && <div className="mt-1.5">{message.footer}</div>}
        {message.onOpen && (
          <button
            type="button"
            onClick={message.onOpen}
            aria-label={message.openLabel}
            className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-blue-600 underline-offset-2 hover:underline dark:text-blue-300"
          >
            {message.openLabel ?? "Open"}
            <ArrowUpRight className="h-3 w-3" />
          </button>
        )}
        {message.answer && <AnswerCard answer={message.answer} />}
      </RecordLine>
    </li>
  );
}

/** Long content folded to a preview, with the toggle that unfolds it. */
function useFolded(message: ConversationMessage) {
  const [expanded, setExpanded] = useState(false);
  const long = Boolean(message.collapsible) && message.content.length > PREVIEW_CHARS;
  const shown =
    long && !expanded ? `${message.content.slice(0, PREVIEW_CHARS).trimEnd()}...` : message.content;
  const toggle = long ? (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        setExpanded((value) => !value);
      }}
      className="mt-1 text-[11.5px] font-medium text-blue-600 underline-offset-2 hover:underline dark:text-blue-300"
    >
      {expanded ? "Show less" : "Show full input"}
    </button>
  ) : null;
  return { shown, toggle };
}

/** What a person wrote: a bubble on the right, who and when under it. */
function UserMessage({ message }: { message: ConversationMessage }) {
  const { shown, toggle } = useFolded(message);
  return (
    <li className="flex flex-col items-end">
      <div className="max-w-[88%] rounded-2xl rounded-br-md bg-blue-600/[0.08] px-4 py-2.5 dark:bg-blue-400/[0.12]">
        <p className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-[color:var(--tp-ink)]">
          {shown}
        </p>
        {toggle}
        {message.footer && <div className="mt-1.5">{message.footer}</div>}
      </div>
      <p className="mt-1.5 flex flex-wrap items-center justify-end gap-x-1.5 text-[11px] text-[color:var(--tp-muted)]">
        {message.chip && (
          <span className="rounded-md border border-[color:var(--tp-line)] px-1.5 py-px text-[10px] font-medium text-[color:var(--tp-ink-2)]">
            {message.chip}
          </span>
        )}
        <span>{message.author}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{formatWhen(message.at)}</span>
      </p>
      {message.onOpen && <OpenCard message={message} />}
    </li>
  );
}

/** What an agent did: the step, its prose, and what it produced or asks. */
function AgentMessage({ message }: { message: ConversationMessage }) {
  const { shown, toggle } = useFolded(message);
  return (
    <li>
      <p className="flex items-center gap-2 text-[12.5px] text-[color:var(--tp-muted)]">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)]">
          <Sparkles className="h-3.5 w-3.5 text-blue-500 dark:text-blue-300" />
        </span>
        <span className="shrink-0 font-medium text-[color:var(--tp-ink-2)]">{message.author}</span>
        {message.chip && (
          <span
            title={message.chip}
            className="min-w-0 truncate rounded-md border border-[color:var(--tp-line)] px-1.5 py-px text-[10.5px] font-medium text-[color:var(--tp-ink-2)]"
          >
            {message.chip}
          </span>
        )}
        <span className="ml-auto shrink-0 tabular-nums">{formatWhen(message.at)}</span>
      </p>
      <p className="mt-2 whitespace-pre-wrap break-words text-[14px] leading-7 text-[color:var(--tp-ink)]">
        {shown}
      </p>
      {toggle}
      {message.footer && <div className="mt-1.5">{message.footer}</div>}
      {message.onOpen && <OpenCard message={message} />}
      {message.answer && <AnswerCard answer={message.answer} />}
    </li>
  );
}

/** A stage an agent produced, as something to open beside the conversation. */
function OpenCard({ message }: { message: ConversationMessage }) {
  const name = message.chip ?? message.openLabel?.replace(/^Open\s+/, "") ?? "Open";
  return (
    <button
      type="button"
      onClick={message.onOpen}
      aria-label={message.openLabel ?? `Open ${name}`}
      title={message.openLabel}
      className="mt-3 flex w-full items-center gap-3 rounded-xl border border-[color:var(--tp-line)] bg-[color:var(--tp-surface-2)] px-3.5 py-2.5 text-left transition-colors hover:border-blue-500/40"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)]">
        <PanelTop className="h-4 w-4 text-blue-500 dark:text-blue-300" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-[color:var(--tp-ink)]">{name}</span>
        <span className="block text-[11.5px] text-[color:var(--tp-muted)]">Stage output</span>
      </span>
      <span className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[color:var(--tp-line-strong)] bg-[color:var(--tp-surface)] px-2.5 py-1 text-[12px] font-medium text-[color:var(--tp-ink-2)]">
        Open
        <ArrowUpRight className="h-3.5 w-3.5" />
      </span>
    </button>
  );
}

/** A question waiting on a person: the reply box sits with the question. */
function AnswerCard({ answer }: { answer: NonNullable<ConversationMessage["answer"]> }) {
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const send = async () => {
    const text = reply.trim();
    if (!text || answer.pending || sending) return;
    setSending(true);
    try {
      await answer.onSubmit(text);
      setReply((current) => (current.trim() === text ? "" : current));
    } catch {
      // Reported where it failed; the answer stays to be sent again.
    } finally {
      setSending(false);
    }
  };
  return (
    <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.05] p-3">
      <p className="text-[11.5px] font-medium text-amber-700 dark:text-amber-300">Waiting for your answer</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            void send();
          }}
          placeholder={answer.placeholder}
          className="min-w-0 flex-1 rounded-lg border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)] px-3 py-1.5 text-[13px] text-[color:var(--tp-ink)] outline-none placeholder:text-[color:var(--tp-muted)] focus:border-blue-500/50"
        />
        <Button
          size="sm"
          variant="primary"
          disabled={!reply.trim() || answer.pending}
          busy={sending}
          onClick={() => void send()}
        >
          Answer
        </Button>
      </div>
    </div>
  );
}

/** What the platform recorded: a quiet line, with who and when under it. */
function RecordLine({
  message,
  children,
}: {
  message: ConversationMessage;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)] text-[color:var(--tp-muted)]">
        <CircleDot className="h-3 w-3" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-[color:var(--tp-ink-2)]">
          {message.content}
        </p>
        <p className="mt-0.5 text-[11px] text-[color:var(--tp-muted)]">
          {message.author} · <span className="tabular-nums">{formatWhen(message.at)}</span>
        </p>
        {children}
      </div>
    </div>
  );
}

/** A run of records, folded into one line that opens to all of them. */
function EventGroup({ events }: { events: ConversationMessage[] }) {
  const [open, setOpen] = useState(false);
  const latest = events[events.length - 1];
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 text-left text-[12.5px] text-[color:var(--tp-muted)] transition-colors hover:text-[color:var(--tp-ink-2)]"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)]">
          <ListChecks className="h-3 w-3" />
        </span>
        <span className="shrink-0 font-medium text-[color:var(--tp-ink-2)]">
          {events.length} recorded events
        </span>
        <span className="min-w-0 flex-1 truncate">· latest: {latest.content}</span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <ol className="mt-3 space-y-3 border-l border-[color:var(--tp-line)] pl-4">
          {events.map((event) => (
            <li key={event.id}>
              <RecordLine message={event} />
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

/* --------------------------------------------------------------- composer */

function Composer({
  composer,
  boxRef,
}: {
  composer: ConversationComposer;
  boxRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const blocked = Boolean(composer.unavailable);

  // The box empties only when the send is accepted, and only of what was sent:
  // a refusal keeps the text to send again, and anything typed while the send
  // was on its way stays.
  const send = async () => {
    const trimmed = text.trim();
    if (!trimmed || composer.pending || sending || blocked) return;
    setSending(true);
    try {
      await composer.onSubmit(trimmed);
      setText((current) => (current.trim() === trimmed ? "" : current));
    } catch {
      // Reported where it failed; the text stays.
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="shrink-0 px-4 pb-4 pt-2">
      <div className="rounded-2xl border border-[color:var(--tp-line-strong)] bg-[color:var(--tp-surface)] shadow-sm transition-colors focus-within:border-blue-500/50">
        <textarea
          ref={boxRef}
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={composer.placeholder}
          // Named, not only hinted: a placeholder is gone once anything is typed.
          aria-label="Message for this phase"
          className="w-full resize-none bg-transparent px-4 pb-1 pt-3 text-[14px] leading-relaxed text-[color:var(--tp-ink)] outline-none placeholder:text-[color:var(--tp-muted)]"
        />
        <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
          <p className="tp-den min-w-0 flex-1 truncate" title={composer.unavailable ?? composer.helper}>
            {composer.unavailable ?? composer.helper}
          </p>
          <button
            type="button"
            onClick={() => void send()}
            disabled={!text.trim() || composer.pending || sending || blocked}
            aria-label="Send"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white transition-colors hover:bg-blue-500 disabled:opacity-40"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
      </div>
      {composer.runsOn && (
        // Its own line rather than beside the helper, which the column already
        // truncates.
        <RunsOnLine runsOn={composer.runsOn} className="tp-den mt-1.5 px-1" />
      )}
    </div>
  );
}

/* ----------------------------------------------------------- the wrappers */

/**
 * The panel as a column beside the work, and as a sheet on a phone.
 *
 * One component so the two never drift: the same transcript, the same composer,
 * the same collapse preference.
 */
export function ConversationDock({
  open,
  sheetOpen,
  onSheetOpenChange,
  children,
}: {
  open: boolean;
  /**
   * The phone sheet's own state, never the desk preference. Rendering the sheet
   * off `open` meant a remembered desktop preference covered the whole screen
   * on first paint at phone width.
   */
  sheetOpen: boolean;
  onSheetOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <>
      {/* Desk width: a real column, sticky so the transcript stays put while the
          artifact scrolls. */}
      <aside
        aria-label="Conversation"
        className={cn(
          // h-full: a child of the fixed height row, so it fills it rather than
          // growing with the transcript.
          "hidden h-full shrink-0 border-r border-[color:var(--tp-line)] bg-[color:var(--tp-surface)] lg:block",
          open ? "w-[360px] xl:w-[400px]" : "w-0 overflow-hidden border-r-0",
        )}
      >
        {/* h-full: the row above fixed the height, so the panel is exactly the
            visible region and the transcript inside it is the only thing that
            scrolls. This replaced a sticky column sized against 100dvh, which
            was taller than its scrollport and started below the fold. */}
        {open && <div className="h-full overflow-hidden">{children}</div>}
      </aside>

      {/* Phone: a full height sheet over the work, because 360px of chat beside
          a stage leaves room for neither. */}
      {sheetOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close the conversation"
            onClick={() => onSheetOpenChange(false)}
            className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px]"
          />
          <div className="absolute inset-x-0 bottom-0 top-16 overflow-hidden rounded-t-2xl border border-[color:var(--tp-line)] bg-[color:var(--tp-surface)]">
            {children}
          </div>
        </div>
      )}
    </>
  );
}

/** The way back in once the panel is closed. */
export function ConversationToggle({
  onOpen,
  unread = 0,
}: {
  onOpen: () => void;
  /**
   * Open questions, which is the only thing worth a badge here. Left out where
   * the conversation holds none: Testing counted its open findings here, which
   * are not in the conversation at all.
   */
  unread?: number;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex items-center gap-2 rounded-xl border px-3 py-2 text-[12.5px] font-medium transition-colors",
        unread > 0
          ? "border-amber-500/40 bg-amber-500/[0.08] text-amber-700 dark:text-amber-300"
          : "border-[color:var(--tp-line-strong)] text-[color:var(--tp-ink-2)] hover:border-blue-500/50 hover:text-blue-600",
      )}
    >
      <MessageSquare className="h-3.5 w-3.5" />
      Conversation
      {unread > 0 && (
        <span className="rounded-full bg-amber-500 px-1.5 text-[10px] font-bold leading-4 text-white">
          {unread}
        </span>
      )}
    </button>
  );
}
