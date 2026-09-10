
(function(){
  const state = {
    snapshot: new Map(),
    lastPrediction: null,
    installed: false,
    observer: null,
    rerenderTimer: null
  };

  const $=(s,r=document)=>r.querySelector(s);
  const $$=(s,r=document)=>[...r.querySelectorAll(s)];

  async function getJson(url){
    const r=await fetch(url,{
      cache:"no-store",
      headers:{"Accept":"application/json"}
    });
    if(!r.ok) throw new Error(`${url} returned ${r.status}`);
    return await r.json();
  }

  function num(v){
    const x=Number(v);
    return Number.isFinite(x)?x:null;
  }

  function riskCard(){
    return $("#riskCard") ||
      $(".risk-card") ||
      $$(".card,.panel,article").find(el=>
        /CURRENT ODOR RISK/i.test(el.textContent||"")
      );
  }

  function driverBox(){
    const card=riskCard();
    return card
      ? ($("#drivers",card)||$(".drivers",card)||$(".primary-drivers",card))
      : null;
  }

  function normalizeName(name){
    const raw=String(name||"").trim();
    const s=raw.toLowerCase();

    if(s.includes("tide")) return "Tide influence";
    if(s.includes("wind")||s.includes("dispersion")) return "Low wind / dispersion";
    if(s.includes("temp")) return "Temperature";
    if(s.includes("live h2s")||s.includes("live h₂s")||s==="h2s") return "Live H₂S";
    if(s.includes("rain")) return "Rainfall";
    if(s.includes("forecast h2s")||s.includes("forecast h₂s")) return "Forecast H₂S";
    if(s.includes("excursion")) return "Experimental excursion potential";
    if(s.includes("wastewater")) return "Wastewater contribution";

    return raw;
  }

  function readRenderedDrivers(){
    const box=driverBox();
    if(!box) return [];

    const rows=[];

    $$(".driver",box).forEach(row=>{
      const label=$(".driver-top span",row)?.textContent?.trim();
      const text=$(".driver-top b",row)?.textContent?.trim();
      const width=$(".bar i",row)?.style?.width;

      if(!label) return;

      let score=num((text||"").replace("%",""));
      if(score===null){
        score=num((width||"").replace("%",""));
      }
      if(score===null) return;

      rows.push({
        name:normalizeName(label),
        score:Math.max(0,Math.min(100,score))
      });
    });

    return rows;
  }

  function preserveSnapshot(){
    const rows=readRenderedDrivers();

    // Only learn from a meaningful multi-driver render. This prevents the
    // broken one-row state from poisoning the canonical snapshot.
    if(rows.length<2) return;

    rows.forEach(d=>{
      // ML-derived values are refreshed separately, so preserve only
      // the environmental/legacy drivers here.
      if(
        d.name==="Wastewater contribution" ||
        d.name==="Forecast H₂S" ||
        d.name==="Experimental excursion potential"
      ){
        return;
      }

      state.snapshot.set(d.name,d.score);
    });
  }

  function wastewaterScore(pred){
    const excess=Math.max(
      0,
      num(pred?.excess_wastewater_contribution_ppb)||0
    );
    return Math.min(100,(excess/15)*100);
  }

  function mlDrivers(pred){
    if(!pred?.model_available) return [];

    const peak=Math.max(
      0,
      num(pred.predicted_next_60m_max_h2s_ppb)||0
    );

    const excursion=Math.max(
      0,
      Math.min(
        1,
        num(pred.excursion_probability)||0
      )
    );

    return [
      {
        name:"Forecast H₂S",
        score:Math.min(100,(peak/60)*100),
        display:`${peak.toFixed(1)} ppb`
      },
      {
        name:"Wastewater contribution",
        score:wastewaterScore(pred),
        display:String(
          pred.wastewater_contribution_level||"Low"
        )
      },
      {
        name:"Experimental excursion potential",
        score:excursion*100,
        display:`${Math.round(excursion*100)}%`
      }
    ];
  }

  function combinedDrivers(){
    const out=[];

    state.snapshot.forEach((score,name)=>{
      out.push({
        name,
        score,
        display:String(Math.round(score))
      });
    });

    out.push(...mlDrivers(state.lastPrediction));

    // Deduplicate by name.
    const dedup=new Map();
    out.forEach(d=>{
      dedup.set(d.name,d);
    });

    return [...dedup.values()]
      .sort((a,b)=>b.score-a.score);
  }

  function render(){
    const box=driverBox();
    if(!box) return;

    const drivers=combinedDrivers();

    // If we have not yet captured any environmental drivers, do not erase
    // whatever the legacy renderer currently has.
    if(
      state.snapshot.size===0 &&
      drivers.length<=3
    ){
      return;
    }

    box.innerHTML="";

    drivers.forEach(d=>{
      const row=document.createElement("div");
      row.className="driver driver-v112";

      row.innerHTML=`
        <div class="driver-top">
          <span>${d.name}</span>
          <b>${d.display}</b>
        </div>
        <div class="bar">
          <i style="width:${Math.max(3,Math.min(100,d.score))}%"></i>
        </div>`;

      box.appendChild(row);
    });
  }

  function hideNarrative(){
    const card=riskCard();
    if(!card) return;

    const p=$("#riskNarrative",card) ||
      $(".risk-narrative",card) ||
      $$("p",card).find(el=>
        /trained ml forecast|engineering risk index|next-hour h₂s|next-hour h2s/i.test(el.textContent||"")
      );

    if(p){
      p.textContent="";
      p.style.display="none";
    }
  }

  async function updatePrediction(){
    try{
      const pred=await getJson("/api/ml/prediction");
      if(pred?.model_available){
        state.lastPrediction=pred;
        render();
      }
    }catch(e){
      console.warn("v1.1.2 prediction refresh failed",e);
    }
  }

  function scheduleRender(){
    clearTimeout(state.rerenderTimer);

    state.rerenderTimer=setTimeout(()=>{
      preserveSnapshot();
      render();
      hideNarrative();
    },80);
  }

  function installObserver(){
    if(state.observer) return;

    state.observer=new MutationObserver(()=>{
      preserveSnapshot();

      const rows=readRenderedDrivers();

      // If a later legacy/override paint collapses the list, restore ours.
      if(
        state.snapshot.size>0 &&
        rows.length<combinedDrivers().length
      ){
        scheduleRender();
      }

      hideNarrative();
    });

    state.observer.observe(
      document.body,
      {
        childList:true,
        subtree:true,
        characterData:true
      }
    );
  }

  function boot(){
    // Capture the legacy list before later overrides can destroy it.
    let tries=0;

    const capture=setInterval(()=>{
      tries+=1;
      preserveSnapshot();

      if(state.snapshot.size>=2 || tries>=30){
        clearInterval(capture);
        updatePrediction();
        render();
      }
    },100);

    installObserver();

    setTimeout(updatePrediction,1000);
    setInterval(updatePrediction,60000);
    hideNarrative();
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",boot);
  }else{
    boot();
  }
})();
