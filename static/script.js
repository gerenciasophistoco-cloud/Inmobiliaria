/* ── Datos del último listado generado ── */
let lastPDFData = null;
let lastPropertyId = null;
let lastVideoPropio = null;
let selectedCoverIndex = 0;
let photoLabels = [];   // nombre libre del espacio (ej: "Cocina con isla")
let photoFiles  = [];

/* ── Elementos principales ── */
const form          = document.getElementById('propertyForm');
const btnGenerate   = document.getElementById('btnGenerate');
const resultsEmpty   = document.getElementById('resultsEmpty');
const resultsContent = document.getElementById('resultsContent');
const resultsLoading = document.getElementById('resultsLoading');
const loadingMsg     = document.getElementById('loadingMessage');
const photoPreview   = document.getElementById('photoPreview');
const uploadArea     = document.getElementById('uploadArea');
const uploadPlaceholder = document.getElementById('uploadPlaceholder');
const fotosInput     = document.getElementById('fotos');

/* ── Formato de precio COP ── */
document.getElementById('precio').addEventListener('input', function () {
  const raw = this.value.replace(/\D/g, '');
  this.value = raw ? parseInt(raw).toLocaleString('de-DE') : '';
});

/* ── Preview de fotos ── */
fotosInput.addEventListener('change', function () {
  if (this.files.length) {
    addPhotos(this.files);
    this.value = ''; // reset para permitir volver a seleccionar
  }
});

/* ── Logo preview ── */
document.getElementById('logo').addEventListener('change', function () {
  const file = this.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('logoPreviewImg').src = e.target.result;
    document.getElementById('logoPlaceholder').style.display = 'none';
    document.getElementById('logoPreviewWrap').style.display = 'flex';
  };
  reader.readAsDataURL(file);
});

/* ── Foto del agente preview ── */
document.getElementById('foto_agente').addEventListener('change', function () {
  const file = this.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('fotoAgentePreviewImg').src = e.target.result;
    document.getElementById('fotoAgentePlaceholder').style.display = 'none';
    document.getElementById('fotoAgentePreviewWrap').style.display = 'flex';
  };
  reader.readAsDataURL(file);
});

/* ── Video propio (Plan A) ── */
document.getElementById('videoInput').addEventListener('change', async function () {
  const file = this.files[0];
  if (!file) return;

  document.getElementById('videoPlaceholder').style.display = 'none';
  document.getElementById('videoFileName').textContent = `⏳ Subiendo ${file.name}...`;
  document.getElementById('videoPreviewWrap').style.display = 'flex';

  try {
    // Subir directamente a /upload-video para obtener la URL de Cloudinary
    const fd = new FormData();
    fd.append('video', file);
    const res = await fetch('/upload-video', { method: 'POST', body: fd });
    if (!res.ok) throw new Error('Error al subir el video');
    const { url } = await res.json();
    lastVideoPropio = url;
    document.getElementById('videoFileName').textContent = `✅ ${file.name}`;
    showToast('🎬 Video listo — se usará en la generación');
  } catch (e) {
    document.getElementById('videoFileName').textContent = `❌ Error: ${e.message}`;
    lastVideoPropio = null;
  }
});

function removeVideo() {
  document.getElementById('videoInput').value = '';
  lastVideoPropio = null;
  document.getElementById('videoPlaceholder').style.display = '';
  document.getElementById('videoPreviewWrap').style.display = 'none';
}

function removeFotoAgente() {
  document.getElementById('foto_agente').value = '';
  document.getElementById('fotoAgentePreviewImg').src = '';
  document.getElementById('fotoAgentePlaceholder').style.display = '';
  document.getElementById('fotoAgentePreviewWrap').style.display = 'none';
}

function removeLogo() {
  document.getElementById('logo').value = '';
  document.getElementById('logoPreviewImg').src = '';
  document.getElementById('logoPaletteChips').innerHTML = '';
  document.getElementById('logoPlaceholder').style.display = '';
  document.getElementById('logoPreviewWrap').style.display = 'none';
}


uploadArea.addEventListener('dragover', e => {
  e.preventDefault();
  uploadArea.classList.add('drag-over');
});
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
uploadArea.addEventListener('drop', e => {
  e.preventDefault();
  uploadArea.classList.remove('drag-over');
  if (e.dataTransfer.files.length) addPhotos(e.dataTransfer.files);
});

/* ── Gestión de fotos ── */
const MAX_PHOTOS = 10;
let dragFromIdx = -1;

