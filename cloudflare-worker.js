// Relay worker — three strategies, picked per request:
//   ?url=...            → direct fetch from Cloudflare's edge (free, fast,
//                         Cloudflare IPs have decent reputation)
//   ?url=...&via=proxy  → CONNECT-tunnel through IPRoyal (for sites that
//                         block CF datacenter IPs)
//   ?url=...&render=1   → headless Chromium via Cloudflare Browser Rendering
//                         (unlocks JS-heavy targets: Homegate CH, Willhaben
//                         AT, Immobiliare IT, etc). Requires [browser]
//                         binding "MYBROWSER" — see wrangler.toml.
//                         Free plan: 10 min/day of browser time.
//
// startTls in Workers is beta + flaky, so the proxy path is HTTP-only.
// The direct path is the workhorse. The render path is the escape hatch
// for sites that bot-block direct + return a JS shell.

import { connect } from 'cloudflare:sockets';
import puppeteer from '@cloudflare/puppeteer';

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: false });

async function directFetch(target) {
  const r = await fetch(target, {
    headers: {
      'User-Agent': UA,
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept-Encoding': 'gzip, deflate, br',
      'Cache-Control': 'no-cache',
    },
    redirect: 'follow',
  });
  return r;
}

async function proxyFetchHttp(target, env) {
  const m = env.IPROYAL_PROXY?.match(/^https?:\/\/([^:]+):([^@]+)@([^:]+):(\d+)/);
  if (!m) throw new Error('IPROYAL_PROXY not configured');
  const [, user, pass, proxyHost, proxyPort] = m;

  const t = new URL(target);
  if (t.protocol !== 'http:') {
    throw new Error('Proxy path only supports http:// targets (startTls in Workers is beta)');
  }

  const socket = connect({ hostname: proxyHost, port: parseInt(proxyPort) });
  const auth = btoa(`${user}:${pass}`);
  // Plain HTTP proxy: send full URL as request line, with Proxy-Authorization
  const req = encoder.encode(
    `GET ${target} HTTP/1.1\r\n` +
    `Host: ${t.host}\r\n` +
    `Proxy-Authorization: Basic ${auth}\r\n` +
    `User-Agent: ${UA}\r\n` +
    `Accept: */*\r\n` +
    `Accept-Encoding: identity\r\n` +
    `Connection: close\r\n\r\n`
  );
  const w = socket.writable.getWriter();
  await w.write(req);
  w.releaseLock();

  const r = socket.readable.getReader();
  const chunks = [];
  while (true) {
    const { value, done } = await r.read();
    if (done) break;
    if (value && value.length) chunks.push(value);
  }
  r.releaseLock();

  const totalLen = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new Uint8Array(totalLen);
  let off = 0;
  for (const c of chunks) { buf.set(c, off); off += c.length; }
  return buf;
}

