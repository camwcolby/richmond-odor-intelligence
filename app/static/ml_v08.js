
async function loadMLPerformance(){
  const root=q('#mlPerformanceContent');
  if(!root) return;

  try{
    const s=await getJson('/api/ml/status');
    const m=s.metrics;
    const p=s.latest_prediction;

    if(!m){
      root.innerHTML=`<div class="ml-empty">
        <div class="small muted">MODEL NOT TRAINED</div>
        <h3>Historical backfill is required.</h3>
        <p>Run <code>python -m app.ml.cli bootstrap --days 365</code>.</p>
      </div>`;
      return;
    }

    const cm=m.confusion_matrix||{};
    const ev=m.event_metrics||{};

    const pct=x=>x==null?'—':`${Math.round(Number(x)*100)}%`;
    const num=x=>x==null?'—':Number(x).toFixed(3);
    const whole=x=>x==null?'—':Math.round(Number(x));

    const reliability = m.metrics_reliable
      ? `<div class="ml-reliability good">Validation includes actual high-H₂S periods.</div>`
      : `<div class="ml-reliability caution">
           <b>Insufficient positive events for reliable validation.</b>
           <span>${m.reliability_message||''}</span>
         </div>`;

    root.innerHTML=`
      ${reliability}

      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Current prediction</span>
          <strong>${p&&p.model_available?pct(p.probability):'—'}</strong>
          <small>next 60 min &gt;60 ppb</small>
        </div>

        <div class="ml-health-card">
          <span>Model version</span>
          <strong class="small-strong">${m.model_version||'—'}</strong>
          <small>${m.model_type||''}</small>
        </div>

        <div class="ml-health-card">
          <span>Historical high events</span>
          <strong>${m.actual_high_events||0}</strong>
          <small>${m.positive_rows||0} positive future rows</small>
        </div>

        <div class="ml-health-card">
          <span>Walk-forward folds</span>
          <strong>${m.walk_forward_folds_used||0}</strong>
          <small>${m.validation_positive_rows||0} validation positives</small>
        </div>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">EVENT-LEVEL PERFORMANCE</div>
              <div class="card-title">Did we warn before actual &gt;60 ppb episodes?</div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div><span>Event Recall</span><strong>${pct(ev.event_recall)}</strong><small>episodes caught</small></div>
            <div><span>Events Caught</span><strong>${whole(ev.events_caught)}</strong><small>with advance / concurrent alert</small></div>
            <div><span>Events Missed</span><strong>${whole(ev.events_missed)}</strong><small>no alert in warning window</small></div>
            <div><span>False Alert Events</span><strong>${whole(ev.false_alert_events)}</strong><small>alert episodes not tied to high H₂S</small></div>
            <div><span>Median Lead Time</span><strong>${ev.median_warning_lead_minutes==null?'—':whole(ev.median_warning_lead_minutes)+' min'}</strong><small>first alert before event start</small></div>
            <div><span>Actual Events</span><strong>${whole(ev.actual_events)}</strong><small>contiguous &gt;60 ppb episodes</small></div>
          </div>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">ROW-LEVEL PERFORMANCE</div>
              <div class="card-title">Walk-Forward Skill</div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div><span>Recall</span><strong>${pct(m.recall)}</strong><small>positive rows caught</small></div>
            <div><span>Precision</span><strong>${pct(m.precision)}</strong><small>alert rows that were right</small></div>
            <div><span>PR-AUC</span><strong>${num(m.average_precision)}</strong><small>rare-event discrimination</small></div>
            <div><span>Balanced Accuracy</span><strong>${pct(m.balanced_accuracy)}</strong><small>both classes</small></div>
            <div><span>Brier Score</span><strong>${num(m.brier_score)}</strong><small>lower is better</small></div>
            <div><span>ROC-AUC</span><strong>${num(m.roc_auc)}</strong><small>ranking performance</small></div>
          </div>

          <p class="ml-note">${m.validation_method||''}</p>
        </article>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">VALIDATION OUTCOMES</div>
              <div class="card-title">Confusion Matrix</div>
            </div>
          </div>

          <div class="confusion-grid">
            <div class="cm-cell cm-good"><span>Caught high rows</span><strong>${cm.true_positive||0}</strong></div>
            <div class="cm-cell cm-warn"><span>Missed high rows</span><strong>${cm.false_negative||0}</strong></div>
            <div class="cm-cell cm-warn"><span>False alert rows</span><strong>${cm.false_positive||0}</strong></div>
            <div class="cm-cell cm-good"><span>Correct low rows</span><strong>${cm.true_negative||0}</strong></div>
          </div>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">MODEL STATUS</div>
              <div class="card-title">Training & Reliability</div>
            </div>
          </div>

          <div class="ml-status-list">
            <div><span>Training through</span><b>${m.training_through_utc?new Date(m.training_through_utc).toLocaleString():'—'}</b></div>
            <div><span>Training rows</span><b>${m.training_rows||0}</b></div>
            <div><span>Threshold</span><b>${m.threshold_ppb||60} ppb</b></div>
            <div><span>Promotion status</span><b>${m.promotion_status||'prototype'}</b></div>
          </div>
        </article>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">MODEL INTERPRETATION</div>
            <div class="card-title">Most Influential Features</div>
          </div>
        </div>

        <div class="ml-feature-list">
          ${(m.feature_importance||[]).map((f,i)=>`
            <div class="ml-feature-row">
              <span>${i+1}. ${f.feature}</span>
              <div class="ml-feature-bar"><i style="width:${Math.min(100,Number(f.importance)*500)}%"></i></div>
              <b>${Number(f.importance).toFixed(3)}</b>
            </div>
          `).join('')}
        </div>

        <p class="ml-note">
          Feature importance remains exploratory while the historical high-event count is small.
        </p>
      </article>
    `;
  }catch(e){
    root.innerHTML=`<div class="ml-empty"><h3>Model status unavailable</h3><p>${e.message}</p></div>`;
  }
}
