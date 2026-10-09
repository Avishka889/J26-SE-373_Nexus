import type { Attachment, DocumentFormat } from "@/types/document";
import { http } from "@/lib/http";
import { isLive } from "@/lib/env";
import { BYTE_LIMIT, LOCAL_FORMATS, countWords, formatOf, megabytes, normalise, truncate } from "./extract";

/**
 * Read one file into the text Component 1 will see.
 *
 * Text formats are read here rather than posted: it removes a round trip, it
 * works with no backend so the fixture demo and the browser suite keep working,
 * and decoding UTF-8 is not worth a network hop. PDF and DOCX need a parser, so
 * they go to the orchestrator.
 */
export async function extractDocument(file: File): Promise<Omit<Attachment, "id">> {
  // Ahead of the branch, so all four formats are refused the same way at pick
  // time. `file.size` is synchronous and equally available whichever path would
  // read the file, and this used to sit inside `readHere`, which covered the two
  // formats the browser reads and left the two it uploads unguarded: an 80 MB
  // PDF crossed the network in full, timed out after sixty seconds, and was
  // reported as "The server did not respond" for a file the client could have
  // refused with this sentence before sending a byte. Checked before the format
  // is read for the same reason the server checks it first: the two paths refuse
  // the same file with the same reason.
  if (file.size > BYTE_LIMIT) {
    throw new Error(`That file is ${megabytes(file.size)}. The limit is ${megabytes(BYTE_LIMIT)}.`);
  }
  const format = formatOf(file.name);
  return LOCAL_FORMATS.includes(format) ? readHere(file, format) : readOnServer(file);
}

async function readHere(file: File, format: DocumentFormat): Promise<Omit<Attachment, "id">> {
  const text = normalise(await file.text());
  if (!text) throw new Error("That file is empty.");
  const capped = truncate(text);
  return {
    name: file.name,
    format,
    bytes: file.size,
    // Both null because a text file has no pages, so it cannot have pages that
    // failed to read. Only a PDF can be partly a scan.
    pages: null,
    pagesWithoutText: null,
    words: countWords(capped.text),
    ...capped,
  };
}

async function readOnServer(file: File): Promise<Omit<Attachment, "id">> {
  if (!isLive("projects")) {
    throw new Error(
      "Reading PDF and DOCX needs the backend. Attach a TXT or MD file, or paste the text.",
    );
  }
  const form = new FormData();
  form.append("file", file);
  // A refusal arrives in the server's words (an oversize file names the limit),
  // and an unreachable server says so: `http` builds both messages.
  return http.post<Omit<Attachment, "id">>("/documents/extract", form, {
    timeoutMs: 60_000,
  });
}
