
const center=[37.928,-122.367];
let mainMap=L.map('map').setView(center,13);
let complaintMap=L.map('complaintMap').setView(center,13);

for (const m of [mainMap, complaintMap]) {
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
    attribution:'© OpenStreetMap contributors'
  }).addTo(m);
}

const q = s => document.querySelector(s);
const qa = s => [...document.querySelectorAll(s)];

function riskColor(level){
  return level==='High'
    ? '#C84E4E'
    : level==='Moderate'
      ? '#E6A83A'
      : '#5EB95E';
}

qa('nav button').forEach(b=>b.onclick=()=>{
  qa('nav button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  qa('.view').forEach(x=>x.classList.remove('active'));
  q('#'+b.dataset.view).classList.add('active');
  if(b.dataset.view==='model-performance' && typeof loadMLPerformance==='function'){loadMLPerformance();}
  setTimeout(()=>{
    mainMap.invalidateSize();
    complaintMap.invalidateSize();
  },100);
});

async function getJson(url, opts){
  let r=await fetch(url,opts);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

async function loadRisk(){
  const r=await getJson('/api/risk');
  const card=q('.risk-card');
  card.className='risk-card '+r.current_level;

  q('#riskLevel').textContent=r.current_level.toUpperCase();
  q('#riskPct').textContent=Math.round(r.current_probability*100)+'%';
  q('#riskNarrative').textContent=
    'Live-data engineering risk index using Sonoma H₂S plus current environmental conditions. Not yet a trained ML probability.';

  q('#drivers').innerHTML=r.drivers.map(d=>
    `<div class="driver">
      <div class="driver-top">
        <span>${d.feature}</span>
        <b>${Math.round(d.importance*100)}</b>
      </div>
      <div class="bar"><i style="width:${d.importance*100}%"></i></div>
    </div>`
  ).join('');

  q('#forecastStrip').innerHTML=r.hourly.map((x,i)=>
    `<div class="forecast-hour">
      <span>${i===0?'Now':'+'+i+' hr'}</span>
      <strong style="color:${riskColor(x.level)}">
        ${Math.round(x.probability*100)}%
      </strong>
      <small>${x.level}</small>
    </div>`
  ).join('');
}

const riskSurfaceLayer=L.layerGroup().addTo(mainMap);
const sensorLayer=L.layerGroup().addTo(mainMap);
const structureLayer=L.layerGroup().addTo(mainMap);
const ssoLayer=L.layerGroup().addTo(mainMap);
const windLayer=L.layerGroup().addTo(mainMap);

async function loadRiskSurface(){
  const d=await getJson('/api/spatial/risk-surface');
  riskSurfaceLayer.clearLayers();
  windLayer.clearLayers();

  (d.cells||[]).forEach(c=>{
    const opacity=Math.min(.28, .045 + c.score*.30);

    L.circle(
      [c.lat,c.lon],
      {
        radius:d.cell_radius_m || 285,
        stroke:false,
        fillColor:riskColor(c.level),
        fillOpacity:opacity,
        interactive:c.score>=.20
      }
    )
    .bindPopup(
      `<b>Prototype Odor Risk Surface</b><br>`+
      `Relative score: ${Math.round(c.score*100)} / 100<br>`+
      `${c.dominant_source ? `Dominant source geometry: ${c.dominant_source}<br>` : ''}`+
      `<small>Engineering visualization, not calibrated ML.</small>`
    )
    .addTo(riskSurfaceLayer);
  });

  if(d.wind_direction_from_deg!==null && d.wind_direction_from_deg!==undefined){
    const windToward=(Number(d.wind_direction_from_deg)+180)%360;

    const icon=L.divIcon({
      className:'wind-arrow-icon',
      html:`<div style="
        transform:rotate(${windToward}deg);
        font-size:30px;
        color:#0D004C;
        text-shadow:0 1px 3px rgba(255,255,255,.9);
        line-height:1;
      ">↑</div>`,
      iconSize:[32,32],
      iconAnchor:[16,16]
    });

    L.marker([37.946,-122.389],{icon})
      .bindPopup(
        `<b>Wind</b><br>`+
        `From ${Number(d.wind_direction_from_deg).toFixed(0)}°`+
        `${d.wind_speed_mps!==null && d.wind_speed_mps!==undefined
          ? `<br>${Number(d.wind_speed_mps).toFixed(1)} m/s`
          : ''}`
      )
      .addTo(windLayer);
  }
}

async function loadH2S(){
  const d=await getJson('/api/h2s');
  sensorLayer.clearLayers();

  q('#sensorCards').innerHTML=d.sensors.map(s=>
    `<div class="sensor">
      <span>${s.name}</span>
      <b>${s.h2s_ppb} ppb</b>
      <small>Live Sonoma • ${s.operation_qc || s.qc || 'Valid'}</small>
    </div>`
  ).join('');

  d.sensors.forEach(s=>{
    L.circleMarker(
      [s.lat,s.lon],
      {
        radius:8,
        weight:3,
        color:'#FFFFFF',
        fillOpacity:1,
        fillColor:'#008FD5'
      }
    )
    .bindPopup(
      `<b>${s.name} H₂S Monitor</b><br>`+
      `${s.h2s_ppb} ppb<br>`+
      `<small>Live Sonoma Insight DMS • ${s.operation_qc || s.qc || ''}</small>`
    )
    .addTo(sensorLayer);
  });
}

async function loadStructures(){
  const fc=await getJson('/api/structures');
  structureLayer.clearLayers();

  (fc.features||[]).forEach(f=>{
    const [lon,lat]=f.geometry.coordinates;
    const p=f.properties||{};

    if(p.category==='WWTP'){
      L.circleMarker(
        [lat,lon],
        {
          radius:13,
          weight:4,
          color:'#5EB95E',
          fillColor:'#FFFFFF',
          fillOpacity:.72
        }
      )
      .bindPopup(
        `<b>${p.name}</b><br>`+
        `Wastewater Treatment Plant<br>`+
        `<small>${p.status||''}</small>`
      )
      .addTo(structureLayer);

    } else if(p.category==='Pump Station'){
      L.circleMarker(
        [lat,lon],
        {
          radius:6,
          weight:2,
          color:'#0D004C',
          fillColor:'#75AABB',
          fillOpacity:.40
        }
      )
      .bindPopup(
        `<b>${p.name}</b><br>`+
        `Pump Station<br>`+
        `<small>${p.asset_id||''}</small>`
      )
      .addTo(structureLayer);

    } else {
      L.circleMarker(
        [lat,lon],
        {
          radius:5,
          weight:1.5,
          color:'#45484D',
          fillColor:'#FFFFFF',
          fillOpacity:.9
        }
      )
      .bindPopup(`<b>${p.name}</b><br>${p.category}`)
      .addTo(structureLayer);
    }
  });
}

async function loadHotspots(){
  const hs=await getJson('/api/hotspots');
  ssoLayer.clearLayers();

  hs.forEach(h=>{
    const placeholder=(h.data_status||'').toLowerCase().includes('placeholder');

    L.circleMarker(
      [h.latitude,h.longitude],
      {
        radius:7,
        weight:2,
        color:'#C97917',
        fillColor:'#E6A83A',
        fillOpacity:.72
      }
    )
    .bindPopup(
      `<b>${h.name}</b><br>`+
      `Historical SSO location${placeholder?' • placeholder dataset':''}<br>`+
      `<small>${h.data_status||''}</small>`
    )
    .addTo(ssoLayer);
  });
}

function cardinalFromDegrees(deg){
  if(deg===null || deg===undefined || Number.isNaN(Number(deg))) return null;
  const dirs=[
    'N','NNE','NE','ENE',
    'E','ESE','SE','SSE',
    'S','SSW','SW','WSW',
    'W','WNW','NW','NNW'
  ];
  return dirs[Math.floor((Number(deg)+11.25)/22.5)%16];
}

async function loadConditions(){
  try {
    const w=await getJson('/api/weather');
    const c=w.current || {};
    const d=w.derived || {};

    const windSpeed=c.wind_speed_10m;
    const windDir=c.wind_direction_10m;
    const windCardinal=d.wind_cardinal || cardinalFromDegrees(windDir);

    if(windSpeed!==null && windSpeed!==undefined){
      q('#wind').textContent=
        `${Number(windSpeed).toFixed(1)} mph` +
        (windCardinal ? ` • ${windCardinal}` : '') +
        (windDir!==null && windDir!==undefined ? ` (${Math.round(Number(windDir))}°)` : '');
    } else {
      q('#wind').textContent='Unavailable';
    }

    q('#temp').textContent=
      c.temperature_2m!==null && c.temperature_2m!==undefined
        ? `${Number(c.temperature_2m).toFixed(1)} °F`
        : 'Unavailable';

    const currentRain=
      c.rain!==null && c.rain!==undefined
        ? Number(c.rain)
        : Number(c.precipitation || 0);

    q('#rain').textContent=`${currentRain.toFixed(2)} in`;

    const windCard=q('#wind')?.closest('.kpi');
    const tempCard=q('#temp')?.closest('.kpi');
    const rainCard=q('#rain')?.closest('.kpi');

    if(windCard){
      const s=windCard.querySelector('small');
      if(s) s.textContent=`Open-Meteo • gust ${Number(c.wind_gusts_10m || 0).toFixed(1)} mph`;
    }

    if(tempCard){
      const s=tempCard.querySelector('small');
      if(s){
        const rh=c.relative_humidity_2m;
        s.textContent=
          rh!==null && rh!==undefined
            ? `Open-Meteo • RH ${Math.round(Number(rh))}%`
            : 'Open-Meteo';
      }
    }

    if(rainCard){
      const s=rainCard.querySelector('small');
      if(s){
        s.textContent=
          `1 hr ${Number(d.rain_1h_in || 0).toFixed(2)} in • `+
          `24 hr ${Number(d.rain_24h_in || 0).toFixed(2)} in`;
      }
    }

  } catch(e) {
    q('#wind').textContent='Provider unavailable';
    q('#temp').textContent='--';
    q('#rain').textContent='--';
    console.error('Weather load failed:', e);
  }

  try{
    const t=await getJson('/api/tides');
    const p=(t.predictions||[])[0];
    q('#tide').textContent=p?`${p.v} ft MLLW`:'Unavailable';
  }catch(e){
    q('#tide').textContent='Provider unavailable';
  }
}

let complaintLayer=L.layerGroup().addTo(complaintMap);

async function loadComplaints(){
  const rows=await getJson('/api/complaints');

  q('#complaintRows').innerHTML=rows.map(r=>
    `<tr>
      <td>${new Date(r.reported_at).toLocaleString()}</td>
      <td>${r.public_location}</td>
      <td>${'●'.repeat(r.intensity)}</td>
      <td>${r.status}</td>
      <td>${r.cmms_work_order}</td>
    </tr>`
  ).join('');

  complaintLayer.clearLayers();

  rows.forEach(r=>{
    const radius=120+r.intensity*65;

    L.circle(
      [r.map_latitude,r.map_longitude],
      {
        radius,
        stroke:false,
        fillOpacity:.12
      }
    ).addTo(complaintLayer);

    L.circleMarker(
      [r.map_latitude,r.map_longitude],
      {
        radius:4+r.intensity,
        weight:1,
        fillOpacity:.65
      }
    )
    .bindPopup(
      `<b>${r.public_location}</b><br>`+
      `Intensity ${r.intensity}/5<br>${r.status}`
    )
    .addTo(complaintLayer);
  });
}

q('#complaintForm').addEventListener('submit',async e=>{
  e.preventDefault();

  const f=new FormData(e.target);

  const body={
    latitude:+f.get('latitude'),
    longitude:+f.get('longitude'),
    odor_type:f.get('odor_type'),
    intensity:+f.get('intensity'),
    comments:f.get('comments')
  };

  try{
    const r=await getJson(
      '/api/complaints',
      {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body)
      }
    );

    q('#formResult').style.background='#eaf6f1';
    q('#formResult').innerHTML=
      `<b>Report received.</b> ${r.complaint_id} • `+
      `Public location: ${r.public_location} • `+
      `Simulated CMMS: ${r.cmms_work_order}`;

    await loadComplaints();

  }catch(err){
    q('#formResult').style.background='#fff0ee';
    q('#formResult').textContent='Could not submit: '+err.message;
  }
});

Promise.all([
  loadRisk(),
  loadRiskSurface(),
  loadH2S(),
  loadStructures(),
  loadHotspots(),
  loadConditions(),
  loadComplaints()
]).catch(console.error);

if(typeof loadModelForecastDrivers==='function'){loadModelForecastDrivers();}

setInterval(()=>{
  loadRisk();
  loadRiskSurface();
  loadH2S();
  loadConditions();
  if(typeof loadModelForecastDrivers==='function'){loadModelForecastDrivers();}
},300000);
