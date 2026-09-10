
async function loadMLPerformance(){
  const root=q('#mlPerformanceContent'); if(!root) return;
  try{
    const s=await getJson('/api/ml/status'), m=s.metrics, p=s.latest_prediction;
    if(!m){
      root.innerHTML=`<div class="ml-empty"><div class="small muted">MODEL NOT TRAINED</div>
      <h3>Historical backfill is required.</h3>
      <p>Run <code>python -m app.ml.cli bootstrap --days 90</code>. If there are too few >60 ppb periods, use 365 days.</p>
      <p>Stored observations: <b>${s.observation_rows||0}</b></p></div>`; return;
    }
    const cm=m.confusion_matrix||{}, pct=x=>x==null?'—':`${Math.round(x*100)}%`, num=x=>x==null?'—':Number(x).toFixed(3);
    root.innerHTML=`
    <div class="ml-health-grid">
      <div class="ml-health-card"><span>Current prediction</span><strong>${p&&p.model_available?pct(p.probability):'—'}</strong><small>next 60 min >60 ppb</small></div>
      <div class="ml-health-card"><span>Model version</span><strong class="small-strong">${m.model_version}</strong><small>${m.model_type}</small></div>
      <div class="ml-health-card"><span>Training through</span><strong class="small-strong">${new Date(m.training_through_utc).toLocaleDateString()}</strong><small>${m.training_rows} training rows</small></div>
      <div class="ml-health-card"><span>&gt;60 ppb periods</span><strong>${m.positive_events}</strong><small>${m.validation_positive_rows} in validation</small></div>
    </div>
    <div class="ml-two-col">
      <article class="panel ml-panel"><div class="card-title-row"><div><div class="small muted">OUT-OF-SAMPLE</div><div class="card-title">High-H₂S Prediction Skill</div></div></div>
      <div class="ml-metrics-grid">
        <div><span>Recall</span><strong>${pct(m.recall)}</strong><small>high periods caught</small></div>
        <div><span>Precision</span><strong>${pct(m.precision)}</strong><small>alerts that were right</small></div>
        <div><span>PR-AUC</span><strong>${num(m.average_precision)}</strong><small>rare-event skill</small></div>
        <div><span>Balanced Accuracy</span><strong>${pct(m.balanced_accuracy)}</strong><small>both classes</small></div>
        <div><span>Brier Score</span><strong>${num(m.brier_score)}</strong><small>lower is better</small></div>
        <div><span>ROC-AUC</span><strong>${num(m.roc_auc)}</strong><small>ranking skill</small></div>
      </div><p class="ml-note">${m.validation_method}</p></article>
      <article class="panel ml-panel"><div class="card-title-row"><div><div class="small muted">VALIDATION</div><div class="card-title">Confusion Matrix</div></div></div>
      <div class="confusion-grid">
        <div class="cm-cell cm-good"><span>Caught high</span><strong>${cm.true_positive||0}</strong></div>
        <div class="cm-cell cm-warn"><span>Missed high</span><strong>${cm.false_negative||0}</strong></div>
        <div class="cm-cell cm-warn"><span>False alarms</span><strong>${cm.false_positive||0}</strong></div>
        <div class="cm-cell cm-good"><span>Correct low</span><strong>${cm.true_negative||0}</strong></div>
      </div><p class="ml-note">${m.target}</p></article>
    </div>
    <article class="panel ml-panel"><div class="card-title-row"><div><div class="small muted">MODEL INTERPRETATION</div><div class="card-title">Most Influential Features</div></div></div>
    <div class="ml-feature-list">${(m.feature_importance||[]).map((f,i)=>`<div class="ml-feature-row"><span>${i+1}. ${f.feature}</span><div class="ml-feature-bar"><i style="width:${Math.min(100,f.importance*500)}%"></i></div><b>${f.importance.toFixed(3)}</b></div>`).join('')}</div></article>
    <article class="panel ml-panel"><div class="card-title-row"><div><div class="small muted">AUTOMATION</div><div class="card-title">Learning Cycle</div></div></div>
    <div class="ml-cycle"><div><b>Every ${s.ingest_minutes} min</b><span>ingest new data</span></div><div class="ml-arrow">→</div><div><b>Continuous</b><span>score with current model</span></div><div class="ml-arrow">→</div><div><b>Every ${s.retrain_hours} hr</b><span>retrain + validate</span></div></div></article>`;
  }catch(e){root.innerHTML=`<div class="ml-empty"><h3>Model status unavailable</h3><p>${e.message}</p></div>`;}
}
