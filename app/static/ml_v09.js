
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
          <div class="small muted">MODEL NOT TRAINED</div>
          <h3>Historical model is not available.</h3>
          <p>Run <code>python -m app.ml.cli train</code>.</p>
        </div>`;
      return;
    }

    const ev=m.high_event_metrics||{};

    const num=(x,d=2)=>
      x===null || x===undefined
        ? '—'
        : Number(x).toFixed(d);

    const pct=x=>
      x===null || x===undefined
        ? '—'
        : `${Math.round(Number(x)*100)}%`;

    const whole=x=>
      x===null || x===undefined
        ? '—'
        : Math.round(Number(x));

    const concentrationReliability=
      m.metrics_reliable
        ? `<div class="ml-reliability good">
             <b>Continuous forecast has usable walk-forward coverage.</b>
             <span>${m.reliability_message||''}</span>
           </div>`
        : `<div class="ml-reliability caution">
             <b>Continuous forecast is still provisional.</b>
             <span>${m.reliability_message||''}</span>
           </div>`;

    const eventReliability=
      m.high_event_metrics_reliable
        ? `<div class="ml-reliability good">
             <b>High-event validation has sufficient historical support.</b>
             <span>${m.high_event_reliability_message||''}</span>
           </div>`
        : `<div class="ml-reliability caution">
             <b>&gt;60 ppb event metrics remain exploratory.</b>
             <span>${m.high_event_reliability_message||''}</span>
           </div>`;

    const currentPeak=
      p && p.model_available
        ? `${num(p.predicted_next_60m_max_h2s_ppb,1)} ppb`
        : '—';

    root.innerHTML=`
      ${concentrationReliability}
      ${eventReliability}

      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Predicted 60-min peak</span>
          <strong>${currentPeak}</strong>
          <small>${p&&p.model_available?p.risk_level:'model unavailable'}</small>
        </div>

        <div class="ml-health-card">
          <span>Model selected</span>
          <strong class="small-strong">${m.model_type||'—'}</strong>
          <small>${m.model_version||''}</small>
        </div>

        <div class="ml-health-card">
          <span>Training through</span>
          <strong class="small-strong">
            ${m.training_through_utc
              ? new Date(m.training_through_utc).toLocaleDateString()
              : '—'}
          </strong>
          <small>${m.training_rows||0} labeled rows</small>
        </div>

        <div class="ml-health-card">
          <span>Historical &gt;60 ppb events</span>
          <strong>${m.actual_high_events||0}</strong>
          <small>operational high threshold</small>
        </div>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">CONTINUOUS FORECAST PERFORMANCE</div>
            <div class="card-title">
              How accurately does the model predict the next-hour H₂S peak?
            </div>
          </div>
        </div>

        <div class="ml-metrics-grid">
          <div>
            <span>MAE</span>
            <strong>${num(m.mae_ppb,2)} ppb</strong>
            <small>average absolute error</small>
          </div>

          <div>
            <span>RMSE</span>
            <strong>${num(m.rmse_ppb,2)} ppb</strong>
            <small>penalizes large misses</small>
          </div>

          <div>
            <span>R²</span>
            <strong>${num(m.r2,3)}</strong>
            <small>explained variation</small>
          </div>

          <div>
            <span>MAE when actual ≥30 ppb</span>
            <strong>${num(m.mae_ge_30_ppb,2)} ppb</strong>
            <small>${m.validation_rows_ge_30_ppb||0} validation rows</small>
          </div>

          <div>
            <span>MAE when actual ≥45 ppb</span>
            <strong>${num(m.mae_ge_45_ppb,2)} ppb</strong>
            <small>${m.validation_rows_ge_45_ppb||0} validation rows</small>
          </div>

          <div>
            <span>Walk-forward rows</span>
            <strong>${m.validation_rows||0}</strong>
            <small>${m.walk_forward_folds_used||0} folds</small>
          </div>
        </div>

        <p class="ml-note">
          ${m.selection_rule||''}
        </p>
      </article>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">HIGH-EVENT PERFORMANCE</div>
              <div class="card-title">
                Did the forecast anticipate actual &gt;60 ppb episodes?
              </div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div>
              <span>Event Recall</span>
              <strong>${pct(ev.event_recall)}</strong>
              <small>historical events anticipated</small>
            </div>

            <div>
              <span>Events Anticipated</span>
              <strong>${whole(ev.events_anticipated)}</strong>
              <small>forecast crossed 60 ppb</small>
            </div>

            <div>
              <span>Events Missed</span>
              <strong>${whole(ev.events_missed)}</strong>
              <small>no high alert</small>
            </div>

            <div>
              <span>False High Alerts</span>
              <strong>${whole(ev.false_high_alert_events)}</strong>
              <small>alert episodes without a high event</small>
            </div>

            <div>
              <span>Median Lead Time</span>
              <strong>
                ${ev.median_warning_lead_minutes==null
                  ? '—'
                  : whole(ev.median_warning_lead_minutes)+' min'}
              </strong>
              <small>advance warning</small>
            </div>

            <div>
              <span>Actual Events</span>
              <strong>${whole(ev.actual_events)}</strong>
              <small>contiguous measured excursions</small>
            </div>
          </div>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">MODEL BENCHMARK</div>
              <div class="card-title">
                Candidate Comparison
              </div>
            </div>
          </div>

          <div class="ml-candidate-list">
            ${Object.entries(m.candidate_models||{}).map(([name,v])=>`
              <div class="ml-candidate ${name===m.model_type?'selected':''}">
                <div>
                  <b>${name}</b>
                  <span>${name===m.model_type?'Selected production model':'Candidate'}</span>
                </div>
                <div>
                  <span>MAE</span>
                  <b>${num(v.mae_ppb,2)} ppb</b>
                </div>
                <div>
                  <span>≥30 MAE</span>
                  <b>${num(v.mae_ge_30_ppb,2)} ppb</b>
                </div>
                <div>
                  <span>R²</span>
                  <b>${num(v.r2,3)}</b>
                </div>
              </div>
            `).join('')}
          </div>
        </article>
      </div>

      ${m.feature_importance && m.feature_importance.length
        ? `
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">MODEL INTERPRETATION</div>
              <div class="card-title">Most Influential Features</div>
            </div>
          </div>

          <div class="ml-feature-list">
            ${m.feature_importance.map((f,i)=>`
              <div class="ml-feature-row">
                <span>${i+1}. ${f.feature}</span>
                <div class="ml-feature-bar">
                  <i style="width:${Math.min(100,Number(f.importance)*500)}%"></i>
                </div>
                <b>${Number(f.importance).toFixed(3)}</b>
              </div>
            `).join('')}
          </div>
        </article>`
        : `
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">MODEL INTERPRETATION</div>
              <div class="card-title">Feature interpretation</div>
            </div>
          </div>
          <p class="ml-note ml-note-pad">
            The selected gradient-boosting model does not expose the same simple
            impurity-based feature ranking. A future patch can add permutation
            importance or SHAP to provide comparable explanations.
          </p>
        </article>`
      }
    `;

  }catch(e){
    root.innerHTML=`
      <div class="ml-empty">
        <h3>Model status unavailable</h3>
        <p>${e.message}</p>
      </div>`;
  }
}
