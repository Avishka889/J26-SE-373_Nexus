/**
 * Saving a rendered diagram.
 *
 * Mermaid renders to a real `<svg>` element in the document, which is what makes
 * this cheap: the vector is already there, so saving is a serialisation. Nothing
 * re-renders and no library is involved.
 *
 * SVG only, deliberately. A PNG export was written and removed: rasterising a
 * vector diagram makes it soft the moment anyone zooms, and offering the worse
 * format invites picking it. Everything a reader will paste a diagram into takes
 * SVG.
 */

/** Lowercase, hyphenated, and safe in a file manager. */
function slug(value: string, limit: number): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, limit) || ""
  );
}

/**
 * What a saved diagram is called.
 *
 * `shopflow-class-v2.svg`, so a folder of exports from several projects and
 * several revisions still says which is which. The title alone gave
 * `class-diagram.svg` every time, and the second download silently became
 * `class-diagram (1).svg`.
 *
 * The version is the requirements version the diagram was generated from, which
 * is the thing that makes two exports of the same diagram different.
 */
export function diagramFileName(
  project: string,
  kind: string,
  version: number,
  extension: "svg",
): string {
  const parts = [slug(project, 40), slug(kind, 24)].filter(Boolean);
  if (parts.length === 0) parts.push("diagram");
  // Version 0 means never generated, so there is nothing truthful to stamp.
  if (version > 0) parts.push(`v${version}`);
  return `${parts.join("-")}.${extension}`;
}

/**
 * The element's own size, which the serialised copy has to carry explicitly.
 *
 * On screen the SVG is sized by CSS (`max-width: 100%`), and CSS does not travel
 * with the file. Without width and height attributes the saved SVG opens at
 * whatever the viewer guesses, and the canvas that rasterises it draws nothing.
 */
export function measure(svg: SVGSVGElement): { width: number; height: number } {
  const box = svg.getBoundingClientRect();
  if (box.width > 0 && box.height > 0) {
    return { width: Math.ceil(box.width), height: Math.ceil(box.height) };
  }
  const viewBox = svg.getAttribute("viewBox")?.split(/[\s,]+/).map(Number);
  if (viewBox?.length === 4 && viewBox[2] > 0 && viewBox[3] > 0) {
    return { width: Math.ceil(viewBox[2]), height: Math.ceil(viewBox[3]) };
  }
  return { width: 1200, height: 800 };
}

/** A standalone copy: sized, namespaced, and carrying its own background. */
export function serialise(svg: SVGSVGElement, background: string): string {
  const { width, height } = measure(svg);
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  copy.setAttribute("width", String(width));
  copy.setAttribute("height", String(height));
  // The page's background is not part of the diagram, so a saved copy on a
  // reader's white document would otherwise show dark text on nothing.
  copy.style.background = background;
  return new XMLSerializer().serializeToString(copy);
}

/** Hand a blob to the browser as a download. */
export function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadSvg(svg: SVGSVGElement, filename: string, background: string): void {
  save(
    new Blob([serialise(svg, background)], { type: "image/svg+xml;charset=utf-8" }),
    filename,
  );
}
