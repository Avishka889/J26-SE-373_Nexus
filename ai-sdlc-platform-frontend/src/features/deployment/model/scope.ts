/** "express, zod" as the packages it names, each once. */
export function packagesIn(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((one) => one.trim()).filter(Boolean))];
}
