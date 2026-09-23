const urlToken = new URLSearchParams(location.search).get('token');
if (urlToken) localStorage.setItem('auraToken', urlToken.trim());
const token = localStorage.getItem('auraToken') || 'local-development-only';
const authHeaders = {Authorization: `Bearer ${token}`};
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/assets/sw.js');

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...authHeaders, ...(options.headers || {})}});
  if (!response.ok) {
    let message = `No se pudo completar la operación (${response.status}).`;
    try { message = (await response.json()).detail || message; } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, type = 'info') {
  const stack = document.querySelector('#toast-stack');
  if (!stack) return;
  const node = document.createElement('div');
  node.className = `toast toast--${type}`;
  node.textContent = message;
  stack.append(node);
  setTimeout(() => { node.dataset.leaving = '1'; setTimeout(() => node.remove(), 220); }, type === 'error' ? 6000 : 3500);
}
const notify = (error, type = 'error') => toast(error && error.message ? error.message : String(error), type);

function confirmAction(message, title = '¿Seguro?') {
  const dialog = document.querySelector('#confirm-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve(window.confirm(message));
  return new Promise(resolve => {
    dialog.querySelector('#confirm-title').textContent = title;
    dialog.querySelector('#confirm-message').textContent = message;
    const accept = dialog.querySelector('#confirm-accept');
    const cancel = dialog.querySelector('#confirm-cancel');
    const done = value => {
      accept.removeEventListener('click', onAccept);
      cancel.removeEventListener('click', onCancel);
      dialog.removeEventListener('cancel', onCancel);
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const onAccept = () => done(true);
    const onCancel = event => { if (event && event.preventDefault) event.preventDefault(); done(false); };
    accept.addEventListener('click', onAccept);
    cancel.addEventListener('click', onCancel);
    dialog.addEventListener('cancel', onCancel);
    dialog.showModal();
  });
}

function empty(message) { const node = document.createElement('div'); node.className = 'empty'; node.textContent = message; return node; }
function setBadge(selector, count) {
  const badge = document.querySelector(selector);
  if (!badge) return;
  badge.hidden = !count;
  badge.textContent = count;
}
const isSameDay = (a, b) => a.toDateString() === b.toDateString();

const ICON = {
  conversation: '<path d="M4 5h16v10H9l-5 4z"/>',
  episode: '<path d="M12 4a4 4 0 0 1 4 4v3a4 4 0 0 1-8 0V8a4 4 0 0 1 4-4Z"/><path d="M5 12a7 7 0 0 0 14 0"/>',
  help_request: '<path d="M12 3l9 16H3z"/><path d="M12 9v5"/><circle cx="12" cy="17" r="1"/>',
  location: '<path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11Z"/><circle cx="12" cy="10" r="2.5"/>',
  recognition: '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
  caregiver_action: '<path d="M12 20s-7-4.5-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.5-7 9-7 9Z"/>',
  hazard: '<path d="M12 4l9 16H3z"/><path d="M12 10v4"/><circle cx="12" cy="17" r="1"/>',
  object_location: '<path d="M4 7l8-3 8 3-8 3z"/><path d="M4 7v9l8 3 8-3V7"/>',
  routine: '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v4h4"/>',
  system: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>',
  medication: '<rect x="4" y="9" width="16" height="6" rx="3"/><path d="M9 9l6 6"/>',
  appointment: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 9h16M8 3v4M16 3v4"/>',
};
function icon(name, size = 16) {
  const path = ICON[name] || ICON.system;
  return `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

async function load() {
  const labels = ['personas', 'personas por aclarar', 'cuidados', 'paciente', 'memoria', 'ubicación', 'ejercicios', 'resumen de ejercicios', 'agenda'];
  const requests = [
    api('/v1/people'), api('/v1/reviews'), api('/v1/care-contacts'), api('/v1/patient-profile'),
    api('/v1/events?limit=500'), api('/v1/location-sessions/active'),
    api('/v1/cognitive-exercises'), api('/v1/cognitive-exercises/summary'), api('/v1/calendar-events'),
  ];
  const settled = await Promise.allSettled(requests);
  const failed = [];
  const pick = index => {
    const result = settled[index];
    if (result.status === 'fulfilled') return result.value;
    failed.push(labels[index]);
    return null;
  };
  const people = pick(0) || [];
  const reviews = pick(1) || [];
  const contacts = pick(2) || [];
  const patient = pick(3);
  const events = pick(4) || [];
  const tracking = pick(5);
  const exercises = pick(6) || [];
  const exerciseSummary = pick(7);
  const agenda = pick(8) || [];

  const pending = reviews.filter(review => review.status === 'pending');
  document.querySelector('#people-count').textContent = people.length;
  document.querySelector('#review-count').textContent = pending.length;
  document.querySelector('#contact-count').textContent = contacts.length;
  setBadge('#review-badge', pending.length);
  setBadge('#patient-badge', patient ? 0 : 1);
  setBadge('#people-badge', people.filter(person => !person.enrollment_complete).length);
  setBadge('#care-badge', contacts.filter(contact => !contact.alerts_enabled).length);
  setBadge('#memory-badge', events.filter(event => event.severity === 'urgent' || event.severity === 'attention').length);
  setBadge('#exercises-badge', exercises.filter(exercise => exercise.status !== 'completed').length);
  setBadge('#agenda-badge', agenda.filter(event => isSameDay(new Date(event.start_at), new Date())).length);
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
  renderMemory(events);
  renderTracking(tracking);
  if (exerciseSummary) renderExercises(exercises, exerciseSummary);
  renderAgenda(agenda);

  if (failed.length) toast(`No se pudo cargar: ${failed.join(', ')}.`, 'error');
}

const eventLabels = {conversation: 'Conversación', episode: 'Pérdida de memoria o episodio', help_request: 'Petición de ayuda', location: 'Ubicación', recognition: 'Persona reconocida', caregiver_action: 'Acción familiar', hazard: 'Peligro detectado', object_location: 'Objeto recordado', routine: 'Rutina', system: 'Sistema'};
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

/* ----------------------------- Memoria --------------------------------- */

let loadedEvents = [];
const MEMORY_PAGE = 25;
let memoryPage = 1;

function dayLabel(date) {
  const today = new Date(), yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return 'Hoy';
  if (sameDay(date, yesterday)) return 'Ayer';
  const label = date.toLocaleDateString('es-ES', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function eventMatches(event, kind, severity, delivery, query) {
  const meta = event.metadata || {};
  const sent = Number(meta.recipients_delivered) > 0 || meta.family_alert_status === 'sent';
  if (kind && event.kind !== kind) return false;
  if (severity && event.severity !== severity) return false;
  if (delivery === 'sent' && !sent) return false;
  if (delivery === 'not_sent' && sent) return false;
  if (query) {
    const haystack = `${event.summary || ''} ${eventLabels[event.kind] || ''} ${alertDetails(event)}`.toLowerCase();
    if (!haystack.includes(query)) return false;
  }
  return true;
}

function eventCard(event) {
  const article = document.createElement('article');
  article.classList.add(event.severity || 'info');
  const label = document.createElement('span');
  label.className = 'event-kind';
  label.innerHTML = `${icon(event.kind)} ${eventLabels[event.kind] || event.kind}`;
  const title = document.createElement('strong');
  title.textContent = (event.summary || '').trim() || eventLabels[event.kind] || 'Momento';
  const time = document.createElement('time');
  time.dateTime = event.occurred_at;
  time.textContent = new Date(event.occurred_at).toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit'});
  article.append(label, title, time);
  if (event.severity && event.severity !== 'info') {
    const chip = document.createElement('span');
    chip.className = `event-severity ${event.severity}`;
    chip.textContent = event.severity === 'urgent' ? 'Urgente' : 'Atención';
    article.append(chip);
  }
  const details = document.createElement('small');
  details.className = 'event-details';
  details.textContent = alertDetails(event);
  if (details.textContent) article.append(details);
  return article;
}

function renderMemory(events) {
  if (events) { loadedEvents = events; memoryPage = 1; }
  const target = document.querySelector('#events');
  if (!target) return;
  const status = document.querySelector('#events-status');
  const kind = document.querySelector('#event-filter').value;
  const severity = document.querySelector('#severity-filter').value;
  const delivery = document.querySelector('#delivery-filter').value;
  const order = document.querySelector('#event-order').value;
  const query = document.querySelector('#event-search').value.trim().toLowerCase();

  const filtered = loadedEvents
    .filter(event => eventMatches(event, kind, severity, delivery, query))
    .sort((a, b) => new Date(b.occurred_at) - new Date(a.occurred_at));
  const total = filtered.length;
  if (order === 'oldest') filtered.reverse();
  const visible = filtered.slice(0, memoryPage * MEMORY_PAGE);

  target.replaceChildren();
  const groups = new Map();
  for (const event of visible) {
    const date = new Date(event.occurred_at);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    if (!groups.has(key)) groups.set(key, {date, items: []});
    groups.get(key).items.push(event);
  }
  for (const group of groups.values()) {
    if (order === 'kind') {
      group.items.sort((a, b) => (eventLabels[a.kind] || a.kind).localeCompare(eventLabels[b.kind] || b.kind) || new Date(b.occurred_at) - new Date(a.occurred_at));
    }
    const day = document.createElement('section');
    day.className = 'timeline-day reveal';
    const heading = document.createElement('h3');
    heading.textContent = dayLabel(group.date);
    const list = document.createElement('div');
    list.className = 'timeline-items';
    for (const event of group.items) list.append(eventCard(event));
    day.append(heading, list);
    target.append(day);
  }
  if (!total) target.append(empty('Todavía no hay eventos en esta categoría.'));
  const shown = visible.length;
  if (status) status.textContent = total ? `Mostrando ${shown} de ${total} momentos.` : 'Sin resultados para estos filtros.';
  if (shown < total) {
    const wrap = document.createElement('div');
    wrap.className = 'more-wrap';
    const more = document.createElement('button');
    more.className = 'secondary';
    more.textContent = `Ver más (${total - shown})`;
    more.onclick = () => { memoryPage += 1; renderMemory(); };
    wrap.append(more);
    target.append(wrap);
  }
  observeReveals(target);
}

async function renderPatientPhoto(patient) {
  const image = document.querySelector('#patient-photo'), avatar = document.querySelector('#patient-avatar'), status = document.querySelector('#patient-photo-status'), gallery = document.querySelector('#patient-saved-gallery');
  gallery.replaceChildren(); gallery.hidden = true;
  avatar.textContent = (patient.preferred_name || '?').trim().charAt(0).toUpperCase();
  status.textContent = patient.face_enrollment_complete ? 'Preparado para reconocer al propio paciente.' : 'Añade al menos una foto para evitar confusiones.';
  if (!patient.profile_photo_available) { image.hidden = true; avatar.hidden = false; return; }
  try {
    const response = await fetch('/v1/patient-profile/photo', {headers: authHeaders});
    if (!response.ok) throw new Error();
    const url = URL.createObjectURL(await response.blob());
    image.src = url; image.hidden = false; avatar.hidden = true; image.onload = () => URL.revokeObjectURL(url);
    const count = Math.min(Math.max(patient.face_enrollment_samples || 0, 0), 5);
    const blobs = await Promise.all([...Array(count)].map((_, index) =>
      fetch(`/v1/patient-profile/face-samples/${index + 1}`, {headers: authHeaders}).then(result => result.ok ? result.blob() : null).catch(() => null)));
    for (const blob of blobs) {
      if (!blob) continue;
      const sampleImage = document.createElement('img'), sampleUrl = URL.createObjectURL(blob);
      sampleImage.src = sampleUrl; sampleImage.loading = 'lazy'; sampleImage.alt = 'Foto de reconocimiento del paciente'; sampleImage.onload = () => URL.revokeObjectURL(sampleUrl);
      gallery.append(sampleImage);
    }
    gallery.hidden = gallery.childElementCount === 0;
  } catch { image.hidden = true; avatar.hidden = false; }
}

function renderTracking(session) {
  const card = document.querySelector('#tracking-status');
  card.hidden = !session;
  if (!session) return;
  const point = session.last_location;
  card.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = 'Seguimiento de ubicación activo';
  const detail = document.createElement('span');
  detail.textContent = point ? `Última actualización: ${new Date(point.recorded_at).toLocaleString()} · precisión aproximada ${Math.round(point.accuracy_meters || 0)} m` : 'Esperando la primera ubicación del teléfono.';
  card.append(title, detail);
}

async function answerExercise(id, correct) {
  try {
    await api(`/v1/cognitive-exercises/${id}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({correct})});
    toast(correct ? 'Registrado: acertó.' : 'Registrado: le costó.', 'success');
    await load();
  } catch (error) { notify(error); }
}

