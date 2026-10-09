/**
 * The languages the viewer colours. Anything else is plain text: every other
 * file used to be read as TypeScript, so a generated workflow's comments had
 * "from" and "as" coloured as keywords and a Dockerfile was labelled TypeScript.
 * JSON keeps TypeScript's colouring, which fits its strings, numbers and
 * literals, under its own name.
 */
type Lang = "typescript" | "tsx" | "java" | "css" | "json" | "yaml" | "dockerfile" | "plaintext";

const themes = {
  dark: {
    keyword: "#569cd6",
    string: "#ce9178",
    comment: "#6a9955",
    type: "#4ec9b0",
    number: "#b5cea8",
    annotation: "#dcdcaa",
    function: "#dcdcaa",
    default: "#d4d4d4",
    punctuation: "#808080",
  },
  light: {
    keyword: "#0000ff",
    string: "#a31515",
    comment: "#008000",
    type: "#267f99",
    number: "#098658",
    annotation: "#795e26",
    function: "#795e26",
    default: "#24292e",
    punctuation: "#393a34",
  },
};

const tsKeywords = new Set([
  "import", "export", "from", "const", "let", "var", "function", "return", "if", "else",
  "async", "await", "interface", "type", "extends", "implements", "new", "class", "public",
  "private", "protected", "static", "void", "null", "undefined", "true", "false", "as",
]);

const javaKeywords = new Set([
  "import", "package", "public", "private", "protected", "class", "interface", "extends",
  "implements", "return", "if", "else", "new", "final", "static", "void", "null", "true",
  "false", "this", "throw", "throws", "enum", "var",
]);

