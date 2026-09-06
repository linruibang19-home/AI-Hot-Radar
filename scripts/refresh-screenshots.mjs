// Refresh the README screenshots from the live site.
//
//   npm i -D playwright && npx playwright install chromium
//   node scripts/refresh-screenshots.mjs docs/assets/screenshots
//
// Fixed 1440x1000 viewport, matching the images already committed, so swapping
// them does not shift the README layout. Run this whenever the numbers on the
// front page have drifted far enough that a reader would notice — the previous
// set showed 1972 items while production held 5061, and a screenshot that
// disagrees with the live site it links to costs more than no screenshot.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = process.argv[2];
const SHOTS = [
  { name: "home", url: "https://aihotradar.online/", wait: ".stat-value, .item-card, main" },
  {
    name: "rag-answer",
    url: "https://aihotradar.online/ask/556065bb-f4e8-49f5-9007-60d2fc1ed84a",
    wait: ".ask-body, main",
  },
  { name: "rag-quality", url: "https://aihotradar.online/eval", wait: ".stat-value, main" },
  { name: "reports", url: "https://aihotradar.online/reports", wait: "main" },
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});

for (const shot of SHOTS) {
  await page.goto(shot.url, { waitUntil: "networkidle", timeout: 60000 });
  try {
    await page.waitForSelector(shot.wait, { timeout: 15000 });
  } catch {
    console.log(`  ${shot.name}: 选择器未命中，仍按当前渲染截图`);
  }
  // Let webfonts settle so Chinese text is not captured mid-swap.
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/${shot.name}.png` });
  const title = await page.title();
  console.log(`✓ ${shot.name}.png  ← ${shot.url}  (${title})`);
}

await browser.close();