function renderExercises(exercises, summary) {
  const target = document.querySelector('#exercises');
  if (!target) return;
  const line = document.querySelector('#exercise-summary');
  if (line) line.textContent = summary.total
    ? `${summary.completed} de ${summary.total} realizados · ${summary.correct} correctos (${summary.accuracy} %).`
    : 'Sin resultados todavía.';
  target.replaceChildren();
  for (const exercise of exercises.slice(0, 30)) {
    const article = document.createElement('article'), question = document.createElement('strong'),
      answer = document.createElement('small'), state = document.createElement('span');
    article.className = 'exercise-card';
    question.textContent = exercise.question;
    answer.textContent = `Respuesta esperada: ${exercise.expected_answer}`;
    const when = exercise.scheduled_at ? ` · programado ${new Date(exercise.scheduled_at).toLocaleString()}` : '';
    state.textContent = exercise.status === 'completed'
      ? (exercise.correct ? 'Resultado: correcto' : 'Resultado: con dificultad')
      : `Pendiente${when}`;
    article.append(question, answer, state);
    if (exercise.patient_answer) {
      const said = document.createElement('small');
      said.className = 'patient-answer';
      said.textContent = `Respondió: «${exercise.patient_answer}»`;
      article.append(said);
    }
    if (exercise.status !== 'completed') {
      const actions = document.createElement('div');
      actions.className = 'exercise-actions';
      const select = document.createElement('select');
      select.append(new Option('¿Cómo respondió?', ''), new Option('Respondió bien', 'correct'), new Option('Respondió mal', 'wrong'));
      const save = document.createElement('button');
      save.className = 'primary';
      save.textContent = 'Guardar resultado';
      save.onclick = async () => {
        if (!select.value) return toast('Elige cómo respondió el paciente.', 'error');
        save.disabled = true;
        try {
          await api(`/v1/cognitive-exercises/${exercise.id}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({correct: select.value === 'correct'})});
          toast('Resultado guardado.', 'success');
          await load();
        } catch (error) { notify(error); } finally { save.disabled = false; }
      };
      actions.append(select, save);
      article.append(actions);
    }
    target.append(article);
  }
  if (!target.children.length) target.append(empty('Todavía no hay ejercicios. Programa uno con el formulario de arriba.'));
}

const exerciseForm = document.querySelector('#exercise-form');
if (exerciseForm) {
  exerciseForm.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.target);
    const when = data.get('scheduled_at');
    if (!when) return notify(new Error('Indica la fecha y la hora.'));
    try {
      await api('/v1/cognitive-exercises/scheduled', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          question: data.get('question'), expected_answer: data.get('expected_answer'),
          scheduled_at: new Date(when).toISOString(), category: data.get('category'),
          notes: data.get('notes') || null,
        }),
      });
      event.target.reset();
      const status = document.querySelector('#exercise-program-status');
      if (status) status.textContent = 'Ejercicio programado. Faro se lo preguntará a la hora indicada.';
      toast('Ejercicio programado.', 'success');
      await load();
    } catch (error) { notify(error); }
  });
}
for (const period of ['daily', 'weekly', 'monthly']) {
  const button = document.querySelector(`#report-${period}`);
  if (button) button.addEventListener('click', async () => {
    try {
      const report = await api(`/v1/cognitive-exercises/report?period=${period}`);
      const line = document.querySelector('#exercise-report');
      if (line) line.textContent = report.summary;
    } catch (error) { notify(error); }
  });
}

const agendaCategoryLabels = {medication: 'Medicación', routine: 'Rutina', appointment: 'Cita', other: 'Otra cosa'};
const agendaRecurrenceLabels = {daily: 'diario', weekly: 'semanal', monthly: 'mensual'};
const agendaWeekdayLabels = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
function agendaRecurrenceText(event) {
  if (!event.recurrence || event.recurrence === 'none') return 'una vez';
  let text = agendaRecurrenceLabels[event.recurrence] || event.recurrence;
  if (event.recurrence_interval > 1) text += ` (cada ${event.recurrence_interval})`;
  if (event.recurrence === 'weekly' && (event.recurrence_weekdays || []).length) {
    text += ` ${event.recurrence_weekdays.map(day => agendaWeekdayLabels[day] || day).join('')}`;
  }
  if (event.recurrence_until) text += ` hasta ${event.recurrence_until}`;
  return text;
}
function toLocalInput(value) {
  const date = new Date(value), offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}

function renderAgenda(events) {
  const target = document.querySelector('#agenda-events');
  if (!target) return;
  const line = document.querySelector('#agenda-status');
  if (line) line.textContent = events.length
    ? `${events.length} ${events.length === 1 ? 'recordatorio programado' : 'recordatorios programados'}.`
    : 'Sin recordatorios todavía.';
  target.replaceChildren();
  for (const event of events) {
    const article = document.createElement('article'), title = document.createElement('strong'),
      meta = document.createElement('small'), actions = document.createElement('div'), form = document.createElement('form');
    article.className = event.enabled ? 'agenda-item' : 'agenda-item agenda-item-disabled';
    title.innerHTML = `${icon(event.category === 'medication' ? 'medication' : event.category === 'appointment' ? 'appointment' : 'routine')} ${event.title}`;
    meta.textContent = `${agendaCategoryLabels[event.category] || event.category} · ${new Date(event.start_at).toLocaleString()} · ${agendaRecurrenceText(event)} · aviso ${event.reminder_minutes_before} min antes · ${event.for_patient ? 'paciente' : 'familia'}`;
    actions.className = 'agenda-actions';
    const toggle = document.createElement('button'); toggle.className = 'secondary';
    toggle.textContent = event.enabled ? 'Desactivar' : 'Activar';
    toggle.onclick = async () => { try { await api(`/v1/calendar-events/${event.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !event.enabled})}); await load(); } catch (error) { notify(error); } };
    const edit = document.createElement('button'); edit.className = 'secondary'; edit.textContent = 'Cambiar hora';
    form.className = 'agenda-edit'; form.hidden = true;
    const label = document.createElement('label'); label.textContent = 'Nueva fecha y hora';
    const input = document.createElement('input'); input.type = 'datetime-local'; input.required = true; input.value = toLocalInput(event.start_at);
    label.append(input);
    const save = document.createElement('button'); save.className = 'primary'; save.textContent = 'Guardar';
    form.append(label, save);
    form.onsubmit = async submitEvent => { submitEvent.preventDefault(); if (!input.value) return notify(new Error('Indica la fecha y la hora.')); try { await api(`/v1/calendar-events/${event.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({start_at: new Date(input.value).toISOString()})}); await load(); } catch (error) { notify(error); } };
    edit.onclick = () => { form.hidden = !form.hidden; };
    const remove = document.createElement('button'); remove.className = 'text-danger'; remove.textContent = 'Eliminar';
    remove.onclick = async () => { if (!(await confirmAction(`¿Eliminar el recordatorio «${event.title}»?`))) return; try { await api(`/v1/calendar-events/${event.id}`, {method: 'DELETE'}); await load(); } catch (error) { notify(error); } };
    actions.append(toggle, edit, remove);
    article.append(title, meta, actions, form);
    target.append(article);
  }
  if (!events.length) target.append(empty('Programa el primer recordatorio con el formulario de arriba.'));
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
  const select = document.querySelector('#care-known-person');
  if (!select) return;
  const current = select.value;
  select.replaceChildren(new Option('Sin vincular', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id)));
  select.value = current;
  select.onchange = () => {
    const person = people.find(item => item.id === select.value);
    if (person) document.querySelector('#care-contact-form').elements.display_name.value = person.display_name;
  };
}

function renderCareContacts(contacts, people) {
  const target = document.querySelector('#care-contacts');
  target.replaceChildren();
  for (const contact of contacts) {
    const item = document.createElement('article'), name = document.createElement('strong'), role = document.createElement('span'), phone = document.createElement('small'), actions = document.createElement('div'), edit = document.createElement('button'), pause = document.createElement('button'), remove = document.createElement('button'), form = document.createElement('form');
    name.textContent = contact.display_name;
    role.textContent = contact.role === 'caregiver' ? 'Cuidador' : 'Familiar';
    const linked = people.find(person => person.id === contact.known_person_id);
    const avatar = document.createElement('div'); avatar.className = 'avatar'; avatar.textContent = (contact.display_name || '?').charAt(0).toUpperCase(); item.append(avatar);
    if (linked) {
      fetch(`/v1/people/${linked.id}/profile-photo`, {headers: authHeaders})
        .then(response => { if (!response.ok) throw new Error(); return response.blob(); })
        .then(blob => { const url = URL.createObjectURL(blob); const image = document.createElement('img'); image.className = 'person-photo'; image.alt = linked.display_name; image.src = url; image.onload = () => URL.revokeObjectURL(url); avatar.replaceWith(image); })
        .catch(() => {});
    }
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
    form.onsubmit = async event => { event.preventDefault(); const data = new FormData(form); const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {...(contact.address || {}), street_address: data.get('street_address') || '', locality: data.get('locality') || ''}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), priority: Number(data.get('priority')), known_person_id: data.get('known_person_id') || null}; try { await api(`/v1/care-contacts/${contact.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); toast('Contacto actualizado.', 'success'); await load(); } catch (error) { notify(error); } };
    remove.onclick = async () => { if (!(await confirmAction(`¿Eliminar a ${contact.display_name} de la red de cuidados?`))) return; try { await api(`/v1/care-contacts/${contact.id}`, {method: 'DELETE'}); await load(); } catch (error) { notify(error); } };
    actions.append(edit, pause, remove); item.append(name, role, phone, actions, form); target.append(item);
  }
  if (!contacts.length) target.append(empty('Todavía no hay familiares o cuidadores configurados.'));
}

function renderPeople(people) {
  const target = document.querySelector('#people');
  target.replaceChildren();
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
    node.querySelector('.enrollment').textContent = person.enrollment_complete
      ? '✓ Reconocimiento preparado'
      : 'Añade al menos una foto para reconocerla';
    const editToggle = node.querySelector('.edit-toggle'), editForm = node.querySelector('.person-edit'), gallery = node.querySelector('.face-sample-gallery');
    editForm.elements.display_name.value = person.display_name;
    editForm.elements.relationship.value = person.relationship;
    editForm.elements.consent_granted.checked = person.consent_granted;
    editToggle.addEventListener('click', () => {
      editForm.hidden = !editForm.hidden;
      gallery.hidden = editForm.hidden;
      editToggle.textContent = editForm.hidden ? 'Ver y editar ficha' : 'Cerrar ficha';
      if (!gallery.hidden && !gallery.childElementCount && person.enrollment_complete) {
        const count = Math.min(Math.max(person.enrollment_samples || 1, 1), 5);
        for (let index = 1; index <= count; index += 1) {
          const sample = document.createElement('img');
          sample.loading = 'lazy';
          sample.alt = `Foto de reconocimiento ${index} de ${count} de ${person.display_name}`;
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
      try { await api(`/v1/people/${person.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); toast('Ficha actualizada.', 'success'); await load(); }
      catch (error) { notify(error); }
    });
    const form = node.querySelector('.samples'), input = form.elements.files, hint = node.querySelector('.file-hint');
    input.addEventListener('change', () => hint.textContent = input.files.length ? `${input.files.length} de 5 fotografías seleccionadas` : 'De 1 a 5 fotos. Frontal, con buena luz y sin otras personas (3–5 mejoran la precisión).');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const files = [...input.files].slice(0, 5);
      if (files.length < 1) return notify(new Error('Selecciona al menos una fotografía.'));
      const data = new FormData();
      for (const file of files) { const prepared = await preparePhoto(file); data.append('files', prepared || file); }
      const button = form.querySelector('button'); button.disabled = true; button.textContent = 'Preparando…';
      try { await api(`/v1/people/${person.id}/face-samples`, {method: 'POST', body: data}); toast('Reconocimiento preparado.', 'success'); await load(); }
      catch (error) { notify(error); }
      finally { button.disabled = false; button.textContent = 'Preparar reconocimiento'; }
    });
    node.querySelector('.delete').addEventListener('click', async () => {
      if (!(await confirmAction(`¿Eliminar a ${person.display_name} y todos sus datos biométricos? Esta acción no se puede deshacer.`))) return;
      try { await api(`/v1/people/${person.id}`, {method: 'DELETE'}); toast('Persona eliminada.', 'success'); await load(); } catch (error) { notify(error); }
    });
    target.append(node);
  }
  if (!people.length) target.append(empty('Aún no hay personas conocidas. Añade la primera para comenzar.'));
}

