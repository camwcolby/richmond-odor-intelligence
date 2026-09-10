
(function(){
  const RICHMOND_SUFFIX = ", Richmond, California";
  const GEOCODER = "https://nominatim.openstreetmap.org/search";

  function q(sel, root=document){ return root.querySelector(sel); }

  function findReportForm(){
    return (
      q('#report form') ||
      q('#reportForm') ||
      q('form[action*="complaint"]') ||
      [...document.querySelectorAll('form')].find(f =>
        /odor/i.test(f.textContent || '')
      )
    );
  }

  function findFieldByLabel(form, labelText){
    const labels=[...form.querySelectorAll('label')];
    const label=labels.find(l =>
      (l.textContent || '').trim().toLowerCase() === labelText.toLowerCase()
    );
    if(!label) return null;

    if(label.htmlFor){
      const byId=document.getElementById(label.htmlFor);
      if(byId) return byId;
    }

    return label.querySelector('input,select,textarea') ||
      label.parentElement?.querySelector('input,select,textarea');
  }

  function findLatLon(form){
    const inputs=[...form.querySelectorAll('input')];

    const latitude =
      q('#latitude', form) ||
      q('input[name="latitude"]', form) ||
      findFieldByLabel(form,'Latitude') ||
      inputs.find(i => /latitude|^lat$/i.test(i.name || i.id || ''));

    const longitude =
      q('#longitude', form) ||
      q('input[name="longitude"]', form) ||
      findFieldByLabel(form,'Longitude') ||
      inputs.find(i => /longitude|^lon$|^lng$/i.test(i.name || i.id || ''));

    return {latitude, longitude};
  }

  function closestFieldWrapper(input){
    if(!input) return null;
    let n=input.parentElement;
    while(n && n.tagName !== 'FORM'){
      const text=(n.textContent || '').toLowerCase();
      if(
        (text.includes('latitude') || text.includes('longitude')) &&
        n.querySelectorAll('input').length <= 2
      ) return n;
      if(n.classList.contains('field') || n.classList.contains('form-field')) return n;
      n=n.parentElement;
    }
    return input.parentElement;
  }

  function setMode(panel, mode){
    panel.dataset.mode=mode;
    panel.querySelectorAll('[data-location-mode]').forEach(btn=>{
      btn.classList.toggle('active',btn.dataset.locationMode===mode);
      btn.setAttribute(
        'aria-pressed',
        btn.dataset.locationMode===mode ? 'true':'false'
      );
    });

    const address=q('#odor-location-address',panel);
    const landmark=q('#odor-location-landmark',panel);

    address.closest('.location-entry-field').hidden = mode !== 'address';
    landmark.closest('.location-entry-field').hidden = mode !== 'landmark';

    if(mode==='address') address.focus();
    else landmark.focus();
  }

  function installLocationUI(){
    const form=findReportForm();
    if(!form || form.dataset.locationUiInstalled==='1') return;

    const {latitude,longitude}=findLatLon(form);
    if(!latitude || !longitude){
      console.warn('Could not locate latitude/longitude fields for odor report.');
      return;
    }

    form.dataset.locationUiInstalled='1';

    // Preserve the existing coordinates for the existing complaint-submit code,
    // but remove them from public view.
    latitude.type='hidden';
    longitude.type='hidden';

    const latWrap=closestFieldWrapper(latitude);
    const lonWrap=closestFieldWrapper(longitude);

    if(latWrap) latWrap.classList.add('coordinate-field-hidden');
    if(lonWrap) lonWrap.classList.add('coordinate-field-hidden');

    // Hide labels that became detached from visible fields.
    [...form.querySelectorAll('label')].forEach(l=>{
      const t=(l.textContent || '').trim().toLowerCase();
      if(t==='latitude' || t==='longitude') l.classList.add('coordinate-field-hidden');
    });

    const panel=document.createElement('div');
    panel.className='location-entry-panel';
    panel.dataset.mode='address';

    panel.innerHTML=`
      <div class="location-entry-heading">
        <div>
          <label class="location-main-label">Where did you notice the odor?</label>
          <p>
            Enter an address, or use a nearby cross street or landmark if you
            prefer not to provide an exact location.
          </p>
        </div>
        <span class="privacy-pill">Exact location not shown publicly</span>
      </div>

      <div class="location-mode-toggle" role="group" aria-label="Location entry type">
        <button type="button" class="active" data-location-mode="address" aria-pressed="true">
          Address
        </button>
        <button type="button" data-location-mode="landmark" aria-pressed="false">
          Cross street / landmark
        </button>
      </div>

      <div class="location-entry-field">
        <label for="odor-location-address">Address</label>
        <input
          id="odor-location-address"
          type="text"
          autocomplete="street-address"
          placeholder="e.g., 450 Civic Center Plaza"
        />
      </div>

      <div class="location-entry-field" hidden>
        <label for="odor-location-landmark">Closest cross street or landmark</label>
        <input
          id="odor-location-landmark"
          type="text"
          placeholder="e.g., 23rd St & Macdonald Ave or Nicholl Park"
        />
      </div>

      <div class="location-geocode-status" aria-live="polite"></div>
    `;

    // Insert where the old coordinate row lived.
    const insertionTarget =
      latWrap && latWrap.parentElement
        ? latWrap.parentElement
        : form.firstElementChild;

    if(insertionTarget){
      if(
        latWrap &&
        latWrap.parentElement===insertionTarget &&
        insertionTarget !== form
      ){
        insertionTarget.parentElement.insertBefore(panel,insertionTarget);
      }else{
        form.insertBefore(panel,form.firstElementChild);
      }
    }else{
      form.prepend(panel);
    }

    panel.querySelectorAll('[data-location-mode]').forEach(btn=>{
      btn.addEventListener('click',()=>setMode(panel,btn.dataset.locationMode));
    });

    form.addEventListener('submit',async function(event){
      if(form.dataset.geocodeReady==='1'){
        form.dataset.geocodeReady='0';
        return;
      }

      const mode=panel.dataset.mode || 'address';
      const input =
        mode==='address'
          ? q('#odor-location-address',panel)
          : q('#odor-location-landmark',panel);

      const location=(input.value || '').trim();
      const status=q('.location-geocode-status',panel);

      if(!location){
        event.preventDefault();
        event.stopImmediatePropagation();
        status.textContent =
          mode==='address'
            ? 'Please enter an address, or choose Cross street / landmark.'
            : 'Please enter the closest cross street or landmark.';
        status.className='location-geocode-status error';
        input.focus();
        return;
      }

      event.preventDefault();
      event.stopImmediatePropagation();

      status.textContent='Locating report…';
      status.className='location-geocode-status working';

      try{
        let search=location;
        if(!/richmond|california|\bca\b/i.test(search)){
          search += RICHMOND_SUFFIX;
        }

        const url=
          `${GEOCODER}?format=jsonv2&limit=1&countrycodes=us&q=${encodeURIComponent(search)}`;

        const response=await fetch(url,{
          headers:{
            'Accept':'application/json'
          }
        });

        if(!response.ok){
          throw new Error(`Geocoder returned ${response.status}`);
        }

        const results=await response.json();

        if(!results.length){
          throw new Error('Location not found');
        }

        latitude.value=Number(results[0].lat).toFixed(6);
        longitude.value=Number(results[0].lon).toFixed(6);

        status.textContent =
          'Location found. Exact coordinates stay behind the scenes; public views use the nearest landmark.';
        status.className='location-geocode-status success';

        form.dataset.geocodeReady='1';

        // Re-dispatch so the existing app.js complaint handler remains the
        // single source of truth for posting the complaint.
        form.dispatchEvent(
          new Event('submit',{
            bubbles:true,
            cancelable:true
          })
        );

      }catch(err){
        console.error('Odor report geocoding failed:',err);
        status.textContent =
          'We could not locate that entry. Try adding a city/street name or a more specific nearby landmark.';
        status.className='location-geocode-status error';
        input.focus();
      }
    },true);
  }

  function install(){
    installLocationUI();
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',install);
  }else{
    install();
  }
})();
