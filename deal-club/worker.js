// Land Deal Club: public teaser page + $5/month members area, as one Cloudflare Worker.
//
// Members-only details (exact location, source link) live in KV, never in this public repo.
// Stripe Payment Link -> /welcome?session_id=... logs the buyer in straight away;
// later logins use an emailed magic link (Resend). Stripe webhooks keep KV in step
// with each subscription (cancelled = locked out at period end).
//
// KV (binding CLUB): picks = [{teaser, private}], sub:<email> = status, cus:<id> = email
// Secrets: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, SESSION_SECRET, ADMIN_TOKEN, RESEND_API_KEY
// Vars: PAYMENT_LINK, CLUB_NAME, FROM_EMAIL

const DAY = 86400;
const enc = new TextEncoder();
const LIVE = ["active", "trialing", "past_due"];

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      switch (`${req.method} ${url.pathname}`) {
        case "GET /": return html(landing(env, await picks(env)));
        case "GET /welcome": return welcome(url, env);
        case "GET /login": return html(page(env, "Log in", loginForm(url.searchParams.get("m"))));
        case "POST /login": return login(req, url, env);
        case "GET /auth": return auth(url, env);
        case "GET /logout": return redirect("/", cookie("", 0));
        case "GET /members": return members(req, env);
        case "POST /stripe/webhook": return webhook(req, env);
        case "POST /admin/publish": return publish(req, env);
      }
      return new Response("Not found", { status: 404 });
    } catch (e) {
      return new Response("Something went wrong: " + e.message, { status: 500 });
    }
  },
};

// ---------- auth ----------

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return [...new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)))]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

function same(a, b) {   // constant-time string compare
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

async function token(env, email, secs, kind) {
  const exp = Math.floor(Date.now() / 1000) + secs;
  const body = `${kind}|${email}|${exp}`;
  return btoa(`${body}|${await hmac(env.SESSION_SECRET, body)}`);
}

async function readToken(env, t, kind) {
  try {
    const [k, email, exp, sig] = atob(t).split("|");
    if (k !== kind || Number(exp) < Date.now() / 1000) return null;
    return same(sig, await hmac(env.SESSION_SECRET, `${k}|${email}|${exp}`)) ? email : null;
  } catch { return null; }
}

function cookie(value, maxAge) {
  return { "Set-Cookie": `club=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}` };
}

async function member(req, env) {
  const c = (req.headers.get("Cookie") || "").match(/(?:^|;\s*)club=([^;]+)/);
  const email = c && (await readToken(env, c[1], "session"));
  return email && LIVE.includes(await env.CLUB.get(`sub:${email}`)) ? email : null;
}

async function stripe(env, path) {
  const r = await fetch(`https://api.stripe.com/v1/${path}`, { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } });
  if (!r.ok) throw new Error(`Stripe ${r.status}`);
  return r.json();
}

// After checkout. Set the Payment Link's confirmation page to redirect to
// https://<worker>/welcome?session_id={CHECKOUT_SESSION_ID}
async function welcome(url, env) {
  const id = url.searchParams.get("session_id") || "";
  if (!/^cs_[A-Za-z0-9_]+$/.test(id)) return redirect("/login");
  const s = await stripe(env, `checkout/sessions/${id}?expand[]=subscription`);
  const email = (s.customer_details?.email || "").toLowerCase();
  if (s.status !== "complete" || !email) return redirect("/login?m=unpaid");
  await saveSub(env, email, s.customer, s.subscription?.status || "active");
  return redirect("/members", cookie(await token(env, email, 30 * DAY, "session"), 30 * DAY));
}

async function login(req, url, env) {
  const email = String((await req.formData()).get("email") || "").trim().toLowerCase();
  // Same reply either way, so the form can't be used to find out who is a member.
  if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) && LIVE.includes(await env.CLUB.get(`sub:${email}`))) {
    const link = `${url.origin}/auth?t=${encodeURIComponent(await token(env, email, 3600, "link"))}`;
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: env.FROM_EMAIL, to: email, subject: `Your ${env.CLUB_NAME} login link`,
        html: `<p><a href="${link}">Log in to ${esc(env.CLUB_NAME)}</a>. The link works for one hour.</p>`,
      }),
    });
    if (!r.ok) throw new Error(`email ${r.status}`);
  }
  return redirect("/login?m=sent");
}

