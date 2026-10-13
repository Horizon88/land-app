# Land Scout — Facebook + DOL auto-capture (for Siri)

A tiny Chrome/Edge extension that reads Thai land-sale posts from **your own
logged-in Facebook** (feed, groups, Marketplace) and DOL parcels, and sends
them into the land app as **scored listings** — with distress detection and
bid guidance applied automatically.

Facebook posts are behind a login wall, so this is the *only* way to pull them:
the extension runs inside your session, in your browser. Nothing leaves your
machine except when you click **Send to app**.

## Install (2 minutes)

1. Open **chrome://extensions** (or edge://extensions).
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked** and pick this `browser_ext` folder.
4. Pin the **Land Scout** icon to your toolbar.

## Use it

1. Log into Facebook and open the Thai land-sale **groups** (or Marketplace).
   From the app: **🔗 Add by link → Hunt Facebook** opens the right searches.
2. **Scroll.** As land posts (with a price + ไร่/rai) scroll past, a green
   toast confirms each capture — you don't click anything.
3. Click the **Land Scout toolbar icon** → **Send to app**. It opens the land
   app and imports every new post into your list, scored and mapped.

## What it captures per post

price (฿ / ล้าน / per-rai) · size (ไร่ + งาน + วา) · GPS coords if present ·
title-deed hint (Chanote / NS3G / SPK warning) · **distress signals**
(ด่วน / ขายด่วน / ลดราคา / owner-direct / leaving …) · seller name · contact
phone · first photo · the post permalink. Duplicates are skipped automatically.

## In the app

Each FB post becomes a Thailand land listing with `src:fb-capture`, so it gets
the same treatment as everything else: distress score, **💰 bid guidance**
(fair value + suggested opening bid vs the ask), and full deal tracking
(status, offers, You/Siri approvals). Sort by 🔥 distress to see the keenest
sellers first.

## Privacy

Everything is local to your browser until you press **Send to app**. Your
Facebook login and cookies are never read or transmitted — the extension only
reads the visible text/photos of posts you scroll past, exactly what you can
already see.
