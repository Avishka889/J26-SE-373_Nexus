import { describe, expect, it } from "vitest";
import { BYTE_LIMIT, CHAR_LIMIT, formatOf, megabytes, normalise, truncate } from "./extract";
import { extractDocument } from "./api";

describe("normalise", () => {
  it("matches the server on the shared vector", () => {
    // The same pair is asserted in orchestrator/tests/test_documents.py. Two
    // implementations exist because the browser reads text files itself; this is
    // what stops them drifting.
    expect(normalise("Requirement one.  \r\n\r\n\r\n\r\nRequirement two.\t\n")).toBe(
      "Requirement one.\n\nRequirement two.",
    );
  });

  it("collapses runs of blank lines and drops trailing spaces", () => {
    expect(normalise("a  \n\n\n\n b \r\n c \n\n")).toBe("a\n\n b\n c");
  });
});

describe("truncate", () => {
  it("reports the full length rather than hiding it", () => {
    const long = "x".repeat(CHAR_LIMIT + 500);
    const result = truncate(long);
    expect(result.truncated).toBe(true);
    expect(result.text).toHaveLength(CHAR_LIMIT);
    expect(result.charsAvailable).toBe(CHAR_LIMIT + 500);
  });

  it("leaves a short document alone", () => {
    const result = truncate("short");
    expect(result.truncated).toBe(false);
    expect(result.text).toBe("short");
    expect(result.charsAvailable).toBe(5);
  });

  // The same vector is asserted in orchestrator/tests/test_documents.py. The
  // ASCII cases above pinned the two implementations on the one input class
  // that cannot diverge; astral characters are the class that did. One leading
  // "a" puts every emoji on an odd code unit boundary, so a cut counted in code
  // units lands between the halves of one.
  const EMOJI = "\u{1F600}";
  const ASTRAL_VECTOR = "a" + EMOJI.repeat(CHAR_LIMIT);

  it("counts astral characters as one character each, as the server does", () => {
    // The browser counted UTF-16 code units and the server counts code points,
    // so this document was 80,001 characters in the chip and 40,001 on the
    // wire: "40,000 characters" meant one thing for a .md and another for a
    // .pdf, which is the number a reader is asked to trust.
    const result = truncate(ASTRAL_VECTOR);
    expect(result.charsAvailable).toBe(CHAR_LIMIT + 1);
    expect(result.chars).toBe(CHAR_LIMIT);
    expect(result.truncated).toBe(true);
  });

  it("never cuts a character in half", () => {
    const result = truncate(ASTRAL_VECTOR);
    // A cut between the two halves of a surrogate pair leaves a lone surrogate.
    // JSON.stringify escapes it into valid JSON, Python's json.loads decodes it
    // straight back, and encoding it for Postgres raises "surrogates not
    // allowed": the PATCH 500s with no reader facing reason, the run never
    // starts, and the project keeps empty requirement text.
    expect(result.text.endsWith(EMOJI)).toBe(true);
    // encodeURIComponent throws URIError on a lone surrogate. isWellFormed()
    // says the same thing more directly and is not in this project's ES2020 lib.
    expect(() => encodeURIComponent(result.text)).not.toThrow();
  });
});

describe("formatOf", () => {
  it("reads the extension", () => {
    expect(formatOf("SRS-v2.PDF")).toBe("pdf");
    expect(formatOf("brief.md")).toBe("md");
  });

  it("names what is supported when it cannot", () => {
    expect(() => formatOf("data.xlsx")).toThrow(/Cannot read \.xlsx files/);
    expect(() => formatOf("README")).toThrow(/no extension/);
  });
});

describe("megabytes", () => {
  it("keeps a whole megabyte whole and shows a tenth otherwise", () => {
    expect(megabytes(24 * 1024 * 1024)).toBe("24 MB");
    expect(megabytes(Math.round(10.4 * 1024 * 1024))).toBe("10.4 MB");
  });

  it("cannot print a file as the size of a limit it exceeds", () => {
    // Rounding to the nearest whole megabyte refused everything from 10 to
    // 10.5 MB with "That file is 10 MB. The limit is 10 MB.", which is a
    // sentence that contradicts itself, in the band an oversize file most often
    // lands in.
    expect(megabytes(BYTE_LIMIT + 1)).not.toBe(megabytes(BYTE_LIMIT));
    expect(megabytes(Math.round(10.4 * 1024 * 1024))).not.toBe(megabytes(BYTE_LIMIT));
  });
});

describe("BYTE_LIMIT", () => {
  it("matches the server's byte limit", () => {
    // orchestrator/orchestrator/documents/extract.py defines the same constant,
    // BYTE_LIMIT = 10 * 1024 * 1024. Hardcoded here, the same way the shared
    // vector above pins normalise(), so this fails the moment the two drift apart.
    expect(BYTE_LIMIT).toBe(10 * 1024 * 1024);
  });
});

describe("the size guard", () => {
  it("refuses an oversize PDF before it is uploaded", async () => {
    const file = new File([new Uint8Array(24 * 1024 * 1024)], "huge.pdf", {
      type: "application/pdf",
    });

    // The message is what proves the ordering. With no backend the server path
    // refuses a PDF with "Reading PDF and DOCX needs the backend", so the size
    // refusal arriving instead means the size was checked before the file was
    // routed anywhere. With a backend the unguarded path uploaded all 24 MB and
    // then hit the sixty second timeout, which surfaced as "The server did not
    // respond": a file refusable at pick time, blamed on a server that was fine.
    await expect(extractDocument(file)).rejects.toThrow(
      "That file is 24 MB. The limit is 10 MB.",
    );
  });

  it("refuses an oversize text file before file.text() ever runs", async () => {
    const file = new File([new Uint8Array(24 * 1024 * 1024)], "huge.txt", {
      type: "text/plain",
    });
    // A stub, not a spy: if the guard did not run first, this would make the
    // rejection message "file.text() ran before the size guard" rather than
    // the expected refusal, so the assertion below fails for a visible reason
    // instead of the test merely recording that a mock was invoked.
    file.text = () => {
      throw new Error("file.text() ran before the size guard");
    };

    await expect(extractDocument(file)).rejects.toThrow(
      "That file is 24 MB. The limit is 10 MB.",
    );
  });
});
