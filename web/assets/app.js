const urlToken = new URLSearchParams(location.search).get('token');
if (urlToken) {
  localStorage.setItem('auraToken', urlToken.trim());
  history.replaceState(null, '', location.pathname + location.hash);
}
const token = (localStorage.getItem('auraToken') || '').trim();
const authHeaders = token ? {Authorization: `Bearer ${token}`} : {};
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/assets/sw.js');

// KAN-191: los errores del portal quedan registrados en el log central de Faro.
function reportFaroError(message, contextText, traceText) {
  if (!token) return;
  try {
    const payload = {
      app: 'portal-faro-familia',
      version: 'twa',
      message: String(message || 'Error sin mensaje').slice(0, 2000),
      context: String(contextText || '').slice(0, 4000),
      traceback_text: String(traceText || '').slice(0, 20000),
    };
    fetch('/v1/app-errors', {method: 'POST', keepalive: true, headers: {...authHeaders, 'Content-Type': 'application/json'}, body: JSON.stringify(payload)}).catch(() => {});
  } catch (ignored) {}
}
window.addEventListener('error', event => {
  reportFaroError(
    event.message || 'window.error',
    `${location.pathname} ${event.filename || ''}:${event.lineno || 0}:${event.colno || 0}`,
    event.error && event.error.stack ? event.error.stack : '',
  );
});
window.addEventListener('unhandledrejection', event => {
  const reason = event.reason;
  reportFaroError(
    reason && reason.message ? reason.message : String(reason),
    `unhandledrejection ${location.pathname}`,
    reason && reason.stack ? reason.stack : '',
  );
});

async function api(path, options = {}) {
  const response = await fetch(path, {...options, cache: 'no-store', headers: {...authHeaders, ...(options.headers || {})}});
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
const acknowledged = JSON.parse(localStorage.getItem('faroAck') || '{}');
const currentCounts = {};
const saveAck = () => localStorage.setItem('faroAck', JSON.stringify(acknowledged));
const BADGE_KEYS = {'review-badge': 'reviews', 'care-badge': 'care', 'memory-badge': 'memory', 'exercises-badge': 'exercises', 'agenda-badge': 'agenda'};
function setBadge(selector, key, count) {
  currentCounts[key] = count;
  const badge = document.querySelector(selector);
  if (!badge) return;
  const pending = count - (acknowledged[key] || 0);
  badge.hidden = pending <= 0;
  badge.textContent = pending > 0 ? pending : '';
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

function renderCameraEye() {
  const target = document.querySelector('#device-camera-body');
  if (!target) return;
  target.replaceChildren();
  const state = document.createElement('p'); state.className = 'device-meta'; state.textContent = 'Comprobando la cámara…';
  const recognition = document.createElement('p'); recognition.className = 'device-recognition';
  recognition.textContent = 'Pulsa «Ver ahora» para pedir una foto y reconocer lo que ve.';
  const image = document.createElement('img');
  image.alt = 'Última imagen del ojo de Faro'; image.hidden = true; image.className = 'camera-preview';
  const actions = document.createElement('div'); actions.className = 'device-actions';
  const shoot = document.createElement('button'); shoot.className = 'primary'; shoot.textContent = 'Ver ahora';
  const hint = document.createElement('p'); hint.className = 'meta';
  hint.textContent = 'Captura bajo demanda: la cámara solo se abre cuando la pides, no en bucle.';
  let previewUrl = null;

  const refresh = async () => {
    const status = await api('/v1/camera/status');
    const when = status.last_frame_at ? new Date(status.last_frame_at).toLocaleString() : 'sin imágenes todavía';
    state.textContent = (status.online ? 'En línea' : 'Sin señal') + ' · última imagen: ' + when;
    if (status.description) recognition.textContent = (status.hazard ? '⚠ ' : '') + status.description;
    if (status.has_preview) {
      const response = await fetch('/v1/camera/preview', {headers: authHeaders, cache: 'no-store'});
      if (response.ok) {
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = URL.createObjectURL(await response.blob());
        image.src = previewUrl; image.hidden = false;
      }
    }
    return status;
  };

  shoot.onclick = async () => {
    shoot.disabled = true; shoot.textContent = 'Pidiendo foto…';
    try {
      const before = (await refresh()).last_frame_at;
      await api('/v1/camera/capture', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note: 'portal'})});
      let received = false;
      for (let attempt = 0; attempt < 45 && !received; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        const status = await refresh();
        received = status.last_frame_at && status.last_frame_at !== before;
      }
      toast(received ? 'Imagen y reconocimiento recibidos.' : 'La cámara no respondió. Comprueba que el puente esté encendido.', received ? 'success' : 'error');
    } catch (error) { notify(error); }
    finally { shoot.disabled = false; shoot.textContent = 'Ver ahora'; }
  };

  actions.append(shoot);
  target.append(state, recognition, actions, image, hint);
  refresh().catch(() => { state.textContent = 'No se pudo consultar la cámara.'; });
}

function renderPatrol(patrol, usage) {
  const target = document.querySelector('#device-camera-patrol');
  if (!target || !patrol) return;
  target.replaceChildren();
  const title = document.createElement('p');
  title.className = 'device-subtitle';
  title.textContent = 'Patrulla de la cámara';
  const state = document.createElement('p');
  state.className = 'device-meta';
  const minutes = Math.round((patrol.interval_seconds || 300) / 60);
  state.textContent = (patrol.enabled ? 'Activa' : 'Apagada') + ' · ' + (patrol.sweep_degrees || 180) + '° horizontal · cada ' + minutes + ' min';
  if (patrol.vertical) state.textContent += ' · vertical ' + (patrol.vertical_degrees || 60) + '°';
  if (usage) state.textContent += ' · IA ' + usage.used + '/' + usage.budget + ' hoy';

  const form = document.createElement('form');
  form.className = 'device-patrol-form';
  const field = (labelText, control) => {
    const label = document.createElement('label');
    label.textContent = labelText;
    label.append(control);
    return label;
  };
  const select = document.createElement('select');
  [180, 260, 360].forEach(value => {
    const option = document.createElement('option'); option.value = String(value); option.textContent = value + '°';
    select.append(option);
  });
  select.value = String(patrol.sweep_degrees || 180);
  const verticalSelect = document.createElement('select');
  [30, 60, 90].forEach(value => {
    const option = document.createElement('option'); option.value = String(value); option.textContent = value + '°';
    verticalSelect.append(option);
  });
  verticalSelect.value = String(patrol.vertical_degrees || 60);
  const interval = document.createElement('input'); interval.type = 'number'; interval.min = '1'; interval.max = '60';
  interval.value = String(minutes);
  const budget = document.createElement('input'); budget.type = 'number'; budget.min = '50'; budget.max = '5000';
  budget.value = String(patrol.daily_budget || 500);
  const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.checked = Boolean(patrol.enabled);
  const labelToggle = document.createElement('label'); labelToggle.className = 'check';
  labelToggle.append(toggle, document.createTextNode(' Activar patrulla'));
  const vertical = document.createElement('input'); vertical.type = 'checkbox'; vertical.checked = Boolean(patrol.vertical);
  const labelVertical = document.createElement('label'); labelVertical.className = 'check';
  labelVertical.append(vertical, document.createTextNode(' Búsqueda vertical'));
  const button = document.createElement('button'); button.type = 'submit'; button.className = 'secondary'; button.textContent = 'Guardar patrulla';
  form.append(
    field('Barrido horizontal', select),
    field('Barrido vertical', verticalSelect),
    field('Intervalo (min)', interval),
    field('Presupuesto IA/día', budget),
    labelToggle, labelVertical, button,
  );
  form.onsubmit = async (event) => {
    event.preventDefault();
    button.disabled = true;
    try {
      await api('/v1/camera/patrol', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        enabled: toggle.checked,
        sweep_degrees: parseInt(select.value, 10),
        step_degrees: 45,
        interval_seconds: Math.max(30, parseInt(interval.value, 10) * 60),
        daily_budget: Math.max(50, parseInt(budget.value, 10)),
        tilt: typeof patrol.tilt === 'number' ? patrol.tilt : -0.4,
        zone: patrol.zone || '',
        vertical: vertical.checked,
        vertical_degrees: parseInt(verticalSelect.value, 10),
        vertical_step_degrees: 30,
      })});
      toast('Patrulla guardada.', 'success');
      await load();
    } catch (error) { notify(error); } finally { button.disabled = false; }
  };
  target.append(title, state, form);
}

