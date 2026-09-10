
(function(){
  async function refreshCacheBadge(){
    try{
      const r=await fetch('/api/live-cache/status');
      if(!r.ok) return;
      const data=await r.json();
      const h=data.h2s||{};
      if(!h.available) return;

      const heading=[...document.querySelectorAll('.card-title,.small')].find(
        el=>/H₂S Monitor Network|H2S Monitor Network/i.test(el.textContent||'')
      );
      if(!heading) return;

      let badge=document.querySelector('.h2s-cache-age');
      if(!badge){
        badge=document.createElement('span');
        badge.className='h2s-cache-age cache-freshness';
        heading.parentElement.appendChild(badge);
      }

      const s=Number(h.age_seconds||0);
      badge.textContent =
        s<90 ? 'Live cache • moments ago' :
        s<3600 ? `Live cache • ${Math.round(s/60)} min old` :
        `Cached fallback • ${Math.round(s/3600)} hr old`;
    }catch(e){}
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',refreshCacheBadge);
  }else{
    refreshCacheBadge();
  }

  setInterval(refreshCacheBadge,60000);
})();
