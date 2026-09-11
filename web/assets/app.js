const token = localStorage.getItem('auraToken') || 'local-development-only';
const authHeaders = {Authorization: `Bearer ${token}`};
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/assets/sw.js');

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...authHeaders, ...(options.headers || {})}});
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
const notify = error => alert(error.message || String(error));
function empty(message) { const node = document.createElement('div'); node.className = 'empty'; node.textContent = message; return node; }

async function load() {
  try {
    const health = await fetch('/health').then(response => response.json());
    document.querySelector('#connection').textContent = `Conectado · ${health.face_provider === 'RekognitionFaceProvider' ? 'reconocimiento activo' : 'modo de prueba'}`;
    const [people, reviews, contacts, patient, events, tracking] = await Promise.all([
      api('/v1/people'), api('/v1/reviews'), api('/v1/care-contacts'), api('/v1/patient-profile'),
      api('/v1/events?limit=100'), api('/v1/location-sessions/active'),
    ]);
    const pending = reviews.filter(review => review.status === 'pending');
    document.querySelector('#people-count').textContent = people.length;
    document.querySelector('#review-count').textContent = pending.length;
    document.querySelector('#contact-count').textContent = contacts.length;
    const badge = document.querySelector('#review-badge');
    badge.hidden = !pending.length; badge.textContent = pending.length;
    document.querySelector('#contact-status').textContent = contacts.length
      ? `Avisos preparados para ${contacts.map(contact => contact.display_name).join(' y ')}.`
      : 'Todavía no hay destinatarios configurados.';
    document.querySelector('#patient-status').textContent = patient
      ? `Ficha guardada para ${patient.preferred_name}.`
      : 'Ficha del paciente pendiente.';
    if (patient) { fillPatient(patient); await renderPatientPhoto(patient); }
    renderCareContacts(contacts, people);
    populateKnownPersonOptions(people);
    renderPeople(people);
    await renderReviews(pending, people);
    renderEvents(events);
    renderTracking(tracking);
  } catch (error) {
    document.querySelector('#connection').textContent = 'Sin conexión';
    notify(error);
  }
}