async function renderReviews(reviews, people) {
  const target = document.querySelector('#reviews');
  target.replaceChildren();
  for (const review of reviews) {
    const item = document.createElement('article'), image = document.createElement('img'), controls = document.createElement('div'), select = document.createElement('select'), button = document.createElement('button'), discard = document.createElement('button');
    image.className = 'review-image'; image.alt = 'Fotografía de la persona pendiente de identificar'; image.loading = 'lazy'; controls.className = 'review-controls';
    try { const response = await fetch(`/v1/reviews/${review.id}/image`, {headers: authHeaders}); if (!response.ok) throw new Error(); const url = URL.createObjectURL(await response.blob()); image.src = url; image.onload = () => URL.revokeObjectURL(url); }
    catch { image.alt = 'La captura ya ha caducado'; image.removeAttribute('src'); }
    const label = document.createElement('label'); label.textContent = `Captura del ${new Date(review.created_at).toLocaleString()}`;
    select.append(new Option('Selecciona una persona…', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id)));
    button.className = 'primary'; button.textContent = 'Confirmar';
    button.onclick = async () => {
      if (!select.value) return toast('Elige una persona o usa «Descartar».', 'error');
      button.disabled = true;
      try { await api(`/v1/reviews/${review.id}/resolve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({person_id: select.value})}); toast('Gracias. Faro ya reconocerá a esa persona.', 'success'); await load(); }
      catch (error) { notify(error); } finally { button.disabled = false; }
    };
    discard.className = 'secondary'; discard.textContent = 'Descartar';
    discard.onclick = async () => {
      if (!(await confirmAction('¿Descartar esta captura? Se borrará la imagen y no volverá a aparecer.', 'Descartar captura'))) return;
      try { await api(`/v1/reviews/${review.id}/resolve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({person_id: null})}); toast('Captura descartada.', 'success'); await load(); }
      catch (error) { notify(error); }
    };
    controls.append(label, select, button, discard); item.append(image, controls); target.append(item);
  }
  if (!reviews.length) target.append(empty('No hay identificaciones pendientes. Todo está al día.'));
}

