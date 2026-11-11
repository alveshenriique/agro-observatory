import { format, MINUS } from "../src/lib/format";

describe("format", () => {
  it("prints fractions as whole percentages", () => {
    expect(format(0.7273, "pct")).toBe("73%");
    expect(format(0.4302, "pct")).toBe("43%");
    expect(format(1, "pct")).toBe("100%");
  });

  it("signs percentages with the minus sign and a plus", () => {
    expect(format(-0.0899, "spct")).toBe(`${MINUS}9%`);
    expect(format(0.0306, "spct")).toBe("+3%");
    expect(format(-0.004, "spct")).toBe("0%");
    expect(format(0, "spct")).toBe("0%");
  });

  it("groups thousands the Brazilian way, even with four digits", () => {
    expect(format(19237, "int")).toBe("19.237");
    expect(format(5571, "int")).toBe("5.571");
    expect(format(537, "int")).toBe("537");
    expect(format(-53, "int")).toBe(`${MINUS}53`);
  });

  it("keeps years plain and decimals with a comma", () => {
    expect(format(2025, "year")).toBe("2025");
    expect(format(0.752, "dec2")).toBe("0,75");
    expect(format(-0.05, "dec2")).toBe(`${MINUS}0,05`);
  });

  it("turns the data version and ISO dates into dd/mm/yyyy", () => {
    expect(format("2026.11.10", "date")).toBe("10/11/2026");
    expect(format("2026-11-10T00:05:09Z", "date")).toBe("10/11/2026");
  });

  it("refuses to format what is not a number", () => {
    expect(() => format(null, "pct")).toThrow(TypeError);
    expect(() => format("73", "int")).toThrow(TypeError);
  });
});