const eventLabels = {conversation: 'Conversación', episode: 'Pérdida de memoria o episodio', help_request: 'Petición de ayuda', location: 'Ubicación', recognition: 'Persona reconocida', caregiver_action: 'Acción familiar', hazard: 'Peligro detectado', object_location: 'Objeto recordado', routine: 'Rutina', system: 'Sistema'};
async function renderPatientPhoto(patient) {
  const image=document.querySelector('#patient-photo'), avatar=document.querySelector('#patient-avatar'), status=document.querySelector('#patient-photo-status'), gallery=document.querySelector('#patient-saved-gallery');
  gallery.replaceChildren(); gallery.hidden=true;
  avatar.textContent=(patient.preferred_name||'?').trim().charAt(0).toUpperCase();
  status.textContent=patient.face_enrollment_complete ? 'Preparado para reconocer al propio paciente.' : 'Añade cinco fotos para evitar confusiones.';
  if (!patient.profile_photo_available) { image.hidden=true; avatar.hidden=false; return; }
  try { const response=await fetch('/v1/patient-profile/photo',{headers:authHeaders}); if(!response.ok) throw new Error(); const url=URL.createObjectURL(await response.blob()); image.src=url; image.hidden=false; avatar.hidden=true; image.onload=()=>URL.revokeObjectURL(url); if(patient.face_enrollment_complete){ for(let index=1;index<=5;index++){ const sample=await fetch(`/v1/patient-profile/face-samples/${index}`,{headers:authHeaders}); if(!sample.ok) continue; const sampleImage=document.createElement('img'), sampleUrl=URL.createObjectURL(await sample.blob()); sampleImage.src=sampleUrl; sampleImage.alt=`Foto ${index} del paciente`; sampleImage.onload=()=>URL.revokeObjectURL(sampleUrl); gallery.append(sampleImage); } gallery.hidden=gallery.childElementCount===0; } }
  catch { image.hidden=true; avatar.hidden=false; }
}
const eventIcons = {conversation: '💬', episode: '🧠', help_request: '!', location: '⌖', recognition: '◉', caregiver_action: '♡', hazard: '!', object_location: '⌂', routine: '↻', system: '•'};
const hazardLabels = {smoke_or_fire: 'Fuego o humo', broken_glass: 'Cristales rotos', dangerous_impact: 'Impacto fuerte', water_running: 'Agua corriendo', cookware_heating: 'Cocina encendida', fridge_open: 'Nevera abierta', door_open: 'Puerta abierta', keys_location: 'Llaves localizadas'};
function alertDetails(event) {
  const meta = event.metadata || {}, details = [];
  if (meta.hazard && hazardLabels[meta.hazard]) details.push(hazardLabels[meta.hazard]);
  if (Number(meta.recipients_delivered) > 0) {
    const roles = String(meta.recipient_roles || '').split(',').filter(Boolean).map(role => role === 'family' ? 'familiar' : role === 'caregiver' ? 'cuidador' : role);
    details.push(`Aviso enviado a ${roles.length ? roles.join(' y ') : `${meta.recipients_delivered} destinatarios`}`);
  } else if (meta.family_alert_status === 'sent') details.push('Aviso familiar enviado');
  if (meta.photo_delivery_status === 'sent') details.push('foto incluida');
  if (meta.location_included === true) details.push('ubicación incluida');
  return details.join(' · ');
}
let loadedEvents = [];
function renderEvents(events) {
  loadedEvents = events;
  const kind = document.querySelector('#event-filter').value;
  const severity = document.querySelector('#severity-filter').value;
  const delivery = document.querySelector('#delivery-filter').value;
  const target = document.querySelector('#events'); target.replaceChildren();
  const matchesDelivery = event => {
    const meta = event.metadata || {};
    const sent = Number(meta.recipients_delivered) > 0 || meta.family_alert_status === 'sent';
    return !delivery || (delivery === 'sent' ? sent : !sent);
  };
  for (const event of events.filter(item => (!kind || item.kind === kind) && (!severity || item.severity === severity) && matchesDelivery(item))) {
    const article = document.createElement('article'), label = document.createElement('span'), title = document.createElement('strong'), time = document.createElement('time'), summary = document.createElement('p'), details = document.createElement('small');
    article.classList.add(event.severity || 'info');
    label.className = 'event-kind'; label.textContent = `${eventIcons[event.kind] || '•'} ${eventLabels[event.kind] || event.kind}`;
    title.textContent = event.severity === 'urgent' ? '¡Importante!' : event.severity === 'attention' ? 'Para revisar' : 'Recuerdo';
    time.dateTime = event.occurred_at; time.textContent = new Date(event.occurred_at).toLocaleString();
    summary.textContent = event.summary; details.className = 'event-details'; details.textContent = alertDetails(event);
    article.append(label, title, time, summary); if (details.textContent) article.append(details); target.append(article);
  }
  if (!target.children.length) target.append(empty('Todavía no hay eventos en esta categoría.'));
}
function renderTracking(session) {
  const card = document.querySelector('#tracking-status'); card.hidden = !session;
  if (!session) return;
  const point = session.last_location;
  card.replaceChildren();
  const title = document.createElement('strong'); title.textContent = 'Seguimiento de ubicación activo';
  const detail = document.createElement('span'); detail.textContent = point ? `Última actualización: ${new Date(point.recorded_at).toLocaleString()} · precisión aproximada ${Math.round(point.accuracy_meters || 0)} m` : 'Esperando la primera ubicación del teléfono.';
  card.append(title, detail);
}

function fillPatient(patient) {
  const form = document.querySelector('#patient-form');
  for (const field of ['preferred_name', 'full_name', 'birth_year', 'phone_e164', 'communication_preferences', 'emergency_notes', 'care_notes']) {
    form.elements[field].value = patient[field] || '';
  }
  const home = patient.home_address || {};
  for (const field of ['street_address', 'postal_code', 'locality', 'province', 'country', 'access_notes', 'latitude', 'longitude']) {
    form.elements[`home_${field}`].value = home[field] ?? (field === 'country' ? 'España' : '');
  }
  form.elements.conditions.value = (patient.conditions || []).join('\n');
}