async function renderFetch(target, env, waitMs, waitUntil) {
  if (!env.MYBROWSER) throw new Error('MYBROWSER binding missing — check wrangler.toml [browser]');
  // Free tier caps concurrent browsers — retry a couple times on 429
  let browser, lastErr;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { browser = await puppeteer.launch(env.MYBROWSER); break; }
    catch (e) {
      lastErr = e;
      if (String(e).includes('429') || String(e).includes('Rate limit')) {
        await new Promise(r => setTimeout(r, 2000 * (attempt + 1)));
        continue;
      }
      throw e;
    }
  }
  if (!browser) throw lastErr;
  try {
    const page = await browser.newPage();
    await page.setUserAgent(UA);
    await page.setViewport({ width: 1280, height: 1000 });
    // Inline stealth: patch the ~10 most common headless-detection signals so
    // Willhaben/Immoscout/Immobiliare hydrate their listings. puppeteer-extra's
    // stealth plugin doesn't compose with @cloudflare/puppeteer so we inline.
    await page.evaluateOnNewDocument(() => {
      // 1. navigator.webdriver false
      Object.defineProperty(navigator, 'webdriver', { get: () => false });
      // 2. window.chrome exists (present in real Chrome, absent in headless)
      window.chrome = window.chrome || { runtime: {}, loadTimes: () => ({}), csi: () => ({}) };
      // 3. Real permissions.query
      const origQuery = navigator.permissions && navigator.permissions.query;
      if (origQuery) {
        navigator.permissions.query = (p) =>
          p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(p);
      }
      // 4. plugins non-empty (headless has 0)
      Object.defineProperty(navigator, 'plugins', {
        get: () => [1,2,3,4,5].map(i => ({ name: `Plugin ${i}` })),
      });
      // 5. languages non-empty
      Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
      // 6. platform mac-ish (matches UA)
      Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
      // 7. WebGL vendor/renderer look like real Chrome (not SwiftShader)
      const getParam = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';        // UNMASKED_VENDOR
        if (p === 37446) return 'Intel Iris OpenGL'; // UNMASKED_RENDERER
        return getParam.call(this, p);
      };
      // 8. deviceMemory / hardwareConcurrency realistic
      Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
      Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    });
    // networkidle0 is strict and times out on ad-heavy sites; default to
    // domcontentloaded which is enough for scraping the initial listing HTML.
    const wu = waitUntil || 'domcontentloaded';
    await page.goto(target, { waitUntil: wu, timeout: 45000 });
    if (waitMs > 0) await new Promise(r => setTimeout(r, Math.min(waitMs, 12000)));
    const html = await page.content();
    return html;
  } finally {
    try { await browser.close(); } catch {}
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const target = url.searchParams.get('url');
    const via = url.searchParams.get('via') || 'direct';
    const render = url.searchParams.get('render');
    const waitMs = parseInt(url.searchParams.get('wait') || '2000', 10);

    if (!target) {
      return new Response(
        'Relay live.\n' +
        '  ?url=<target>            → fetch via Cloudflare edge (default)\n' +
        '  ?url=<target>&via=proxy  → via IPRoyal (HTTP targets only)\n' +
        '  ?url=<target>&render=1   → headless Chromium (JS-rendered pages)\n' +
        '     &wait=<ms>            → extra idle time after networkidle (default 2000)\n',
        { status: 200, headers: { 'Content-Type': 'text/plain' } }
      );
    }

    try {
      if (render === '1' || render === 'true') {
        const waitUntil = url.searchParams.get('waitUntil');
        const html = await renderFetch(target, env, waitMs, waitUntil);
        return new Response(html, {
          status: 200,
          headers: {
            'Content-Type': 'text/html; charset=utf-8',
            'X-Relay-Mode': 'render',
            'X-Relay-Target': new URL(target).host,
            'X-Relay-Bytes': String(html.length),
          },
        });
      }

      if (via === 'proxy') {
        const buf = await proxyFetchHttp(target, env);
        const txt = decoder.decode(buf);
        const headerEnd = txt.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
          return new Response('No header terminator from proxy', { status: 502 });
        }
        const status = parseInt(txt.match(/^HTTP\/1\.\d (\d+)/)?.[1] || '200');
        const headers = txt.slice(0, headerEnd);
        const contentType =
          headers.match(/content-type:\s*([^\r\n]+)/i)?.[1] ||
          'text/html; charset=utf-8';
        return new Response(buf.slice(headerEnd + 4), {
          status,
          headers: {
            'Content-Type': contentType,
            'X-Relay-Mode': 'proxy',
            'X-Relay-Target': new URL(target).host,
          },
        });
      }

      // Default: direct fetch from Cloudflare edge
      const r = await directFetch(target);
      const body = await r.arrayBuffer();
      const contentType = r.headers.get('Content-Type') || 'text/html; charset=utf-8';
      return new Response(body, {
        status: r.status,
        headers: {
          'Content-Type': contentType,
          'X-Relay-Mode': 'direct',
          'X-Relay-Target': new URL(target).host,
          'X-Relay-Bytes': String(body.byteLength),
        },
      });
    } catch (e) {
      return new Response(
        `Relay error (mode=${via}): ${e.message || e}`,
        { status: 500 }
      );
    }
  },
};
