
(function(){
  const $=(s,r=document)=>r.querySelector(s);
  const $$=(s,r=document)=>[...r.querySelectorAll(s)];

  async function j(url){
    const r=await fetch(url,{cache:"no-store",headers:{"Accept":"application/json"}});
    if(!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }

  function num(v){ const x=Number(v); return Number.isFinite(x)?x:null; }

  function fmtTs(v){
    if(!v) return "timestamp unavailable";
    const d=new Date(v);
    if(Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString([],{
      month:"short",day:"numeric",hour:"numeric",minute:"2-digit"
    });
  }

  function age(v){
    if(!v) return "";
    const d=new Date(v);
    if(Number.isNaN(d.getTime())) return "";
    const s=Math.max(0,(Date.now()-d.getTime())/1000);
    if(s<90) return "moments ago";
    if(s<3600) return `${Math.round(s/60)} min ago`;
    if(s<86400) return `${Math.round(s/3600)} hr ago`;
    return `${Math.round(s/86400)} d ago`;
  }

  function riskCard(){
    return $("#riskCard") || $(".risk-card") ||
      $$(".card,.panel,article").find(x=>/CURRENT ODOR RISK/i.test(x.textContent||""));
  }

  function driversBox(){
    const c=riskCard();
    return c ? ($("#drivers",c)||$(".drivers",c)||$(".primary-drivers",c)) : null;
  }

  function canon(name){
    const s=String(name||"").toLowerCase();
    if(s.includes("tide")) return "Tide influence";
    if(s.includes("wind")||s.includes("dispersion")) return "Low wind / dispersion";
    if(s.includes("temp")) return "Temperature";
    if(s.includes("rain")) return "Rainfall";
    if(s.includes("h2s")||s.includes("h₂s")) return "Live H₂S";
    return name;
  }

  function add(out,name,value){
    const score=num(value);
    if(score===null) return;
    out.push({name:canon(name),score:Math.max(0,Math.min(100,score))});
  }

  function engineeringDrivers(risk){
    const out=[];
    const direct=[
      ["Tide influence",risk?.tide_proxy],
      ["Tide influence",risk?.tide_score],
      ["Low wind / dispersion",risk?.low_wind_dispersion],
      ["Low wind / dispersion",risk?.wind_score],
      ["Low wind / dispersion",risk?.dispersion_score],
      ["Temperature",risk?.temperature_score],
      ["Temperature",risk?.temp_score],
      ["Live H₂S",risk?.live_h2s_score],
      ["Live H₂S",risk?.h2s_score],
      ["Rainfall",risk?.rainfall_score],
      ["Rainfall",risk?.rain_score],
    ];
    direct.forEach(([k,v])=>add(out,k,v));

    for(const key of ["drivers","primary_drivers","components","driver_scores","risk_components"]){
      const block=risk?.[key];
      if(!block) continue;

      if(Array.isArray(block)){
        block.forEach(item=>{
          if(!item||typeof item!=="object") return;
          add(out,item.name||item.label||item.driver||item.feature,
              item.score??item.value??item.percent??item.risk_score);
        });
      } else if(typeof block==="object"){
        Object.entries(block).forEach(([name,v])=>{
          if(v&&typeof v==="object"){
            add(out,v.name||v.label||name,v.score??v.value??v.percent??v.risk_score);
          } else {
            add(out,name,v);
          }
        });
      }
    }

    // fallback: use legacy-rendered rows before v109 replaced them
    const box=driversBox();
    if(box){
      $$(".driver",box).forEach(row=>{
        if(row.classList.contains("ml-authoritative-driver")) return;
        const label=$(".driver-top span",row)?.textContent?.trim();
        const val=$(".driver-top b",row)?.textContent?.trim();
        const bar=$(".bar i",row)?.style?.width;
        const score=num((val||"").replace("%","")) ?? num((bar||"").replace("%",""));
        if(label&&score!==null) add(out,label,score);
      });
    }

    const dedup=new Map();
    out.forEach(d=>{
      if(!d.name||/wastewater/i.test(d.name)) return;
      const prev=dedup.get(d.name);
      if(!prev||d.score>prev.score) dedup.set(d.name,d);
    });
    return [...dedup.values()];
  }

  function wastewaterScore(pred){
    const excess=Math.max(0,num(pred?.excess_wastewater_contribution_ppb)||0);
    return Math.min(100,(excess/15)*100);
  }

  function renderDrivers(pred,risk){
    const box=driversBox();
    if(!box) return;

    const list=[
      ...engineeringDrivers(risk),
      {name:"Wastewater contribution",score:wastewaterScore(pred),wastewater:true}
    ];

    const dedup=new Map();
    list.forEach(d=>{
      const prev=dedup.get(d.name);
      if(!prev||d.score>prev.score||d.wastewater) dedup.set(d.name,d);
    });

    const sorted=[...dedup.values()].sort((a,b)=>b.score-a.score);
    box.innerHTML="";

    sorted.forEach(d=>{
      const row=document.createElement("div");
      row.className="driver ml-authoritative-driver";
      const label=d.wastewater
        ? String(pred?.wastewater_contribution_level||"Low")
        : String(Math.round(d.score));

      row.innerHTML=`
        <div class="driver-top"><span>${d.name}</span><b>${label}</b></div>
        <div class="bar"><i style="width:${Math.max(3,d.score)}%"></i></div>`;
      box.appendChild(row);
    });
  }

  function hideNarrative(){
    const c=riskCard();
    if(!c) return;
    const p=$("#riskNarrative",c)||$(".risk-narrative",c)||
      $$("p",c).find(x=>/trained ml forecast|engineering risk|next-hour h₂s|next-hour h2s/i.test(x.textContent||""));
    if(p){ p.textContent=""; p.style.display="none"; }
  }

  function findCard(label){
    return $$(".card,.kpi,.condition-card").find(card=>{
      return (card.textContent||"").toLowerCase().includes(label.toLowerCase());
    });
  }

  function setStamp(card,stamp,source){
    if(!card) return;
    let el=$(".data-asof",card);
    if(!el){
      el=document.createElement("div");
      el.className="data-asof";
      card.appendChild(el);
    }
    const a=age(stamp);
    el.textContent=`As of ${fmtTs(stamp)}${a?` • ${a}`:""}${source?` • ${source}`:""}`;
  }

  function firstTs(obj,keys){
    for(const k of keys){ if(obj?.[k]) return obj[k]; }
    return null;
  }

  function stampSensors(h2s){
    const sensors=h2s?.sensors||[];
    const cards=$$(".sensor-card,#conditions .card").filter(c=>/North Side|South Side/i.test(c.textContent||""));

    cards.forEach(card=>{
      const north=/North Side/i.test(card.textContent||"");
      const sensor=sensors.find(s=>north?/North/i.test(s.name||""):/South/i.test(s.name||""));
      if(!sensor) return;
      const ts=firstTs(sensor,["timestamp_utc","timestamp","utc","timestamp_local"]) ||
               firstTs(h2s,["timestamp","timestamp_utc"]);
      const fb=Boolean(h2s?.stale_fallback)||/fallback|history/i.test(sensor?.qc||"");
      setStamp(card,ts,fb?"Historical fallback":"Sonoma");
    });
  }

  function stampEnvironment(weather,tide){
    const wt=firstTs(weather,["timestamp_utc","timestamp","observation_time","time","current_time"]);
    const rt=firstTs(weather,["precipitation_timestamp_utc","rain_timestamp_utc","timestamp_utc","timestamp","time"]);
    const tt=firstTs(tide,["timestamp_utc","timestamp","time","date_time"]);

    setStamp(findCard("Wind"),wt,"Open-Meteo");
    setStamp(findCard("Temperature"),wt,"Open-Meteo");
    setStamp(findCard("Rainfall"),rt,"Open-Meteo");
    setStamp(findCard("Tide"),tt,"NOAA");
  }

  async function refresh(){
    const res=await Promise.allSettled([
      j("/api/ml/prediction"),
      j("/api/risk"),
      j("/api/h2s"),
      j("/api/weather"),
      j("/api/tide"),
    ]);

    const pred=res[0].status==="fulfilled"?res[0].value:null;
    const risk=res[1].status==="fulfilled"?res[1].value:{};
    const h2s=res[2].status==="fulfilled"?res[2].value:null;
    const weather=res[3].status==="fulfilled"?res[3].value:{};
    const tide=res[4].status==="fulfilled"?res[4].value:{};

    if(pred?.model_available) renderDrivers(pred,risk);
    hideNarrative();
    if(h2s) stampSensors(h2s);
    stampEnvironment(weather,tide);
  }

  function boot(){
    setTimeout(refresh,800);
    setTimeout(refresh,2200);
    setInterval(refresh,60000);

    const obs=new MutationObserver(hideNarrative);
    obs.observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",boot);
  } else {
    boot();
  }
})();
