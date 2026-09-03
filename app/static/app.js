
const center=[37.935,-122.365];
let mainMap=L.map('map').setView(center,13);
let complaintMap=L.map('complaintMap').setView(center,13);
for (const m of [mainMap, complaintMap]) {
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
    attribution:'© OpenStreetMap contributors'
  }).addTo(m);
}
const q = s => document.querySelector(s);
const qa = s => [...document.querySelectorAll(s)];

function riskColor(level){return level==='High'?'#C84E4E':level==='Moderate'?'#E6A83A':'#5EB95E'}

qa('nav button').forEach(b=>b.onclick=()=>{
  qa('nav button').forEach(x=>x.classList.remove('active')); b.classList.add('active');
  qa('.view').forEach(x=>x.classList.remove('active')); q('#'+b.dataset.view).classList.add('active');
  setTimeout(()=>{mainMap.invalidateSize();complaintMap.invalidateSize()},100);
});

async function getJson(url, opts){let r=await fetch(url,opts); if(!r.ok) throw new Error(await r.text()); return r.json()}

async function loadRisk(){
  const r=await getJson('/api/risk');
  const card=q('.risk-card'); card.className='risk-card '+r.current_level;
  q('#riskLevel').textContent=r.current_level.toUpperCase();
  q('#riskPct').textContent=Math.round(r.current_probability*100)+'%';
  q('#riskNarrative').textContent=`Estimated probability of an odor episode under current conditions. ${r.model_status}.`;
  q('#drivers').innerHTML=r.drivers.map(d=>`<div class="driver"><div class="driver-top"><span>${d.feature}</span><b>${Math.round(d.importance*100)}</b></div><div class="bar"><i style="width:${d.importance*100}%"></i></div></div>`).join('');
  q('#forecastStrip').innerHTML=r.hourly.map((x,i)=>`<div class="forecast-hour"><span>${i===0?'Now':'+'+i+' hr'}</span><strong style="color:${riskColor(x.level)}">${Math.round(x.probability*100)}%</strong><small>${x.level}</small></div>`).join('');
}

async function loadH2S(){
  const d=await getJson('/api/h2s');
  q('#sensorCards').innerHTML=d.sensors.map(s=>`<div class="sensor"><span>${s.name}</span><b>${s.h2s_ppb} ppb</b><small>${s.simulated?'Simulated':'Live'}</small></div>`).join('');
  d.sensors.forEach(s=>L.circleMarker([s.lat,s.lon],{radius:9,weight:2,fillOpacity:.82,color:'#008FD5',fillColor:'#008FD5'}).bindPopup(`<b>${s.name}</b><br>${s.h2s_ppb} ppb H₂S<br><small>Simulated feed</small>`).addTo(mainMap));
}

async function loadHotspots(){
  const hs=await getJson('/api/hotspots');
  hs.forEach(h=>L.circleMarker([h.latitude,h.longitude],{radius:6,weight:1,fillOpacity:.55,color:'#5EB95E',fillColor:'#5EB95E'}).bindPopup(`<b>${h.name}</b><br>${h.category}<br>Source score ${h.source_score}`).addTo(mainMap));
}

async function loadConditions(){
  try {
    const w=await getJson('/api/weather'), c=w.current;
    q('#wind').textContent=`${c.wind_speed_10m} mph @ ${c.wind_direction_10m}°`;
    q('#temp').textContent=`${c.temperature_2m} °F`;
    q('#rain').textContent=`${c.precipitation} in`;
  } catch(e) { q('#wind').textContent='Provider unavailable'; }
  try{
    const t=await getJson('/api/tides');
    const p=(t.predictions||[])[0];
    q('#tide').textContent=p?`${p.v} ft MLLW`:'Unavailable';
  }catch(e){q('#tide').textContent='Provider unavailable'}
}

let complaintLayer=L.layerGroup().addTo(complaintMap);
async function loadComplaints(){
  const rows=await getJson('/api/complaints');
  q('#complaintRows').innerHTML=rows.map(r=>`<tr><td>${new Date(r.reported_at).toLocaleString()}</td><td>${r.public_location}</td><td>${'●'.repeat(r.intensity)}</td><td>${r.status}</td><td>${r.cmms_work_order}</td></tr>`).join('');
  complaintLayer.clearLayers();
  rows.forEach(r=>{
    const radius=120 + r.intensity*65;
    L.circle([r.map_latitude,r.map_longitude],{radius,stroke:false,fillOpacity:.12}).addTo(complaintLayer);
    L.circleMarker([r.map_latitude,r.map_longitude],{radius:4+r.intensity,weight:1,fillOpacity:.65}).bindPopup(`<b>${r.public_location}</b><br>Intensity ${r.intensity}/5<br>${r.status}`).addTo(complaintLayer);
  });
}

q('#complaintForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const f=new FormData(e.target);
  const body={latitude:+f.get('latitude'),longitude:+f.get('longitude'),odor_type:f.get('odor_type'),intensity:+f.get('intensity'),comments:f.get('comments')};
  try{
    const r=await getJson('/api/complaints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    q('#formResult').style.background='#eaf6f1';
    q('#formResult').innerHTML=`<b>Report received.</b> ${r.complaint_id} • Public location: ${r.public_location} • Simulated CMMS: ${r.cmms_work_order}`;
    await loadComplaints();
  }catch(err){
    q('#formResult').style.background='#fff0ee'; q('#formResult').textContent='Could not submit: '+err.message;
  }
});

Promise.all([loadRisk(),loadH2S(),loadHotspots(),loadConditions(),loadComplaints()]).catch(console.error);
setInterval(()=>{loadRisk();loadH2S();loadConditions()},300000);
