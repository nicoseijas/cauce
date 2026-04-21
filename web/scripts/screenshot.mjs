import puppeteer from "puppeteer-core";

const url = process.argv[2] ?? "http://localhost:4173/";
const out = process.argv[3] ?? "spike.png";

const browser = await puppeteer.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: "new",
  args: ["--window-size=1280,960", "--use-angle=default"],
  defaultViewport: { width: 1280, height: 960 },
});
const page = await browser.newPage();
page.on("console", (m) => console.log("[console]", m.type(), m.text()));
page.on("pageerror", (e) => console.log("[pageerror]", e.message));

await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
try {
  await page.waitForFunction(
    () => document.getElementById("hud")?.textContent?.includes("fps"),
    { timeout: 30000 },
  );
} catch {
  console.log("[warn] HUD nunca mostró fps");
}
await new Promise((r) => setTimeout(r, 3000));
console.log("[hud]", await page.$eval("#hud", (el) => el.textContent));
await page.screenshot({ path: out });
await browser.close();
