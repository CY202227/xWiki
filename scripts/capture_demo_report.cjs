// Optional browser tooling: capture the HTML produced by render_demo_report.py.
const path = require('node:path');
const { pathToFileURL } = require('node:url');

async function main() {
  const args = process.argv.slice(2);
  const value = (name) => {
    const index = args.indexOf(name);
    if (index === -1) return undefined;
    if (!args[index + 1] || args[index + 1].startsWith('--')) throw new Error(`Missing value for ${name}`);
    return args[index + 1];
  };
  const modulePath = value('--playwright-module');
  const { chromium } = modulePath ? require(path.resolve(modulePath)) : require('playwright');
  const folder = path.resolve(value('--directory') || 'docs/assets');
  const browser = await chromium.launch({headless: true, executablePath: value('--browser-path')});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 1100}, deviceScaleFactor: 1});
    await page.goto(pathToFileURL(path.join(folder, 'demo-report.html')).href);
    await page.screenshot({path: path.join(folder, 'demo-report.png'), fullPage: true});
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