async function auth(url, env) {
  const email = await readToken(env, url.searchParams.get("t") || "", "link");
  if (!email) return redirect("/login?m=expired");
  return redirect("/members", cookie(await token(env, email, 30 * DAY, "session"), 30 * DAY));
}

// ---------- Stripe webhook ----------
// Events: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted

async function webhook(req, env) {
  const body = await req.text();
  const sig = Object.fromEntries((req.headers.get("Stripe-Signature") || "").split(",").map((p) => p.split("=")));
  if (!sig.t || !sig.v1 || Math.abs(Date.now() / 1000 - Number(sig.t)) > 300
      || !same(sig.v1, await hmac(env.STRIPE_WEBHOOK_SECRET, `${sig.t}.${body}`))) {
    return new Response("bad signature", { status: 400 });
  }
  const ev = JSON.parse(body), o = ev.data.object;
  if (ev.type === "checkout.session.completed" && o.customer_details?.email) {
    await saveSub(env, o.customer_details.email.toLowerCase(), o.customer, "active");
  } else if (ev.type.startsWith("customer.subscription.")) {
    let email = await env.CLUB.get(`cus:${o.customer}`);
    if (!email) email = ((await stripe(env, `customers/${o.customer}`)).email || "").toLowerCase();
    if (email) await saveSub(env, email, o.customer, ev.type.endsWith("deleted") ? "canceled" : o.status);
  }
  return new Response("ok");
}

async function saveSub(env, email, customer, status) {
  await env.CLUB.put(`sub:${email}`, status);
  if (customer) await env.CLUB.put(`cus:${customer}`, email);
}

// ---------- admin ----------

async function publish(req, env) {
  const auth = req.headers.get("Authorization") || "";
  if (!env.ADMIN_TOKEN || !same(auth, `Bearer ${env.ADMIN_TOKEN}`)) return new Response("no", { status: 401 });
  const incoming = await req.json();
  const all = await picks(env);
  const have = new Set(all.map((p) => p.teaser.code));
  const fresh = incoming.filter((p) => p?.teaser?.code && p?.private && !have.has(p.teaser.code));
  await env.CLUB.put("picks", JSON.stringify([...fresh, ...all]));
  return Response.json({ added: fresh.length, total: fresh.length + all.length });
}

async function picks(env) {
  return JSON.parse((await env.CLUB.get("picks")) || "[]");
}

// ---------- pages ----------

