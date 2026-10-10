import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import type { DomainModel } from "../../model/domain";

/**
 * A projection of the architecture graph, not a second copy of it.
 *
 * Four columns rather than four stacked sections, so the whole shape of the
 * domain is one screenful: how many people, how much it stores, what happens and
 * what it has to obey, all comparable at a glance. Stacked, the actions and the
 * rules were below the fold, and a project with no external systems left an empty
 * half-width card sitting in the middle of the page.
 *
 * What did not change is what each column says. An action reads "Pharmacist
 * records Dispense" rather than "record", because the sentence is the thing the
 * projection exists to produce and a bare verb cannot contradict or agree with
 * the diagram. Actors keep the distinction between a person and another system,
 * which a rule enforces and which decides whether a journey is drawn for them.
 * And every item keeps its trace chips: traceability on every element is the
 * claim this phase makes, so it is not something to reveal on hover.
 */

/** Literal classes, never interpolated, so Tailwind can see them. */
const DOT: Record<"actors" | "entities" | "actions" | "rules", string> = {
  actors: "bg-emerald-500",
  entities: "bg-blue-500",
  actions: "bg-violet-500",
  rules: "bg-amber-500",
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function ColumnDot({ kind }: { kind: keyof typeof DOT }) {
  return <span className={cn("h-2 w-2 rounded-full", DOT[kind])} aria-hidden />;
}

/**
 * What a column says when it holds nothing.
 *
 * Named rather than blank. An empty column is a fact about the design, and on a
 * small brief it is often the correct one: a calculator has no external systems
 * and no compliance rules, and saying so reads better than a gap.
 */
function Empty({ children }: { children: string }) {
  return <Note>{children}</Note>;
}

export function StageDomainModel({
  domain,
  onJump,
}: {
  domain: DomainModel;
  onJump: (requirementId: string) => void;
}) {
  const actors = [
    ...domain.primaryActors.map((a) => ({ ...a, external: false })),
    ...domain.externalSystems.map((a) => ({ ...a, external: true })),
  ];

  return (
    <StageSection
      id="domain-columns"
      // Fits itself to the space it actually has, rather than to the window.
      // Viewport breakpoints were wrong here: with the conversation open the
      // content area is about half the screen, and `xl:grid-cols-4` still fired,
      // giving four columns so narrow that "Payment Provider settles Order" wrapped
      // onto three lines. auto-fit drops to two columns or one on its own.
      className="grid gap-5 grid-cols-[repeat(auto-fit,minmax(15rem,1fr))]"
    >
      <Panel
        icon={<ColumnDot kind="actors" />}
        label="Actors"
        title="People, and the systems this one talks to"
        meta={plural(actors.length, "actor")}
      >
        {actors.length === 0 ? (
          <Empty>Nothing in the requirements names anyone using this system.</Empty>
        ) : (
          <ul className="space-y-2">
            {actors.map((actor) => (
              <li
                key={actor.id}
                className="rounded-xl border border-[color:var(--tp-line)] px-3 py-2.5"
              >
                <p className="flex flex-wrap items-start justify-between gap-2">
                  <span className="text-[13px] font-medium text-[color:var(--tp-ink)]">
                    {actor.name}
                  </span>
                  {/* The distinction a rule enforces, kept visible: only a person
                      gets a journey drawn for them later. */}
                  <Chip tone={actor.external ? "info" : "neutral"}>
                    {actor.external ? "system" : "person"}
                  </Chip>
                </p>
                {actor.description && (
                  <p className="tp-den mt-0.5 leading-relaxed">{actor.description}</p>
                )}
                <div className="mt-1.5">
                  <TraceChips traces={actor.traces} onJump={onJump} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        icon={<ColumnDot kind="entities" />}
        label="Entities"
        title="What the system keeps. Open one for its fields."
        meta={plural(domain.entities.length, "entity", "entities")}
      >
        {domain.entities.length === 0 ? (
          <Empty>This design stores nothing yet.</Empty>
        ) : (
          <ul className="space-y-2">
            {domain.entities.map((entity) => (
              <EntityRow key={entity.id} entity={entity} onJump={onJump} />
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        icon={<ColumnDot kind="actions" />}
        label="Actions"
        title="Who does what to what, read off the graph"
        meta={plural(domain.actions.length, "action")}
      >
        {domain.actions.length === 0 ? (
          <Empty>Nobody in this design does anything to anything yet.</Empty>
        ) : (
          <ul className="space-y-2">
            {domain.actions.map((action) => (
              <li
                key={action.id}
                className="rounded-xl border border-[color:var(--tp-line)] px-3 py-2.5"
              >
                <p className="text-[13px] leading-relaxed">
                  <span className="font-medium text-[color:var(--tp-ink)]">{action.actor}</span>{" "}
                  <span className="text-[color:var(--tp-ink-2)]">{action.verb}</span>{" "}
                  <span className="font-medium text-[color:var(--tp-ink)]">{action.entity}</span>
                </p>
                <div className="mt-1.5">
                  <TraceChips traces={action.traces} onJump={onJump} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        icon={<ColumnDot kind="rules" />}
        label="Rules"
        title="What the design has to obey"
        meta={plural(domain.constraints.length, "rule")}
      >
        {domain.constraints.length === 0 ? (
          <Empty>No standard or rule was named for this design.</Empty>
        ) : (
          <ul className="space-y-2">
            {domain.constraints.map((constraint) => (
              <li
                key={constraint.id}
                className="rounded-xl border border-[color:var(--tp-line)] px-3 py-2.5"
              >
                <p className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium text-[color:var(--tp-ink)]">
                    {constraint.name}
                  </span>
                  {constraint.standard && <Chip>{constraint.standard}</Chip>}
                </p>
                {constraint.description && (
                  <p className="tp-den mt-0.5 leading-relaxed">{constraint.description}</p>
                )}
                {constraint.appliesTo.length > 0 && (
                  <p className="tp-den mt-1">Applies to {constraint.appliesTo.join(", ")}</p>
                )}
                <div className="mt-1.5">
                  <TraceChips traces={constraint.traces} onJump={onJump} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </StageSection>
  );
}

function EntityRow({
  entity,
  onJump,
}: {
  entity: DomainModel["entities"][number];
  onJump: (requirementId: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <li className="rounded-xl border border-[color:var(--tp-line)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-2 px-3 py-2.5 text-left"
      >
        <span className="min-w-0">
          <span className="block text-[13px] font-medium text-[color:var(--tp-ink)]">
            {entity.name}
          </span>
          <span className="tp-den mt-0.5 block">
            {entity.attributes.length} {entity.attributes.length === 1 ? "field" : "fields"}
          </span>
        </span>
        <ChevronDown
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0 text-[color:var(--tp-muted)] transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {!open && (
        <div className="px-3 pb-2.5">
          <TraceChips traces={entity.traces} onJump={onJump} />
        </div>
      )}

      {open && (
        <div className="border-t border-[color:var(--tp-line)] px-3 py-2.5">
          {entity.description && (
            <p className="tp-den mb-2 leading-relaxed">{entity.description}</p>
          )}
          <ul className="space-y-1">
            {entity.attributes.map((attribute) => (
              <li key={attribute.name} className="tp-mono text-[12px] text-[color:var(--tp-ink-2)]">
                {attribute.name}
                <span className="text-[color:var(--tp-muted)]"> : {attribute.type}</span>
              </li>
            ))}
          </ul>
          {/* Ownership is a relationship, and it belongs to the entity it is
              about rather than to a column of its own. */}
          {entity.ownedBy.length > 0 && (
            <Note className="mt-2">Read and written by {entity.ownedBy.join(", ")}.</Note>
          )}
          <div className="mt-2">
            <TraceChips traces={entity.traces} onJump={onJump} />
          </div>
        </div>
      )}
    </li>
  );
}