/* --------------------------- Navegación (tabs) -------------------------- */

const tabs = [...document.querySelectorAll('.tab')];
function activateTab(tab) {
  tabs.forEach(node => {
    const active = node === tab;
    node.classList.toggle('active', active);
    node.setAttribute('aria-selected', String(active));
    node.tabIndex = active ? 0 : -1;
    document.querySelector(`#${node.dataset.view}`).classList.toggle('active', active);
  });
}
tabs.forEach((tab, index) => {
  tab.tabIndex = tab.classList.contains('active') ? 0 : -1;
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', event => {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (delta) { event.preventDefault(); const next = tabs[(index + delta + tabs.length) % tabs.length]; next.focus(); activateTab(next); }
    if (event.key === 'Home') { event.preventDefault(); tabs[0].focus(); activateTab(tabs[0]); }
    if (event.key === 'End') { event.preventDefault(); tabs[tabs.length - 1].focus(); activateTab(tabs[tabs.length - 1]); }
  });
});

/* --------------------------- Animaciones suaves ------------------------- */

let revealObserver = null;
if ('IntersectionObserver' in window) {
  revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('is-visible'); revealObserver.unobserve(entry.target); } });
  }, {threshold: 0.12});
}
function observeReveals(root = document) {
  const nodes = root.querySelectorAll ? root.querySelectorAll('.reveal:not(.is-visible)') : [];
  nodes.forEach(node => revealObserver ? revealObserver.observe(node) : node.classList.add('is-visible'));
}
let scrollTick = false;
addEventListener('scroll', () => {
  if (scrollTick) return;
  scrollTick = true;
  requestAnimationFrame(() => { document.documentElement.style.setProperty('--scroll', `${Math.min(scrollY, 500)}px`); scrollTick = false; });
}, {passive: true});

