/**
 * Times from the server, shown in the reader's own time zone.
 *
 * The server keeps every time in UTC. It sent them as "2026-10-03 09:12" with
 * the zone dropped, and the pages showed that string as it came, so a reader
 * in Colombo saw every time five and a half hours early. Times now arrive as
 * ISO 8601 with their zone and are shown through here, in one place, as the
 * reader's local "2026-10-03 14:42". Artefacts stored before the change still
 * carry the old shape, which was always UTC, so it is read as UTC.
 */

const LEGACY = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/;

// A date and a time with their zone, and nothing less: a bare date, or a time
// without a zone, is read by the browser as local time and would be wrong again.
const ZONED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

/** The moment a server time names, or null when the text names none. */
export function parseServerTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const legacy = LEGACY.exec(value);
  if (legacy) {
    const [, year, month, day, hour, minute] = legacy;
    return new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute));
  }
  if (!ZONED.test(value)) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * A server time as the reader's local "2026-10-03 14:42". Text that is not a
 * time ("still running", or a fixture's bare "09:12") is shown as it is.
 */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return "";
  const at = parseServerTime(value);
  if (!at) return value;
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ` +
    `${pad(at.getHours())}:${pad(at.getMinutes())}`
  );
}

/** Which of two server times is later, for ordering; an unreadable one counts as earliest. */
export function compareServerTimes(a: string | null | undefined, b: string | null | undefined): number {
  return (parseServerTime(a)?.getTime() ?? -Infinity) - (parseServerTime(b)?.getTime() ?? -Infinity) || 0;
}
