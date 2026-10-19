// A small API that registers its delete route through app.del, the old alias
// that Express 4 kept, deprecated, and Express 5 removed.
const express = require("express");

const items = new Map([
  ["1", "first"],
  ["2", "second"],
]);

const app = express();
app.get("/items", (req, res) => res.json([...items.keys()]));
app.del("/items/:id", (req, res) => {
  items.delete(req.params.id);
  res.sendStatus(204);
});

module.exports = { app, items };