/* ------------------------------------------------ Acciones --------------- */

document.querySelector('#show-person-form').onclick = () => { document.querySelector('#person-form-card').hidden = false; document.querySelector('#person-form-card input').focus(); };
document.querySelector('#hide-person-form').onclick = () => document.querySelector('#person-form-card').hidden = true;
document.querySelector('#person-form').addEventListener('submit', async event => {
  event.preventDefault();
  const data = new FormData(event.target);
  try {
    await api('/v1/people', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({display_name: String(data.get('display_name')).trim(), relationship: String(data.get('relationship')).trim(), consent_granted: data.get('consent_granted') === 'on'})});
    event.target.reset();
    document.querySelector('#person-form-card').hidden = true;
    toast('Persona creada. Añade ahora sus fotos.', 'success');
    await load();
  } catch (error) { notify(error); }
});

document.querySelector('#patient-form').addEventListener('submit', async event => {
  event.preventDefault(); const data = new FormData(event.target), year = data.get('birth_year');
  const numberOrNull = (value, label, min, max) => {
    const raw = String(value ?? '').trim(); if (!raw) return null;
    const parsed = Number(raw.replace(',', '.'));
    if (!Number.isFinite(parsed) || parsed < min || parsed > max) throw new Error(`${label} no es válida.`);
    return parsed;
  };
  let latitude, longitude;
  try { latitude = numberOrNull(data.get('home_latitude'), 'La latitud', -90, 90); longitude = numberOrNull(data.get('home_longitude'), 'La longitud', -180, 180); }
  catch (error) { notify(error); return; }
  const payload = {preferred_name: data.get('preferred_name'), full_name: data.get('full_name') || '', birth_year: year ? Number(year) : null, phone_e164: data.get('phone_e164') || null, home_address: {street_address: data.get('home_street_address') || '', postal_code: data.get('home_postal_code') || '', locality: data.get('home_locality') || '', province: data.get('home_province') || '', country: data.get('home_country') || 'España', access_notes: data.get('home_access_notes') || '', latitude, longitude}, conditions: String(data.get('conditions') || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean), communication_preferences: data.get('communication_preferences') || '', emergency_notes: data.get('emergency_notes') || '', care_notes: data.get('care_notes') || ''};
  try {
    await api('/v1/patient-profile', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const photos = [...patientPhotoFiles];
    if (photos.length) { const samples = new FormData(); photos.forEach(file => samples.append('files', file)); await api('/v1/patient-profile/face-samples', {method: 'POST', body: samples}); }
    patientPhotoFiles = []; renderPatientPhotoProgress();
    toast('Ficha del paciente guardada.', 'success');
    await load();
  } catch (error) { notify(error); }
});

let patientPhotoFiles = [];
function renderPatientPhotoProgress() {
  const strip = document.querySelector('#patient-photo-strip'), count = document.querySelector('#patient-photo-count'), progress = document.querySelector('#patient-photo-progress');
  strip.replaceChildren(); count.textContent = `${patientPhotoFiles.length} / 5`;
  patientPhotoFiles.forEach((file, index) => { const item = document.createElement('button'), image = document.createElement('img'), remove = document.createElement('span'); const url = URL.createObjectURL(file); item.type = 'button'; item.className = 'patient-photo-thumb'; item.title = `Quitar foto ${index + 1}`; item.setAttribute('aria-label', `Quitar foto ${index + 1}`); image.src = url; image.alt = `Foto ${index + 1} preparada`; image.onload = () => URL.revokeObjectURL(url); remove.textContent = '×'; item.append(image, remove); item.onclick = () => { patientPhotoFiles.splice(index, 1); renderPatientPhotoProgress(); }; strip.append(item); });
  for (let index = patientPhotoFiles.length; index < 5; index++) { const blank = document.createElement('span'); blank.className = 'patient-photo-empty'; blank.textContent = index + 1; strip.append(blank); }
  progress.textContent = patientPhotoFiles.length >= 1 ? 'Puedes guardar ya. Con 3 a 5 fotos el reconocimiento es más fiable.' : 'Empieza con una foto frontal y bien iluminada.';
}
async function preparePhoto(file) {
  if (!file || !file.size) return null;
  try {
    const bitmap = await createImageBitmap(file), maxSide = 1600, scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height)), canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale)); canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    return blob ? new File([blob], `faro-${Date.now()}.jpg`, {type: 'image/jpeg'}) : file;
  } catch { return file; }
}
const preparePatientPhoto = preparePhoto;
async function addPatientPhoto(file) { const prepared = await preparePatientPhoto(file); if (!prepared) return; if (patientPhotoFiles.length >= 5) patientPhotoFiles.shift(); patientPhotoFiles.push(prepared); renderPatientPhotoProgress(); }
for (const input of [document.querySelector('#patient-camera-input'), document.querySelector('#patient-gallery-input')]) input.addEventListener('change', async () => { const files = [...(input.files || [])].slice(0, Math.max(0, 5 - patientPhotoFiles.length)); input.value = ''; try { for (const file of files) await addPatientPhoto(file); } catch (error) { notify(new Error('No se pudo preparar alguna foto. Prueba con otra imagen.')); } });
renderPatientPhotoProgress();

