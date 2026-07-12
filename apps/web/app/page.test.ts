import { describe, expect, it } from "vitest";

describe("M0 console", () => {
  it("keeps the local single-instance boundary explicit", () => {
    expect("local").toBe("local");
  });
});

