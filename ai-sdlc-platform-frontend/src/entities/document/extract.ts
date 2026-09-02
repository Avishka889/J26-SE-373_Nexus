import type { DocumentFormat } from "@/types/document";

/**
 * Where a document stops being read.
 *
 * MAX_BUDGET in the requirements rule layer caps the result at thirty
 * requirements however much text arrives, and the whole string goes into the
 * prompt, so a forty page SRS costs about twenty thousand tokens per attempt and
 * buys nothing.
 *
 * The same constant, the same normalisation and the same cap exist in
 * orchestrator/orchestrator/documents/extract.py, because the browser reads text
 * files itself and the server reads the binary formats. A shared test vector
 * pins them together. Change one, change both.
 *
 * A character here is a code point, which is what Python's `len()` counts and
 * what a reader means by "character": one emoji is one. `String.length` counts
 * UTF-16 code units instead, so measuring with it made the same document
 * 80,001 characters on the chip and 40,001 on the wire, and made "40,000
 * characters" mean one thing for a .md read here and another for a .pdf read
 * there. `characterCount()` below is what keeps the two saying the same thing.
 */
export const CHAR_LIMIT = 40_000;

/**
 * The same ten megabytes the server enforces, in `BYTE_LIMIT` in
 * orchestrator/orchestrator/documents/extract.py, before its own PDF and DOCX
 * parsers ever see the bytes.
 *
 * Checked against `file.size` in `extractDocument`, ahead of the branch that
 * picks a read path, so it covers all four formats. Both paths need it and
 * neither can apply it later: `file.text()` in `readHere` decodes the entire
 * file into one string with no partial or streaming mode, so nothing after it,
 * `CHAR_LIMIT`'s own truncation included, can bound what reading it costs; and
 * an upload in `readOnServer` has already crossed the network by the time the
 * server refuses it.
 *
 * The two constants are deliberately the same number: a file this size is
 * accepted or refused identically whichever of the four formats it is and
 * whichever path reads it.
 */
export const BYTE_LIMIT = 10 * 1024 * 1024;

/**
 * "24 MB", "10.4 MB", matching the server's own `_megabytes()` exactly, so the
 * two paths produce the same sentence for the same file.
 *
 * Rounded up to a tenth rather than to the nearest whole megabyte. Rounding to
 * the nearest printed everything from 10 to 10.5 MB as "10 MB", so an oversize
 * file was refused with "That file is 10 MB. The limit is 10 MB.", a sentence
 * that contradicts itself, and that band is where an oversize file most often
 * lands. Rounding up cannot understate, so a file can never print as the size
 * of a limit it exceeds. Whole megabytes keep their whole number.
 */
export function megabytes(bytes: number): string {
  const tenths = Math.ceil((bytes / (1024 * 1024)) * 10);
  return tenths % 10 === 0 ? `${tenths / 10} MB` : `${(tenths / 10).toFixed(1)} MB`;
}

const SUPPORTED: readonly DocumentFormat[] = ["pdf", "docx", "txt", "md"];

/** Formats the browser can read without a backend. */
export const LOCAL_FORMATS: readonly DocumentFormat[] = ["txt", "md"];

export function normalise(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * How many UTF-16 code units the character at `index` occupies: two when it is
 * an astral character stored as a surrogate pair, one otherwise.
 *
 * `charCodeAt` past the end of the string is NaN and every comparison against
 * it is false, so a high surrogate with nothing after it counts as one, which
 * is also how Python counts a lone surrogate.
 */
function stepAt(text: string, index: number): number {
  const unit = text.charCodeAt(index);
  if (unit < 0xd800 || unit > 0xdbff) return 1;
  const next = text.charCodeAt(index + 1);
  return next >= 0xdc00 && next <= 0xdfff ? 2 : 1;
}

/**
 * Characters, meaning code points, the way `len()` counts them on the server.
 *
 * `[...text].length` says this in one line and allocates one string per
 * character to say it, on text of up to BYTE_LIMIT bytes, so this walks the
 * string instead and allocates nothing.
 */
function characterCount(text: string): number {
  let count = 0;
  for (let index = 0; index < text.length; index += stepAt(text, index)) count += 1;
  return count;
}

/** The code unit index just past the `limit`th character. */
function cutAt(text: string, limit: number): number {
  let index = 0;
  for (let counted = 0; counted < limit; counted += 1) index += stepAt(text, index);
  return index;
}

export function truncate(text: string): {
  text: string;
  chars: number;
  charsAvailable: number;
  truncated: boolean;
} {
  const charsAvailable = characterCount(text);
  if (charsAvailable <= CHAR_LIMIT) {
    return { text, chars: charsAvailable, charsAvailable, truncated: false };
  }
  // Cut on a character boundary, never inside one. `text.slice(0, CHAR_LIMIT)`
  // counted code units, so a document of ASCII plus emoji ended on a lone high
  // surrogate: JSON.stringify escapes it into valid JSON, Python's json.loads
  // decodes it straight back, and encoding it for Postgres raises "surrogates
  // not allowed". The PATCH then returned a 500 with no reader facing reason,
  // the run never started, and the project was left with empty requirement
  // text, while the chip had said "first 40,000 of 45,002 characters read".
  return {
    text: text.slice(0, cutAt(text, CHAR_LIMIT)),
    chars: CHAR_LIMIT,
    charsAvailable,
    truncated: true,
  };
}

export function countWords(text: string): number {
  return (text.match(/\S+/g) ?? []).length;
}

export function formatOf(name: string): DocumentFormat {
  const dot = name.lastIndexOf(".");
  if (dot <= 0) {
    throw new Error("That file has no extension. Attach a PDF, DOCX, TXT or MD file.");
  }
  const claimed = name.slice(dot + 1).toLowerCase() as DocumentFormat;
  if (!SUPPORTED.includes(claimed)) {
    throw new Error(`Cannot read .${claimed} files. Attach a PDF, DOCX, TXT or MD file.`);
  }
  return claimed;
}