document.querySelector('#care-contact-form').addEventListener('submit', async event => {
  event.preventDefault(); const data = new FormData(event.target);
  const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {street_address: data.get('street_address') || '', postal_code: data.get('postal_code') || '', locality: data.get('locality') || '', province: data.get('province') || '', country: 'España'}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), whatsapp_consent: data.get('whatsapp_consent') === 'on', priority: Number(data.get('priority')), alerts_enabled: true, known_person_id: data.get('known_person_id') || null};
  try { await api('/v1/care-contacts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); event.target.reset(); toast('Contacto añadido.', 'success'); await load(); } catch (error) { notify(error); }
});

document.querySelector('#refresh').onclick = load;
for (const filter of ['#event-filter', '#severity-filter', '#delivery-filter', '#event-order']) document.querySelector(filter).onchange = () => renderMemory();
let searchTimer = null;
document.querySelector('#event-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { memoryPage = 1; renderMemory(); }, 220); });
document.querySelector('#pair').onclick = async () => { try { const invite = await api('/v1/pairing-invites', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({role: document.querySelector('#pair-role').value})}); document.querySelector('#pair-code').textContent = invite.code; toast('Código creado. Caduca en 10 minutos.', 'success'); } catch (error) { notify(error); } };

/* ------------------------------ Voz / chat ------------------------------ */

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

