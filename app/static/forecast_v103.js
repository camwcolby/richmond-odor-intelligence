
async function loadModelForecastDrivers(){
  try{
    const p=await getJson('/api/ml/prediction');

    if(
      !p
      || !p.model_available
    ) return;

    const drivers=q('#drivers');

    if(!drivers) return;

    [
      ...drivers.querySelectorAll(
        '.v10-ml-driver'
      )
    ].forEach(
      el=>el.remove()
    );

    const excursion=
      p.excursion_probability==null
        ? 0
        : Number(
            p.excursion_probability
          );

    const threshold=
      p.excursion_operating_threshold==null
        ? 0.5
        : Number(
            p.excursion_operating_threshold
          );

    const excess=Math.max(
      0,
      Number(
        p.excess_wastewater_contribution_ppb
        || 0
      )
    );

    const current=Math.max(
      1,
      Number(
        p.current_system_h2s_ppb
        || 1
      )
    );

    const wasteScore=Math.min(
      1,
      Math.max(
        excess/15,
        excess/current
      )
    );

    const extras=[
      {
        name:'Excursion potential',
        value:Math.min(
          1,
          excursion/Math.max(
            threshold,
            0.01
          )
        ),
        text:p.excursion_alert
          ? 'ALERT'
          : `${Math.round(excursion*100)}%`
      },
      {
        name:'Wastewater contribution',
        value:wasteScore,
        text:
          p.wastewater_contribution_level
          || 'Low'
      }
    ];

    extras.forEach(
      d=>{
        const el=document.createElement(
          'div'
        );

        el.className=
          'driver v10-ml-driver';

        el.innerHTML=`
          <div class="driver-top">
            <span>${d.name}</span>
            <b>${d.text}</b>
          </div>
          <div class="bar">
            <i style="width:${Math.max(4,d.value*100)}%"></i>
          </div>`;

        drivers.appendChild(el);
      }
    );

    const narrative=q(
      '#riskNarrative'
    );

    if(narrative){
      const excursionPhrase =
        p.excursion_alert
          ? `Excursion alert triggered at ${Math.round(excursion*100)}%.`
          : `Excursion potential ${Math.round(excursion*100)}%, below the ${Math.round(threshold*100)}% alert threshold.`;

      narrative.textContent=
        `Predicted next-hour H₂S peak ${Number(p.predicted_next_60m_max_h2s_ppb).toFixed(1)} ppb. `+
        `${excursionPhrase} `+
        `Wastewater contribution ${(p.wastewater_contribution_level||'Low').toLowerCase()}.`;
    }

  }catch(e){
    console.warn(
      'v1.0.3 model forecast drivers unavailable',
      e
    );
  }
}
