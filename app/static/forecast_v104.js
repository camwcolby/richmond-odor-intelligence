
async function loadModelForecastDrivers(){
  try{
    const p=await getJson('/api/ml/prediction');
    if(!p || !p.model_available) return;

    const drivers=q('#drivers');
    if(!drivers) return;

    [...drivers.querySelectorAll('.v10-ml-driver')].forEach(el=>el.remove());

    const excursion=p.excursion_probability==null?0:Number(p.excursion_probability);
    const threshold=p.excursion_operating_threshold==null?0.5:Number(p.excursion_operating_threshold);

    const excess=Math.max(0,Number(p.excess_wastewater_contribution_ppb||0));
    const current=Math.max(1,Number(p.current_system_h2s_ppb||1));
    const wasteScore=Math.min(1,Math.max(excess/15,excess/current));

    const peak=Number(p.predicted_next_60m_max_h2s_ppb||0);

    const cards=[
      {
        name:'Forecast H₂S',
        value:Math.min(1,peak/60),
        text:`${peak.toFixed(1)} ppb`
      },
      {
        name:'Wastewater contribution',
        value:wasteScore,
        text:p.wastewater_contribution_level||'Low'
      },
      {
        name:'Experimental excursion potential',
        value:Math.min(1,excursion/Math.max(threshold,0.01)),
        text:`${Math.round(excursion*100)}%`
      }
    ];

    cards.forEach(d=>{
      const el=document.createElement('div');
      el.className='driver v10-ml-driver';
      el.innerHTML=`
        <div class="driver-top">
          <span>${d.name}</span>
          <b>${d.text}</b>
        </div>
        <div class="bar"><i style="width:${Math.max(4,d.value*100)}%"></i></div>`;
      drivers.appendChild(el);
    });

    const narrative=q('#riskNarrative');
    if(narrative){
      const excursionText =
        excursion>=threshold
          ? `Experimental excursion signal is above its ${Math.round(threshold*100)}% research threshold, but does not independently change the overall outlook.`
          : `Experimental excursion potential is ${Math.round(excursion*100)}%, below its ${Math.round(threshold*100)}% research threshold.`;

      narrative.textContent=
        `Forecast next-hour H₂S peak ${peak.toFixed(1)} ppb. `+
        `Wastewater contribution ${(p.wastewater_contribution_level||'Low').toLowerCase()} (${Number(p.excess_wastewater_contribution_ppb||0).toFixed(1)} ppb above environmental baseline). `+
        excursionText;
    }

  }catch(e){
    console.warn('v1.0.4 forecast polish unavailable',e);
  }
}