if (SpeechRecognition && talkMic) {
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
} else if (talkMic) {
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

const exerciseRefresh = document.querySelector('#exercise-refresh');
if (exerciseRefresh) exerciseRefresh.addEventListener('click', () => load());

const agendaForm = document.querySelector('#agenda-form');
if (agendaForm) {
  agendaForm.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.target);
    const startAt = data.get('start_at');
    if (!startAt) return notify(new Error('Indica la fecha y la hora.'));
    const payload = {
      title: data.get('title'), category: data.get('category'),
      start_at: new Date(startAt).toISOString(),
      duration_minutes: Number(data.get('duration_minutes') || 30),
      reminder_minutes_before: Number(data.get('reminder_minutes_before') || 15),
      notes: data.get('notes') || null,
      for_patient: data.get('for_patient') === 'on',
      enabled: true,
      recurrence: data.get('recurrence') || 'none',
      recurrence_interval: Number(data.get('recurrence_interval') || 1),
      recurrence_until: data.get('recurrence_until') || null,
      recurrence_weekdays: (data.get('recurrence') === 'weekly')
        ? data.getAll('recurrence_weekdays').map(Number) : null,
    };
    try { await api('/v1/calendar-events', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); event.target.reset(); document.querySelector('#agenda-weekdays').hidden = true; toast('Recordatorio programado.', 'success'); await load(); }
    catch (error) { notify(error); }
  });
}
const agendaRefresh = document.querySelector('#agenda-refresh');
if (agendaRefresh) agendaRefresh.addEventListener('click', () => load());

const agendaRecurrence = document.querySelector('#agenda-recurrence');
const agendaWeekdays = document.querySelector('#agenda-weekdays');
if (agendaRecurrence && agendaWeekdays) {
  const syncWeekdays = () => { agendaWeekdays.hidden = agendaRecurrence.value !== 'weekly'; };
  agendaRecurrence.addEventListener('change', syncWeekdays);
  agendaForm.addEventListener('reset', () => setTimeout(syncWeekdays, 0));
}

(async function boot() {
  try {
    const health = await fetch('/health').then(response => response.json());
    document.querySelector('#connection').textContent = `Conectado · ${health.face_provider === 'RekognitionFaceProvider' ? 'reconocimiento activo' : 'modo de prueba'}`;
  } catch { document.querySelector('#connection').textContent = 'Sin conexión'; }
  try { await load(); } catch (error) { document.querySelector('#connection').textContent = 'Sin conexión'; notify(error); }
  observeReveals();
})();