function populateKnownPersonOptions(people) {
  const select = document.querySelector('#care-known-person'), current = select.value;
  select.replaceChildren(new Option('Sin vincular', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id)));
  select.value = current;
  select.onchange = () => {
    const person = people.find(item => item.id === select.value);
    if (person) document.querySelector('#care-contact-form').elements.display_name.value = person.display_name;
  };
}

function renderCareContacts(contacts, people) {
  const target = document.querySelector('#care-contacts'); target.replaceChildren();
  for (const contact of contacts) {
    const item = document.createElement('article'), name = document.createElement('strong'), role = document.createElement('span'), phone = document.createElement('small'), actions = document.createElement('div'), edit = document.createElement('button'), pause = document.createElement('button'), remove = document.createElement('button'), form = document.createElement('form');
    name.textContent = contact.display_name;
    role.textContent = contact.role === 'caregiver' ? 'Cuidador' : 'Familiar';
    const linked = people.find(person => person.id === contact.known_person_id);
    phone.textContent = `${contact.phone_e164} · prioridad ${contact.priority} · ${contact.alerts_enabled ? 'recibe alertas' : 'alertas pausadas'}${linked ? ` · vinculada con ${linked.display_name}` : ''}`;
    actions.className = 'care-actions'; edit.className = 'secondary'; edit.textContent = 'Editar ficha';
    pause.className = 'secondary'; pause.textContent = contact.alerts_enabled ? 'Pausar alertas' : 'Activar alertas';
    remove.className = 'text-danger'; remove.textContent = 'Eliminar';
    form.className = 'care-contact-edit'; form.hidden = true;
    const field = (labelText, control) => { const label = document.createElement('label'); label.append(labelText, control); return label; };
    const displayName = document.createElement('input'); displayName.name = 'display_name'; displayName.required = true; displayName.maxLength = 80; displayName.value = contact.display_name;
    const phoneInput = document.createElement('input'); phoneInput.name = 'phone_e164'; phoneInput.required = true; phoneInput.pattern = '\\+[1-9][0-9]{7,14}'; phoneInput.value = contact.phone_e164;
    const alternatePhone = document.createElement('input'); alternatePhone.name = 'alternate_phone_e164'; alternatePhone.pattern = '\\+[1-9][0-9]{7,14}'; alternatePhone.value = contact.alternate_phone_e164 || '';
    const streetAddress = document.createElement('input'); streetAddress.name = 'street_address'; streetAddress.maxLength = 200; streetAddress.value = contact.address?.street_address || '';
    const locality = document.createElement('input'); locality.name = 'locality'; locality.maxLength = 100; locality.value = contact.address?.locality || '';
    const availability = document.createElement('textarea'); availability.name = 'availability_notes'; availability.maxLength = 500; availability.value = contact.availability_notes || '';
    const roleSelect = document.createElement('select'); roleSelect.name = 'role'; roleSelect.append(new Option('Familiar', 'family'), new Option('Cuidador', 'caregiver')); roleSelect.value = contact.role;
    const prioritySelect = document.createElement('select'); prioritySelect.name = 'priority'; for (let value = 1; value <= 5; value += 1) prioritySelect.append(new Option(String(value), String(value))); prioritySelect.value = String(contact.priority);
    const personSelect = document.createElement('select'); personSelect.name = 'known_person_id'; personSelect.append(new Option('Sin vincular', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id))); personSelect.value = contact.known_person_id || '';
    const save = document.createElement('button'); save.className = 'primary'; save.textContent = 'Guardar cambios';
    form.append(field('Nombre', displayName), field('Teléfono', phoneInput), field('Teléfono alternativo', alternatePhone), field('Dirección', streetAddress), field('Localidad', locality), field('Disponibilidad', availability), field('Rol', roleSelect), field('Prioridad', prioritySelect), field('Persona conocida vinculada', personSelect), save);
    edit.onclick = () => { form.hidden = !form.hidden; edit.textContent = form.hidden ? 'Editar ficha' : 'Cerrar ficha'; };
    pause.onclick = async () => { try { await api(`/v1/care-contacts/${contact.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({alerts_enabled: !contact.alerts_enabled})}); await load(); } catch (error) { notify(error); } };
    form.onsubmit = async event => { event.preventDefault(); const data = new FormData(form); const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {...(contact.address || {}), street_address: data.get('street_address') || '', locality: data.get('locality') || ''}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), priority: Number(data.get('priority')), known_person_id: data.get('known_person_id') || null}; try { await api(`/v1/care-contacts/${contact.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); await load(); } catch (error) { notify(error); } };
    remove.onclick = async () => { if (!confirm(`¿Eliminar a ${contact.display_name} de la red de cuidados?`)) return; try { await api(`/v1/care-contacts/${contact.id}`, {method: 'DELETE'}); await load(); } catch (error) { notify(error); } };
    actions.append(edit, pause, remove); item.append(name, role, phone, actions, form); target.append(item);
  }
  if (!contacts.length) target.append(empty('Todavía no hay familiares o cuidadores configurados.'));
}

