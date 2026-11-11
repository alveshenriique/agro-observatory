// Titles never end a line with a word of one or two letters ("a", "na", "de"), as Portuguese
// typography asks: such a word is tied to the next one with a no-break space. CSS
// text-wrap: balance evens the line lengths; this keeps the short words in place.
const NO_BREAK_SPACE = " ";

export function bindShortWords(text: string): string {
  return text.replace(/(?<=^|[\s(“"])(\p{L}{1,2}[,;:]?) +(?=\S)/gu, `$1${NO_BREAK_SPACE}`);
}
