// Model Performance tab for the trained risk nowcast (replaces ml_v104.js).
async function loadMLPerformance(){
  const root=q('#mlPerformanceContent');
  if(!root) return;

  const fmtDate=x=>{
    if(!x) return '—';
    try{return new Date(String(x).replace(' ','T')).toLocaleString([], {dateStyle:'medium',timeStyle:'short'});}
    catch(e){return x;}
  };
  const pct=x=>x==null?'—':`${Math.round(Number(x)*100)}%`;
  const bar=(label,value,max,text,muted)=>`
    <div class="driver${muted?' nc-muted':''}">
      <div class="driver-top"><span>${label}</span><b>${text}</b></div>
      <div class="bar"><i style="width:${max?Math.max(2,value/max*100):0}%"></i></div>
    </div>`;

  try{
    const d=await getJson('/api/ml/nowcast/performance');
    const v=d.validation, m=d.model, c=d.current||{};

    if(!v || !m){
      root.innerHTML=`
        <div class="ml-empty">
          <h3>Risk model not installed</h3>
          <p>Run <code>python -m app.ml.cli train-nowcast</code>.</p>
        </div>`;
      return;
    }

    const stateText=c.available
      ? `${c.state} · ${Math.round(c.risk_percentile)}th percentile`
      : `Waiting for data (${c.reason||'history rebuilding'})`;

    const bins=v.warning_bins||[];
    const maxBin=Math.max(1,...bins.map(b=>b.count));
    const binsHtml=bins.map(b=>bar(b.label,b.count,maxBin,`${b.count}`,b.label==='Not flagged')).join('');
    const drivers=v.driver_shares||[];
    const driversHtml=drivers.map(x=>bar(x.name,x.share,1,pct(x.share))).join('');
    const ex=v.worked_example||{};

    const rows=(v.episodes_list||[]).slice().reverse().map(e=>{
      const dt=new Date(e.onset_local.replace(' ','T'));
      const warn=e.flagged
        ? (e.warning_hours<1 ? `${Math.round(e.warning_hours*60)} min` : (e.warning_hours>=5 ? '5 h+' : `${e.warning_hours.toFixed(1)} h`))
        : '—';
      return `<tr class="${e.flagged?'':'nc-miss'}">
        <td>${dt.toLocaleDateString([], {month:'short',day:'numeric',year:'numeric'})}</td>
        <td class="${e.peak_ppb>=60?'nc-viol':''}">${e.peak_ppb.toFixed(0)} ppb</td>
        <td>${e.flagged?'Flagged':'Not flagged'}</td>
        <td>${warn}</td>
      </tr>`;
    }).join('');

    root.innerHTML=`
      <div class="ml-reliability good">
        <b>Validated on two years of fence-line data (${v.period}).</b>
        <span>Each month was scored by a model trained on the other months, so every result below is out-of-sample.</span>
      </div>

      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Exceedances flagged in advance</span>
          <strong>${v.flagged_within_3h} of ${v.episodes}</strong>
          <small>elevated state within 3 h before a ${v.exceedance_threshold_ppb}+ ppb reading</small>
        </div>
        <div class="ml-health-card">
          <span>More likely after a flag</span>
          <strong>${Math.round(v.rate_ratio)}×</strong>
          <small>a random moment passes the same test ${pct(v.chance_rate)} of the time</small>
        </div>
        <div class="ml-health-card">
          <span>Median warning</span>
          <strong>${v.median_warning_hours} h</strong>
          <small>${v.flagged_with_over_1h} of ${v.flagged_within_3h} flagged had more than 1 h</small>
        </div>
        <div class="ml-health-card">
          <span>Time at elevated risk</span>
          <strong>${pct(v.time_elevated_share)}</strong>
          <small>${pct(v.elevated_share_oct_to_mar)} of it October through March</small>
        </div>
      </div>

      <div class="ml-meta-strip">
        <div><span>Current state</span><b>${stateText}</b></div>
        <div><span>Current data timestamp</span><b>${c.available?fmtDate(c.timestamp_utc):'—'}${c.stale?' (stale)':''}</b></div>
        <div><span>Model trained</span><b>${fmtDate(m.trained_at_utc)}</b></div>
        <div><span>Training window</span><b>${fmtDate(m.training_start_utc)} to ${fmtDate(m.training_through_utc)}</b></div>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row"><div>
            <div class="small muted">WARNING TIME</div>
            <div class="card-title">How far ahead each exceedance was flagged</div>
          </div></div>
          <div class="drivers nc-pad">${binsHtml}</div>
          <p class="ml-note">How long the dashboard had shown elevated risk when the exceedance started. The 5 h+ group reflects long stretches of sustained elevated conditions.</p>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row"><div>
            <div class="small muted">DRIVERS</div>
            <div class="card-title">What raised the risk before an exceedance</div>
          </div></div>
          <div class="drivers nc-pad">${driversHtml}</div>
          <p class="ml-note">Average across all ${v.episodes} exceedances. The plant's own odor usually shows up faintly at the sensors first; weather decides whether it builds.</p>
        </article>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row"><div>
          <div class="small muted">WORKED EXAMPLE</div>
          <div class="card-title">${ex.label}: ${Math.round(ex.peak_ppb)} ppb at ${ex.onset_local}</div>
        </div></div>
        <p class="nc-text">The dashboard turned elevated at ${ex.elevated_local}, ${ex.warning_minutes} minutes before the peak. It was a fast release in nearly dead air, the hardest pattern to see coming, and it was not part of the data used to score that month.</p>
      </article>

      <article class="panel ml-panel">
        <div class="card-title-row"><div>
          <div class="small muted">EVERY EXCEEDANCE</div>
          <div class="card-title">${v.episodes} readings of ${v.exceedance_threshold_ppb}+ ppb, newest first</div>
        </div></div>
        <div class="nc-table-wrap">
          <table class="nc-table">
            <thead><tr><th>Date</th><th>Peak</th><th>Advance flag</th><th>Warning</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="ml-note">Limits: ${v.episodes-v.flagged_within_3h} of ${v.episodes} exceedances had no advance flag. The model uses public sensor, weather and tide data only; plant process data is the natural next input.</p>
      </article>
    `;
  }catch(e){
    root.innerHTML=`
      <div class="ml-empty">
        <h3>Model status unavailable</h3>
        <p>${e.message}</p>
      </div>`;
  }
}
