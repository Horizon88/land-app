// Auto-capture Thai DOL parcels as you browse landsmaps.dol.go.th
// Watches for parcel info-panel updates and pulls the fields silently.

(() => {
  const APP_URL = 'https://horizon88.github.io/land-app/';

  const store = {
    async load(){ return (await chrome.storage.local.get('parcels')).parcels || {}; },
    async save(p){ await chrome.storage.local.set({parcels: p}); },
  };

  // DOL info panel text patterns (matches the "Land Parcel Information" sidebar)
  function extractDol(text){
    const out = {};
    const m = (re) => (text.match(re) || [])[1];
    out.deed = m(/Title\s*Deed\s*Number\s*[:.]?\s*(\d+)/i)
            || m(/โฉนดเลขที่\s*[:.]?\s*(\d+)/);
    if(!out.deed) return null;
    out.tambon_num = m(/Tambon\s*Number\s*[:.]?\s*(\d+)/i);
    out.land_num   = m(/Land\s*Number\s*[:.]?\s*(\d+)/i);
    out.map_sheet  = m(/Map\s*Sheet\s*[:.]?\s*([^\n]+?)(?=\n|Sub|$)/i);
    out.subdistrict= m(/Sub[- ]?District\s*[:.]?\s*([A-Za-z0-9\s฀-๿]+?)(?=\n|District|$)/i);
    out.district   = m(/(?:^|\n)District\s*[:.]?\s*([A-Za-z0-9\s฀-๿]+?)(?=\n|Province|$)/i);
    out.province   = m(/Province\s*[:.]?\s*([A-Za-z0-9\s฀-๿]+?)(?=\n|Area|$)/i);
    const area = text.match(/Area\s*[:.]?\s*(\d+)\s*Rai\s*(\d+)\s*ngan\s*([\d.]+)\s*square\s*wah/i);
    if(area){
      out.rai = parseInt(area[1]);
      out.ngan = parseInt(area[2]);
      out.wah = parseFloat(area[3]);
      out.rai_display = `${out.rai}-${out.ngan}-${out.wah}`;
      out.rai_decimal = +(out.rai + out.ngan/4 + out.wah/400).toFixed(4);
    }
    out.treasury = m(/(\d+)\s*Baht\s*\/\s*sq(?:uare)?\s*wah/i);
    const c = text.match(/Land\s*Parcel\s*Coordinate\s*[:.]?\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/i);
    if(c){ out.lat = parseFloat(c[1]); out.lng = parseFloat(c[2]); }
    return out;
  }

  async function capture(){
    const text = document.body.innerText;
    if(!/Title\s*Deed\s*Number|โฉนดเลขที่/i.test(text)) return;
    const parcel = extractDol(text);
    if(!parcel || !parcel.deed) return;
    const parcels = await store.load();
    if(parcels[parcel.deed]) return;   // already have it
    parcels[parcel.deed] = {
      ...parcel,
      captured_at: new Date().toISOString(),
      source: 'dol',
      source_url: location.href,
    };
    await store.save(parcels);
    // Small toast
    showToast(`🇹🇭 Captured deed #${parcel.deed} · ${Object.keys(parcels).length} total`);
  }

  function showToast(msg){
    let t = document.getElementById('__land_scout_toast');
    if(!t){
      t = document.createElement('div');
      t.id = '__land_scout_toast';
      t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1a3a2a;color:#7ce38b;border:1px solid #7ce38b;padding:10px 14px;border-radius:6px;z-index:99999;font-family:sans-serif;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.4)';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = '1';
    clearTimeout(t._h);
    t._h = setTimeout(()=>{ t.style.opacity = '0'; t.style.transition = 'opacity 0.4s'; }, 3500);
  }

  // Watch for DOM changes — DOL uses SPA routing, info panel updates without page reload
  const debounced = (() => {
    let h; return () => { clearTimeout(h); h = setTimeout(capture, 500); };
  })();
  new MutationObserver(debounced).observe(document.body, {childList: true, subtree: true, characterData: true});
  // Also immediate on load
  setTimeout(capture, 1500);
})();
