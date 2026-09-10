
async function loadMLPerformance(){
  const root=q('#mlPerformanceContent');
  if(!root) return;

  try{
    const s=await getJson('/api/ml/status');
    const m=s.metrics;
    const p=s.latest_prediction;

    if(!m){
      root.innerHTML=`
        <div class="ml-empty">
          <h3>Model not trained</h3>
          <p>Run <code>python -m app.ml.cli train</code>.</p>
        </div>`;
      return;
    }

    const peak=m.peak_forecast||{};
    const exc=m.excursion_model||{};
    const curve=exc.threshold_curve||[];

    const num=(x,d=2)=>x==null?'—':Number(x).toFixed(d);
    const pct=x=>x==null?'—':`${Math.round(Number(x)*100)}%`;
    const fmtDate=x=>{
      if(!x) return '—';
      try{return new Date(x).toLocaleString();}
      catch(e){return x;}
    };

    const operationalSkill =
      exc.recall!=null &&
      Number(exc.recall) >= 0.20 &&
      exc.false_alerts_per_week!=null &&
      Number(exc.false_alerts_per_week) <= Number(exc.false_alert_constraint_per_week||2);

    const excursionStatus = operationalSkill
      ? `<div class="ml-reliability good">
           <b>Excursion model shows usable operational skill.</b>
           <span>Current validation operating point balances detection and nuisance alerts.</span>
         </div>`
      : `<div class="ml-reliability caution">
           <b>Excursion potential is experimental.</b>
           <span>Ranking signal exists, but current operational recall is too low to drive the overall forecast by itself.</span>
         </div>`;

    const peakStatus =
      m.metrics_reliable
        ? `<div class="ml-reliability good">
             <b>Peak H₂S forecast has usable walk-forward validation coverage.</b>
             <span>${m.peak_model_note||''}</span>
           </div>`
        : `<div class="ml-reliability caution">
             <b>Peak H₂S forecast remains provisional.</b>
           </div>`;

    const maxFalse=Math.max(
      1,
      ...curve.map(x=>Number(x.false_alerts_per_week||0))
    );

    const curveHtml = curve.length
      ? curve.map(x=>{
          const t=Number(x.threshold||0);
          const recall=Number(x.recall||0);
          const falseWeek=Number(x.false_alerts_per_week||0);
          const selected=Math.abs(t-Number(exc.operating_threshold||0))<0.0001;
          return `
            <div class="threshold-row ${selected?'selected':''}">
              <div class="threshold-label">${Math.round(t*100)}%</div>
              <div class="threshold-bars">
                <div class="threshold-metric">
                  <span>Recall</span>
                  <div class="threshold-track"><i style="width:${Math.max(1,recall*100)}%"></i></div>
                  <b>${Math.round(recall*100)}%</b>
                </div>
                <div class="threshold-metric nuisance">
                  <span>False alerts/wk</span>
                  <div class="threshold-track"><i style="width:${Math.max(1,(falseWeek/maxFalse)*100)}%"></i></div>
                  <b>${falseWeek.toFixed(1)}</b>
                </div>
              </div>
              ${selected?'<div class="selected-chip">Selected</div>':''}
            </div>`;
        }).join('')
      : `<div class="ml-note ml-note-pad">No threshold-curve data available.</div>`;

    root.innerHTML=`
      ${peakStatus}
      ${excursionStatus}

      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Predicted 60-min peak</span>
          <strong>${p&&p.model_available?num(p.predicted_next_60m_max_h2s_ppb,1)+' ppb':'—'}</strong>
          <small>${p&&p.model_available?p.risk_level:'model unavailable'}</small>
        </div>

        <div class="ml-health-card">
          <span>Wastewater contribution</span>
          <strong>${p&&p.model_available?num(p.excess_wastewater_contribution_ppb,1)+' ppb':'—'}</strong>
          <small>${p&&p.model_available?p.wastewater_contribution_level:'—'}</small>
        </div>

        <div class="ml-health-card">
          <span>Experimental excursion potential</span>
          <strong>${p&&p.model_available?pct(p.excursion_probability):'—'}</strong>
          <small>alert threshold ${pct(exc.operating_threshold)}</small>
        </div>

        <div class="ml-health-card">
          <span>Model version</span>
          <strong class="small-strong">${m.model_version||'—'}</strong>
          <small>${m.training_rows||0} rows • ${m.walk_forward_folds_used||0} folds</small>
        </div>
      </div>

      <div class="ml-meta-strip">
        <div><span>Training through</span><b>${fmtDate(m.training_through_utc)}</b></div>
        <div><span>Model trained</span><b>${fmtDate(m.trained_at_utc)}</b></div>
        <div><span>Current data timestamp</span><b>${p&&p.timestamp_utc?fmtDate(p.timestamp_utc):'—'}</b></div>
        <div><span>Operational high threshold</span><b>${m.operational_high_threshold_ppb||60} ppb</b></div>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">PEAK H₂S FORECAST</div>
              <div class="card-title">Next-hour concentration performance</div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div><span>MAE</span><strong>${num(peak.mae_ppb)} ppb</strong><small>average absolute error</small></div>
            <div><span>RMSE</span><strong>${num(peak.rmse_ppb)} ppb</strong><small>large-error sensitive</small></div>
            <div><span>R²</span><strong>${num(peak.r2,3)}</strong><small>explained variation</small></div>
            <div><span>MAE ≥30 ppb</span><strong>${num(peak.mae_ge_30_ppb)} ppb</strong><small>elevated periods</small></div>
            <div><span>MAE ≥45 ppb</span><strong>${num(peak.mae_ge_45_ppb)} ppb</strong><small>near-high periods</small></div>
            <div><span>Validation rows</span><strong>${peak.validation_rows||0}</strong><small>walk-forward</small></div>
          </div>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">EXCURSION MODEL STATUS</div>
              <div class="card-title">Experimental, not a primary alert driver</div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div><span>ROC-AUC</span><strong>${num(exc.roc_auc,3)}</strong><small>ranking skill</small></div>
            <div><span>PR-AUC</span><strong>${num(exc.average_precision,3)}</strong><small>rare-event precision-recall</small></div>
            <div><span>Recall</span><strong>${pct(exc.recall)}</strong><small>excursions caught</small></div>
            <div><span>Precision</span><strong>${pct(exc.precision)}</strong><small>alerts that were right</small></div>
            <div><span>False alerts / week</span><strong>${num(exc.false_alerts_per_week,1)}</strong><small>validation estimate</small></div>
            <div><span>Alert threshold</span><strong>${pct(exc.operating_threshold)}</strong><small>nuisance constrained</small></div>
          </div>
        </article>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">EXCURSION THRESHOLD TRADEOFF</div>
            <div class="card-title">Detection vs nuisance alerts</div>
          </div>
        </div>
        <div class="threshold-curve">${curveHtml}</div>
        <p class="ml-note">
          The selected threshold is constrained to approximately ≤ ${num(exc.false_alert_constraint_per_week,1)} false alert episodes per week when possible.
          Excursion probability remains informational until operational recall improves materially.
        </p>
      </article>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">EXCESS WASTEWATER CONTRIBUTION</div>
            <div class="card-title">Explanatory “X” component</div>
          </div>
        </div>

        <div class="ml-x-driver">
          <div>
            <span>Current measured H₂S</span>
            <strong>${p&&p.model_available?num(p.current_system_h2s_ppb,1)+' ppb':'—'}</strong>
          </div>

          <div class="ml-minus">−</div>

          <div>
            <span>Ordinary-condition environmental baseline</span>
            <strong>${p&&p.model_available?num(p.environmental_baseline_ppb,1)+' ppb':'—'}</strong>
          </div>

          <div class="ml-equals">=</div>

          <div class="ml-x-result">
            <span>Excess wastewater contribution</span>
            <strong>${p&&p.model_available?num(p.excess_wastewater_contribution_ppb,1)+' ppb':'—'}</strong>
          </div>
        </div>

        <p class="ml-note ml-note-pad">
          ${m.environmental_baseline_definition||''}<br>
          ${m.excess_wastewater_definition||''}
        </p>
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