function addPhotos(fileList) {
  const imgs = Array.from(fileList).filter(f => f.type.startsWith('image/'));
  const canAdd = MAX_PHOTOS - photoFiles.length;
  imgs.slice(0, canAdd).forEach(f => { photoFiles.push(f); photoLabels.push(''); });
  if (imgs.length > canAdd) showToast(`⚠️ Máximo ${MAX_PHOTOS} fotos. Se ignoraron ${imgs.length - canAdd}.`);
  renderPhotoPreviews();
}

function deletePhoto(index) {
  photoFiles.splice(index, 1);
  photoLabels.splice(index, 1);
  if (selectedCoverIndex >= photoFiles.length) selectedCoverIndex = 0;
  else if (selectedCoverIndex > index) selectedCoverIndex--;
  renderPhotoPreviews();
}

function movePhoto(from, to) {
  if (to < 0 || to >= photoFiles.length) return;
  const [f] = photoFiles.splice(from, 1);
  const [l] = photoLabels.splice(from, 1);
  photoFiles.splice(to, 0, f);
  photoLabels.splice(to, 0, l);
  if (selectedCoverIndex === from) selectedCoverIndex = to;
  else if (from < to && selectedCoverIndex > from && selectedCoverIndex <= to) selectedCoverIndex--;
  else if (from > to && selectedCoverIndex >= to && selectedCoverIndex < from) selectedCoverIndex++;
  renderPhotoPreviews();
}

function renderPhotoPreviews() {
  photoPreview.innerHTML = '';

  if (!photoFiles.length) {
    uploadPlaceholder.style.display = '';
    return;
  }
  uploadPlaceholder.style.display = 'none';

  photoFiles.forEach((file, i) => {
    const isCover = i === 0;

    const wrap = document.createElement('div');
    wrap.className = 'photo-thumb-wrap' + (isCover ? ' is-cover' : '');
    wrap.dataset.index = String(i);
    wrap.draggable = true;

    /* ── Thumbnail ── */
    const thumbContainer = document.createElement('div');
    thumbContainer.className = 'photo-thumb-container';

    const badge = document.createElement('span');
    badge.className = 'cover-badge';
    badge.textContent = 'PORTADA';
    thumbContainer.appendChild(badge);

    // Botón eliminar sobre la imagen
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'photo-del-btn';
    delBtn.textContent = '✕';
    delBtn.title = 'Eliminar foto';
    delBtn.addEventListener('click', e => { e.stopPropagation(); deletePhoto(i); });
    thumbContainer.appendChild(delBtn);

    wrap.appendChild(thumbContainer);

    /* ── Input: nombre del espacio (texto libre) ── */
    const spaceInput = document.createElement('input');
    spaceInput.type = 'text';
    spaceInput.className = 'photo-space-input';
    spaceInput.placeholder = isCover ? 'Ej: Fachada principal' : 'Ej: Cocina con isla, Hab. principal…';
    spaceInput.value = photoLabels[i] || '';
    spaceInput.title = 'Nombre del espacio — aparece en el video';
    spaceInput.addEventListener('click', e => e.stopPropagation());
    spaceInput.addEventListener('input', () => { photoLabels[i] = spaceInput.value; });
    wrap.appendChild(spaceInput);

    /* ── Drag & drop ── */
    wrap.addEventListener('dragstart', e => {
      dragFromIdx = i;
      e.dataTransfer.effectAllowed = 'move';
      setTimeout(() => wrap.classList.add('dragging'), 0);
    });
    wrap.addEventListener('dragend', () => {
      wrap.classList.remove('dragging');
      document.querySelectorAll('.photo-thumb-wrap').forEach(w => w.classList.remove('drag-over'));
    });
    wrap.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (dragFromIdx !== i) wrap.classList.add('drag-over');
    });
    wrap.addEventListener('dragleave', () => wrap.classList.remove('drag-over'));
    wrap.addEventListener('drop', e => {
      e.preventDefault();
      wrap.classList.remove('drag-over');
      if (dragFromIdx >= 0 && dragFromIdx !== i) movePhoto(dragFromIdx, i);
      dragFromIdx = -1;
    });

    photoPreview.appendChild(wrap);

    const reader = new FileReader();
    reader.onload = ev => {
      const img = document.createElement('img');
      img.src = ev.target.result;
      img.className = 'photo-thumb';
      img.style.pointerEvents = 'none';
      thumbContainer.insertBefore(img, badge);
    };
    reader.readAsDataURL(file);
  });

  const counter = document.createElement('p');
  counter.className = 'photo-count';
  counter.innerHTML =
    `${photoFiles.length} foto${photoFiles.length !== 1 ? 's' : ''} · ` +
    `La primera es la portada · Arrastra para reordenar`;
  photoPreview.appendChild(counter);
}


