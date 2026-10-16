import { useEffect, useState } from "react";
import type { TestingView } from "../../model/view";
import { HealingDetail } from "./healing/HealingDetail";
import { HealingInbox } from "./healing/HealingInbox";
import { matchesInboxFilter, type InboxFilter } from "./healing/inboxFilter";

export type { InboxFilter };

export function StepHealing({
  view,
  filter,
  onFilter,
  selectedId,
  onSelect,
  onApprove,
  onReject,
  onDecideTest,
  onOpenFile,
  onOpenCode,
}: {
  view: TestingView;
  filter: InboxFilter;
  onFilter: (f: InboxFilter) => void;
  selectedId: string;
  onSelect: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onDecideTest: (
    id: string,
    decision: "quarantined" | "restored" | "rewrite",
    note?: string,
  ) => Promise<unknown>;
  onOpenFile: (path: string, line: number, label: string) => void;
  onOpenCode: () => void;
}) {
  const list = view.failures.filter((f) => matchesInboxFilter(f, filter, view.build));
  const selected = view.failures.find((f) => f.id === selectedId) ?? list[0];
  // Below lg there is only room for one pane, so tapping a failure drills in
  // and a back control returns to the list. From lg up both are always visible.
  const [showDetail, setShowDetail] = useState(false);

  // Keep whatever is selected as long as it still exists, so deciding on a
  // repair leaves its outcome on screen instead of jumping to the next item.
  useEffect(() => {
    if (list.length === 0) return;
    if (!view.failures.some((f) => f.id === selectedId)) onSelect(list[0].id);
  }, [list, selectedId, onSelect, view.failures]);

  return (
    <div className="space-y-4">
      <HealingInbox
        view={view}
        filter={filter}
        onFilter={onFilter}
        list={list}
        selectedId={selected?.id}
        onSelect={onSelect}
        showDetail={showDetail}
        onShowDetail={setShowDetail}
      >
        {selected && (
          <HealingDetail
            failure={selected}
            showDetail={showDetail}
            onBack={() => setShowDetail(false)}
            onApprove={onApprove}
            onReject={onReject}
            onDecideTest={onDecideTest}
            onOpenFile={onOpenFile}
            onOpenCode={onOpenCode}
          />
        )}
      </HealingInbox>
    </div>
  );
}
