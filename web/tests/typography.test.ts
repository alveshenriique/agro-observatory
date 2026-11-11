import { bindShortWords } from "../src/lib/typography";

const NBSP = " ";

describe("bindShortWords", () => {
  it("ties words of one or two letters to the next one", () => {
    expect(bindShortWords("Quando falta chuva na floração, a soja rende menos")).toBe(
      `Quando falta chuva na${NBSP}floração, a${NBSP}soja rende menos`,
    );
  });

  it("handles runs of short words and leaves longer words alone", () => {
    expect(bindShortWords("E a seca de um ano")).toBe(`E${NBSP}a${NBSP}seca de${NBSP}um${NBSP}ano`);
    expect(bindShortWords("Rendimento menor")).toBe("Rendimento menor");
  });

  it("never binds the last word of the title to nothing", () => {
    expect(bindShortWords("Rio Grande do Sul")).toBe(`Rio Grande do${NBSP}Sul`);
    expect(bindShortWords("Fim de")).toBe(`Fim de`);
  });
});