/* ── Mensajes de carga rotativos ── */
const loadingMsgs = [
  'Analizando la propiedad...',
  'Generando descripción profesional...',
  'Creando copy para Instagram...',
  'Añadiendo los toques finales...',
];
let loadingTimer;

function startLoading() {
  let i = 0;
  loadingMsg.textContent = loadingMsgs[0];
  loadingTimer = setInterval(() => {
    i = (i + 1) % loadingMsgs.length;
    loadingMsg.style.opacity = '0';
    setTimeout(() => {
      loadingMsg.textContent = loadingMsgs[i];
      loadingMsg.style.opacity = '1';
    }, 200);
  }, 2200);
}

function stopLoading() {
  clearInterval(loadingTimer);
}

/* ── Validación del formulario ── */
const REQUIRED = [
  { name: 'tipo_propiedad',  label: 'Tipo de propiedad' },
  { name: 'direccion',       label: 'Dirección / Sector' },
  { name: 'ciudad',          label: 'Ciudad' },
  { name: 'precio',          label: 'Precio' },
  { name: 'nombre_agente',   label: 'Nombre del agente' },
  { name: 'telefono_agente', label: 'Teléfono del agente' },
];

function validateForm() {
  for (const { name, label } of REQUIRED) {
    const el = form.querySelector(`[name="${name}"]`);
    if (!el || !el.value.trim()) {
      el?.classList.add('error');
      el?.focus();
      setTimeout(() => el?.classList.remove('error'), 2500);
      showToast(`⚠️  Completa el campo: ${label}`);
      return false;
    }
  }
  return true;
}

/* ── Envío del formulario ── */
form.addEventListener('submit', async e => {
  e.preventDefault();
  if (!validateForm()) return;

  setUILoading(true);

  const formData = new FormData(form);
  formData.delete('fotos');
  photoFiles.forEach(f => formData.append('fotos', f));
  // Nombre del espacio de cada foto → el video usa esto para narrar
  formData.set('foto_labels', JSON.stringify(photoLabels));
  // Vincular el video de recorrido subido al property record
  if (lastVideoPropio) formData.set('video_recorrido_url', lastVideoPropio);

  try {
    const res = await fetch('/generate', { method: 'POST', body: formData });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `Error HTTP ${res.status}` }));
      throw new Error(err.detail || 'Error desconocido');
    }

    const data = await res.json();
    lastPropertyId = data.property_id || null;
    renderResults(data);

    // Deshabilitar "Ver inmueble" hasta que video_ready = true en DB
    if (lastPropertyId) startVideoReadyPolling(lastPropertyId);

  } catch (err) {
    showToast(`❌ ${err.message}`);
    showPanel('empty');
  } finally {
    setUILoading(false);
  }
});

function setUILoading(on) {
  btnGenerate.disabled = on;
  btnGenerate.querySelector('.btn-text').style.display  = on ? 'none' : '';
  btnGenerate.querySelector('.btn-loading').style.display = on ? 'inline' : 'none';

  if (on) {
    showPanel('loading');
    startLoading();
  } else {
    stopLoading();
  }
}

function showPanel(which) {
  resultsEmpty.style.display   = which === 'empty'   ? 'flex' : 'none';
  resultsLoading.style.display = which === 'loading' ? 'flex' : 'none';
  resultsContent.style.display = which === 'content' ? 'block' : 'none';
}

