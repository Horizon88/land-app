// Auto-capture BAM (Bangkok Commercial Asset Management) NPA property pages
// as you browse them. BAM's search API is walled, but each property DETAIL
// page embeds the full asset record server-side — so browsing a land listing
// captures it. Every BAM asset is a bank-repossessed forced sale (distress).

(() => {
  const store = {
    async load(){ return (await chrome.storage.local.get('bam_items')).bam_items || {}; },
    async save(p){ await chrome.storage.local.set({bam_items: p}); },
  };

  function esc(field){ return new RegExp('\\\\"'+field+'\\\\":\\\\"([^"\\\\]{0,800})'); }
  function escNum(field){ return new RegExp('\\\\"'+field+'\\\\":\\s*"?([0-9][0-9.,]*)'); }

  function extract(){
    const idm = location.pathname.match(/\/property\/(\d+)/);
    if(!idm) return null;
    const id = idm[1];
    const html = document.documentElement.outerHTML;
    if(!new RegExp('\\\\"id\\\\":'+id+',\\\\"market_code\\\\"').test(html)) return null; // not the canonical record yet
    const g = (re) => { const m = html.match(re); return m ? m[1] : ''; };
    const f  = (field) => g(esc(field));
    const fn = (field) => g(escNum(field));

    const rai = parseFloat(fn('rai')||'0')||0;
    const ngan = parseFloat(fn('ngan')||'0')||0;
    const wa = parseFloat(fn('wa')||'0')||0;
    const sqm_land = rai*1600 + ngan*400 + wa*4;
    const asset_type = f('npa_type') || f('col_typedesc');
    const price = parseFloat((fn('center_price')||'0').replace(/,/g,''))||0;

    // JSON-LD for a clean name + image
    let name='', img='';
    const ld = html.match(/"@type":"Product","name":"([^"]+)".*?"image":"([^"]+)"/s);
    if(ld){ name=ld[1]; img=ld[2].replace(/\\\//g,'/'); }

    return {
      id, source:'bam', captured_at:new Date().toISOString(),
      asset_type, province: f('province_name'), district: f('city_name'),
      rai: Math.round((rai + ngan/4 + wa/400)*1000)/1000,
      sqm_land: Math.round(sqm_land),
      lat: parseFloat(f('gps_lat1'))||null, lng: parseFloat(f('gps_long1'))||null,
      price_thb: price, grade: f('grade'), state: f('asset_state'),
      note: f('note').slice(0,300), name: name.slice(0,160), img,
      url: `https://www.bam.co.th/th/th/npa/property/${id}`,
    };
  }

  const LAND_TYPES = ['ที่ดิน','ที่ดินเปล่า','ที่ดินพร้อมสิ่งปลูกสร้าง'];

  async function capture(){
    const rec = extract();
    if(!rec || !rec.price_thb) return;
    const items = await store.load();
    if(items[rec.id]) return;
    items[rec.id] = rec;
    await store.save(items);
    const isLand = LAND_TYPES.some(t => (rec.asset_type||'').includes(t));
    toast(`🏦 Captured BAM ${isLand?'LAND':rec.asset_type||'asset'} · ฿${rec.price_thb.toLocaleString()} · ${Object.keys(items).length} total`);
  }

  function toast(msg){
    let t = document.getElementById('__land_scout_bam_toast');
    if(!t){ t=document.createElement('div'); t.id='__land_scout_bam_toast';
      t.style.cssText='position:fixed;bottom:20px;right:20px;background:#3a1a1a;color:#ff9090;border:1px solid #702030;padding:10px 14px;border-radius:8px;z-index:99999;font-family:sans-serif;font-size:13px;box-shadow:0 2px 10px rgba(0,0,0,.45)';
      document.body.appendChild(t); }
    t.textContent=msg; t.style.opacity='1'; clearTimeout(t._h);
    t._h=setTimeout(()=>{ t.style.opacity='0'; t.style.transition='opacity .4s'; }, 3800);
  }

  // Property pages load their record via streamed data — retry a few times.
  let tries=0;
  const iv=setInterval(()=>{ tries++; capture(); if(tries>8) clearInterval(iv); }, 1200);
  new MutationObserver(()=>capture()).observe(document.body,{childList:true,subtree:true});
})();
