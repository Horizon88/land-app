"""Central America: the three signals the user wants, and the rule 'at least 2 of 3'.

  big       10+ acres
  pacific   the listing mentions an ocean / Pacific view AND sits on the Pacific side
            (nearer the Pacific coast than the Caribbean, within 45 km of it)
  waterfall the listing mentions a waterfall (EN/ES)

Also: per-country foreign-ownership notes for the region.
"""
import math, re

# rough coast polylines (lat, lon), NW -> SE
PACIFIC = [(14.6, -92.2), (14.2, -91.6), (13.9, -91.0), (13.7, -90.1), (13.5, -89.3), (13.2, -88.0), (13.0, -87.5),
           (12.5, -87.2), (11.9, -86.6), (11.2, -85.9), (10.9, -85.8), (10.6, -85.7), (10.3, -85.85), (9.9, -85.6),
           (9.6, -85.1), (9.65, -84.6), (9.2, -84.0), (8.9, -83.7), (8.6, -83.5), (8.1, -82.9), (8.2, -82.2),
           (7.6, -81.6), (7.4, -80.4), (8.0, -80.4), (8.5, -79.8), (8.9, -79.5), (8.4, -78.6), (7.7, -78.1), (7.2, -77.9)]
CARIBBEAN = [(18.3, -88.1), (17.5, -88.2), (16.4, -88.4), (15.7, -88.6), (15.85, -87.4), (15.9, -86.0), (15.9, -85.5),
             (15.6, -84.5), (15.2, -83.4), (14.0, -83.4), (12.9, -83.6), (11.9, -83.8), (10.9, -83.7), (10.0, -83.0),
             (9.6, -82.6), (9.3, -82.2), (9.1, -81.5), (9.35, -79.9), (9.55, -78.9), (9.0, -77.8), (8.7, -77.4)]

BIG_ACRES = 10
VIEW = re.compile(r"ocean ?views?|sea ?views?|views? (?:of|to|over) the (?:ocean|sea|pacific|gulf|bay)|pacific views?|"
                  r"vistas? al mar|vistas? (?:al|del) (?:oc[eé]ano|pac[ií]fico|golfo)|vista oce[aá]nica|"
                  r"panoramic (?:ocean|pacific)|whale.?s? ?tail|ocean.?view", re.I)
WATERFALL = re.compile(r"waterfalls?|cascadas?|catarata|salto de agua|caída de agua|cascade", re.I)

FOREIGN = {
    "Costa Rica": "Costa Rica: foreigners can own titled land. The first 200 m from high tide is the Maritime-Terrestrial Zone (public strip + concessions; foreigners max 49% of a concession).",
    "Panama": "Panama: foreigners can own titled land, except within 10 km of a border. Many beach/island parcels are 'derechos posesorios' (possession rights, not title): check before buying.",
    "Nicaragua": "Nicaragua: foreigners can own titled land; the first 50 m from high tide is public. Title history can be messy (1980s confiscations): get a full title search.",
    "Belize": "Belize: foreigners can own freehold land like citizens; transfer tax ~8% for non-citizens.",
    "El Salvador": "El Salvador: foreigners can own land; rural holdings are capped at 245 ha per owner.",
    "Guatemala": "Guatemala: foreigners can own land, except a 3 km coastal and 15 km border strip (state 'reserva territorial', leased not owned).",
    "Honduras": "Honduras: within 40 km of the coast or borders foreigners can own only urban/tourism plots, typically through a declaration or a Honduran company.",
}

def _seg_dist_km(lat, lon, a, b):
    # flat-earth approximation is fine at these scales
    kx = 111.32 * math.cos(math.radians(lat)); ky = 110.57
    px, py = lon * kx, lat * ky
    ax, ay, bx, by = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def coast_dist(lat, lon, line):
    return min(_seg_dist_km(lat, lon, a, b) for a, b in zip(line, line[1:]))

def pacific_side(lat, lon):
    if lat is None or lon is None: return False, None
    p, c = coast_dist(lat, lon, PACIFIC), coast_dist(lat, lon, CARIBBEAN)
    return (p < c and p <= 45), round(p, 1)

def signals(text, lat, lon, acres, country=None):
    """-> (list of signals present, km to the Pacific coast or None)."""
    s = []
    if (acres or 0) >= BIG_ACRES: s.append("big")
    side, pkm = pacific_side(lat, lon)
    if side and country != "Belize" and VIEW.search(text or ""): s.append("pacific")
    if WATERFALL.search(text or ""): s.append("waterfall")
    return s, pkm