/* ── Renderizado de resultados ── */
function renderResults(data) {
  const p = data.propiedad;
  const badgeClass = p.operacion === 'Venta' ? 'badge-venta' : 'badge-renta';
  const badgeEmoji = p.operacion === 'Venta' ? '🏷️' : '🔑';

  document.getElementById('resultHeader').innerHTML = `
    <div class="prop-badge ${badgeClass}">${badgeEmoji} En ${p.operacion}</div>
    <div class="prop-title">${p.tipo} &mdash; ${p.ciudad}</div>
    <div class="prop-address">${p.direccion}</div>
    <div class="prop-price">${p.precio}</div>
    <div class="prop-details">
      <span class="prop-detail">👤 ${p.agente}</span>
      <span class="prop-detail">📞 ${p.telefono}</span>
      ${p.email ? `<span class="prop-detail">✉️ ${p.email}</span>` : ''}
    </div>
  `;

  const coverPhoto = document.getElementById('resultCoverPhoto');
  if (data.fotos && data.fotos.length > 0) {
    coverPhoto.src = data.fotos[0];
    coverPhoto.style.display = 'block';
  } else {
    coverPhoto.style.display = 'none';
  }

  renderDescOptions(data.descripciones || [data.descripcion], data.descripcion);
  document.getElementById('instagram-text').textContent = data.ig_copy;

  // Mostrar chip de Video 2 si el usuario subió un video de recorrido
  const v2chip = document.getElementById('video2Chip');
  if (v2chip) v2chip.style.display = lastVideoPropio ? 'flex' : 'none';

  showPanel('content');

  // En móvil, hacer scroll a resultados
  if (window.innerWidth < 960) {
    document.getElementById('resultsPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Mostrar chips de color del logo si existen
  if (data.colors) {
    const chips = document.getElementById('logoPaletteChips');
    if (chips) {
      const { primary, secondary, accent } = data.colors;
      chips.innerHTML = [primary, secondary, accent]
        .filter(Boolean)
        .map(c => `<span class="palette-chip" style="background:rgb(${c[0]},${c[1]},${c[2]})" title="rgb(${c})"></span>`)
        .join('');
    }
  }

  // Guardar datos completos para el PDF
  const specs = data.specs || {};
  lastPDFData = {
    tipo_propiedad:     p.tipo,
    operacion:          p.operacion,
    direccion:          p.direccion,
    ciudad:             p.ciudad,
    precio:             p.precio,
    habitaciones:       specs.habitaciones   || null,
    banos:              specs.banos          || null,
    metros_construidos: specs.metros_construidos || null,
    metros_terreno:     specs.metros_terreno  || null,
    estacionamientos:   specs.estacionamientos || null,
    amenidades:         specs.amenidades      || [],
    descripcion:        data.descripcion,
    descripcion_2:      (data.descripciones && data.descripciones[1]) || data.descripcion,
    frase_inspiradora:  data.frase_inspiradora || '',
    fotos:              data.fotos            || [],
    nombre_agente:      p.agente,
    telefono_agente:    p.telefono,
    email_agente:       p.email              || null,
    nombre_inmobiliaria: specs.nombre_inmobiliaria || null,
    estrato:            specs.estrato         || null,
    ano_construccion:   specs.ano_construccion || null,
    logo:               data.logo            || null,
    foto_agente:        data.foto_agente     || null,
    colors:             data.colors          || null,
  };
}

/* ── Copiar al portapapeles ── */
async function copyText(elementId, btnId) {
  const el   = document.getElementById(elementId);
  const text = el.value !== undefined ? el.value : el.textContent;
  const btn  = document.getElementById(btnId);

  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Fallback para contextos sin permiso de clipboard
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }

  const original = btn.textContent;
  btn.textContent = '✅ Copiado!';
  btn.classList.add('copied');
  setTimeout(() => {
    btn.textContent = original;
    btn.classList.remove('copied');
  }, 2200);
}

/* ── Construir payload para exportar (PDF o imagen) ── */
function getExportPayload() {
  const payload = { ...lastPDFData };
  for (let i = 1; i <= 9; i++) {
    payload[`label_${i + 1}`] = photoLabels[i] || '';
  }
  return payload;
}

/* ── Helper genérico de descarga ── */
async function _triggerDownload(endpoint, btnId, textClass, loadClass, filename) {
  const btn    = document.getElementById(btnId);
  const txtEl  = btn.querySelector(textClass);
  const loadEl = btn.querySelector(loadClass);

  btn.disabled = true;
  txtEl.style.display  = 'none';
  loadEl.style.display = 'inline';

  try {
    const res = await fetch(endpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(getExportPayload()),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error HTTP ${res.status}`);
    }

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('✅ Archivo descargado');
  } catch (err) {
    showToast(`❌ ${err.message}`);
  } finally {
    btn.disabled = false;
    txtEl.style.display  = '';
    loadEl.style.display = 'none';
  }
}

/* ── Descargar PDF ── */
function downloadPDF() {
  if (!lastPDFData) return;
  const safe = s => (s || '').replace(/[^a-zA-Z0-9]/g, '_');
  _triggerDownload(
    '/download-pdf',
    'btnDownloadPDF', '.btn-pdf-text', '.btn-pdf-loading',
    `ListaPro_${safe(lastPDFData.tipo_propiedad)}_${safe(lastPDFData.ciudad)}.pdf`
  );
}

/* ── Abrir página web del inmueble ── */
function openPropiedad() {
  if (!lastPropertyId) { showToast('⚠️ Genera el contenido primero'); return; }
  window.open(`/propiedad/${lastPropertyId}`, '_blank');
}

/* ── Polling: esperar a que video_ready = true en DB ── */
let _readyTimer = null;

function startVideoReadyPolling(propertyId) {
  const btn    = document.getElementById('btnVerInmueble');
  const txtEl  = btn.querySelector('.btn-pdf-text');

  // Deshabilitar botón mientras el video se procesa
  btn.disabled = true;
  txtEl.textContent = '⏳ Preparando link...';

  if (_readyTimer) clearInterval(_readyTimer);

  let elapsed = 0;
  const MAX_WAIT = 120; // 2 minutos máximo

  _readyTimer = setInterval(async () => {
    elapsed += 5;
    try {
      const res  = await fetch(`/property-ready/${propertyId}`);
      if (!res.ok) throw new Error('poll error');
      const data = await res.json();

      if (data.ready) {
        clearInterval(_readyTimer);
        btn.disabled = false;
        txtEl.textContent = '🌐 Ver inmueble';
        showToast(data.video_url
          ? '✅ Link listo — el video ya está disponible'
          : '✅ Link listo — abre la página del inmueble'
        );
        return;
      }
    } catch (_) { /* seguir intentando */ }

    if (elapsed >= MAX_WAIT) {
      clearInterval(_readyTimer);
      btn.disabled = false;
      txtEl.textContent = '🌐 Ver inmueble';
    }
  }, 5000);
}

/* ── Descargar imagen (legacy, mantenido por si se restaura) ── */
function downloadImage() {
  if (!lastPDFData) return;
  const safe = s => (s || '').replace(/[^a-zA-Z0-9]/g, '_');
  _triggerDownload(
    '/download-image',
    'btnDownloadIMG', '.btn-img-text', '.btn-img-loading',
    `ListaPro_${safe(lastPDFData.tipo_propiedad)}_${safe(lastPDFData.ciudad)}.jpg`
  );
}


/* ── Resetear formulario ── */
function resetForm() {
  form.reset();
  photoPreview.innerHTML = '';
  uploadPlaceholder.style.display = '';
  lastPDFData = null;
  lastPropertyId = null;
  lastVideoPropio = null;
  selectedCoverIndex = 0;
  photoLabels = [];
  if (_readyTimer) { clearInterval(_readyTimer); _readyTimer = null; }
  const btnVer = document.getElementById('btnVerInmueble');
  if (btnVer) { btnVer.disabled = false; btnVer.querySelector('.btn-pdf-text').textContent = '🌐 Ver inmueble'; }
  removeLogo();
  showPanel('empty');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── Toast de notificaciones ── */
let toastEl = null;

function showToast(message) {
  if (toastEl) toastEl.remove();

  toastEl = document.createElement('div');
  toastEl.className = 'toast';
  toastEl.textContent = message;
  document.body.appendChild(toastEl);

  requestAnimationFrame(() => {
    requestAnimationFrame(() => toastEl.classList.add('show'));
  });

  setTimeout(() => {
    toastEl.classList.remove('show');
    setTimeout(() => { toastEl?.remove(); toastEl = null; }, 300);
  }, 3200);
}

/* ── Selector de descripciones ── */
const ENFOQUES = [
  'Emocional',
  'Ubicación',
  'Características',
  'Estilo de vida',
  'Directa',
];

function renderDescOptions(opciones, defaultDesc) {
  const container = document.getElementById('descOptions');
  const textarea  = document.getElementById('descripcion-text');
  container.innerHTML = '';

  opciones.forEach((texto, i) => {
    const card = document.createElement('div');
    card.className = 'desc-option-card' + (i === 0 ? ' selected' : '');
    card.innerHTML = `<div class="desc-option-label">${ENFOQUES[i] || `Opción ${i + 1}`}</div>
                      <div class="desc-option-text">${texto}</div>`;
    card.addEventListener('click', () => {
      container.querySelectorAll('.desc-option-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      textarea.value = texto;
      if (lastPDFData) lastPDFData.descripcion = texto;
    });
    container.appendChild(card);
  });

  textarea.value = defaultDesc || (opciones[0] ?? '');
  if (lastPDFData) lastPDFData.descripcion = textarea.value;
}

function onDescEdit(value) {
  if (lastPDFData) lastPDFData.descripcion = value;
  document.querySelectorAll('#descOptions .desc-option-card').forEach(c => c.classList.remove('selected'));
}

