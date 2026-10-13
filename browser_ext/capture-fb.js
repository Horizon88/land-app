// Auto-capture Facebook posts that look like Thai land-sale listings.
// Runs inside YOUR logged-in Facebook (feed / groups / marketplace) and
// pulls posts with price + rai signals — the only way to read auth-walled
// FB content. Captures text, price, size, coords, PHOTOS, the post
// permalink, the seller name, and distress signals, then dedups and
// stores locally. Send them into the land app from the toolbar popup.

(() => {
  const store = {
    async load(){ return (await chrome.storage.local.get('fb_posts')).fb_posts || {}; },
    async save(p){ await chrome.storage.local.set({fb_posts: p}); },
  };

  // Distress language (Thai + English) — flagged at capture so a "must sell"
  // post lands already marked.
  const DISTRESS = [
    [/ด่วน|ขายด่วน|ต้องการเงินด่วน/i, 'urgent'],
    [/ขายขาดทุน|ยอมขาดทุน/i, 'selling-at-loss'],
    [/ลดราคา|ลดแล้ว|price\s*drop|reduced/i, 'price-drop'],
    [/ต่อรอง|ต่อรองได้|negotiable|offer/i, 'negotiable'],
    [/เจ้าของขายเอง|owner\s*(?:direct|sale)|by\s*owner/i, 'owner-direct'],
    [/urgent|must\s*sell|quick\s*sale|fire\s*sale/i, 'urgent'],
    [/ย้าย(?:กลับ|ประเทศ)|leaving|relocat/i, 'leaving'],
  ];

  function looksLikeLandPost(text){
    if(!text || text.length < 40 || text.length > 4000) return false;
    const hasArea = /ไร่|\brai\b|ตารางวา|งาน\b|sqwa|sq\.?\s*wah|ไร่/i.test(text);
    const hasPrice = /ราคา|price|บาท|baht|฿|thb\b|ล้าน|million/i.test(text);
    return hasArea && hasPrice;
  }

  function extractFbPost(text, article){
    const out = { source: 'fb', captured_at: new Date().toISOString() };
    const m = (re) => (text.match(re) || [])[1];

    // Coord (from an embedded maps link or a lat,lng pair)
    let c = text.match(/[?&]q=(-?\d+\.\d+)[, ]+(-?\d+\.\d+)/)
         || text.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/)
         || text.match(/(-?\d{1,2}\.\d{4,})[,\s]+(\d{1,3}\.\d{4,})/);
    if(c && parseFloat(c[1])>5 && parseFloat(c[1])<21){ out.lat = parseFloat(c[1]); out.lng = parseFloat(c[2]); }

    // Size: rai + ngan + wah → rai (1 rai = 4 ngan = 400 wah)
    let rai = parseFloat((m(/(\d[\d.,]*)\s*ไร่/) || m(/(\d[\d.,]*)\s*\brai\b/i) || '').replace(/,/g,'')) || 0;
    const ngan = parseFloat((m(/(\d[\d.,]*)\s*งาน/) || '').replace(/,/g,'')) || 0;
    const wah = parseFloat((m(/(\d[\d.,]*)\s*(?:ตารางวา|ตร\.?ว|sqwa|sq\.?\s*wah)/i) || '').replace(/,/g,'')) || 0;
    rai += ngan/4 + wah/400;
    if(rai > 0) out.rai = Math.round(rai*1000)/1000;

    // Price → baht (handle ล้าน / million)
    let priceThb = null;
    const mil = text.match(/([\d.,]+)\s*(?:ล้าน|million|mb\b|m฿)/i);
    if(mil) priceThb = Math.round(parseFloat(mil[1].replace(/,/g,'')) * 1e6);
    if(!priceThb){ const p = m(/ราคา\s*[:.]?\s*([\d,]{5,})/) || m(/price\s*[:.]?\s*([\d,]{5,})/i) || m(/฿\s*([\d,]{5,})/); if(p) priceThb = parseInt(p.replace(/,/g,'')); }
    if(priceThb && out.rai && /ต่อไร่|per\s*rai|\/rai|\/ไร่|ไร่ละ/i.test(text)){ priceThb *= out.rai; out.price_note = 'converted from per-rai'; }
    if(priceThb) out.price_thb = priceThb;

    // Contact phone
    const ph = text.match(/\b0\d[- ]?\d{3,4}[- ]?\d{4}\b/); if(ph) out.contact = ph[0].replace(/[- ]/g,'');

    // Title deed hint
    if(/โฉนด|chanote|krut\s*daeng|น\.?ส\.?\s*4/i.test(text)) out.title_hint = 'Chanote';
    else if(/น\.?ส\.?\s*3\s*ก/i.test(text)) out.title_hint = 'NS3G';
    else if(/สปก|ส\.?ป\.?ก|spk/i.test(text)) out.title_hint = 'SPK (not sellable to foreigners)';

    // Distress signals
    const ds = []; for(const [re,tag] of DISTRESS){ if(re.test(text) && !ds.includes(tag)) ds.push(tag); }
    if(ds.length) out.distress = ds;

    // Poster / seller name (author link near the top of the article)
    const author = article.querySelector('h3 a, h4 a, strong a, [role="link"] strong');
    if(author && author.textContent.trim()) out.seller = author.textContent.trim().slice(0,60);

    // Permalink to the post (timestamp link / posts / permalink / story)
    let perma = '';
    const link = article.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[href*="/groups/"][href*="/posts/"], a[href*="/share/p/"], a[href*="/marketplace/item/"]');
    if(link){ try { perma = new URL(link.getAttribute('href'), location.origin).href.split('?')[0]; } catch(e){} }
    out.permalink = perma || location.href;

    // First real photo (skip tiny avatars/emoji)
    let img = '';
    for(const im of article.querySelectorAll('img')){
      const s = im.src || '';
      if(/scontent|fbcdn/.test(s) && (im.naturalWidth>200 || im.width>200)){ img = s; break; }
    }
    if(img) out.img = img;

    out.text_preview = text.slice(0, 400).replace(/\s+/g, ' ').trim();
    return out;
  }

  async function scanArticles(){
    const articles = document.querySelectorAll('[role="article"]');
    const posts = await store.load();
    let newCount = 0;
    for(const a of articles){
      const text = a.innerText;
      if(!looksLikeLandPost(text)) continue;
      let h = 0; const s = text.slice(0, 300);
      for(let i=0; i<s.length; i++) h = ((h<<5) - h + s.charCodeAt(i)) | 0;
      const id = 'fb_' + Math.abs(h).toString(36);
      if(posts[id]) continue;
      posts[id] = { id, ...extractFbPost(text, a) };
      newCount++;
    }
    if(newCount){
      await store.save(posts);
      const total = Object.keys(posts).length;
      try { chrome.runtime.sendMessage({type:'count', n: total}); } catch(e){}
      showToast(`📘 +${newCount} land post${newCount>1?'s':''} · ${total} captured — open the toolbar to send`);
    }
  }

  function showToast(msg){
    let t = document.getElementById('__land_scout_fb_toast');
    if(!t){
      t = document.createElement('div');
      t.id = '__land_scout_fb_toast';
      t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#0f2a1a;color:#7ce8a8;border:1px solid #1e6a40;padding:10px 14px;border-radius:8px;z-index:99999;font-family:sans-serif;font-size:13px;box-shadow:0 2px 10px rgba(0,0,0,0.45)';
      document.body.appendChild(t);
    }
    t.textContent = msg; t.style.opacity = '1';
    clearTimeout(t._h); t._h = setTimeout(()=>{ t.style.opacity = '0'; t.style.transition='opacity 0.4s'; }, 3800);
  }

  const debounced = (() => { let h; return () => { clearTimeout(h); h = setTimeout(scanArticles, 800); }; })();
  new MutationObserver(debounced).observe(document.body, {childList:true, subtree:true});
  setTimeout(scanArticles, 2000);
})();