async function members(req, env) {
  if (!(await member(req, env))) return redirect("/login");
  const list = await picks(env);
  const cards = list.map(({ teaser: t, private: p }) => `
    <article class="card">
      ${t.photos[0] ? `<img src="${esc(t.photos[0])}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}
      <div class="body">
        <div class="price">${money(t.usd)} · ${t.acres} acres</div>
        <h3>${esc(p.place)}${p.area && p.area !== t.region ? ` · ${esc(p.area)}` : ""}</h3>
        <ul>${t.highlights.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
        <p class="meta">$${p.usd_per_acre.toLocaleString()}/acre vs about $${p.similar_size_median_usd_per_acre.toLocaleString()} for similar-size land nearby${p.price_local ? ` · listed at ${esc(p.price_local)}` : ""}</p>
        ${p.foreign_note ? `<p class="meta">Foreign buyers: ${esc(p.foreign_note)}</p>` : ""}
        <p class="links">
          <a href="${esc(p.url)}" target="_blank" rel="noopener">Original listing ↗</a>
          ${p.lat != null ? `<a href="https://www.google.com/maps?q=${p.lat},${p.lon}&t=k" target="_blank" rel="noopener">Satellite map ↗</a>` : ""}
        </p>
        <p class="meta">${esc(t.code)} · picked ${esc(p.picked)}</p>
      </div>
    </article>`).join("");
  return html(page(env, "Members", `
    <header><h1>${esc(env.CLUB_NAME)}</h1><a href="/logout">Log out</a></header>
    <p class="lede">Every deal so far, newest first. Listings sell, so check the link before you get attached. Always confirm foreign-ownership rules and title with a local lawyer.</p>
    <section class="grid">${cards || "<p>The first deals land soon.</p>"}</section>`));
}

function landing(env, list) {
  const cards = list.slice(0, 9).map(({ teaser: t }) => `
    <article class="card">
      ${t.photos[0] ? `<img src="${esc(t.photos[0])}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}
      <div class="body">
        <div class="price">${money(t.usd)} · ${t.acres} acres</div>
        <h3>${esc(t.headline)} · ${esc(t.country)}</h3>
        <p class="lock">🔒 Location and listing link for members</p>
      </div>
    </article>`).join("");
  return page(env, env.CLUB_NAME, `
    <header><h1>${esc(env.CLUB_NAME)}</h1><a href="/login">Member login</a></header>
    <section class="hero">
      <h2>Cheap land in beautiful places, worldwide.</h2>
      <p>Every day we go through tens of thousands of listings in 20+ countries and pick the beachfront, lakeside, ski and big-view plots that are priced well below similar land nearby. Members get the exact location and the link to the original listing.</p>
      <a class="cta" href="${esc(env.PAYMENT_LINK)}">Join for $5/month</a>
      <p class="meta">Cancel any time.</p>
    </section>
    <section class="grid">${cards}</section>`);
}

function loginForm(m) {
  const note = { sent: "If that email has an active membership, a login link is on its way.",
    expired: "That link has expired. Ask for a new one.", unpaid: "We couldn't confirm that payment." }[m] || "";
  return `<header><h1>Log in</h1><a href="/">Home</a></header>
    ${note ? `<p class="lede">${note}</p>` : ""}
    <form method="post" action="/login"><input type="email" name="email" required placeholder="you@example.com" autocomplete="email"><button>Email me a login link</button></form>`;
}

function page(env, title, body) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>
:root{--bg:#f6f4ef;--fg:#1d2321;--muted:#5d6763;--card:#fff;--accent:#0f6b5c;--line:#e3dfd6}
@media (prefers-color-scheme:dark){:root{--bg:#121614;--fg:#e9ece9;--muted:#9aa5a0;--card:#1b211e;--accent:#4fc2a8;--line:#2a322e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}header{display:flex;justify-content:space-between;align-items:center;gap:12px}
h1{font-size:20px;margin:8px 0}a{color:var(--accent)}.hero{padding:32px 0 24px;max-width:640px}.hero h2{font-size:clamp(28px,6vw,44px);line-height:1.1;margin:0 0 12px}
.cta{display:inline-block;background:var(--accent);color:#fff;padding:14px 22px;border-radius:10px;text-decoration:none;font-weight:600;margin-top:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;padding:8px 0 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:var(--line)}
.body{padding:12px 14px}.price{font-weight:700;font-size:18px}h3{font-size:16px;margin:4px 0 8px}ul{margin:0 0 8px;padding-left:18px}
.meta,.lock,.lede{color:var(--muted);font-size:14px}.links{display:flex;gap:16px;flex-wrap:wrap}
form{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}input{flex:1 1 220px;padding:12px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit}
button{padding:12px 18px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;font-weight:600}
</style></head><body><main>${body}</main></body></html>`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (usd) => (usd >= 1e6 ? `$${(usd / 1e6).toFixed(2)}M` : `$${Math.round(usd / 1000)}K`);
const html = (s) => new Response(s, { headers: { "Content-Type": "text/html; charset=utf-8" } });
const redirect = (to, headers = {}) => new Response(null, { status: 302, headers: { Location: to, ...headers } });
