
async function loadModelForecastDrivers(){
  try{
    const p=await getJson('/api/ml/prediction');
    if(!p || !p.model_available) return;

    const drivers=q('#drivers');
    if(!drivers) return;

    const existing=[...drivers.querySelectorAll('.driver')]
      .filter(x=>!x.classList.contains('v10-ml-driver'));

    const excursion=p.excursion_probability==null?0:Number(p.excursion_probability);
    const excess=Math.max(0,Number(p.excess_wastewater_contribution_ppb||0));
    const current=Math.max(1,Number(p.current_system_h2s_ppb||1));
    const wasteScore=Math.min(1,Math.max(excess/15, excess/current));

    const label=p.wastewater_contribution_level||'Low';

    const extras=[
      {
        name:'Excursion potential',
        value:excursion,
        text:`${Math.round(excursion*100)}%`
      },
      {
        name:'Wastewater contribution',
        value:wasteScore,
        text:label
      }
    ];

    extras.forEach(d=>{
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
      narrative.textContent=
        `Predicted next-hour H₂S peak ${Number(p.predicted_next_60m_max_h2s_ppb).toFixed(1)} ppb. `+
        `Excursion potential ${Math.round(excursion*100)}%. `+
        `Wastewater contribution ${label.toLowerCase()}.`;
    }

  }catch(e){
    console.warn('v1.0 model forecast drivers unavailable',e);
  }
}
