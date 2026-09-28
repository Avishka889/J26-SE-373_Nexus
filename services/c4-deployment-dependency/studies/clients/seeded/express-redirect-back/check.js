// Subscribe from the sign up page and check the browser is sent back to it.
const assert = require("node:assert");
const { app, subscribers } = require("./app");

const server = app.listen(0, "127.0.0.1", async () => {
  try {
    const { port } = server.address();
    const answer = await fetch(`http://127.0.0.1:${port}/subscribe`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded", referer: "/signup" },
      body: "email=someone%40example.com",
    });
    assert.equal(answer.status, 302);
    assert.equal(answer.headers.get("location"), "/signup");
    assert.deepEqual(subscribers, ["someone@example.com"]);
    console.log("redirected back to", answer.headers.get("location"));
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    server.close();
  }
});
