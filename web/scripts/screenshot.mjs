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
    () => document.getElementById("fps")?.textContent?.includes("fps"),
    { timeout: 30000 },
  );
} catch {
  console.log("[warn] HUD nunca mostró fps");
}
await new Promise((r) => setTimeout(r, 3000));
if (process.argv[4] === "--hover") {
  // barrido diagonal hasta que aparezca el tooltip sobre algún río
  for (let i = 0; i < 40; i++) {
    await page.mouse.move(400 + i * 12, 300 + i * 8);
    await new Promise((r) => setTimeout(r, 120));
    const visible = await page.$eval("#tooltip", (el) => el.style.display === "block");
    if (visible) break;
  }
  console.log("[tooltip]", await page.$eval("#tooltip", (el) => el.textContent));
}
console.log("[hud]", await page.$eval("#fps", (el) => el.textContent));
await page.screenshot({ path: out });
await browser.close();