function escapeHtml(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function span(color: string, text: string) {
  return `<span style="color:${color}">${escapeHtml(text)}</span>`;
}

function highlightTsLine(line: string, t: typeof themes.dark) {
  if (/^\s*\/\//.test(line) || /^\s*\/\*/.test(line)) {
    return span(t.comment, line);
  }

  let result = "";
  let i = 0;
  while (i < line.length) {
    const rest = line.slice(i);

    if (/^["'`]/.test(rest)) {
      const quote = rest[0];
      const end = rest.indexOf(quote, 1);
      const token = end === -1 ? rest : rest.slice(0, end + 1);
      result += span(t.string, token);
      i += token.length;
      continue;
    }

    const word = rest.match(/^[A-Za-z_$][\w$]*/);
    if (word) {
      const w = word[0];
      if (tsKeywords.has(w)) result += span(t.keyword, w);
      else if (/^[A-Z]/.test(w)) result += span(t.type, w);
      else if (rest[w.length] === "(") result += span(t.function, w);
      else result += span(t.default, w);
      i += w.length;
      continue;
    }

    if (/^\d+/.test(rest)) {
      const num = rest.match(/^\d+/)![0];
      result += span(t.number, num);
      i += num.length;
      continue;
    }

    result += span(t.punctuation, rest[0]);
    i += 1;
  }

  return result;
}

function highlightJavaLine(line: string, t: typeof themes.dark): string {
  if (/^\s*\/\//.test(line)) return span(t.comment, line);
  if (/^\s*@/.test(line)) {
    const match = line.match(/^(\s*@\w+)/);
    if (match) {
      return span(t.annotation, match[1]) + highlightJavaLine(line.slice(match[1].length), t);
    }
  }

  let result = "";
  let i = 0;
  while (i < line.length) {
    const rest = line.slice(i);
    if (/^["']/.test(rest)) {
      const quote = rest[0];
      const end = rest.indexOf(quote, 1);
      const token = end === -1 ? rest : rest.slice(0, end + 1);
      result += span(t.string, token);
      i += token.length;
      continue;
    }

    const word = rest.match(/^[A-Za-z_$][\w$]*/);
    if (word) {
      const w = word[0];
      if (javaKeywords.has(w)) result += span(t.keyword, w);
      else if (/^[A-Z]/.test(w)) result += span(t.type, w);
      else result += span(t.default, w);
      i += w.length;
      continue;
    }

    result += span(t.punctuation, rest[0] ?? "");
    i += 1;
  }

  return result;
}

/** A YAML scalar: quoted, numeric and literal values coloured; a trailing comment too. */
function highlightYamlValue(value: string, t: typeof themes.dark): string {
  const at = value.search(/\s#/);
  const body = at === -1 ? value : value.slice(0, at);
  const tail = at === -1 ? "" : span(t.comment, value.slice(at));
  const trimmed = body.trim();
  const lead = body.slice(0, body.length - body.trimStart().length);
  const trail = body.slice(body.trimEnd().length);
  let colour = t.default;
  if (/^(["']).*\1$/.test(trimmed)) colour = t.string;
  else if (/^-?\d+(\.\d+)?$/.test(trimmed)) colour = t.number;
  else if (/^(true|false|null|~)$/.test(trimmed)) colour = t.keyword;
  return escapeHtml(lead) + (trimmed ? span(colour, trimmed) : "") + escapeHtml(trail) + tail;
}

function highlightYamlLine(line: string, t: typeof themes.dark): string {
  const comment = line.match(/^(\s*)(#.*)$/);
  if (comment) return escapeHtml(comment[1]) + span(t.comment, comment[2]);
  const pair = line.match(/^(\s*(?:-\s+)?)([\w.$/-]+)(\s*:)(.*)$/);
  if (pair) {
    return (
      span(t.punctuation, pair[1]) +
      span(t.function, pair[2]) +
      span(t.punctuation, pair[3]) +
      highlightYamlValue(pair[4], t)
    );
  }
  const item = line.match(/^(\s*-\s+)(.*)$/);
  if (item) return span(t.punctuation, item[1]) + highlightYamlValue(item[2], t);
  return highlightYamlValue(line, t);
}

const dockerInstructions = new Set([
  "FROM", "RUN", "CMD", "LABEL", "EXPOSE", "ENV", "ADD", "COPY", "ENTRYPOINT", "VOLUME",
  "USER", "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL",
]);

function highlightDockerfileLine(line: string, t: typeof themes.dark): string {
  if (/^\s*#/.test(line)) return span(t.comment, line);
  const match = line.match(/^(\s*)([A-Z]+)(\b.*)$/);
  if (!match || !dockerInstructions.has(match[2])) return span(t.default, line);
  const rest = match[3]
    .split(/("[^"]*")/)
    .map((part) =>
      part.length > 1 && part.startsWith('"') && part.endsWith('"')
        ? span(t.string, part)
        : part
            .split(/(\bAS\b)/)
            .map((piece) => (piece === "AS" ? span(t.keyword, piece) : span(t.default, piece)))
            .join(""),
    )
    .join("");
  return escapeHtml(match[1]) + span(t.keyword, match[2]) + rest;
}

function highlightCssLine(line: string, t: typeof themes.dark) {
  if (/^\s*\/\*/.test(line)) return span(t.comment, line);
  return line.replace(/([.#][\w-]+)/g, (_, sel) => span(t.type, sel))
    .replace(/([\w-]+)(?=\s*:)/g, (m) => span(t.function, m))
    .replace(/:\s*([^;]+);/g, (_, val) => `: ${span(t.string, val.trim())};`);
}

export function highlightCode(code: string, language: Lang, isDark: boolean) {
  const t = isDark ? themes.dark : themes.light;
  const lines = code.split("\n");

  return lines.map((line) => {
    if (language === "java") return highlightJavaLine(line, t);
    if (language === "css") return highlightCssLine(line, t);
    if (language === "yaml") return highlightYamlLine(line, t);
    if (language === "dockerfile") return highlightDockerfileLine(line, t);
    if (language === "plaintext") return span(t.default, line);
    return highlightTsLine(line, t);
  });
}

export function languageFromPath(path: string): Lang {
  const name = path.split("/").pop() ?? path;
  if (/\.(tsx|jsx)$/.test(name)) return "tsx";
  if (/\.(ts|mts|cts|js|mjs|cjs)$/.test(name)) return "typescript";
  if (name.endsWith(".java")) return "java";
  if (name.endsWith(".css")) return "css";
  if (name.endsWith(".json")) return "json";
  if (/\.ya?ml$/.test(name)) return "yaml";
  if (name === "Dockerfile" || name.startsWith("Dockerfile.") || name.endsWith(".dockerfile")) {
    return "dockerfile";
  }
  return "plaintext";
}
