const APP_URL = 'https://horizon88.github.io/land-app/';

async function refresh(){
  const {parcels = {}, fb_posts = {}, bam_items = {}} = await chrome.storage.local.get(['parcels', 'fb_posts', 'bam_items']);
  document.getElementById('dolCount').textContent = Object.keys(parcels).length;
  document.getElementById('fbCount').textContent = Object.keys(fb_posts).length;
  document.getElementById('bamCount').textContent = Object.keys(bam_items).length;
}

document.getElementById('pushBtn').onclick = async () => {
  const {parcels = {}, fb_posts = {}, bam_items = {}} = await chrome.storage.local.get(['parcels', 'fb_posts', 'bam_items']);
  const all = { dol: Object.values(parcels), fb: Object.values(fb_posts), bam: Object.values(bam_items) };
  if(all.dol.length === 0 && all.fb.length === 0 && all.bam.length === 0){
    alert('No captured items yet. Browse DOL, Facebook, or BAM first — the extension captures silently as you scroll.');
    return;
  }
  // Encode compact JSON in URL hash
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(all))));
  chrome.tabs.create({url: APP_URL + '#captured=' + payload});
};

document.getElementById('copyBtn').onclick = async () => {
  const {parcels = {}, fb_posts = {}} = await chrome.storage.local.get(['parcels', 'fb_posts']);
  const rows = [];
  rows.push(['source','deed_or_id','lat','lng','rai','price_thb','location','contact','url'].join('\t'));
  for(const p of Object.values(parcels)){
    rows.push(['dol', p.deed||'', p.lat||'', p.lng||'', p.rai_decimal||'', '', p.subdistrict||'', '', p.source_url||''].join('\t'));
  }
  for(const p of Object.values(fb_posts)){
    rows.push(['fb', p.id, p.lat||'', p.lng||'', p.rai||'', p.price_thb||'', p.location||'', p.contact||'', p.source_url||''].join('\t'));
  }
  await navigator.clipboard.writeText(rows.join('\n'));
  const btn = document.getElementById('copyBtn');
  const orig = btn.textContent;
  btn.textContent = '✓ Copied ' + (rows.length - 1) + ' rows';
  setTimeout(()=>{ btn.textContent = orig; }, 2000);
};

document.getElementById('clearBtn').onclick = async () => {
  if(!confirm('Clear all captured DOL parcels, FB posts, and BAM assets?')) return;
  await chrome.storage.local.set({parcels: {}, fb_posts: {}, bam_items: {}});
  refresh();
};

refresh();
