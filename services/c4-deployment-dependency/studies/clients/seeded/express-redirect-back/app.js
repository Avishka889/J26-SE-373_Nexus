// A form handler that sends the browser back where it came from with the
// "back" shortcut, which later Express 4 releases deprecated.
const express = require("express");

const subscribers = [];

const app = express();
app.use(express.urlencoded({ extended: false }));
app.post("/subscribe", (req, res) => {
  subscribers.push(req.body.email);
  res.redirect("back");
});

module.exports = { app, subscribers };