function renderPeople(people) {
  const target = document.querySelector('#people'); target.replaceChildren();
  for (const person of people) {
    const node = document.querySelector('#person-template').content.cloneNode(true);
    const avatar = node.querySelector('.avatar'), photo = node.querySelector('.person-photo');
    avatar.textContent = person.display_name.slice(0, 1).toUpperCase();
    if (person.profile_photo_available) {
      fetch(`/v1/people/${person.id}/profile-photo`, {headers: authHeaders}).then(response => {
        if (!response.ok) throw new Error(); return response.blob();
      }).then(blob => {
        const url = URL.createObjectURL(blob); photo.src = url; photo.hidden = false; avatar.hidden = true;
        photo.onload = () => URL.revokeObjectURL(url);
      }).catch(() => {});
    }
    node.querySelector('strong').textContent = person.display_name;
    node.querySelector('small').textContent = person.relationship;
    node.querySelector('.enrollment').textContent = person.enrollment_complete ? '✓ Reconocimiento preparado' : 'Faltan cinco fotografías';
    const editToggle = node.querySelector('.edit-toggle'), editForm = node.querySelector('.person-edit'), gallery = node.querySelector('.face-sample-gallery');
    editForm.elements.display_name.value = person.display_name;
    editForm.elements.relationship.value = person.relationship;
    editForm.elements.consent_granted.checked = person.consent_granted;
    editToggle.addEventListener('click', () => {
      editForm.hidden = !editForm.hidden;
      gallery.hidden = editForm.hidden;
      editToggle.textContent = editForm.hidden ? 'Ver y editar ficha' : 'Cerrar ficha';
      if (!gallery.hidden && !gallery.childElementCount && person.enrollment_complete) {
        for (let index = 1; index <= 5; index += 1) {
          const sample = document.createElement('img');
          sample.alt = `Foto de reconocimiento ${index} de 5 de ${person.display_name}`;
          fetch(`/v1/people/${person.id}/face-samples/${index}`, {headers: authHeaders}).then(response => {
            if (!response.ok) throw new Error(); return response.blob();
          }).then(blob => {
            const url = URL.createObjectURL(blob); sample.src = url;
            sample.onload = () => URL.revokeObjectURL(url);
          }).catch(() => sample.remove());
          gallery.append(sample);
        }
      }
    });
    editForm.addEventListener('submit', async event => {
      event.preventDefault();
      const payload = {
        display_name: editForm.elements.display_name.value.trim(),
        relationship: editForm.elements.relationship.value.trim(),
        consent_granted: editForm.elements.consent_granted.checked,
      };
      try { await api(`/v1/people/${person.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); await load(); }
      catch (error) { notify(error); }
    });
    const form = node.querySelector('.samples'), input = form.elements.files, hint = node.querySelector('.file-hint');
    input.addEventListener('change', () => hint.textContent = input.files.length ? `${input.files.length} de 5 fotografías seleccionadas` : 'Frontal, con buena luz y sin otras personas.');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (input.files.length !== 5) return notify(new Error('Selecciona exactamente cinco fotografías.'));
      const data = new FormData(); [...input.files].forEach(file => data.append('files', file));
      const button = form.querySelector('button'); button.disabled = true; button.textContent = 'Preparando…';
      try { await api(`/v1/people/${person.id}/face-samples`, {method: 'POST', body: data}); await load(); }
      catch (error) { notify(error); }
      finally { button.disabled = false; button.textContent = 'Preparar reconocimiento'; }
    });
    node.querySelector('.delete').addEventListener('click', async () => {
      if (!confirm(`¿Eliminar a ${person.display_name} y todos sus datos biométricos?`)) return;
      try { await api(`/v1/people/${person.id}`, {method: 'DELETE'}); await load(); } catch (error) { notify(error); }
    });
    target.append(node);
  }
  if (!people.length) target.append(empty('Aún no hay personas conocidas. Añade la primera para comenzar.'));
}

async function renderReviews(reviews, people) {
  const target = document.querySelector('#reviews'); target.replaceChildren();
  for (const review of reviews) {
    const item = document.createElement('article'), image = document.createElement('img'), controls = document.createElement('div'), select = document.createElement('select'), button = document.createElement('button');
    image.className = 'review-image'; image.alt = 'Fotografía de la persona pendiente de identificar'; controls.className = 'review-controls';
    try { const response = await fetch(`/v1/reviews/${review.id}/image`, {headers: authHeaders}); if (!response.ok) throw new Error(); const url = URL.createObjectURL(await response.blob()); image.src = url; image.onload = () => URL.revokeObjectURL(url); }
    catch { image.alt = 'La captura ya ha caducado'; image.removeAttribute('src'); }
    const label = document.createElement('label'); label.textContent = `Vista ${new Date(review.created_at).toLocaleString()}`;
    select.append(new Option('No sé quién es', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id)));
    button.className = 'primary'; button.textContent = 'Confirmar respuesta';
    button.onclick = async () => { button.disabled = true; try { await api(`/v1/reviews/${review.id}/resolve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({person_id: select.value || null})}); await load(); } catch (error) { notify(error); } finally { button.disabled = false; } };
    controls.append(label, select, button); item.append(image, controls); target.append(item);
  }
  if (!reviews.length) target.append(empty('No hay identificaciones pendientes. Todo está al día.'));
}

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => { document.querySelectorAll('.tab,.view').forEach(node => node.classList.remove('active')); tab.classList.add('active'); document.querySelector(`#${tab.dataset.view}`).classList.add('active'); }));
document.querySelector('#show-person-form').onclick = () => { document.querySelector('#person-form-card').hidden = false; document.querySelector('#person-form-card input').focus(); };
document.querySelector('#hide-person-form').onclick = () => document.querySelector('#person-form-card').hidden = true;
document.querySelector('#person-form').addEventListener('submit', async event => { event.preventDefault(); const data = new FormData(event.target); try { await api('/v1/people', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({display_name: data.get('display_name'), relationship: data.get('relationship'), consent_granted: data.get('consent_granted') === 'on'})}); event.target.reset(); document.querySelector('#person-form-card').hidden = true; await load(); } catch (error) { notify(error); } });
document.querySelector('#patient-form').addEventListener('submit', async event => {
  event.preventDefault(); const data = new FormData(event.target), year = data.get('birth_year');
  const numberOrNull = (value, label, min, max) => {
    const raw=String(value??'').trim(); if(!raw)return null;
    const parsed=Number(raw.replace(',','.'));
    if(!Number.isFinite(parsed)||parsed<min||parsed>max) throw new Error(`${label} no es válida.`);
    return parsed;
  };
  let latitude, longitude;
  try { latitude=numberOrNull(data.get('home_latitude'),'La latitud',-90,90); longitude=numberOrNull(data.get('home_longitude'),'La longitud',-180,180); }
  catch(error) { notify(error); return; }
  const payload = {preferred_name: data.get('preferred_name'), full_name: data.get('full_name') || '', birth_year: year ? Number(year) : null, phone_e164: data.get('phone_e164') || null, home_address: {street_address: data.get('home_street_address') || '', postal_code: data.get('home_postal_code') || '', locality: data.get('home_locality') || '', province: data.get('home_province') || '', country: data.get('home_country') || 'España', access_notes: data.get('home_access_notes') || '', latitude, longitude}, conditions: String(data.get('conditions') || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean), communication_preferences: data.get('communication_preferences') || '', emergency_notes: data.get('emergency_notes') || '', care_notes: data.get('care_notes') || ''};
  try {
    await api('/v1/patient-profile', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const photos=[...patientPhotoFiles];
    if(photos.length){ if(photos.length!==5) throw new Error('Selecciona exactamente cinco fotos del paciente.'); const samples=new FormData(); photos.forEach(file=>samples.append('files',file)); await api('/v1/patient-profile/face-samples',{method:'POST',body:samples}); }
    patientPhotoFiles=[]; renderPatientPhotoProgress(); await load();
  } catch (error) { notify(error); }
});
let patientPhotoFiles=[];
function renderPatientPhotoProgress(){
  const strip=document.querySelector('#patient-photo-strip'), count=document.querySelector('#patient-photo-count'), progress=document.querySelector('#patient-photo-progress');
  strip.replaceChildren(); count.textContent=`${patientPhotoFiles.length} / 5`;
  patientPhotoFiles.forEach((file,index)=>{ const item=document.createElement('button'), image=document.createElement('img'), remove=document.createElement('span'), url=URL.createObjectURL(file); item.type='button'; item.className='patient-photo-thumb'; item.title=`Quitar foto ${index+1}`; image.src=url; image.alt=`Foto ${index+1} preparada`; image.onload=()=>URL.revokeObjectURL(url); remove.textContent='×'; item.append(image,remove); item.onclick=()=>{patientPhotoFiles.splice(index,1);renderPatientPhotoProgress();}; strip.append(item); });
  for(let index=patientPhotoFiles.length;index<5;index++){ const empty=document.createElement('span'); empty.className='patient-photo-empty'; empty.textContent=index+1; strip.append(empty); }
  progress.textContent=patientPhotoFiles.length===5 ? 'Todo listo. Guarda la ficha para preparar el reconocimiento.' : `Siguiente: foto ${patientPhotoFiles.length+1} de 5. Varía ligeramente el ángulo.`;
}
async function preparePatientPhoto(file){
  if(!file||!file.size)return null;
  const bitmap=await createImageBitmap(file), maxSide=1600, scale=Math.min(1,maxSide/Math.max(bitmap.width,bitmap.height)), canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(bitmap.width*scale)); canvas.height=Math.max(1,Math.round(bitmap.height*scale)); canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height); bitmap.close();
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.82));
  return blob ? new File([blob],`paciente-${Date.now()}.jpg`,{type:'image/jpeg'}) : file;
}
async function addPatientPhoto(file){ const prepared=await preparePatientPhoto(file); if(!prepared)return; if(patientPhotoFiles.length>=5)patientPhotoFiles.shift(); patientPhotoFiles.push(prepared); renderPatientPhotoProgress(); }
for(const input of [document.querySelector('#patient-camera-input'),document.querySelector('#patient-gallery-input')]) input.addEventListener('change',async()=>{const files=[...(input.files||[])].slice(0,Math.max(0,5-patientPhotoFiles.length));input.value='';try{for(const file of files)await addPatientPhoto(file);}catch(error){notify(new Error('No se pudo preparar alguna foto. Prueba con otra imagen.'));}});
renderPatientPhotoProgress();
document.querySelector('#care-contact-form').addEventListener('submit', async event => {
  event.preventDefault(); const data = new FormData(event.target);
  const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {street_address: data.get('street_address') || '', postal_code: data.get('postal_code') || '', locality: data.get('locality') || '', province: data.get('province') || '', country: 'España'}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), whatsapp_consent: data.get('whatsapp_consent') === 'on', priority: Number(data.get('priority')), alerts_enabled: true, known_person_id: data.get('known_person_id') || null};
  try { await api('/v1/care-contacts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); event.target.reset(); await load(); } catch (error) { notify(error); }
});
document.querySelector('#refresh').onclick = load;
for (const filter of ['#event-filter', '#severity-filter', '#delivery-filter']) document.querySelector(filter).onchange = () => renderEvents(loadedEvents);
document.querySelector('#pair').onclick = async () => { try { const invite = await api('/v1/pairing-invites', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({role: document.querySelector('#pair-role').value})}); document.querySelector('#pair-code').textContent = invite.code; } catch (error) { notify(error); } };

