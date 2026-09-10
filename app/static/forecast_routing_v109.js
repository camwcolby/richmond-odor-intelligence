
(function(){
  const state = {
    rendering: false,
    timer: null,
    observer: null,
  };

  function q(sel, root=document){
    return root.querySelector(sel);
  }

  function qa(sel, root=document){
    return [...root.querySelectorAll(sel)];
  }

  async function getJson(url){
    const response = await fetch(url, {
      headers: {"Accept": "application/json"},
      cache: "no-store",
    });

    if(!response.ok){
      throw new Error(`${url} returned ${response.status}`);
    }

    return await response.json();
  }

  function cleanName(name){
    const raw = String(name || "")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    const lower = raw.toLowerCase();

    if(lower.includes("tide")) return "Tide influence";
    if(lower.includes("low wind") || lower.includes("dispersion")) return "Low wind / dispersion";
    if(lower.includes("temperature")) return "Temperature";
    if(lower.includes("live h2s") || lower.includes("live h₂s") || lower === "h2s") return "Live H₂S";
    if(lower.includes("rain")) return "Rainfall";
    if(lower.includes("wastewater")) return "Wastewater contribution";

    return raw
      .replace(/\b\w/g, c => c.toUpperCase())
      .replace("H2S", "H₂S");
  }

  function scoreWastewater(prediction){
    const excess = Math.max(
      0,
      Number(prediction?.excess_wastewater_contribution_ppb || 0)
    );

    // 15 ppb excess = full-scale "High" contribution.
    return Math.max(
      0,
      Math.min(
        100,
        (excess / 15.0) * 100.0
      )
    );
  }

  function extractEngineeringDrivers(risk){
    const drivers = [];

    function add(name, value){
      const n = Number(value);

      if(!Number.isFinite(n)) return;

      const cleaned = cleanName(name);

      if(
        /wastewater/i.test(cleaned) ||
        /overall/i.test(cleaned) ||
        /risk/i.test(cleaned)
      ){
        return;
      }

      drivers.push({
        name: cleaned,
        score: Math.max(0, Math.min(100, n)),
      });
    }

    const candidates = [
      risk?.drivers,
      risk?.primary_drivers,
      risk?.components,
      risk?.risk_drivers,
      risk?.driver_scores,
    ].filter(Boolean);

    for(const block of candidates){
      if(Array.isArray(block)){
        block.forEach(item=>{
          if(item && typeof item === "object"){
            add(
              item.name || item.label || item.driver || item.feature,
              item.score ?? item.value ?? item.risk ?? item.percent
            );
          }
        });
      }else if(typeof block === "object"){
        Object.entries(block).forEach(([name,value])=>{
          if(value && typeof value === "object"){
            add(
              value.name || value.label || name,
              value.score ?? value.value ?? value.risk ?? value.percent
            );
          }else{
            add(name,value);
          }
        });
      }
    }

    // Some versions expose the four engineering components at top level.
    const directMap = [
      ["Tide influence", risk?.tide_proxy ?? risk?.tide_score ?? risk?.tide],
      ["Low wind / dispersion", risk?.low_wind_dispersion ?? risk?.wind_score ?? risk?.dispersion_score],
      ["Temperature", risk?.temperature_score ?? risk?.temperature_risk],
      ["Live H₂S", risk?.live_h2s_score ?? risk?.h2s_score ?? risk?.sensor_score],
      ["Rainfall", risk?.rainfall_score ?? risk?.rain_score],
    ];

    directMap.forEach(([name,value])=>add(name,value));

    // Deduplicate by name, preserving the highest value.
    const dedup = new Map();

    drivers.forEach(d=>{
      const prior = dedup.get(d.name);
      if(!prior || d.score > prior.score){
        dedup.set(d.name,d);
      }
    });

    return [...dedup.values()];
  }

  function findRiskCard(){
    const explicit =
      q("#riskCard") ||
      q(".risk-card");

    if(explicit) return explicit;

    return qa(".card,.panel,article").find(el=>
      /CURRENT ODOR RISK|CURRENT ODOR OUTLOOK/i.test(el.textContent || "")
    ) || null;
  }

  function findRiskElements(card){
    const level =
      q("#riskLevel",card) ||
      q("[data-risk-level]",card) ||
      q(".risk-level",card) ||
      qa("h1,h2,h3,strong,.big-number",card).find(el=>
        /LOW|WATCH|ELEVATED|HIGH|LOADING/i.test((el.textContent || "").trim())
      );

    const pct =
      q("#riskPct",card) ||
      q("#riskPercent",card) ||
      q("[data-risk-percent]",card) ||
      q(".risk-pct",card) ||
      q(".risk-percent",card) ||
      qa("h1,h2,h3,strong,.big-number",card).find(el=>
        /--%|\d+\s*%/i.test((el.textContent || "").trim())
      );

    const narrative =
      q("#riskNarrative",card) ||
      q(".risk-narrative",card) ||
      qa("p",card).find(el=>
        /engineering risk|forecast next-hour|predicted next-hour|trained ml/i.test(el.textContent || "")
      );

    const drivers =
      q("#drivers",card) ||
      q(".drivers",card) ||
      q(".primary-drivers",card);

    return {level,pct,narrative,drivers};
  }

  function sourceNote(h2s){
    if(!h2s) return "";

    const stale = Boolean(h2s.stale_fallback);

    const source = String(
      h2s.source ||
      h2s.metadata?.fallback_source ||
      ""
    );

    if(stale || /history|fallback/i.test(source)){
      return " H₂S is being served from the latest valid cached/ingested observation while the live Sonoma feed refreshes.";
    }

    return " H₂S source is live/cached Sonoma data.";
  }

  function labelForScore(driver){
    if(driver.name === "Wastewater contribution"){
      const score = driver.score;
      if(score >= 100) return "High";
      if(score >= 47) return "Elevated";
      if(score >= 20) return "Moderate";
      return "Low";
    }

    return `${Math.round(driver.score)}`;
  }

  function renderDrivers(container, drivers){
    if(!container) return;

    const sorted = [...drivers]
      .filter(d=>Number.isFinite(d.score))
      .sort((a,b)=>b.score-a.score);

    container.innerHTML = "";

    sorted.forEach(driver=>{
      const row = document.createElement("div");
      row.className = "driver ml-authoritative-driver";

      row.innerHTML = `
        <div class="driver-top">
          <span>${driver.name}</span>
          <b>${labelForScore(driver)}</b>
        </div>
        <div class="bar">
          <i style="width:${Math.max(3,Math.min(100,driver.score))}%"></i>
        </div>
      `;

      container.appendChild(row);
    });
  }

  function renderMlCard(prediction, risk, h2s){
    const card = findRiskCard();
    if(!card) return;

    const {level,pct,narrative,drivers} = findRiskElements(card);

    const peak = Number(
      prediction.predicted_next_60m_max_h2s_ppb || 0
    );

    const riskLevel = String(
      prediction.risk_level || "Low"
    ).toUpperCase();

    if(level){
      level.textContent = riskLevel;
    }

    // We do not fabricate an ML "probability".
    // Replace the old engineering percentage with the actual ML forecast.
    if(pct){
      pct.textContent = `${peak.toFixed(1)} ppb`;
      pct.classList.add("ml-peak-value");

      let caption = q(".ml-peak-caption", pct.parentElement);

      if(!caption){
        caption = document.createElement("div");
        caption.className = "ml-peak-caption";
        pct.insertAdjacentElement("afterend", caption);
      }

      caption.textContent = "Predicted next-hour peak H₂S";
    }

    if(narrative){
      const excess = Number(
        prediction.excess_wastewater_contribution_ppb || 0
      );

      const wastewaterLevel = String(
        prediction.wastewater_contribution_level || "Low"
      ).toLowerCase();

      const excursion = prediction.excursion_probability == null
        ? null
        : Math.round(
            Number(prediction.excursion_probability) * 100
          );

      const excursionText = excursion == null
        ? ""
        : ` Experimental excursion potential ${excursion}% (informational only).`;

      narrative.textContent =
        `Trained ML forecast: next-hour H₂S peak ${peak.toFixed(1)} ppb. ` +
        `Wastewater contribution ${wastewaterLevel} (${excess.toFixed(1)} ppb above environmental baseline).` +
        excursionText +
        sourceNote(h2s);
    }

    const engineering = extractEngineeringDrivers(risk);

    const wastewater = {
      name: "Wastewater contribution",
      score: scoreWastewater(prediction),
    };

    renderDrivers(
      drivers,
      [
        ...engineering,
        wastewater,
      ]
    );

    card.dataset.forecastSource = "ml";
  }

  function renderEngineeringFallback(risk){
    const card = findRiskCard();
    if(!card) return;

    const {narrative} = findRiskElements(card);

    if(narrative){
      narrative.textContent =
        "Engineering risk index fallback. The trained ML prediction endpoint is currently unavailable.";
    }

    card.dataset.forecastSource = "engineering-fallback";
  }

  async function routeForecast(){
    if(state.rendering) return;
    state.rendering = true;

    try{
      const [mlResult,riskResult,h2sResult] = await Promise.allSettled([
        getJson("/api/ml/prediction"),
        getJson("/api/risk"),
        getJson("/api/h2s"),
      ]);

      const prediction =
        mlResult.status === "fulfilled"
          ? mlResult.value
          : null;

      const risk =
        riskResult.status === "fulfilled"
          ? riskResult.value
          : {};

      const h2s =
        h2sResult.status === "fulfilled"
          ? h2sResult.value
          : null;

      if(
        prediction &&
        prediction.model_available
      ){
        renderMlCard(
          prediction,
          risk,
          h2s
        );
      }else{
        renderEngineeringFallback(risk);
      }

    }catch(err){
      console.warn(
        "v1.0.9 forecast routing failed",
        err
      );
    }finally{
      state.rendering = false;
    }
  }

  function schedule(){
    clearTimeout(state.timer);

    state.timer = setTimeout(
      routeForecast,
      150
    );
  }

  function installObserver(){
    const card = findRiskCard();

    if(
      !card ||
      state.observer
    ) return;

    state.observer = new MutationObserver(()=>{
      const text = card.textContent || "";

      if(
        /Loading|engineering risk index|Not yet a trained ML probability/i.test(text)
      ){
        schedule();
      }
    });

    state.observer.observe(
      card,
      {
        childList:true,
        subtree:true,
        characterData:true,
      }
    );
  }

  function boot(){
    routeForecast();

    // Re-run after the legacy app.js initial load completes.
    setTimeout(routeForecast,1200);
    setTimeout(installObserver,1500);

    // Keep model + drivers fresh without hammering endpoints.
    setInterval(routeForecast,60000);
  }

  if(document.readyState === "loading"){
    document.addEventListener(
      "DOMContentLoaded",
      boot
    );
  }else{
    boot();
  }
})();