const HEALTH_TONE = {good: 'Bien', warn: 'Atención', bad: 'Revisar', neutral: 'Sin dato'};

function minutesAgo(value) {
  if (!value) return null;
  const stamp = new Date(value).getTime();
  if (Number.isNaN(stamp)) return null;
  return Math.max(0, Math.round((Date.now() - stamp) / 60000));
}

function timeAgoText(minutes) {
  if (minutes == null) return 'sin datos';
  if (minutes < 1) return 'ahora mismo';
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

function toneForAge(minutes, good = 5, warn = 30) {
  if (minutes == null) return 'neutral';
  if (minutes < good) return 'good';
  if (minutes < warn) return 'warn';
  return 'bad';
}

function latestStamp(items) {
  return items.reduce((best, value) => {
    if (!value) return best;
    const stamp = new Date(value).getTime();
    if (Number.isNaN(stamp)) return best;
    return !best || stamp > best.stamp ? {stamp, value} : best;
  }, null);
}

function healthCard(title, value, detail, tone) {
  const card = document.createElement('article');
  card.className = `health-card health-card--${tone}`;
  const name = document.createElement('span');
  name.className = 'health-card-title';
  name.textContent = title;
  const main = document.createElement('strong');
  main.className = 'health-card-value';
  main.textContent = value;
  const chip = document.createElement('span');
  chip.className = `health-chip health-chip--${tone}`;
  chip.textContent = HEALTH_TONE[tone] || HEALTH_TONE.neutral;
  const text = document.createElement('p');
  text.className = 'health-card-detail';
  text.textContent = detail;
  card.append(name, main, chip, text);
  return card;
}

function renderHealth({inventory, tracking, reviews, contacts, events}) {
  const target = document.querySelector('#device-health');
  if (!target) return;
  target.replaceChildren();
  const sources = ['glasses', 'phone', 'portal'];
  const allEvents = events || [];
  const pending = (reviews || []).filter(review => review.status === 'pending').length;
  const activeContacts = (contacts || []).filter(contact => contact.alerts_enabled && contact.whatsapp_consent);
  const camera = ((inventory && inventory.cameras) || [])[0];

  const ages = sources.map(kind => ({kind, minutes: minutesAgo(deviceSource(inventory || {}, kind).last_event_at)}));
  const knownAges = ages.filter(item => item.minutes != null);
  const newest = knownAges.length ? Math.min(...knownAges.map(item => item.minutes)) : null;

  const batteries = {};
  allEvents.forEach(event => {
    const value = event && event.metadata ? event.metadata.battery_percent : null;
    if (value == null || !event.source) return;
    const stamp = new Date(event.created_at || event.occurred_at || 0).getTime();
    if (!batteries[event.source] || stamp > batteries[event.source].stamp) {
      batteries[event.source] = {value: Number(value), stamp};
    }
  });
  if (tracking && tracking.last_location && tracking.last_location.battery_percent != null) {
    const stamp = new Date(tracking.last_location.recorded_at || tracking.created_at || 0).getTime();
    if (!batteries.phone || stamp >= batteries.phone.stamp) batteries.phone = {value: Number(tracking.last_location.battery_percent), stamp};
  }
  const batteryItems = Object.entries(batteries).filter(([, item]) => Number.isFinite(item.value));
  const batteryDetail = batteryItems.map(([kind, item]) => `${DEVICE_LABELS[kind] || kind} ${item.value}%`).join(' · ');
  const lowestBattery = batteryItems.length ? Math.min(...batteryItems.map(([, item]) => item.value)) : null;

  const cameraAge = camera ? minutesAgo(camera.last_frame_at) : null;
  const heartbeat = [newest, cameraAge].filter(value => value != null);
  const newestHeartbeat = heartbeat.length ? Math.min(...heartbeat) : null;
  const lastEvent = latestStamp(allEvents.map(event => event.created_at || event.occurred_at));
  const lastEventAge = lastEvent ? minutesAgo(lastEvent.value) : null;

  const lastAlert = allEvents
    .filter(event => event && event.metadata && (event.metadata.delivery_status || event.metadata.family_alert_status || event.metadata.alert_status)
      && ['episode', 'help_request', 'hazard'].includes(event.kind))
    .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0];
  const alertStatus = lastAlert
    ? (lastAlert.metadata.family_alert_status || lastAlert.metadata.delivery_status || lastAlert.metadata.alert_status)
    : null;

  const cards = [
    (() => {
      if (!batteryItems.length) return healthCard('Batería', 'Sin dato', 'Ningún dispositivo ha enviado su batería todavía.', 'neutral');
      const tone = lowestBattery < 20 ? 'bad' : lowestBattery < 40 ? 'warn' : 'good';
      return healthCard('Batería', `${lowestBattery}%`, batteryDetail, tone);
    })(),
    healthCard(
      'Última conexión',
      knownAges.length ? timeAgoText(newest) : 'Sin conexión',
      ages.map(item => `${DEVICE_LABELS[item.kind] || item.kind}: ${timeAgoText(item.minutes)}`).join(' · '),
      knownAges.length ? toneForAge(newest, 15, 30) : 'bad',
    ),
    (() => {
      if (!camera) return healthCard('Estado de la cámara', 'Sin cámara', 'No hay ninguna cámara configurada.', 'neutral');
      const tone = camera.online && (cameraAge == null || cameraAge < 10) ? 'good' : cameraAge != null && cameraAge < 30 ? 'warn' : 'bad';
      return healthCard('Estado de la cámara', camera.online ? 'En línea' : 'Sin señal', camera.last_frame_at ? `Última imagen ${timeAgoText(cameraAge)}.` : 'Sin imágenes registradas todavía.', tone);
    })(),
    healthCard(
      'Calidad de conexión',
      newestHeartbeat == null ? 'Sin datos' : newestHeartbeat < 5 ? 'Buena' : newestHeartbeat < 30 ? 'Irregular' : 'Mala',
      newestHeartbeat == null ? 'Aún no hay latidos de dispositivos.' : `Último latido ${timeAgoText(newestHeartbeat)}.`,
      newestHeartbeat == null ? 'neutral' : toneForAge(newestHeartbeat, 5, 30),
    ),
    healthCard(
      'Última sincronización',
      lastEvent ? timeAgoText(lastEventAge) : 'Sin eventos',
      lastEvent ? `${allEvents.length} eventos cargados en el panel.` : 'Todavía no se ha sincronizado ningún evento.',
      lastEvent ? toneForAge(lastEventAge, 5, 30) : 'bad',
    ),
    healthCard(
      'Errores de reconocimiento',
      `${pending} por aclarar`,
      pending ? 'Revisa las capturas pendientes en Personas por aclarar.' : 'No hay identificaciones pendientes.',
      pending === 0 ? 'good' : pending <= 2 ? 'warn' : 'bad',
    ),
    (() => {
      if (!(contacts || []).length) return healthCard('Estado de los avisos', 'Sin destinatarios', 'Añade contactos en la pestaña Cuidados.', 'warn');
      if (alertStatus) {
        const label = {sent: 'Entregado', failed: 'Fallido', test_mode: 'Modo prueba', pending: 'Pendiente'}[alertStatus] || alertStatus;
        const tone = alertStatus === 'sent' ? 'good' : alertStatus === 'failed' ? 'bad' : 'warn';
        return healthCard('Estado de los avisos', label, `Último aviso ${timeAgoText(minutesAgo(lastAlert.created_at))} · ${activeContacts.length} contacto(s) con avisos activos.`, tone);
      }
      return healthCard(
        'Estado de los avisos',
        activeContacts.length ? 'Preparados' : 'Sin avisos',
        activeContacts.length ? `${activeContacts.length} contacto(s) listos para recibir avisos.` : 'Ningún contacto tiene avisos y consentimiento activos.',
        activeContacts.length ? 'good' : 'warn',
      );
    })(),
  ];

  const toneCount = cards.reduce((acc, card) => {
    const tone = ['good', 'warn', 'bad', 'neutral'].find(value => card.classList.contains(`health-card--${value}`)) || 'neutral';
    acc[tone] = (acc[tone] || 0) + 1;
    return acc;
  }, {});
  const overallTone = toneCount.bad ? 'bad' : toneCount.warn ? 'warn' : 'good';
  const overall = document.createElement('div');
  overall.className = `health-overall health-overall--${overallTone}`;
  const overallTitle = document.createElement('strong');
  overallTitle.textContent = overallTone === 'good'
    ? 'Faro está funcionando correctamente.'
    : overallTone === 'warn'
      ? `Faro funciona con ${toneCount.warn} indicador(es) a vigilar.`
      : `Revisa ${toneCount.bad} indicador(es) de Faro.`;
  const overallDetail = document.createElement('p');
  overallDetail.textContent = `Comprobado a las ${new Date().toLocaleTimeString()}. Los semáforos usan la última actividad real de cada dispositivo.`;
  overall.append(overallTitle, overallDetail);
  const grid = document.createElement('div');
  grid.className = 'health-grid';
  grid.append(...cards);
  target.append(overall, grid);
}

