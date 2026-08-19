import puppeteer from "puppeteer-core";

const [url, out, w, h, ...clicks] = process.argv.slice(2);
const browser = await puppeteer.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: "new",
  defaultViewport: { width: Number(w) || 1280, height: Number(h) || 960 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
await page.waitForFunction(
  () => document.getElementById("fps")?.textContent?.includes("fps"),
  { timeout: 30000 },
);
for (const sel of clicks) {
  try { await page.click(sel); } catch (e) { console.log("[click fail]", sel, e.message); }
  await new Promise((r) => setTimeout(r, 800));
}
await new Promise((r) => setTimeout(r, 2000));
await page.screenshot({ path: out });
await browser.close();
console.log("ok", out);
