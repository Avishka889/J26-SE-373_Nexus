import { scrollMotion } from "@/shared/utils/motion";
import { useEffect, useState } from "react";

/**
 * Which of a page's sections the reader is currently looking at.
 *
 * The anchor pills double as a position indicator, so this has to answer "where
 * am I" rather than "what did I last click". It watches the sections themselves
 * and picks the topmost one currently on screen, which is what a reader would
 * say if asked.
 *
 * `topOffset` is how much of the viewport the sticky chrome covers: without it
 * the section behind the sticky bar counts as visible and the highlight sits one
 * section behind the reader.
 */
export function useScrollSpy(
  sectionIds: string[],
  topOffset = 140,
): string | null {
  const [activeId, setActiveId] = useState<string | null>(
    sectionIds[0] ?? null,
  );
  // The ids are a small fixed list per stage, so their joined form is a stable
  // and cheap dependency; passing the array itself would re-subscribe on every
  // render because a new array is a new value.
  const key = sectionIds.join("|");

  useEffect(() => {
    const ids = key ? key.split("|") : [];
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return;

    // Outside the callback on purpose. The observer reports only what changed,
    // so a section that came into view earlier and has not moved since is absent
    // from `entries`. Rebuilding this map per batch dropped it and the pill fell
    // back to whichever section happened to be reported.
    const visible = new Map<string, boolean>();

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          visible.set(entry.target.id, entry.isIntersecting);

        const onScreen = elements.filter((el) => visible.get(el.id));
        if (onScreen.length > 0) {
          // The section nearest the top of the band, not the first in DOM order.
          // A tall section still intersects long after the reader has scrolled
          // into the next one, so DOM order kept the previous pill lit: jumping
          // to Behaviour left Structure highlighted because the structural grid
          // above it was still clipping the band.
          const nearest = onScreen.reduce((best, el) =>
            Math.abs(el.getBoundingClientRect().top - topOffset) <
            Math.abs(best.getBoundingClientRect().top - topOffset)
              ? el
              : best,
          );
          setActiveId(nearest.id);
          return;
        }
        // Nothing on screen means the reader is past the last section, or before
        // the first. Falling back to the nearest one above keeps the pill lit.
        const above = elements.filter(
          (el) => el.getBoundingClientRect().top < topOffset,
        );
        setActiveId(
          above.length > 0 ? above[above.length - 1].id : elements[0].id,
        );
      },
      { rootMargin: `-${topOffset}px 0px -55% 0px`, threshold: 0 },
    );

    for (const element of elements) observer.observe(element);
    return () => observer.disconnect();
  }, [key, topOffset]);

  return activeId;
}

/**
 * Scroll a section into view under the sticky chrome, and flash it.
 *
 * The flash is the same ring the trace chips use, so a jump from an anchor, a
 * summary tile and a trace chip all land the same way and the reader learns one
 * behaviour rather than three.
 */
export function scrollToSection(id: string) {
  const element = document.getElementById(id);
  if (!element) return;

  // `scrollIntoView` rather than a computed window scroll: the app scrolls inside
  // its main element, not the window, so an absolute offset would target the
  // wrong scroller entirely. The gap under the sticky chrome comes from
  // `scroll-margin-top` in the stylesheet, which this respects.
  element.scrollIntoView({ behavior: scrollMotion(), block: "start" });

  element.classList.add("tp-flash");
  window.setTimeout(() => element.classList.remove("tp-flash"), 1600);
}