async function load() {
  const labels = ['personas', 'personas por aclarar', 'cuidados', 'paciente', 'memoria', 'ubicación', 'ejercicios', 'resumen de ejercicios', 'agenda', 'estadísticas', 'dispositivos', 'transmisiones', 'panel longitudinal', 'patrulla', 'uso de cámara', 'rastreadores'];
  const requests = [
    api('/v1/people'), api('/v1/reviews'), api('/v1/care-contacts'), api('/v1/patient-profile'),
    api('/v1/events?limit=500'), api('/v1/location-sessions/active'),
    api('/v1/cognitive-exercises'), api('/v1/cognitive-exercises/summary'), api('/v1/calendar-events'),
    api('/v1/stats/evolution?days=30'),
    api('/v1/devices'),
    api('/v1/live-views'),
    api('/v1/stats/longitudinal?days=30'),
    api('/v1/camera/patrol'),
    api('/v1/camera/usage'),
    api('/v1/trackers'),
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
  const stats = pick(9);
  const devices = pick(10);
  const liveViews = pick(11) || [];
  const longitudinal = pick(12);
  const patrol = pick(13) || {};
  const cameraUsage = pick(14);
  const trackers = pick(15) || [];

  const pending = reviews.filter(review => review.status === 'pending');
  document.querySelector('#people-count').textContent = people.length;
  document.querySelector('#review-count').textContent = pending.length;
  document.querySelector('#contact-count').textContent = contacts.length;
  document.querySelector('#device-count').textContent = devices ? devices.devices.filter(device => !device.revoked).length : 0;
  setBadge('#review-badge', 'reviews', pending.length);
  setBadge('#care-badge', 'care', contacts.filter(contact => !contact.alerts_enabled).length);
  setBadge('#memory-badge', 'memory', events.filter(event => event.severity === 'urgent' || event.severity === 'attention').length);
  setBadge('#exercises-badge', 'exercises', exercises.filter(exercise => exercise.status !== 'completed').length);
  setBadge('#agenda-badge', 'agenda', agenda.filter(event => isSameDay(new Date(event.start_at), new Date())).length);
  document.querySelector('#contact-status').textContent = contacts.length
    ? `Avisos preparados para ${contacts.map(contact => contact.display_name).join(' y ')}.`
    : 'Todavía no hay destinatarios configurados.';
  document.querySelector('#patient-status').textContent = patient
    ? `Ficha guardada para ${patient.preferred_name}.`
    : 'Ficha del paciente pendiente.';

  if (patient) { fillPatient(patient); await renderPatientPhoto(patient); }
  renderCareContacts(contacts, people);
  renderHealth({inventory: devices, tracking, reviews, contacts, events});
  renderDevices(devices, liveViews, trackers);
  renderPatrol(patrol, cameraUsage);
  renderCameraEye();
  populateKnownPersonOptions(people);
  renderPeople(people);
  await renderReviews(pending, people);
  renderMemory(events);
  renderTracking(tracking);
  if (exerciseSummary) renderExercises(exercises, exerciseSummary);
  renderAgenda(agenda);
  renderStats(stats);
  renderLongitudinal(longitudinal);

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
let memoryDay = '';

function hourMatches(event, from, to) {
  if (from === '' && to === '') return true;
  const hour = new Date(event.occurred_at).getHours();
  if (from !== '' && hour < Number(from)) return false;
  if (to !== '' && hour > Number(to)) return false;
  return true;
}

async function refreshMemoryDay() {
  const params = new URLSearchParams({limit: '500'});
  if (memoryDay) {
    params.set('since', new Date(`${memoryDay}T00:00:00`).toISOString());
    params.set('until', new Date(`${memoryDay}T23:59:59.999`).toISOString());
  }
  try { loadedEvents = await api(`/v1/events?${params.toString()}`); }
  catch (error) { notify(error); return; }
  memoryPage = 1;
  renderMemory();
}

function shiftMemoryDay(delta) {
  const base = memoryDay ? new Date(`${memoryDay}T12:00:00`) : new Date();
  base.setDate(base.getDate() + delta);
  const yyyy = base.getFullYear();
  const mm = String(base.getMonth() + 1).padStart(2, '0');
  const dd = String(base.getDate()).padStart(2, '0');
  memoryDay = `${yyyy}-${mm}-${dd}`;
  document.querySelector('#event-date').value = memoryDay;
  refreshMemoryDay();
}

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
  const meta = event.metadata || {};
  if (meta.has_photo && meta.alert_id) {
    const foto = document.createElement('img');
    foto.className = 'event-photo';
    foto.loading = 'lazy';
    foto.alt = 'Foto capturada en el momento';
    foto.hidden = true;
    foto.onclick = () => foto.classList.toggle('expanded');
    fetch(`/v1/emergency-alerts/${meta.alert_id}/image`, {headers: authHeaders})
      .then(response => (response.ok ? response.blob() : null))
      .then(blob => { if (blob) { foto.src = URL.createObjectURL(blob); foto.hidden = false; } })
      .catch(() => {});
    article.append(foto);
  }
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
  const hourFrom = document.querySelector('#event-hour-from') ? document.querySelector('#event-hour-from').value : '';
  const hourTo = document.querySelector('#event-hour-to') ? document.querySelector('#event-hour-to').value : '';

  const filtered = loadedEvents
    .filter(event => eventMatches(event, kind, severity, delivery, query))
    .filter(event => hourMatches(event, hourFrom, hourTo))
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
    const details = [];
    details.push(`Categoría: ${({recall: 'recuerdo', orientation: 'orientación', naming: 'nombrar', movement: 'movimiento/deporte'}[exercise.category] || exercise.category)}`);
    if (exercise.response_seconds != null) details.push(`respondió en ${exercise.response_seconds} s`);
    if (exercise.abandoned) details.push('sin respuesta (posible frustración)');
    const meta = document.createElement('small');
    meta.className = 'exercise-meta';
    meta.textContent = details.join(' · ');
    article.append(meta);
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

function renderLongitudinal(panel) {
  const target = document.querySelector('#longitudinal');
  if (!target) return;
  target.replaceChildren();
  if (!panel) { target.append(empty('Sin datos del panel longitudinal todavía.')); return; }
  const labelMap = {
    help_requests: 'Peticiones de ayuda', hazards: 'Avisos preventivos', impacts: 'Caídas o golpes',
    disorientation: 'Desorientación', location_incidents: 'Ubicación', escalations: 'Escalados a la red', urgent: 'Urgentes',
  };
  const grid = document.createElement('div'); grid.className = 'device-list';
  Object.keys(labelMap).forEach(key => {
    const card = document.createElement('article'); card.className = 'device-card';
    const title = document.createElement('strong'); title.textContent = labelMap[key];
    const value = document.createElement('p');
    const delta = (panel.delta_percent || {})[key] || 0;
    const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '=';
    value.textContent = `${(panel.totals || {})[key] || 0} (antes: ${(panel.previous_totals || {})[key] || 0} · ${arrow} ${Math.abs(delta)}%)`;
    card.append(title, value); grid.append(card);
  });
  target.append(grid);
  const hours = document.createElement('p'); hours.className = 'status-line';
  const withHours = (panel.by_hour || []).map((count, hour) => `${String(hour).padStart(2, '0')}h:${count}`).filter((_, hour) => (panel.by_hour || [])[hour] > 0);
  hours.textContent = 'Distribución por hora: ' + (withHours.length ? withHours.join('  ') : 'sin eventos en el periodo');
  target.append(hours);
  const days = document.createElement('p'); days.className = 'status-line';
  const activeDays = (panel.by_day || []).filter(day => Object.keys(labelMap).some(key => (day[key] || 0) > 0));
  days.textContent = activeDays.length
    ? 'Días con actividad: ' + activeDays.slice(-10).map(day => `${day.date}→${Object.keys(labelMap).reduce((sum, key) => sum + (day[key] || 0), 0)}`).join(' · ')
    : 'Sin días con actividad en el periodo.';
  target.append(days);
  const note = document.createElement('p'); note.className = 'device-card'; note.textContent = panel.notes || '';
  target.append(note);
}

function renderStats(stats) {
  const summary = document.querySelector('#stats-summary');
  const chart = document.querySelector('#stats-chart');
  const list = document.querySelector('#stats-list');
  const donut = document.querySelector('#stats-donut');
  if (!stats) { if (summary) summary.textContent = 'Sin datos de estadísticas todavía.'; return; }
  const s = stats.summary;
  const trend = {
    mejora: {label: 'mejorando', arrow: '↑', color: 'var(--family)'},
    deterioro: {label: 'en deterioro', arrow: '↓', color: 'var(--danger)'},
    estable: {label: 'estable', arrow: '→', color: 'var(--muted)'},
    'sin-datos': {label: 'sin datos suficientes', arrow: '·', color: 'var(--muted)'},
  }[s.trend] || {label: s.trend, arrow: '', color: 'var(--muted)'};
  if (summary) {
    const extra = [
      s.movement ? `${s.movement} de movimiento/deporte` : null,
      s.avg_response_seconds != null ? `tiempo medio de respuesta ${s.avg_response_seconds} s` : null,
      s.abandoned ? `${s.abandoned} sin respuesta` : null,
    ].filter(Boolean).join(' · ');
    summary.textContent = `${s.exercises_completed} ejercicios completados · ${s.accuracy}% de aciertos · ${s.alerts} avisos en 30 días · Tendencia: ${trend.arrow} ${trend.label}` + (extra ? ` · ${extra}` : '') + '.';
  }
  if (donut) {
    const size = 150, stroke = 16, r = (size - stroke) / 2, circumference = 2 * Math.PI * r;
    const filled = Math.max(0, Math.min(100, s.accuracy)) / 100 * circumference;
    const color = s.accuracy >= 70 ? 'var(--family)' : s.accuracy >= 40 ? '#e0a63a' : 'var(--danger)';
    donut.innerHTML =
      `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${Math.round(s.accuracy)}% de aciertos">` +
      `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--line)" stroke-width="${stroke}"/>` +
      `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" ` +
      `stroke-dasharray="${filled} ${circumference - filled}" transform="rotate(-90 ${size / 2} ${size / 2})"/>` +
      `<text x="50%" y="47%" text-anchor="middle" font-size="30" font-weight="700" fill="var(--brand)">${Math.round(s.accuracy)}%</text>` +
      `<text x="50%" y="63%" text-anchor="middle" font-size="12" fill="var(--muted)">aciertos</text></svg>`;
  }
  if (chart) {
    chart.replaceChildren();
    const withData = stats.days.some(day => day.exercises);
    if (!withData) {
      chart.append(empty('Todavía no hay ejercicios completados en los últimos 30 días.'));
    } else {
      const W = 640, H = 220, padL = 36, padR = 12, padT = 16, padB = 28;
      const n = stats.days.length;
      const x = index => padL + (W - padL - padR) * (n <= 1 ? 0.5 : index / (n - 1));
      const y = value => padT + (H - padT - padB) * (1 - Math.max(0, Math.min(100, value)) / 100);
      const points = stats.days.map((day, index) => ({index, acc: day.exercises ? day.accuracy : null}));
      const filled = points.filter(point => point.acc !== null);
      const line = filled.map((point, k) => `${k === 0 ? 'M' : 'L'} ${x(point.index).toFixed(1)} ${y(point.acc).toFixed(1)}`).join(' ');
      const area = filled.length
        ? `${line} L ${x(filled[filled.length - 1].index).toFixed(1)} ${y(0).toFixed(1)} L ${x(filled[0].index).toFixed(1)} ${y(0).toFixed(1)} Z`
        : '';
      const dots = filled.map(point => `<circle cx="${x(point.index).toFixed(1)}" cy="${y(point.acc).toFixed(1)}" r="4" fill="var(--brand)"/>`).join('');
      const alerts = stats.days.map((day, index) => day.alerts
        ? `<rect x="${(x(index) - 3).toFixed(1)}" y="${H - padB - 14}" width="6" height="14" rx="2" fill="${day.urgent ? 'var(--danger)' : '#e0a63a'}" opacity="0.85"/>`
        : '').join('');
      const grid = [0, 50, 100].map(value =>
        `<line x1="${padL}" y1="${y(value).toFixed(1)}" x2="${W - padR}" y2="${y(value).toFixed(1)}" stroke="var(--line)"/>` +
        `<text x="4" y="${(y(value) + 4).toFixed(1)}" font-size="10" fill="var(--muted)">${value}%</text>`).join('');
      const step = Math.max(1, Math.floor(n / 5));
      const xlabels = stats.days.map((day, index) => (index % step === 0 || index === n - 1)
        ? `<text x="${x(index).toFixed(1)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="var(--muted)">${day.date.slice(8, 10)}/${day.date.slice(5, 7)}</text>`
        : '').join('');
      chart.innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Evolución cronológica de aciertos y avisos">` +
        grid +
        (area ? `<path d="${area}" fill="var(--calm)" opacity="0.28"/>` : '') +
        (line ? `<path d="${line}" fill="none" stroke="var(--brand)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>` : '') +
        dots + alerts + xlabels +
        `<text x="${padL}" y="11" font-size="10" fill="var(--muted)">azul: % aciertos · ámbar/rojo: avisos (abajo)</text>` +
        `</svg>`;
    }
  }
  if (list) {
    list.replaceChildren();
    const rows = stats.days.filter(day => day.exercises || day.alerts).reverse();
    for (const day of rows) {
      const row = document.createElement('div');
      row.className = 'stat-row';
      const when = new Date(`${day.date}T12:00:00`).toLocaleDateString('es-ES', {weekday: 'short', day: 'numeric', month: 'short'});
      row.textContent = `${when} · ${day.exercises} ejercicios, ${day.exercises_correct} correctos (${day.accuracy}%) · ${day.alerts} avisos`;
      list.append(row);
    }
    if (!rows.length) list.append(empty('Todavía no hay actividad registrada en los últimos 30 días.'));
  }
  const cats = document.querySelector('#stats-categories');
  if (cats) {
    cats.replaceChildren();
    const labels = {recall: 'Recuerdo', orientation: 'Orientación', naming: 'Nombrar', movement: 'Movimiento/deporte'};
    if (!stats.categories || !stats.categories.length) {
      cats.append(empty('Sin datos por categoría todavía.'));
    } else {
      for (const item of stats.categories) {
        const row = document.createElement('div');
        row.className = 'stat-cat';
        const name = document.createElement('span');
        name.className = 'stat-cat-name';
        name.textContent = labels[item.category] || item.category;
        const bar = document.createElement('span');
        bar.className = 'stat-cat-bar';
        const fill = document.createElement('span');
        fill.className = 'stat-cat-fill';
        fill.style.width = `${Math.max(0, Math.min(100, item.accuracy))}%`;
        bar.append(fill);
        const value = document.createElement('span');
        value.className = 'stat-cat-value';
        value.textContent = `${item.exercises} · ${item.accuracy}%`;
        row.append(name, bar, value);
        cats.append(row);
      }
    }
  }
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
  form.elements.home_safe_points.value = (patient.safe_points || []).map(point => point.street_address || point.locality || '').filter(Boolean).join('\n');
  form.elements.home_address_verified.value = patient.address_verified_at ? new Date(patient.address_verified_at).toLocaleString('es-ES') : 'Pendiente de verificar';
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
    const postalCode = document.createElement('input'); postalCode.name = 'postal_code'; postalCode.maxLength = 20; postalCode.value = contact.address?.postal_code || '';
    const locality = document.createElement('input'); locality.name = 'locality'; locality.maxLength = 100; locality.value = contact.address?.locality || '';
    const province = document.createElement('input'); province.name = 'province'; province.maxLength = 100; province.value = contact.address?.province || '';
    const availability = document.createElement('textarea'); availability.name = 'availability_notes'; availability.maxLength = 500; availability.value = contact.availability_notes || '';
    const channel = document.createElement('select'); channel.name = 'preferred_channel'; channel.append(new Option('WhatsApp', 'whatsapp'), new Option('SMS', 'sms'), new Option('Llamada', 'call')); channel.value = contact.preferred_channel || 'whatsapp';
    const shareScope = document.createElement('select'); shareScope.name = 'emergency_share_scope'; shareScope.append(new Option('Nombre, domicilio, teléfono y ubicación del paciente', 'full'), new Option('Nombre y ubicación del paciente', 'location'), new Option('Solo nombre y relación', 'basic')); shareScope.value = contact.emergency_share_scope || 'full';
    const emergencyNotes = document.createElement('textarea'); emergencyNotes.name = 'emergency_notes'; emergencyNotes.maxLength = 500; emergencyNotes.value = contact.emergency_notes || '';
    const roleSelect = document.createElement('select'); roleSelect.name = 'role'; roleSelect.append(new Option('Familiar', 'family'), new Option('Cuidador', 'caregiver')); roleSelect.value = contact.role;
    const prioritySelect = document.createElement('select'); prioritySelect.name = 'priority'; for (let value = 1; value <= 5; value += 1) prioritySelect.append(new Option(String(value), String(value))); prioritySelect.value = String(contact.priority);
    const personSelect = document.createElement('select'); personSelect.name = 'known_person_id'; personSelect.append(new Option('Sin vincular', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id))); personSelect.value = contact.known_person_id || '';
    const save = document.createElement('button'); save.className = 'primary'; save.textContent = 'Guardar cambios';
    form.append(field('Nombre', displayName), field('Teléfono', phoneInput), field('Teléfono alternativo', alternatePhone), field('Dirección', streetAddress), field('Código postal', postalCode), field('Localidad', locality), field('Provincia', province), field('Canal preferido', channel), field('Datos que pueden facilitarse en una emergencia', shareScope), field('Notas para emergencias o coordinación', emergencyNotes), field('Disponibilidad', availability), field('Rol', roleSelect), field('Prioridad', prioritySelect), field('Persona conocida vinculada', personSelect), save);
    edit.onclick = () => { form.hidden = !form.hidden; edit.textContent = form.hidden ? 'Editar ficha' : 'Cerrar ficha'; };
    pause.onclick = async () => { try { await api(`/v1/care-contacts/${contact.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({alerts_enabled: !contact.alerts_enabled})}); await load(); } catch (error) { notify(error); } };
    form.onsubmit = async event => { event.preventDefault(); const data = new FormData(form); const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {...(contact.address || {}), street_address: data.get('street_address') || '', postal_code: data.get('postal_code') || '', locality: data.get('locality') || '', province: data.get('province') || ''}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), priority: Number(data.get('priority')), known_person_id: data.get('known_person_id') || null, preferred_channel: data.get('preferred_channel') || contact.preferred_channel || 'whatsapp', emergency_share_scope: data.get('emergency_share_scope') || contact.emergency_share_scope || 'full', emergency_notes: data.get('emergency_notes') || ''}; try { await api(`/v1/care-contacts/${contact.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); toast('Contacto actualizado.', 'success'); await load(); } catch (error) { notify(error); } };
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
      : (person.profile_photo_available
        ? 'Fotos guardadas. No se detectó una cara clara; añade otra para activar el reconocimiento'
        : 'Añade al menos una foto para reconocerla');
    const editToggle = node.querySelector('.edit-toggle'), editForm = node.querySelector('.person-edit'), gallery = node.querySelector('.face-sample-gallery');
    editForm.elements.display_name.value = person.display_name;
    editForm.elements.relationship.value = person.relationship;
    editForm.elements.consent_granted.checked = person.consent_granted;
    editToggle.addEventListener('click', () => {
      editForm.hidden = !editForm.hidden;
      gallery.hidden = editForm.hidden;
      editToggle.textContent = editForm.hidden ? 'Ver y editar ficha' : 'Cerrar ficha';
      if (!gallery.hidden && !gallery.childElementCount && (person.enrollment_complete || person.profile_photo_available)) {
        const count = Math.min(Math.max(person.enrollment_samples || (person.profile_photo_available ? 5 : 1), 1), 5);
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
      try {
        const updated = await api(`/v1/people/${person.id}/face-samples`, {method: 'POST', body: data});
        toast(updated && updated.enrollment_complete
          ? 'Reconocimiento preparado.'
          : 'Fotos guardadas. No se detectó una cara clara; añade otra para activar el reconocimiento.', 'success');
        await load();
      }
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

const DEVICE_LABELS = {glasses: 'Gafas', phone: 'Móvil', portal: 'Portal', backend: 'Servicio'};
const DEVICE_ROLE_LABELS = {family: 'Familiar', caregiver: 'Cuidador', clinician: 'Profesional sanitario'};
const DEVICE_VIEW_LABELS = {pending: 'Pendiente', active: 'Activa', completed: 'Terminada', cancelled: 'Cancelada', denied: 'Denegada'};

function deviceSection(title, hint) {
  const section = document.createElement('section');
  section.className = 'device-group';
  const heading = document.createElement('div');
  heading.className = 'device-group-heading';
  const headingTitle = document.createElement('h3');
  headingTitle.className = 'section-title';
  headingTitle.textContent = title;
  heading.append(headingTitle);
  if (hint) {
    const text = document.createElement('p');
    text.className = 'device-group-hint';
    text.textContent = hint;
    heading.append(text);
  }
  const body = document.createElement('div');
  body.className = 'device-grid';
  section.append(heading, body);
  return {section, body};
}

function deviceSource(inventory, kind) {
  return (inventory.sources || []).find(source => source.source === kind)
    || {source: kind, events_24h: 0, last_event_at: null};
}

function deviceSettings(inventory, kind) {
  return (inventory.settings || []).find(item => item.source === kind)
    || {source: kind, microphone: false, camera: false, location: false, tracking: false};
}

function deviceOnline(source) {
  return Boolean(source.last_event_at && Date.now() - new Date(source.last_event_at).getTime() < 15 * 60 * 1000);
}

function statusChip(online, onlineText = 'En línea', offlineText = 'Sin actividad reciente') {
  const chip = document.createElement('span');
  chip.className = 'device-status ' + (online ? 'is-online' : 'is-offline');
  chip.textContent = online ? onlineText : offlineText;
  return chip;
}

function testConnectionButton(kind) {
  const output = document.createElement('output');
  output.className = 'device-test';
  output.setAttribute('aria-live', 'polite');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary';
  button.textContent = 'Probar conexión';
  button.onclick = async () => {
    button.disabled = true;
    output.textContent = 'Probando…';
    try {
      const result = await api('/v1/devices/connection-test', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({device: kind})});
      output.textContent = (result.online ? 'Conexión correcta' : 'Sin conexión') + ` · ${result.detail} · ${result.latency_ms} ms`;
      toast(result.online ? `${result.label}: conexión correcta.` : `${result.label}: ${result.detail}.`, result.online ? 'success' : 'error');
    } catch (error) {
      output.textContent = 'No se pudo probar la conexión.';
      notify(error);
    } finally {
      button.disabled = false;
    }
  };
  return {button, output};
}

function permissionsForm(kind, settings) {
  const form = document.createElement('form');
  form.className = 'device-permissions';
  const legend = document.createElement('p');
  legend.className = 'device-subtitle';
  legend.textContent = 'Permisos del dispositivo';
  const grid = document.createElement('div');
  grid.className = 'permission-grid';
  const inputs = {};
  [['microphone', 'Micrófono'], ['camera', 'Cámara'], ['location', 'Ubicación'], ['tracking', 'Seguimiento']].forEach(([name, label]) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'check permission-item';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.name = name;
    input.checked = Boolean(settings[name]);
    const span = document.createElement('span');
    span.textContent = label;
    wrapper.append(input, span);
    grid.append(wrapper);
    inputs[name] = input;
  });
  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'secondary';
  save.textContent = 'Guardar permisos';
  form.append(legend, grid, save);
  form.onsubmit = async event => {
    event.preventDefault();
    save.disabled = true;
    try {
      await api(`/v1/devices/sources/${kind}/settings`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        microphone: inputs.microphone.checked,
        camera: inputs.camera.checked,
        location: inputs.location.checked,
        tracking: inputs.tracking.checked,
      })});
      toast('Permisos guardados.', 'success');
      await load();
    } catch (error) { notify(error); } finally { save.disabled = false; }
  };
  return form;
}

let activeLiveView = null;

function stopLiveView() {
  if (activeLiveView) {
    clearInterval(activeLiveView.timer);
    if (activeLiveView.url) URL.revokeObjectURL(activeLiveView.url);
    activeLiveView = null;
  }
  const host = document.querySelector('#live-view');
  if (host) { host.replaceChildren(); host.hidden = true; }
}

function renderLiveView(view) {
  stopLiveView();
  const host = document.querySelector('#live-view');
  if (!host) return;
  host.hidden = false;
  const panel = document.createElement('article');
  panel.className = 'device-card device-card--live-viewer';
  const head = document.createElement('div');
  head.className = 'device-card-head';
  const title = document.createElement('strong');
  title.textContent = `Directo de ${DEVICE_LABELS[view.source] || view.source}`;
  const state = statusChip(true, 'Conectando…', 'Conectando…');
  head.append(title, state);
  const image = document.createElement('img');
  image.className = 'live-view-image';
  image.alt = `Transmisión en directo de ${DEVICE_LABELS[view.source] || view.source}`;
  image.hidden = true;
  const meta = document.createElement('p');
  meta.className = 'device-meta';
  meta.textContent = 'Esperando el primer fotograma del dispositivo…';
  const actions = document.createElement('div');
  actions.className = 'device-actions';
  const stop = document.createElement('button');
  stop.type = 'button';
  stop.className = 'secondary';
  stop.textContent = 'Detener transmisión';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'secondary';
  close.textContent = 'Cerrar visor';
  actions.append(stop, close);
  panel.append(head, image, meta, actions);
  host.append(panel);

  const session = {viewId: view.id, source: view.source, timer: null, url: null, frames: 0, stopped: false};
  activeLiveView = session;

  const finish = async (label) => {
    if (session.stopped) return;
    session.stopped = true;
    clearInterval(session.timer);
    state.replaceWith(statusChip(false, label, label));
    meta.textContent = 'Transmisión finalizada.';
    stop.disabled = true;
    if (session.url) { URL.revokeObjectURL(session.url); session.url = null; }
  };

  const tick = async () => {
    if (session.stopped) return;
    try {
      const status = await api(`/v1/live-views/${session.viewId}`);
      if (status.status === 'completed' || status.status === 'cancelled' || status.status === 'denied') {
        await finish(DEVICE_VIEW_LABELS[status.status] || status.status);
        return;
      }
      if (status.frame_count > session.frames) {
        const response = await fetch(`/v1/live-views/${session.viewId}/frame`, {headers: authHeaders, cache: 'no-store'});
        if (response.ok) {
          const blob = await response.blob();
          if (session.url) URL.revokeObjectURL(session.url);
          session.url = URL.createObjectURL(blob);
          image.src = session.url;
          image.hidden = false;
          session.frames = status.frame_count;
          meta.textContent = `Recibidos ${status.frame_count} fotograma(s) · último ${new Date(status.last_frame_at).toLocaleTimeString()}`;
          state.replaceWith(statusChip(true, 'En directo', 'En directo'));
        }
      }
    } catch (error) {
      if (error && error.message && /404|No frame/i.test(error.message)) return;
      await finish('Sin conexión');
    }
  };

  stop.onclick = async () => {
    stop.disabled = true;
    try {
      await api(`/v1/live-views/${session.viewId}/status`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: 'completed'})});
    } catch (error) { notify(error); }
    await finish('Finalizada');
    await load();
  };
  close.onclick = () => { finish('Finalizada'); load(); };

  tick();
  session.timer = setInterval(tick, 1200);
}

