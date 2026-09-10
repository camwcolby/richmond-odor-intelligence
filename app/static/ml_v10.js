
async function loadMLPerformance(){
  const root=q('#mlPerformanceContent');
  if(!root) return;

  try{
    const s=await getJson('/api/ml/status');
    const m=s.metrics;
    const p=s.latest_prediction;

    if(!m){
      root.innerHTML=`<div class="ml-empty"><h3>Model not trained</h3><p>Run <code>python -m app.ml.cli train</code>.</p></div>`;
      return;
    }

    const peak=m.peak_forecast||{};
    const exc=m.excursion_model||{};
    const num=(x,d=2)=>x==null?'—':Number(x).toFixed(d);
    const pct=x=>x==null?'—':`${Math.round(Number(x)*100)}%`;

    root.innerHTML=`
      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Predicted 60-min peak</span>
          <strong>${p&&p.model_available?num(p.predicted_next_60m_max_h2s_ppb,1)+' ppb':'—'}</strong>
          <small>${p&&p.model_available?p.risk_level:'model unavailable'}</small>
        </div>
        <div class="ml-health-card">
          <span>Excursion probability</span>
          <strong>${p&&p.model_available?pct(p.excursion_probability):'—'}</strong>
          <small>unusual rise vs current condition</small>
        </div>
        <div class="ml-health-card">
          <span>Excess wastewater contribution</span>
          <strong>${p&&p.model_available?num(p.excess_wastewater_contribution_ppb,1)+' ppb':'—'}</strong>
          <small>${p&&p.model_available?p.wastewater_contribution_level:'—'}</small>
        </div>
        <div class="ml-health-card">
          <span>Model version</span>
          <strong class="small-strong">${m.model_version||'—'}</strong>
          <small>${m.training_rows||0} rows • ${m.walk_forward_folds_used||0} folds</small>
        </div>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row"><div><div class="small muted">BASELINE PEAK FORECAST</div><div class="card-title">Next-hour H₂S concentration skill</div></div></div>
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
          <div class="card-title-row"><div><div class="small muted">EXCURSION MODEL</div><div class="card-title">Can conditions flag an unusual rise?</div></div></div>
          <div class="ml-metrics-grid">
            <div><span>Recall</span><strong>${pct(exc.recall)}</strong><small>excursions caught</small></div>
            <div><span>Precision</span><strong>${pct(exc.precision)}</strong><small>alerts that were right</small></div>
            <div><span>PR-AUC</span><strong>${num(exc.average_precision,3)}</strong><small>rare-event skill</small></div>
            <div><span>Balanced Accuracy</span><strong>${pct(exc.balanced_accuracy)}</strong><small>both classes</small></div>
            <div><span>ROC-AUC</span><strong>${num(exc.roc_auc,3)}</strong><small>ranking skill</small></div>
            <div><span>Positive rows</span><strong>${exc.positive_rows||0}</strong><small>${m.excursion_metrics_reliable?'usable':'still limited'}</small></div>
          </div>
          <p class="ml-note">${m.excursion_definition||''}</p>
        </article>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row"><div><div class="small muted">EXCESS WASTEWATER CONTRIBUTION</div><div class="card-title">The unexplained “X” component</div></div></div>
        <div class="ml-x-driver">
          <div>
            <span>Current measured H₂S</span>
            <strong>${p&&p.model_available?num(p.current_system_h2s_ppb,1)+' ppb':'—'}</strong>
          </div>
          <div class="ml-minus">−</div>
          <div>
            <span>Environmentally explained baseline</span>
            <strong>${p&&p.model_available?num(p.environmental_baseline_ppb,1)+' ppb':'—'}</strong>
          </div>
          <div class="ml-equals">=</div>
          <div class="ml-x-result">
            <span>Excess wastewater contribution</span>
            <strong>${p&&p.model_available?num(p.excess_wastewater_contribution_ppb,1)+' ppb':'—'}</strong>
          </div>
        </div>
        <p class="ml-note ml-note-pad">${m.excess_wastewater_definition||''}</p>
      </article>

      <article class="panel ml-panel">
        <div class="card-title-row"><div><div class="small muted">MODEL INTERPRETATION</div><div class="card-title">Most Influential Peak-Forecast Features</div></div></div>
        <div class="ml-feature-list">
          ${(m.feature_importance||[]).map((f,i)=>`
            <div class="ml-feature-row">
              <span>${i+1}. ${f.feature}</span>
              <div class="ml-feature-bar"><i style="width:${Math.min(100,Number(f.importance)*500)}%"></i></div>
              <b>${Number(f.importance).toFixed(3)}</b>
            </div>`).join('')}
        </div>
      </article>
    `;
  }catch(e){
    root.innerHTML=`<div class="ml-empty"><h3>Model status unavailable</h3><p>${e.message}</p></div>`;
  }
}
