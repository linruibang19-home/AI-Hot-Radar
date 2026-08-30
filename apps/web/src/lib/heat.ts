/**
 * How a hot score is shown to a reader.
 *
 * `hot_score` decays by half-life and is unbounded above, so at any moment most
 * of the corpus sits below 1. Rounding it — which every call site did — turns
 * that majority into a flat "0". Measured on production 2026-08-29: 3029 of
 * 3392 reader-visible items and 71 of 76 stories.
 *
 * The rule lives here rather than at each call site because it had already
 * drifted: the item card, the story list and the story detail page each carried
 * their own `Math.round(...)`, and fixing one left the other two showing "0".
 */

/** Below this the number carries no information a reader can act on. */
const VISIBLE_THRESHOLD = 1;

/**
 * Whether a badge should appear at all.
 *
 * Badges are unlabelled — a dot and a number — so a "0" reads as a claim that
 * the item is cold rather than as a decayed score. Absence says the same thing
 * without spending a slot in the header row.
 */
export function showsHeatBadge(heat: number | null | undefined): heat is number {
  return typeof heat === "number" && Math.round(heat) >= VISIBLE_THRESHOLD;
}

/** The badge value. Only meaningful when `showsHeatBadge` passed. */
export function heatBadge(heat: number): string {
  return String(Math.round(heat));
}

/**
 * The value for a labelled statistic.
 *
 * A labelled row is the one place the number can stay when it is small: "当前
 * 热度 0.2" is a reading, while a bare "0" beside a label still looks like the
 * score failed to compute. One decimal, and only below the threshold, because
 * above it the integer is what the badges show and the two must agree.
 */
export function heatStat(heat: number | null | undefined): string {
  if (typeof heat !== "number") return "—";
  return heat < VISIBLE_THRESHOLD ? heat.toFixed(1) : String(Math.round(heat));
}
