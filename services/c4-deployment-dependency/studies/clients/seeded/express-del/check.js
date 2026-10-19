// Start the app, delete one item over HTTP, and check it is gone.
const assert = require("node:assert");
const { app, items } = require("./app");

const server = app.listen(0, "127.0.0.1", async () => {
  try {
    const { port } = server.address();
    const deleted = await fetch(`http://127.0.0.1:${port}/items/1`, { method: "DELETE" });
    assert.equal(deleted.status, 204);
    assert.equal(items.has("1"), false);
    console.log("delete works");
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    server.close();
  }
});
