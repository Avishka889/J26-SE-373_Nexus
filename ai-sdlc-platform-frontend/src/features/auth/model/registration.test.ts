import { describe, expect, it } from "vitest";
import { registrationProblem } from "./registration";

describe("a registration, before the server is asked", () => {
  it("names what is missing, one thing at a time", () => {
    expect(registrationProblem("", "ada@example.com", "correct horse")).toBe("Enter your name.");
    expect(registrationProblem("Ada", "ada", "correct horse")).toBe(
      "Enter an email address, such as you@example.com.",
    );
    expect(registrationProblem("Ada", "ada@example.com", "short")).toBe(
      "Use a password of at least 8 characters.",
    );
    expect(registrationProblem("Ada", "ada@example.com", "correct horse")).toBeNull();
  });
});
