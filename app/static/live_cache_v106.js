
(function(){
  async function decorateFreshness(){
    try{
      const r=await fetch('/api/live-cache/status');
      if(!r.ok) return;
      const data=await r.json();
      const h=data.h2s||{};
      const title=[...document.querySelectorAll('.card-title')].find(
        n=>/H₂S Monitor Network|H2S Monitor Network/i.test(n.textContent||'')
      );
      if(title && h.available){
        let tag=document.querySelector('.cache-freshness-h2s');
        if(!tag){
          tag=document.createElement('span');
          tag.className='cache-freshness cache-freshness-h2s';
          title.parentElement.appendChild(tag);
        }
        const s=Number(h.age_seconds||0);
        tag.textContent=s<90?'updated moments ago':s<3600?`updated ${Math.round(s/60)} min ago`:`updated ${Math.round(s/3600)} hr ago`;
      }
    }catch(e){}
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',decorateFreshness);
  }else{
    decorateFreshness();
  }
  setInterval(decorateFreshness,60000);
})();
