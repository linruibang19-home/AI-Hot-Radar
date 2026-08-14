import { describe, expect, it } from "vitest";

import { toPlainPreview } from "@/lib/content-preview";

describe("toPlainPreview", () => {
  it("removes provider HTML and Markdown instead of displaying raw tags", () => {
    const raw =
      '<img width="600" alt="ollama and qwen" src="https://example.com/a.png" /> ## Qwen 3.8 support';

    expect(toPlainPreview(raw)).toBe("ollama and qwen Qwen 3.8 support");
  });

  it("keeps link labels and decodes common entities", () => {
    expect(toPlainPreview("Read [R&amp;D notes](https://example.com) &mdash; now")).toBe(
      "Read R&D notes — now",
    );
  });

  it("collapses list syntax and whitespace", () => {
    expect(toPlainPreview("- first\n- second\n\n  third")).toBe("first second third");
  });
});
