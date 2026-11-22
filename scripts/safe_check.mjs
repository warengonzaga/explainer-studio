import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [manifestPath, packageRoot] = process.argv.slice(2);
const { compositions, width, height } = JSON.parse(readFileSync(manifestPath, 'utf8'));
const require = createRequire(`${packageRoot}/package.json`);
const puppeteer = require('puppeteer-core');
const browserPath = process.env.HYPERFRAMES_BROWSER_PATH;
if (!browserPath) throw new Error('Chrome or Edge is required for native composition safe checks');

const browser = await puppeteer.launch({ executablePath: browserPath, headless: true, pipe: true, args: ['--allow-file-access-from-files'] });
const findings = [];
try {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  for (const composition of compositions) {
    await page.goto(pathToFileURL(composition.path).href, { waitUntil: 'load' });
    await page.evaluate(async () => { await document.fonts.ready; return document.fonts.status; });
    if (pageErrors.length) throw new Error(`composition script failed: ${pageErrors.slice(0, 3).join('; ')}`);
    const duration = composition.duration;
    for (let time = 0, sample = 0; time < duration; time += 1 / 15, sample++) {
      const outside = await page.evaluate((at) => {
        const timeline = window.__timelines?.root;
        if (!timeline || typeof timeline.seek !== 'function') throw new Error('composition must register a seekable window.__timelines.root');
        timeline.seek(at, false);
        const bounds = { left: innerWidth * 0.093, top: innerHeight * 0.13, right: innerWidth * 0.82, bottom: innerHeight * 0.771 };
        return [...document.querySelectorAll('*')].flatMap((element) => {
          const tag = element.tagName.toLowerCase();
          const graphic = ['img', 'video', 'canvas', 'iframe', 'object', 'embed', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'use'].includes(tag);
          const text = element.childElementCount === 0 && (element.textContent || '').trim().length > 0;
          const style = getComputedStyle(element);
          const painted = style.backgroundImage !== 'none' ||
            (style.backgroundColor !== 'rgba(0, 0, 0, 0)' && style.backgroundColor !== 'transparent') ||
            [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth].some(width => parseFloat(width) > 0);
          if (!graphic && !text && !painted) return [];
          let opacity = 1;
          for (let parent = element; parent; parent = parent.parentElement) {
            const parentStyle = parent === element ? style : getComputedStyle(parent);
            if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') return [];
            opacity *= Number(parentStyle.opacity);
          }
          if (opacity <= 0.01) return [];
          const rect = element.getBoundingClientRect();
          // shortcut: whole-frame backgrounds are ignored; classify them if backdrop art needs its own bounds.
          if (rect.width <= 0 || rect.height <= 0 || (rect.width >= innerWidth * 0.9 && rect.height >= innerHeight * 0.9)) return [];
          if (rect.left >= bounds.left && rect.top >= bounds.top && rect.right <= bounds.right && rect.bottom <= bounds.bottom) return [];
          return [{ tag, id: element.id || undefined, text: text ? element.textContent.trim().slice(0, 80) : undefined,
            bounds: { left: Math.round(rect.left), top: Math.round(rect.top), right: Math.round(rect.right), bottom: Math.round(rect.bottom) } }];
        });
      }, time);
      for (const item of outside) {
        findings.push({ scene: composition.scene, time: Number(time.toFixed(3)), sample, ...item });
        if (findings.length >= 100) break;
      }
      if (findings.length >= 100) break;
    }
    if (findings.length >= 100) break;
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ applicable: true, sample_rate: 15, compositions: compositions.length, findings, pass: findings.length === 0 }));
