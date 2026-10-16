import type { ReactNode } from "react";
import { Bug, CheckCircle2, CircleHelp, Clock, Inbox, Wrench, XCircle } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Card, CardContent } from "@/shared/ui/primitives";
import { Note, Panel, StateChip, TriageChip } from "../../bits/index";
import type { TestingView, ViewFailure } from "../../../model/view";
import type { InboxFilter } from "./inboxFilter";

const filterCards: {
  id: Exclude<InboxFilter, "attention" | "all">;
  label: string;
  icon: typeof Bug;
  color: string;
  key: keyof TestingView["inbox"];
}[] = [
  { id: "regression", label: "Real regressions", icon: XCircle, color: "text-red-400", key: "regressions" },
  { id: "unclassified", label: "Not classified", icon: CircleHelp, color: "text-slate-400", key: "unclassified" },
  { id: "brittle", label: "Brittle tests", icon: Wrench, color: "text-amber-400", key: "brittle" },
  { id: "healed", label: "Healed", icon: CheckCircle2, color: "text-emerald-400", key: "healed" },
  { id: "awaiting", label: "Awaiting you", icon: Clock, color: "text-blue-400", key: "awaiting" },
];

export function HealingInbox({
  view,
  filter,
  onFilter,
  list,
  selectedId,
  onSelect,
  showDetail,
  onShowDetail,
  children,
}: {
  view: TestingView;
  filter: InboxFilter;
  onFilter: (f: InboxFilter) => void;
  list: ViewFailure[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  showDetail: boolean;
  onShowDetail: (show: boolean) => void;
  children?: ReactNode;
}) {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {filterCards.map((card) => {
          const Icon = card.icon;
          const count = view.inbox[card.key];
          const active = filter === card.id;
          return (
            <button
              key={card.id}
              type="button"
              aria-pressed={active}
              onClick={() => {
                onShowDetail(false);
                onFilter(active ? "attention" : card.id);
              }}
              className="text-left"
            >
              <Card className={cn("h-full", active ? "border-blue-500/40 bg-blue-500/5" : "hover:border-blue-500/30")}>
                <CardContent className="flex items-center gap-3 p-4">
                  <Icon className={cn("h-7 w-7 shrink-0", card.color)} />
                  <div className="min-w-0">
                    <p className="tp-num text-2xl">{count}</p>
                    <p className="tp-label mt-0.5 truncate">{card.label}</p>
                  </div>
                </CardContent>
              </Card>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Panel
          className={cn(showDetail && "hidden lg:block")}
          icon={<Inbox className="h-4 w-4 text-blue-400" />}
          label="Failure inbox"
          title={
            filter === "attention"
              ? `${list.length} to look at`
              : filter === "all"
              ? `${list.length} in this run`
              : `${list.length} ${filterCards.find((c) => c.id === filter)?.label.toLowerCase() ?? ""}`
          }
          meta="This list is the approval queue. Repairs are approved here and nowhere else."
          action={
            <button
              type="button"
              onClick={() => onFilter(filter === "all" ? "attention" : "all")}
              className="text-xs text-blue-600 underline underline-offset-2 dark:text-blue-400"
            >
              {filter === "all" ? "Needs attention" : "Show all"}
            </button>
          }
          bodyClassName="max-h-[620px] space-y-2 overflow-y-auto p-3"
        >
          {list.length === 0 && <Note className="px-1 py-4">Nothing here. Try another filter.</Note>}
          {list.map((failure) => {
            const active = failure.id === selectedId;
            return (
              <button
                key={failure.id}
                type="button"
                onClick={() => {
                  onSelect(failure.id);
                  onShowDetail(true);
                }}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-colors",
                  active
                    ? "border-blue-500/40 bg-blue-500/5"
                    : "border-slate-200 hover:border-slate-300 dark:border-white/[0.06] dark:hover:border-white/15"
                )}
              >
                {/* The reference first: two failures of one story differ only
                    there, and the story's sentence, cut to fit, was the same
                    for both. Then what the runner said, where every first-run
                    row repeated that there was nothing to compare with. */}
                {failure.label?.ref ? (
                  <p className="truncate text-xs">
                    <span className="font-mono font-semibold">{failure.label.ref}</span>
                    {failure.label.story && <span className="tp-den"> {failure.label.story}</span>}
                  </p>
                ) : (
                  <p className="truncate font-mono text-xs font-medium">{failure.test}</p>
                )}
                <p className="tp-prose mt-1 line-clamp-2 break-words text-xs">
                  {failure.message || failure.reason}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <TriageChip failure={failure} />
                  <StateChip failure={failure} />
                  <span className="tp-den ml-auto shrink-0">{failure.age}</span>
                </div>
              </button>
            );
          })}
        </Panel>

        {children}
      </div>
    </>
  );
}
