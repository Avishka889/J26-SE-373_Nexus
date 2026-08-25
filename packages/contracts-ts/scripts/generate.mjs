// Generate TypeScript from the committed JSON Schemas.
//
// The schemas are generated from the Pydantic models and the types are
// generated from the schemas, so there is one author and two derived artefacts.
// CI runs this and fails on a dirty diff, which is what stops the frontend
// compiling against a shape the backend no longer sends.

import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const contractsDir = resolve(here, "../../../contracts");
const outDir = resolve(here, "../src");

const BANNER = `/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */`;

const toPascal = (name) =>
  name.split(/[-_]/).map((part) => part[0].toUpperCase() + part.slice(1)).join("");

const files = (await readdir(contractsDir)).filter((f) => f.endsWith(".schema.json")).sort();
await mkdir(outDir, { recursive: true });

// The barrel exports every interface exactly once. A blind `export *` per
// module collided the moment two schemas shared a name (Id appeared in ten of
// them), which made the barrel unusable by the frontend. Only interfaces are
// exported: they are the named contract models. The property derived type
// aliases (Kind, Traces, Id) are generator noise and stay module local.
//
// Identity is checked on the schema's $defs JSON, not on the emitted
// TypeScript: the emitter numbers its local aliases per file, so two identical
// models print differently. The $defs text is generated sorted from one
// author, so same title with different JSON means two models genuinely share
// a name, which fails the generation rather than shipping a silent lie.
const claimed = new Map(); // name -> { file, def }
const perFile = new Map(); // file -> names it exports from the barrel

// A def's top level `title` and `description` are display metadata that a
// root schema carries differently, so both are dropped there and only there:
// nested occurrences stay, because `description` is a legitimate property
// name inside a `properties` map.
const withoutMeta = ({ title, description, ...shape }) => shape;

const defsOf = (schema, rootName) => {
  const defs = {};
  for (const [key, value] of Object.entries(schema.$defs ?? {})) {
    defs[key] = withoutMeta(value);
  }
  const { $defs: _ignored, $schema, $id, ...root } = schema;
  defs[rootName] = withoutMeta(root);
  return defs;
};

const canonical = (value) =>
  JSON.stringify(value, (key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1)))
      : v,
  );

// Which file each name belongs to, worked out before anything is claimed.
//
// Two schemas legitimately contain the same model: a view model embeds the
// artefacts it shows, so `test-snapshot` inlines `ValidationReport` and every
// type beneath it. Both files then emit the same interface, identically, and
// first-come claiming handed it to whichever sorted earlier. That is not wrong,
// since the definitions are checked identical below, but it is misleading: the
// barrel sourced `ValidationReport` from a file where it is a nested detail,
// and `validation-report.ts` exported almost nothing.
//
// A name belongs to the most specific schema that defines it: the one it is the
// root of, or failing that the smallest one, which is the artefact rather than
// the view model that embeds it. Ties break on the filename so two runs on the
// same contracts always produce the same barrel.
const ownerOf = new Map(); // name -> file that should export it
{
  const candidates = new Map(); // name -> [{ file, isRoot, size }]
  for (const file of files) {
    const name = file.replace(".schema.json", "");
    const schema = JSON.parse(await readFile(join(contractsDir, file), "utf8"));
    const rootName = schema.title ?? toPascal(name);
    const defs = defsOf(schema, rootName);
    const size = Object.keys(defs).length;
    for (const defName of Object.keys(defs)) {
      if (!candidates.has(defName)) candidates.set(defName, []);
      candidates.get(defName).push({ file: name, isRoot: defName === rootName, size });
    }
  }
  for (const [defName, found] of candidates) {
    found.sort(
      (a, b) =>
        Number(b.isRoot) - Number(a.isRoot) || a.size - b.size || (a.file < b.file ? -1 : 1),
    );
    ownerOf.set(defName, found[0].file);
  }
}

for (const file of files) {
  const name = file.replace(".schema.json", "");
  const schema = JSON.parse(await readFile(join(contractsDir, file), "utf8"));
  const ts = await compile(schema, toPascal(name), {
    bannerComment: BANNER,
    additionalProperties: false,
    style: { singleQuote: false, semi: true },
  });
  await writeFile(join(outDir, `${name}.ts`), ts, "utf8");

  const names = [...ts.matchAll(/^export interface (\w+)/gm)].map((m) => m[1]);
  // The emitter names the root interface after the schema's own title, not
  // after the filename, so the root def must be registered under that name.
  const defs = defsOf(schema, schema.title ?? toPascal(name));
  const kept = [];
  for (const exported of names) {
    const def = canonical(defs[exported] ?? null);
    const owner = ownerOf.get(exported);
    if (owner !== undefined && owner !== name) {
      // A more specific schema is about this model. That file exports it; this
      // one inlines it because it embeds it.
      continue;
    }
    const earlier = claimed.get(exported);
    if (!earlier) {
      claimed.set(exported, { file: name, def });
      kept.push(exported);
    } else if (earlier.def !== def) {
      console.error(
        `refusing to generate: "${exported}" means different things in ` +
          `${earlier.file} and ${name}. Rename one model so the barrel stays honest.`,
      );
      process.exit(1);
    }
  }
  if (kept.length > 0) perFile.set(name, kept);
}

const barrel = [BANNER, ""];
for (const [name, names] of perFile) {
  barrel.push(`export type { ${names.join(", ")} } from "./${name}";`);
}
await writeFile(join(outDir, "index.ts"), barrel.join("\n") + "\n", "utf8");
console.log(`generated ${files.length} type modules, ${claimed.size} names in the barrel`);
