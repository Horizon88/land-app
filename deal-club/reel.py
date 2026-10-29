"""Turn a pick into a ~15 s vertical reel (1080x1920 MP4) plus an Instagram caption.

Slides: hook (price + size + setting) -> photos with one highlight each -> call to action.
The reel never shows the exact location or the source site: that is what members pay for.

Photos belong to whoever listed the property. Credit the agent, and ask before posting
when you can; most agents are glad of the free exposure.

Usage: python3 deal-club/reel.py [CODE ...]     (default: every pick in out/picks.json)
Writes deal-club/out/<CODE>/reel.mp4 and caption.txt
"""
import io, json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "deal-club", "out")
W, H, FPS, SECS = 1080, 1920, 30, 3.2
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CLUB = os.environ.get("CLUB_NAME", "Land Deal Club")
HANDLE = os.environ.get("CLUB_HANDLE", "@landdealclub")

def fetch(url):
    try:
        b = subprocess.run(["curl", "-sL", "-m", "30", "-A", "Mozilla/5.0", url],
                           capture_output=True, timeout=40).stdout
        im = Image.open(io.BytesIO(b)).convert("RGB")
        return im if im.width >= 300 else None
    except Exception:
        return None

def cover(im):
    """Fill 9:16, with a blurred copy behind landscape photos so nothing important is cropped."""
    bg = im.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    scale = W / im.width
    fg = im.resize((W, int(im.height * scale)))
    if fg.height >= H * 0.75:   # tall enough: just crop to fill
        s = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
        x, y = (im.width - W) // 2, (im.height - H) // 2
        return im.crop((x, y, x + W, y + H))
    bg.paste(fg, (0, (H - fg.height) // 2))
    return bg

def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= width:
            line = test
        else:
            lines.append(line); line = word
    return lines + [line]

def slide(photo, big, small="", top=""):
    im = cover(photo) if photo else Image.new("RGB", (W, H), (18, 32, 38))
    shade = Image.new("L", (1, H))
    for y in range(H):   # darken top and bottom so text reads on any photo
        shade.putpixel((0, y), int(170 * max(0, (y - H * 0.55) / (H * 0.45)) ** 1.3 + 120 * max(0, 1 - y / (H * 0.18))))
    im = Image.composite(Image.new("RGB", (W, H)), im, shade.resize((W, H)))
    d = ImageDraw.Draw(im)
    if top:
        d.text((70, 110), top, font=ImageFont.truetype(BOLD, 44), fill=(255, 255, 255))
    fb, fs = ImageFont.truetype(BOLD, 84), ImageFont.truetype(REG, 50)
    big_lines, small_lines = wrap(d, big, fb, W - 140), wrap(d, small, fs, W - 140) if small else []
    y = H - 260 - len(big_lines) * 100 - len(small_lines) * 64
    for ln in big_lines:
        d.text((70, y), ln, font=fb, fill=(255, 255, 255)); y += 100
    y += 16
    for ln in small_lines:
        d.text((70, y), ln, font=fs, fill=(225, 238, 240)); y += 64
    return im

def money(usd):
    return f"${usd / 1e6:.2f}M" if usd >= 1e6 else f"${usd / 1000:.0f}K"

def render(pick):
    t = pick["teaser"]
    folder = os.path.join(OUT, t["code"])
    os.makedirs(folder, exist_ok=True)
    photos = [p for p in (fetch(u) for u in t["photos"]) if p] or [None]
    where = t["region"] + ", " + t["country"] if t["region"] else t["country"]
    slides = [slide(photos[0], f"{t['acres']:g} acres. {t['headline']}. {money(t['usd'])}.", where, CLUB)]
    for i, line in enumerate(t["highlights"][1:4]):
        slides.append(slide(photos[(i + 1) % len(photos)], line, "", t["country"]))
    slides.append(slide(photos[-1], "Want the exact location and the listing?",
                        f"Members get it, plus a new deal every day. $5/month. Link in bio {HANDLE}"))

    clips = []
    for i, im in enumerate(slides):
        png = os.path.join(folder, f"s{i}.png"); im.save(png)
        clips.append(png)
    n = int(SECS * FPS)
    # slow Ken Burns zoom on each slide, then crossfade them together
    inputs, chains = [], []
    for i, png in enumerate(clips):
        inputs += ["-i", png]   # one still frame; zoompan turns it into n frames
        zoom = "min(zoom+0.0007,1.08)" if i % 2 == 0 else "if(eq(on,0),1.08,max(zoom-0.0007,1))"
        chains.append(f"[{i}:v]scale=1296:2304,zoompan=z='{zoom}':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1[v{i}]")
    last, offset = "v0", 0.0
    for i in range(1, len(clips)):
        offset += SECS - 0.4
        chains.append(f"[{last}][v{i}]xfade=transition=fade:duration=0.4:offset={offset:.2f}[x{i}]")
        last = f"x{i}"
    mp4 = os.path.join(folder, "reel.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
                    "-map", f"[{last}]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
                    "-crf", "21", "-movflags", "+faststart", mp4], check=True)
    for png in clips:
        os.remove(png)

    tags = ["#land", "#landforsale", "#realestate", "#offgrid", "#homestead", "#cheapland",
            f"#{t['country'].replace(' ', '').lower()}", f"#{t['country'].replace(' ', '').lower()}realestate"]
    caption = "\n".join([
        f"{t['acres']:g} acres in {where} for {money(t['usd'])} 🌏",
        "",
        *[f"• {h}" for h in t["highlights"]],
        "",
        f"Exact location + the original listing are in {CLUB}: a hand-picked land deal every day for $5/month. Link in bio.",
        "",
        "Photos: the listing agent. Not financial or legal advice; check foreign ownership rules before you buy.",
        "",
        " ".join(tags),
    ])
    open(os.path.join(folder, "caption.txt"), "w").write(caption + "\n")
    print(f"{t['code']}: {mp4} ({len(photos)} photos)")

if __name__ == "__main__":
    picks = json.load(open(os.path.join(OUT, "picks.json")))
    want = set(sys.argv[1:])
    for p in picks:
        if not want or p["teaser"]["code"] in want:
            render(p)