function liveViewButton(kind, inventory) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'primary';
  button.textContent = 'Ver en directo';
  button.setAttribute('aria-label', 'Solicitar transmisión en directo');
  button.disabled = !inventory.video_consent;
  button.title = inventory.video_consent ? 'Solicitar transmisión en directo' : 'Activa el consentimiento de vídeo primero';
  button.onclick = async () => {
    button.disabled = true;
    try {
      const view = await api('/v1/live-views', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source: kind, reason: 'Petición desde Faro Familia'})});
      toast('Solicitud enviada. Esperando al dispositivo…', 'success');
      renderLiveView(view);
      load();
    } catch (error) { notify(error); } finally { button.disabled = false; }
  };
  return button;
}

function sourceCard(kind, inventory, options = {}) {
  const source = deviceSource(inventory, kind);
  const card = document.createElement('article');
  card.className = 'device-card device-card--' + kind;
  const head = document.createElement('div');
  head.className = 'device-card-head';
  const title = document.createElement('strong');
  title.textContent = DEVICE_LABELS[kind] || kind;
  head.append(title, statusChip(deviceOnline(source), options.onlineText, options.offlineText));
  const last = document.createElement('p');
  last.className = 'device-meta';
  last.textContent = source.last_event_at
    ? `Última actividad: ${new Date(source.last_event_at).toLocaleString()}`
    : 'Sin actividad registrada';
  const count = document.createElement('p');
  count.className = 'device-meta';
  count.textContent = `${source.events_24h} evento(s) en 24 h`;
  card.append(head, last, count);
  if (options.permissions) card.append(permissionsForm(kind, deviceSettings(inventory, kind)));
  const actions = document.createElement('div');
  actions.className = 'device-actions';
  const {button, output} = testConnectionButton(kind);
  actions.append(button);
  if (kind === 'glasses' || kind === 'phone') actions.append(liveViewButton(kind, inventory));
  card.append(actions, output);
  return card;
}

