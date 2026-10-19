// Input checks written the way the compiler used to accept them: a fallback
// that can never apply, because a comparison is never null or undefined, and a
// regular expression used as a condition, which is always truthy.

export function withinLimit(
  value: string | number,
  options: any,
  strictness: "strict" | "loose",
): boolean {
  if (strictness === "loose") {
    value = +value;
  }
  return value < options.max ?? 100;
}

export function looksHex(text: string): boolean {
  if (/0x[0-9a-f]/) {
    return text.startsWith("0x");
  }
  return false;
}
