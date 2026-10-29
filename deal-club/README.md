# Land Deal Club

The LandGlobally model on top of this repo's listings: pick cheap land in beautiful
places, post a short reel to Instagram, and charge $5/month for the exact location and
the link to the original listing.

| Step | Command | Output |
|---|---|---|
| 1. Pick deals | `python3 deal-club/pick.py 7 2` | `out/picks.json`: 7 picks, at most 2 per country |
| 2. Make reels | `python3 deal-club/reel.py` | `out/<CODE>/reel.mp4` (1080×1920, ~14 s) + `caption.txt` |
| 3. Publish to members | `CLUB_URL=… CLUB_ADMIN_TOKEN=… python3 deal-club/publish.py` | picks go into the worker's KV; codes go into `posted.json` |
| 4. Post | upload `reel.mp4` with `caption.txt` to Instagram, one a day | |

`out/` is gitignored on purpose. **This repo is public**, so nothing members pay for may
be committed. That includes `docs/listings.json`, which already holds every source link,
so anyone who finds the repo could skip the paywall. Before launch, make this repo private
or move the data to `Horizon88/landsearchprivate`, and serve the free app from somewhere
that isn't linked from the club.

## How picks are chosen (`pick.py`)

- **Qualifies:** land, $15k–$400k, at least 1 acre, at least one photo, no deal-killer
  warnings, location not approximate, not archived, not posted before.
- **Nice place:** beachfront or within 500 m of the sea, sea views, within 3 km of a ski
  lift, within 300 m of a lake, or a view score of 55 or more.
- **Value:** price per acre against the median for land of half to twice the size in the
  same country. Large blocks are always cheaper per acre, so comparing against every plot
  in the country would overstate the deal. Anything more than 6× cheaper is skipped,
  because that is usually a bad price or a bad area in the source data.

Read each pick's listing before posting. The scrapers make mistakes, and listings sell.

## Paywall (`worker.js`)

One Cloudflare Worker, free tier:

- `/` landing page with locked teasers and a **Join for $5/month** button (a Stripe Payment Link)
- `/welcome?session_id=…` logs the buyer in straight after checkout
- `/login` emails a one-hour magic link (Resend); sessions last 30 days
- `/members` every pick: location, satellite map, original listing, price per acre against the area
- `/stripe/webhook` signed Stripe events keep KV in step; a cancelled subscription is locked out
- `/admin/publish` used by `publish.py` (Bearer token)

Tested locally against a fake KV store and a fake Stripe: forged webhooks and bad admin
tokens are rejected, the landing page doesn't leak listing links, and members are logged
out once their subscription is cancelled. It has not run against live Stripe or Resend yet.

### Setup (about 30 minutes)

1. **Stripe:** create a product "Land Deal Club" with a $5/month recurring price, then a
   Payment Link for it. Under the link's *After payment* settings, choose *Don't show
   confirmation page* and redirect to `https://<worker>/welcome?session_id={CHECKOUT_SESSION_ID}`.
   Turn on the Customer Portal so members can cancel on their own.
2. **Webhook:** Stripe Dashboard → Developers → Webhooks → endpoint
   `https://<worker>/stripe/webhook` with events `checkout.session.completed`,
   `customer.subscription.updated` and `customer.subscription.deleted`.
3. **Resend:** add and verify a sending domain, then create an API key.
4. **Cloudflare:**
   ```bash
   cd deal-club
   npx wrangler kv namespace create CLUB        # paste the id into wrangler.toml
   for s in STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET SESSION_SECRET ADMIN_TOKEN RESEND_API_KEY; do npx wrangler secret put $s; done
   npx wrangler deploy
   ```
   Set `PAYMENT_LINK` and `FROM_EMAIL` in `wrangler.toml`. For `SESSION_SECRET` and
   `ADMIN_TOKEN`, use long random strings (`openssl rand -hex 32`).
5. Put the worker URL (or a custom domain) in the Instagram bio.

## Money

On a $5 charge, Stripe takes 2.9% + 30¢ for a domestic US card plus 0.7% for Billing,
which comes to about $0.48. You keep about $4.52 per member per month, before tax.
International cards and currency conversion cost more. [1]

Running costs at the start are close to zero: the Cloudflare Workers and KV free tiers,
the Resend free tier, and the Instagram account.

## Instagram

- Post by hand to begin with. Automating it later works through the Instagram Graph API
  content-publishing endpoint. That needs a professional (Business or Creator) account,
  supports reels (`media_type=REELS`), and allows 100 API-published posts in a rolling
  24 hours. [2]
- **Photos are copyrighted** by the agent or photographer. The caption credits the agent,
  but credit alone isn't permission. Ask the agent first (most agents are glad of the
  exposure) or use your own footage. Instagram removes reposts that get reported, and
  repeated reports can take the account down.
- The caption says it isn't financial or legal advice and tells buyers to check
  foreign-ownership rules. Many of these countries restrict foreign buyers; Thailand, for
  example, does not let foreigners own land outright.

## Sources

1. Stripe pricing: 2.9% + 30¢ per successful domestic card charge; Billing at 0.7% of
   Billing volume on pay-as-you-go. https://stripe.com/pricing (checked 2026-10-29)
2. Meta, Instagram Platform, Content Publishing: professional accounts, `media_type=REELS`,
   and "limited to 100 API-published posts within a 24-hour moving period".
   https://developers.facebook.com/docs/instagram-platform/content-publishing (checked 2026-10-29)