function cameraCard(inventory) {
  const camera = (inventory.cameras || [])[0];
  const card = document.createElement('article');
  card.className = 'device-card device-card--camera';
  const head = document.createElement('div');
  head.className = 'device-card-head';
  const title = document.createElement('strong');
  title.textContent = 'Ojo de Faro';
  head.append(title, statusChip(Boolean(camera && camera.online), 'En línea', 'Sin señal'));
  const meta = document.createElement('p');
  meta.className = 'device-meta';
  meta.textContent = `${camera && camera.name ? camera.name : 'Cámara Tapo'} · ${camera && camera.location ? camera.location : 'Casa'}`
    + (camera && camera.last_frame_at ? ` · última imagen: ${new Date(camera.last_frame_at).toLocaleString()}` : ' · sin imágenes todavía');
  const actions = document.createElement('div');
  actions.className = 'device-actions';
  const {button, output} = testConnectionButton('camera');
  actions.append(button);
  const body = document.createElement('div');
  body.id = 'device-camera-body';
  body.className = 'device-camera-body';
  const patrol = document.createElement('div');
  patrol.id = 'device-camera-patrol';
  patrol.className = 'device-camera-patrol';
  card.append(head, meta, actions, output, body, patrol);
  return card;
}

function renderDevices(inventory, liveViews, trackers) {
  const target = document.querySelector('#devices');
  if (!target) return;
  target.replaceChildren();
  if (!inventory) {
    target.append(empty('No se pudo cargar el inventario de dispositivos.'));
    return;
  }

  const cameraOnline = Boolean((inventory.cameras || [])[0] && (inventory.cameras || [])[0].online);
  const onlineCount = ['glasses', 'phone', 'portal'].filter(kind => deviceOnline(deviceSource(inventory, kind))).length + (cameraOnline ? 1 : 0);
  const summary = document.querySelector('#device-summary');
  if (summary) {
    summary.textContent = `${onlineCount} de 4 dispositivos en línea · actualizado a las ${new Date().toLocaleTimeString()}`;
  }

  const hardware = deviceSection('Dispositivos', 'Estado, permisos y acciones de cada dispositivo real de la casa.');
  hardware.body.append(sourceCard('glasses', inventory, {permissions: true}));
  hardware.body.append(sourceCard('phone', inventory, {permissions: true}));
  hardware.body.append(cameraCard(inventory));
  hardware.body.append(sourceCard('portal', inventory, {permissions: true}));
  hardware.body.append(sourceCard('backend', inventory, {onlineText: 'Servicio activo', offlineText: 'Sin actividad'}));
  target.append(hardware.section);

  const access = deviceSection('Accesos autorizados', 'Cada código de emparejamiento crea una credencial con un rol. Revócala cuando deje de usarse.');
  (inventory.devices || []).forEach(device => {
    const card = document.createElement('article');
    card.className = 'device-card device-card--access';
    const head = document.createElement('div');
    head.className = 'device-card-head';
    const title = document.createElement('strong');
    title.textContent = DEVICE_ROLE_LABELS[device.role] || device.role;
    head.append(title, statusChip(!device.revoked, 'Activo', 'Revocado'));
    const meta = document.createElement('p');
    meta.className = 'device-meta';
    meta.textContent = `Emparejado el ${new Date(device.created_at).toLocaleDateString()}`;
    card.append(head, meta);
    if (!device.revoked) {
      const revoke = document.createElement('button');
      revoke.type = 'button';
      revoke.className = 'text-danger';
      revoke.textContent = 'Revocar acceso';
      revoke.onclick = async () => {
        if (!(await confirmAction(`¿Revocar el acceso de ${DEVICE_ROLE_LABELS[device.role] || device.role}? Dejará de poder entrar con esa credencial.`, 'Revocar acceso'))) return;
        revoke.disabled = true;
        try {
          await api(`/v1/devices/${device.id}/revoke`, {method: 'POST'});
          toast('Acceso revocado.', 'success');
          await load();
        } catch (error) { notify(error); } finally { revoke.disabled = false; }
      };
      card.append(revoke);
    }
    access.body.append(card);
  });
  if (!access.body.children.length) access.body.append(empty('Todavía no hay accesos emparejados. Usa «Emparejar dispositivo».'));
  target.append(access.section);

  const privacy = deviceSection('Privacidad y consentimiento', 'El vídeo en directo solo se puede solicitar con consentimiento activo y queda auditado.');
  const consent = document.createElement('article');
  consent.className = 'device-card device-card--consent';
  const consentHead = document.createElement('div');
  consentHead.className = 'device-card-head';
  const consentTitle = document.createElement('strong');
  consentTitle.textContent = 'Vídeo en directo';
  consentHead.append(consentTitle, statusChip(Boolean(inventory.video_consent), 'Consentimiento activo', 'Sin consentimiento'));
  const consentText = document.createElement('p');
  consentText.className = 'device-meta';
  consentText.textContent = inventory.video_consent
    ? 'Puedes solicitar transmisiones de las gafas o del móvil.'
    : 'Actívalo para poder solicitar transmisiones de las gafas o del móvil.';
  const consentButton = document.createElement('button');
  consentButton.type = 'button';
  consentButton.className = inventory.video_consent ? 'secondary' : 'primary';
  consentButton.textContent = inventory.video_consent ? 'Retirar consentimiento' : 'Activar consentimiento';
  consentButton.onclick = async () => {
    consentButton.disabled = true;
    try {
      await api('/v1/devices/video-consent', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({granted: !inventory.video_consent, notes: ''})});
      toast('Consentimiento actualizado.', 'success');
      await load();
    } catch (error) { notify(error); } finally { consentButton.disabled = false; }
  };
  consent.append(consentHead, consentText, consentButton);
  privacy.body.append(consent);
  target.append(privacy.section);

  const transmissions = deviceSection('Transmisiones', 'Solicitudes de vídeo en directo registradas y auditadas.');
  (liveViews || []).forEach(view => {
    const card = document.createElement('article');
    card.className = 'device-card device-card--live';
    const head = document.createElement('div');
    head.className = 'device-card-head';
    const title = document.createElement('strong');
    title.textContent = DEVICE_LABELS[view.source] || view.source;
    head.append(title, statusChip(view.status === 'active' || view.status === 'pending', DEVICE_VIEW_LABELS[view.status] || view.status, DEVICE_VIEW_LABELS[view.status] || view.status));
    const meta = document.createElement('p');
    meta.className = 'device-meta';
    meta.textContent = new Date(view.created_at).toLocaleString();
    card.append(head, meta);
    if (view.status === 'pending' || view.status === 'active') {
      const actions = document.createElement('div');
      actions.className = 'device-actions';
      const watch = document.createElement('button');
      watch.type = 'button';
      watch.className = 'primary';
      watch.textContent = view.frame_count ? 'Ver en directo' : 'Abrir visor';
      watch.onclick = () => renderLiveView(view);
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'secondary';
      cancel.textContent = 'Cancelar solicitud';
      cancel.onclick = async () => {
        cancel.disabled = true;
        try {
          await api(`/v1/live-views/${view.id}/status`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: 'cancelled'})});
          toast('Solicitud cancelada.', 'success');
          await load();
        } catch (error) { notify(error); } finally { cancel.disabled = false; }
      };
      actions.append(watch, cancel);
      card.append(actions);
    }
    if (view.frame_count) {
      const frames = document.createElement('p');
      frames.className = 'device-meta';
      frames.textContent = `${view.frame_count} fotograma(s) recibidos`;
      card.append(frames);
    }
    transmissions.body.append(card);
  });
  if (!transmissions.body.children.length) transmissions.body.append(empty('Sin solicitudes de transmisión.'));
  target.append(transmissions.section);

  const trackerSection = deviceSection('Rastreadores', 'Objetos con localizador (llaves, cartera…) y su último estado conocido.');
  const trackerLabels = {keys: 'Llaves', wallet: 'Cartera', bag: 'Bolso', other: 'Objeto'};
  const trackerStatus = {near: 'Cerca', far: 'Lejos', lost: 'Perdido', home: 'En casa', unknown: 'Sin estado'};
  (trackers || []).forEach(tracker => {
    const card = document.createElement('article');
    card.className = 'device-card device-card--tracker';
    const head = document.createElement('div');
    head.className = 'device-card-head';
    const title = document.createElement('strong');
    title.textContent = tracker.name;
    head.append(title, statusChip(tracker.status === 'near' || tracker.status === 'home', trackerStatus[tracker.status] || tracker.status, trackerStatus[tracker.status] || tracker.status));
    const meta = document.createElement('p');
    meta.className = 'device-meta';
    meta.textContent = `${trackerLabels[tracker.kind] || tracker.kind}${tracker.place ? ` · ${tracker.place}` : ''}`
      + (tracker.last_seen_at ? ` · visto ${new Date(tracker.last_seen_at).toLocaleString()}` : '');
    card.append(head, meta);
    trackerSection.body.append(card);
  });
  if (!trackerSection.body.children.length) trackerSection.body.append(empty('Sin rastreadores vinculados. Se gestionan con la API de rastreadores.'));
  target.append(trackerSection.section);
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
    const suggestion = review.suggestion && !review.suggestion.dismissed ? review.suggestion : null;
    if (suggestion) {
      const hint = document.createElement('div'); hint.className = 'review-suggestion';
      const strength = suggestion.confidence === 'high' ? 'sugerencia fuerte' : 'pista';
      const guessed = `Posiblemente es su ${suggestion.relationship}${suggestion.display_name ? `, ${suggestion.display_name}` : ''} (${strength}).`;
      const text = document.createElement('p'); text.className = 'review-suggestion-text'; text.textContent = guessed;
      hint.append(text);
      if (suggestion.context) {
        const context = document.createElement('p'); context.className = 'review-suggestion-context';
        context.textContent = `Contexto: «${suggestion.context}»`;
        hint.append(context);
      }
      const accept = document.createElement('button'); accept.className = 'primary'; accept.textContent = 'Confirmar sugerencia';
      accept.onclick = async () => {
        if (!suggestion.person_id) return toast('Elige abajo la persona correcta y confirma.', 'error');
        accept.disabled = true;
        try { await api(`/v1/reviews/${review.id}/resolve`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({person_id: suggestion.person_id})}); toast('Gracias. Faro ya reconocerá a esa persona.', 'success'); await load(); }
        catch (error) { notify(error); } finally { accept.disabled = false; }
      };
      const reject = document.createElement('button'); reject.className = 'secondary'; reject.textContent = 'Descartar sugerencia';
      reject.onclick = async () => {
        try { await api(`/v1/reviews/${review.id}/suggestion/dismiss`, {method: 'POST'}); toast('Sugerencia descartada.', 'success'); await load(); }
        catch (error) { notify(error); }
      };
      hint.append(accept, reject);
      controls.append(hint);
    }
    select.append(new Option('Selecciona una persona…', ''), ...people.map(person => new Option(`${person.display_name} · ${person.relationship}`, person.id)));
    if (suggestion && suggestion.person_id) select.value = suggestion.person_id;
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
function acknowledgeTab(tab) {
  const badge = tab.querySelector('.badge');
  if (!badge) return;
  const key = BADGE_KEYS[badge.id];
  if (!key) return;
  acknowledged[key] = currentCounts[key] || 0;
  saveAck();
  badge.hidden = true;
  badge.textContent = '';
}
function activateTab(tab) {
  tabs.forEach(node => {
    const active = node === tab;
    node.classList.toggle('active', active);
    node.setAttribute('aria-selected', String(active));
    node.tabIndex = active ? 0 : -1;
    document.querySelector(`#${node.dataset.view}`).classList.toggle('active', active);
  });
  acknowledgeTab(tab);
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
  const safePoints = String(data.get('home_safe_points') || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean).map(item => ({street_address: item, country: 'España'}));
  const payload = {preferred_name: data.get('preferred_name'), full_name: data.get('full_name') || '', birth_year: year ? Number(year) : null, phone_e164: data.get('phone_e164') || null, home_address: {street_address: data.get('home_street_address') || '', postal_code: data.get('home_postal_code') || '', locality: data.get('home_locality') || '', province: data.get('home_province') || '', country: data.get('home_country') || 'España', access_notes: data.get('home_access_notes') || '', latitude, longitude}, safe_points: safePoints, conditions: String(data.get('conditions') || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean), communication_preferences: data.get('communication_preferences') || '', emergency_notes: data.get('emergency_notes') || '', care_notes: data.get('care_notes') || ''};
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
  const payload = {display_name: data.get('display_name'), phone_e164: data.get('phone_e164'), alternate_phone_e164: data.get('alternate_phone_e164') || null, address: {street_address: data.get('street_address') || '', postal_code: data.get('postal_code') || '', locality: data.get('locality') || '', province: data.get('province') || '', country: 'España'}, availability_notes: data.get('availability_notes') || '', role: data.get('role'), whatsapp_consent: data.get('whatsapp_consent') === 'on', priority: Number(data.get('priority')), alerts_enabled: true, known_person_id: data.get('known_person_id') || null, preferred_channel: data.get('preferred_channel') || 'whatsapp', emergency_share_scope: data.get('emergency_share_scope') || 'full', emergency_notes: data.get('emergency_notes') || ''};
  try { await api('/v1/care-contacts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); event.target.reset(); toast('Contacto añadido.', 'success'); await load(); } catch (error) { notify(error); }
});

document.querySelector('#refresh').onclick = load;
const clearHistory = document.querySelector('#clear-history');
if (clearHistory) clearHistory.addEventListener('click', async () => {
  if (!(await confirmAction('¿Borrar todo el historial de la Memoria? Esta acción no se puede deshacer.', 'Limpiar historial'))) return;
  try { await api('/v1/events', {method: 'DELETE'}); toast('Historial borrado.', 'success'); await load(); }
  catch (error) { notify(error); }
});
for (const filter of ['#event-filter', '#severity-filter', '#delivery-filter', '#event-order']) document.querySelector(filter).onchange = () => renderMemory();
let searchTimer = null;
document.querySelector('#event-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { memoryPage = 1; renderMemory(); }, 220); });
for (const id of ['#event-hour-from', '#event-hour-to']) {
  const select = document.querySelector(id);
  for (let hour = 0; hour < 24; hour += 1) {
    const option = document.createElement('option');
    option.value = String(hour);
    option.textContent = `${String(hour).padStart(2, '0')}:00`;
    select.append(option);
  }
  select.onchange = () => { memoryPage = 1; renderMemory(); };
}
document.querySelector('#event-date').onchange = event => { memoryDay = event.target.value || ''; refreshMemoryDay(); };
document.querySelector('#event-prev-day').onclick = () => shiftMemoryDay(-1);
document.querySelector('#event-next-day').onclick = () => shiftMemoryDay(1);
document.querySelector('#event-today').onclick = () => { memoryDay = ''; document.querySelector('#event-date').value = ''; refreshMemoryDay(); };
document.querySelector('#pair').onclick = async () => { try { const invite = await api('/v1/pairing-invites', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({role: document.querySelector('#pair-role').value})}); document.querySelector('#pair-code').textContent = invite.code; toast('Código creado. Caduca en 10 minutos.', 'success'); } catch (error) { notify(error); } };

const devicePairDialog = document.querySelector('#pair-dialog');
const devicePairCode = document.querySelector('#device-pair-code');
const devicePairStatus = document.querySelector('#device-pair-status');
const devicePairCopy = document.querySelector('#device-pair-copy');
const devicesRefresh = document.querySelector('#devices-refresh');
if (devicesRefresh) devicesRefresh.addEventListener('click', () => load());
const devicePairOpen = document.querySelector('#device-pair');
if (devicePairOpen) devicePairOpen.addEventListener('click', () => {
  if (devicePairCode) devicePairCode.textContent = '';
  if (devicePairStatus) devicePairStatus.textContent = '';
  if (devicePairCopy) devicePairCopy.hidden = true;
  if (devicePairDialog && typeof devicePairDialog.showModal === 'function') devicePairDialog.showModal();
});
const devicePairCreate = document.querySelector('#device-pair-create');
if (devicePairCreate) devicePairCreate.addEventListener('click', async () => {
  devicePairCreate.disabled = true;
  try {
    const invite = await api('/v1/pairing-invites', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({role: document.querySelector('#device-pair-role').value})});
    if (devicePairCode) devicePairCode.textContent = invite.code;
    if (devicePairStatus) devicePairStatus.textContent = `Válido hasta las ${new Date(invite.expires_at).toLocaleTimeString()}`;
    if (devicePairCopy) devicePairCopy.hidden = false;
    toast('Código creado. Caduca en 10 minutos.', 'success');
  } catch (error) { notify(error); } finally { devicePairCreate.disabled = false; }
});
if (devicePairCopy) devicePairCopy.addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(devicePairCode.textContent || ''); toast('Código copiado.', 'success'); }
  catch { notify(new Error('No se pudo copiar. Selecciona el código a mano.')); }
});
const devicePairClose = document.querySelector('#device-pair-close');
if (devicePairClose) devicePairClose.addEventListener('click', () => { if (devicePairDialog) devicePairDialog.close(); });

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

