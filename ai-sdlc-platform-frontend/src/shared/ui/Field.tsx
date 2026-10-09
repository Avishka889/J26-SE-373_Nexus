import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ReactNode,
} from "react";
import { useIsDark } from "@/shared/theme";
import { cn } from "@/shared/utils/cn";
import { InfoTip } from "./InfoTip";

/** What a field's control takes so its label names it and its hint describes it. */
export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
}

const CONTROLS = new Set(["input", "select", "textarea"]);

/**
 * A labelled field, its hint behind an info icon beside the label.
 *
 * The hint used to sit under the control, inside the `<label>` that wrapped
 * it, which also made it part of the field's name. Beside the label it is a
 * button, and a button inside a `<label>` breaks the label: a label with no
 * `for` names its first labelable descendant, and a button is one, so it would
 * name the icon instead of the field. So the label stands beside the control
 * and points at it (`htmlFor`, with ids from `useId`, unique without anybody
 * keeping them so), and the hint is the control's description.
 *
 * The control is found three ways: a single `input`, `select` or `textarea`
 * child is given the ids; a child that wraps its control (an icon beside an
 * input) is a function that spreads them onto it; anything else is shown
 * content, not a control, and the label is its caption.
 */
export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode | ((control: FieldControlProps) => ReactNode);
  className?: string;
}) {
  const isDark = useIsDark();
  const controlId = useId();
  const hintId = useId();
  const captionId = useId();
  const described = hint ? hintId : undefined;

  let labelled: string | null = null;
  let body: ReactNode;
  if (typeof children === "function") {
    labelled = controlId;
    body = children({ id: controlId, "aria-describedby": described });
  } else if (
    isValidElement(children) &&
    typeof children.type === "string" &&
    CONTROLS.has(children.type)
  ) {
    const own = children.props as { id?: string; "aria-describedby"?: string };
    labelled = own.id ?? controlId;
    body = cloneElement(children as ReactElement<FieldControlProps>, {
      id: labelled,
      "aria-describedby":
        [own["aria-describedby"], described].filter(Boolean).join(" ") ||
        undefined,
    });
  } else {
    body = children;
  }

  const title = cn(
    "text-sm font-medium",
    isDark ? "text-slate-200" : "text-slate-700",
  );
  return (
    <div
      className={cn("block", className)}
      {...(labelled
        ? {}
        : {
            role: "group",
            "aria-labelledby": captionId,
            "aria-describedby": described,
          })}
    >
      <div className="mb-1.5 flex items-center gap-1.5">
        {labelled ? (
          <label htmlFor={labelled} className={title}>
            {label}
          </label>
        ) : (
          <span id={captionId} className={title}>
            {label}
          </span>
        )}
        {hint && <InfoTip id={hintId} text={hint} label={`About ${label}`} />}
      </div>
      {body}
    </div>
  );
}
