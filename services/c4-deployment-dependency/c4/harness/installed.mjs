// Proves a pin took: which version of a package each place resolves, and
// whether it is the one pinned. Run by the lane right after the install.
//
//   node installed.mjs PACKAGE VERSION [WORKSPACE...]
//
// Each place is looked up the way Node looks a package up, in its own
// node_modules and then in each parent's. Every place is printed, so the step's
// output records what was installed. A place that resolves another version, or
// none, prints the marker below and exits 3: that is the harness failing, not
// the update, and the study stops rather than scoring it.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const MARKER = "C4-PIN-NOT-APPLIED";

const [name, wanted, ...workspaces] = process.argv.slice(2);
if (!name || !wanted) {
  console.error("usage: node installed.mjs PACKAGE VERSION [WORKSPACE...]");
  process.exit(2);
}

function installed(place) {
  let directory = resolve(place);
  for (;;) {
    const manifest = join(directory, "node_modules", name, "package.json");
    if (existsSync(manifest)) return JSON.parse(readFileSync(manifest, "utf8")).version;
    const parent = dirname(directory);
    if (parent === directory) return null;
    directory = parent;
  }
}

let wrong = 0;
for (const place of workspaces.length ? workspaces : ["."]) {
  const version = installed(place);
  console.log(`${place} resolves ${name}@${version ?? "nothing"}`);
  if (version !== wanted) wrong += 1;
}
if (wrong) {
  console.log(`${MARKER}: ${name} is not at ${wanted} everywhere it was pinned`);
  process.exit(3);
}
