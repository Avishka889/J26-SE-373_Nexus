// Mint an id and check its shape: the only part of uuid this client uses.
import assert from "node:assert";
import { v4 as uuid, validate, version } from "uuid";

const id = uuid();
assert.ok(validate(id), `${id} is not a UUID`);
assert.equal(version(id), 4);
console.log("minted", id);
