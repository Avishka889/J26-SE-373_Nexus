import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * A modal dialog's focus, the way a keyboard and a screen reader expect it.
 *
 * Focus moves into the dialog when it opens (to the element marked
 * `data-autofocus`, else the first control); Tab and Shift+Tab wrap inside it
 * rather than walking out into the page behind; Escape closes it; and when it
 * closes, focus goes back to whatever opened it. The dialogs neither trapped
 * nor returned focus, so a keyboard user tabbed into the page under the
 * backdrop and, on closing, started again from the top of the document.
 *
 * A marker rather than React's `autoFocus`: that focuses during the commit,
 * before this effect runs, so the opener it records would be the dialog's own
 * field, and focus could not go back to what opened it.
 */
export function useDialogFocus(
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
  open = true,
): void {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) {
      const first =
        node.querySelector<HTMLElement>("[data-autofocus]") ??
        node.querySelector<HTMLElement>(FOCUSABLE) ??
        node;
      first.focus();
    }

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const at = document.activeElement;
      if (event.shiftKey && (at === first || !node.contains(at))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (at === last || !node.contains(at))) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, [open, ref]);
}