let currentAudio = null;

function stopSpeaking() {
  if (currentAudio) { try { currentAudio.pause(); } catch {} currentAudio = null; }
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}

function speakWithBrowser(text, language) {
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

async function speakAnswer(text, language) {
  if (!text) return;
  stopSpeaking();
  try {
    const response = await fetch('/v1/family/speech', {method: 'POST', headers: {...authHeaders, 'Content-Type': 'application/json'}, body: JSON.stringify({text, language})});
    if (!response.ok) throw new Error(`speech ${response.status}`);
    const blob = await response.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    currentAudio = audio;
    await new Promise((resolve, reject) => {
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error('No se pudo reproducir el audio.'));
      audio.play().catch(reject);
    });
    if (currentAudio === audio) currentAudio = null;
  } catch (error) {
    return speakWithBrowser(text, language);
  }
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
    try { stopSpeaking(); recognition.start(); setListening(true); }
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
    stopSpeaking();
    localStorage.removeItem('familyConversationId');
    talkAnswer.hidden = true; talkAnswer.textContent = '';
    talkInput.value = '';
    talkReset.hidden = true;
  });
}

const exerciseRefresh = document.querySelector('#exercise-refresh');
if (exerciseRefresh) exerciseRefresh.addEventListener('click', () => load());
const statsRefresh = document.querySelector('#stats-refresh');
if (statsRefresh) statsRefresh.addEventListener('click', () => load());
const statsInsightBtn = document.querySelector('#stats-insight-btn');
if (statsInsightBtn) statsInsightBtn.addEventListener('click', async () => {
  const text = document.querySelector('#stats-insight-text');
  statsInsightBtn.disabled = true;
  if (text) text.textContent = 'Analizando la evolución…';
  try {
    const result = await api('/v1/stats/insights?days=30');
    if (text) text.textContent = result.insight;
  } catch (error) { if (text) text.textContent = 'No se pudo generar la valoración.'; notify(error); }
  finally { statsInsightBtn.disabled = false; }
});

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
  // KAN-203: con la contrasena maestra el navegador envia HTTP Basic en las peticiones del
  // mismo origen; no hace falta token en la URL. El enlace ?token= sigue funcionando.
  try {
    const health = await fetch('/health').then(response => response.json());
    document.querySelector('#connection').textContent = `Conectado · ${health.face_provider === 'RekognitionFaceProvider' ? 'reconocimiento activo' : 'modo de prueba'}`;
  } catch { document.querySelector('#connection').textContent = 'Sin conexión'; }
  try { await load(); } catch (error) { document.querySelector('#connection').textContent = 'Sin conexión'; notify(error); }
  observeReveals();
})();