const talkForm = document.querySelector('#talk-form');
const talkInput = document.querySelector('#talk-question');
const talkAnswer = document.querySelector('#talk-answer');
const talkStatus = document.querySelector('#talk-status');
const talkMic = document.querySelector('#talk-mic');
const talkReset = document.querySelector('#talk-reset');
let conversationMode = false;
let startListening = null;
let stopListening = null;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const speechLanguages = {es: 'es-ES', gl: 'gl-ES', en: 'en-US'};

function speakAnswer(text, language) {
  return new Promise(resolve => {
    if (!('speechSynthesis' in window) || !text) return resolve();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = speechLanguages[language] || 'es-ES';
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  });
}

async function askFaro(question) {
  const text = String(question || '').trim();
  if (text.length < 2) return notify(new Error('Escribe o di una pregunta.'));
  talkAnswer.hidden = true; talkAnswer.textContent = '';
  talkStatus.hidden = false; talkStatus.textContent = 'Faro está pensando…';
  const button = talkForm.querySelector('button');
  button.disabled = true;
  try {
    const conversationId = localStorage.getItem('familyConversationId') || null;
    const answer = await api('/v1/family/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question: text, conversation_id: conversationId})});
    if (answer.conversation_id) localStorage.setItem('familyConversationId', answer.conversation_id);
    talkAnswer.textContent = answer.answer;
    talkAnswer.hidden = false;
    if (talkReset) talkReset.hidden = false;
    talkStatus.hidden = true;
    await speakAnswer(answer.answer, answer.language);
    if (answer.end_conversation) { conversationMode = false; if (stopListening) stopListening(); }
    else if (conversationMode && startListening) startListening();
  } catch (error) { talkStatus.hidden = true; notify(error); }
  finally { button.disabled = false; }
}

talkForm.addEventListener('submit', event => { event.preventDefault(); askFaro(talkInput.value); });

const microphoneMessage = 'Necesitas permitir el micrófono. En la app instalada, abre Ajustes del teléfono → Aplicaciones → Faro → Permisos → Micrófono, y vuelve a intentarlo.';

async function requestMicrophone() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    stream.getTracks().forEach(track => track.stop());
    return true;
  } catch (error) { return false; }
}

