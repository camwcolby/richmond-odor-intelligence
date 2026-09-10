
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

    const num=(x,d=2)=>
      x==null
        ? '—'
        : Number(x).toFixed(d);

    const pct=x=>
      x==null
        ? '—'
        : `${Math.round(Number(x)*100)}%`;

    root.innerHTML=`
      <div class="ml-reliability good">
        <b>Stabilized two-layer architecture.</b>
        <span>
          Peak concentration, excursion warning and wastewater residual are evaluated as separate signals.
        </span>
      </div>

      <div class="ml-health-grid">
        <div class="ml-health-card">
          <span>Predicted 60-min peak</span>
          <strong>
            ${p&&p.model_available
              ? num(p.predicted_next_60m_max_h2s_ppb,1)+' ppb'
              : '—'}
          </strong>
          <small>
            ${p&&p.model_available?p.risk_level:'model unavailable'}
          </small>
        </div>

        <div class="ml-health-card">
          <span>Excursion probability</span>
          <strong>
            ${p&&p.model_available
              ? pct(p.excursion_probability)
              : '—'}
          </strong>
          <small>
            alert at ${pct(exc.operating_threshold)}
          </small>
        </div>

        <div class="ml-health-card">
          <span>Wastewater contribution</span>
          <strong>
            ${p&&p.model_available
              ? num(p.excess_wastewater_contribution_ppb,1)+' ppb'
              : '—'}
          </strong>
          <small>
            ${p&&p.model_available?p.wastewater_contribution_level:'—'}
          </small>
        </div>

        <div class="ml-health-card">
          <span>Model version</span>
          <strong class="small-strong">${m.model_version||'—'}</strong>
          <small>
            ${m.training_rows||0} rows • ${m.walk_forward_folds_used||0} folds
          </small>
        </div>
      </div>

      <div class="ml-two-col">
        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">PEAK H₂S FORECAST</div>
              <div class="card-title">
                Next-hour concentration performance
              </div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div>
              <span>MAE</span>
              <strong>${num(peak.mae_ppb)} ppb</strong>
              <small>average absolute error</small>
            </div>

            <div>
              <span>RMSE</span>
              <strong>${num(peak.rmse_ppb)} ppb</strong>
              <small>large-error sensitive</small>
            </div>

            <div>
              <span>R²</span>
              <strong>${num(peak.r2,3)}</strong>
              <small>explained variation</small>
            </div>

            <div>
              <span>MAE ≥30 ppb</span>
              <strong>${num(peak.mae_ge_30_ppb)} ppb</strong>
              <small>elevated periods</small>
            </div>

            <div>
              <span>MAE ≥45 ppb</span>
              <strong>${num(peak.mae_ge_45_ppb)} ppb</strong>
              <small>near-high periods</small>
            </div>

            <div>
              <span>Validation rows</span>
              <strong>${peak.validation_rows||0}</strong>
              <small>walk-forward</small>
            </div>
          </div>

          <p class="ml-note">
            ${m.peak_model_note||''}
          </p>
        </article>

        <article class="panel ml-panel">
          <div class="card-title-row">
            <div>
              <div class="small muted">EXCURSION ALERT</div>
              <div class="card-title">
                Operator-friendly operating point
              </div>
            </div>
          </div>

          <div class="ml-metrics-grid">
            <div>
              <span>Alert threshold</span>
              <strong>${pct(exc.operating_threshold)}</strong>
              <small>validation selected</small>
            </div>

            <div>
              <span>Recall</span>
              <strong>${pct(exc.recall)}</strong>
              <small>excursions caught</small>
            </div>

            <div>
              <span>Precision</span>
              <strong>${pct(exc.precision)}</strong>
              <small>alerts that were right</small>
            </div>

            <div>
              <span>ROC-AUC</span>
              <strong>${num(exc.roc_auc,3)}</strong>
              <small>ranking skill</small>
            </div>

            <div>
              <span>False alerts / week</span>
              <strong>${num(exc.false_alerts_per_week,1)}</strong>
              <small>target ≤ ${num(exc.false_alert_constraint_per_week,1)}</small>
            </div>

            <div>
              <span>Constraint met?</span>
              <strong>${exc.false_alert_constraint_met?'Yes':'No'}</strong>
              <small>nuisance-alert ceiling</small>
            </div>
          </div>

          <p class="ml-note">
            Threshold maximizes recall while keeping false excursion alert episodes
            at or below the configured weekly nuisance limit when possible.
          </p>
        </article>
      </div>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">EXCESS WASTEWATER CONTRIBUTION</div>
            <div class="card-title">
              Explanatory “X” component
            </div>
          </div>
        </div>

        <div class="ml-x-driver">
          <div>
            <span>Current measured H₂S</span>
            <strong>
              ${p&&p.model_available
                ? num(p.current_system_h2s_ppb,1)+' ppb'
                : '—'}
            </strong>
          </div>

          <div class="ml-minus">−</div>

          <div>
            <span>Ordinary-condition environmental baseline</span>
            <strong>
              ${p&&p.model_available
                ? num(p.environmental_baseline_ppb,1)+' ppb'
                : '—'}
            </strong>
          </div>

          <div class="ml-equals">=</div>

          <div class="ml-x-result">
            <span>Excess wastewater contribution</span>
            <strong>
              ${p&&p.model_available
                ? num(p.excess_wastewater_contribution_ppb,1)+' ppb'
                : '—'}
            </strong>
          </div>
        </div>

        <p class="ml-note ml-note-pad">
          ${m.environmental_baseline_definition||''}<br>
          ${m.excess_wastewater_definition||''}
        </p>
      </article>

      <article class="panel ml-panel">
        <div class="card-title-row">
          <div>
            <div class="small muted">PEAK MODEL INTERPRETATION</div>
            <div class="card-title">
              Most Influential Forecast Features
            </div>
          </div>
        </div>

        <div class="ml-feature-list">
          ${(m.feature_importance||[]).map((f,i)=>`
            <div class="ml-feature-row">
              <span>${i+1}. ${f.feature}</span>
              <div class="ml-feature-bar">
                <i style="width:${Math.min(100,Number(f.importance)*500)}%"></i>
              </div>
              <b>${Number(f.importance).toFixed(3)}</b>
            </div>
          `).join('')}
        </div>
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
