const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  mdash: "—",
  ndash: "–",
  nbsp: " ",
  quot: '"',
};

function decodeEntity(match: string, body: string): string {
  if (body.startsWith("#x") || body.startsWith("#X")) {
    const value = Number.parseInt(body.slice(2), 16);
    return Number.isFinite(value) ? String.fromCodePoint(value) : match;
  }
  if (body.startsWith("#")) {
    const value = Number.parseInt(body.slice(1), 10);
    return Number.isFinite(value) ? String.fromCodePoint(value) : match;
  }
  return NAMED_ENTITIES[body.toLowerCase()] ?? match;
}

/**
 * Turn third-party HTML/Markdown into a compact text preview.
 *
 * React already escapes markup, so this is a presentation boundary rather
 * than an XSS boundary. It prevents a malformed provider excerpt from being
 * rendered literally while a row is being repaired or reprocessed.
 */
export function toPlainPreview(value?: string | null): string {
  if (!value) return "";

  return value
    .replace(/<img\b[^>]*\balt=(['"])(.*?)\1[^>]*>/gi, " $2 ")
    .replace(/<[^>]+>/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, " $1 ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, decodeEntity)
    .replace(/(^|\s)#{1,6}\s+/g, " ")
    .replace(/^\s{0,3}(?:[-+*]|\d+[.)])\s+/gm, "")
    .replace(/[*_~`>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