if (SpeechRecognition) {
  const recognition = new SpeechRecognition();
  recognition.lang = 'es-ES';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  let listening = false;
  const updateMic = () => {
    talkMic.setAttribute('aria-pressed', String(conversationMode));
    talkMic.textContent = conversationMode ? (listening ? '⏹ Escuchando…' : '🎤 Hablar') : '🎤 Hablar';
  };
  const setListening = value => { listening = value; updateMic(); };
  startListening = async () => {
    const granted = await requestMicrophone();
    if (!granted) { conversationMode = false; setListening(false); return notify(new Error(microphoneMessage)); }
    try { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); recognition.start(); setListening(true); }
    catch (error) { setListening(false); }
  };
  stopListening = () => { setListening(false); try { recognition.stop(); } catch (error) {} };
  recognition.addEventListener('result', event => {
    const transcript = event.results[0][0].transcript;
    talkInput.value = transcript;
    setListening(false);
    askFaro(transcript);
  });
  recognition.addEventListener('end', () => setListening(false));
  recognition.addEventListener('error', event => {
    setListening(false);
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') { conversationMode = false; return notify(new Error(microphoneMessage)); }
    if (event.error !== 'aborted' && event.error !== 'no-speech') notify(new Error('No se pudo escuchar. Prueba a escribir la pregunta.'));
  });
  talkMic.addEventListener('click', () => {
    if (conversationMode) { conversationMode = false; setListening(false); try { recognition.stop(); } catch (error) {} return; }
    conversationMode = true;
    startListening();
  });
} else {
  talkMic.hidden = true;
}

if (talkReset) {
  talkReset.addEventListener('click', () => {
    localStorage.removeItem('familyConversationId');
    talkAnswer.hidden = true; talkAnswer.textContent = '';
    talkInput.value = '';
    talkReset.hidden = true;
  });
}

load();
