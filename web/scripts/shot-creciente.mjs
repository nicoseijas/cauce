import puppeteer from "puppeteer-core";

const [url, out, periodo] = process.argv.slice(2);
const browser = await puppeteer.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: "new",
  defaultViewport: { width: 1280, height: 960 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
await page.waitForFunction(
  () => document.getElementById("fps")?.textContent?.includes("fps"),
  { timeout: 30000 },
);
await page.click("#creciente-toggle");
await page.waitForFunction(
  () => document.getElementById("creciente-toggle")?.textContent === "Modo creciente",
  { timeout: 30000 },
);
if (periodo) await page.click(`[data-periodo="${periodo}"]`);
for (const sel of process.argv.slice(5)) await page.click(sel);
await new Promise((r) => setTimeout(r, 2500));
await page.screenshot({ path: out });
await browser.close();
console.log("ok", out);
