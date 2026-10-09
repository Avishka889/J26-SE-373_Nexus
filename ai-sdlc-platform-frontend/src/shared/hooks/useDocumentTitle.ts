import { useEffect } from "react";

/** The product's name, after the page's own in every title. */
const PRODUCT = "Nexus";

/**
 * The browser tab's title, for the page that is open.
 *
 * Every page was titled "Nexus", so tabs, history and a screen reader's
 * announcement of a new page all said the same word whatever was open. A
 * phase reads "Testing & Security, Book Tracker | Nexus".
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `${title} | ${PRODUCT}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
