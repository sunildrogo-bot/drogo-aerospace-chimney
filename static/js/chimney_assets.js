/* Project files live in a compact Manage Files menu above the 3D viewer.
   Files are uploaded in resumable chunks and processed by a separate worker.
   All authorized sessions poll the same server-side job status. */
(function () {
  'use strict';
  const root = document.getElementById('chim-assets');
  if (!root) return;
  const dropdown = document.getElementById('chim-files-dropdown');
  const menu = document.getElementById('chim-files-menu');
  const toggle = document.getElementById('chim-files-toggle');
  const indicator = document.getElementById('chim-files-indicator');
  function closeFilesMenu() {
    if (menu) menu.hidden = true;
    if (dropdown) dropdown.classList.remove('open');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }
  window.closeChimneyFilesMenu = closeFilesMenu;
  window.toggleChimneyFilesMenu = function (event) {
    if (event) event.stopPropagation();
    if (!dropdown || !menu) return;
    const opening = menu.hidden;
    menu.hidden = !opening;
    dropdown.classList.toggle('open', opening);
    if (toggle) toggle.setAttribute('aria-expanded', String(opening));
    if (opening) {
      document.getElementById('map-style-menu')?.classList.remove('open');
      document.getElementById('map-style-dropdown')?.classList.remove('open');
      document.getElementById('map-style-toggle')?.setAttribute('aria-expanded', 'false');
      refresh();
    }
  };
  document.addEventListener('click', event => {
    if (dropdown?.classList.contains('open') && !dropdown.contains(event.target)) closeFilesMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && dropdown?.classList.contains('open')) {
      closeFilesMenu();
      toggle?.focus();
    }
  });
  const pid = window.CHIM_PROJECT_ID;
  const api = `/api/chimney-projects/${encodeURIComponent(pid)}/assets`;
  const input = document.getElementById('chim-assets-input');
  const status = document.getElementById('chim-assets-status');
  const list = document.getElementById('chim-assets-list');
  const progress = document.getElementById('chim-assets-progress');
  const progressValue = document.getElementById('chim-assets-progress-value');
  const controls = Array.from(root.querySelectorAll('[data-upload-kind]'));
  const CHUNK = 6 * 1024 * 1024;  // below 8 MiB server limit
  let busy = false;
  let previousModel = !!window.CHIM_TILESET_URL;

  const accepts = {
    '3tz': '.3tz,.zip',
    'ortho': '.tif,.tiff,.geotiff,.jp2,.jpg,.jpeg,.png,.webp,.mbtiles,.zip',
    'tileset_json': '.json,.zip',
    'all': '.3tz,.zip,.json,.tif,.tiff,.geotiff,.jp2,.jpg,.jpeg,.png,.webp,.mbtiles',
  };

  function message(text, error) {
    status.textContent = text;
    status.classList.toggle('error', !!error);
  }
  function errorText(r, obj) { return obj.error || `HTTP ${r.status}: request failed.`; }
  async function readJson(r) {
    let result = {};
    try { result = await r.json(); } catch (_) { throw new Error(`Unexpected server response (HTTP ${r.status}). Try logging in again or inspect server logs.`); }
    if (!r.ok) throw new Error(errorText(r, result));
    return result;
  }
  function showAssets(data) {
    const byType = data.by_type || {};
    ['3tz','ortho','tileset_json'].forEach(kind => {
      const row = root.querySelector(`[data-asset-kind="${kind}"]`);
      if (!row) return;
      const entries = byType[kind] || [];
      const ready = entries.length > 0 || (kind === '3tz' && data.has_model);
      const icon = row.querySelector('.chim-asset-icon');
      icon.textContent = ready ? '✓' : '+';
      icon.classList.toggle('ready', !!ready);
      row.querySelector('.chim-asset-state').textContent = entries.length
        ? (entries.length === 1 ? entries[0].name : `${entries.length} files uploaded`)
        : (kind === '3tz' && data.has_model ? 'Existing 3D model ready' : 'Not uploaded');
    });
    list.replaceChildren();
    const files = data.files || [];
    if (!files.length) {
      const empty = document.createElement('span');
      empty.textContent = 'No uploaded files recorded yet.';
      list.append(empty);
    }
    files.forEach(file => {
      const chip = document.createElement('span');
      chip.className = 'chim-asset-file';
      chip.textContent = file.name;
      chip.title = (file.source === 'inside_archive' ? 'Inside ZIP / 3TZ' : 'Uploaded file')
        + (file.uploaded_at ? ` · ${file.uploaded_at}` : '');
      list.append(chip);
    });
    const jobs = data.jobs || [];
    const activeJob = jobs.find(j => ['uploading','queued','processing'].includes(j.state));
    const failedJob = jobs.find(j => j.state === 'failed');
    if (indicator) {
      indicator.hidden = !activeJob && !failedJob;
      indicator.textContent = failedJob && !activeJob ? '!' : '●';
      indicator.classList.toggle('error', !activeJob && !!failedJob);
      indicator.title = activeJob ? 'File transfer or processing in progress'
        : failedJob ? 'A recent file upload failed; open Manage Files for details.' : '';
    }
    if (!busy) {
      const active = activeJob;
      if (active) {
        const pct = active.size ? Math.round(100 * active.received / active.size) : 0;
        progress.hidden = false;
        progressValue.value = pct;
        message(active.state === 'uploading'
          ? `${active.filename} — ${pct}% transferred. Transfer pauses if you leave; choose the same file to resume.`
          : `${active.filename} — ${active.state === 'queued' ? 'Queued' : 'Processing on server'}. You may leave; other users see this status.`);
      } else {
        progress.hidden = true;
        const failed = failedJob;
        if (failed) message(`${failed.filename}: ${failed.error || 'Processing failed. Existing files safe.'}`, true);
        else if (jobs[0] && jobs[0].state === 'completed') message(`${jobs[0].filename} — processed successfully on server.`);
        else message('');
      }
    }
    if (data.has_model && !previousModel && !busy) {
      // Viewer initialization needs a fresh Jinja render with the model URL.
      window.location.reload();
    }
  }

  async function refresh() {
    try {
      const response = await fetch(api, {cache:'no-store'});
      showAssets(await readJson(response));
    } catch (error) { if (!busy) message(error.message || 'Cannot read project files.', true); }
  }

  window.chimSelectAssets = function (kind) {
    if (busy || !input || !window.CHIM_IS_ADMIN) return;
    input.accept = accepts[kind] || accepts.all;
    input.value = '';
    input.click();
  };

  async function uploadOne(file) {
    const res = await readJson(await fetch(`${api}/jobs`, {cache:'no-store'}));
    // Resume only the job created from *this* browser session, not a
    // similarly named upload started by a different administrator.
    const resumeKey = `chimney-upload:${pid}:${file.name}:${file.size}`;
    const priorId = window.sessionStorage.getItem(resumeKey);
    const resumable = (res.jobs || []).find(j => j.state === 'uploading'
                         && j.id === priorId && j.size === file.size);
    let job = resumable;
    if (!job) {
      job = await readJson(await fetch(`${api}/jobs`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({filename:file.name, size:file.size}),
      }));
      window.sessionStorage.setItem(resumeKey, job.id);
    }
    let offset = job.received;
    while (offset < file.size) {
      const block = file.slice(offset, Math.min(offset + CHUNK, file.size));
      const response = await fetch(`${api}/jobs/${job.id}/chunk`, {
        method:'POST', headers:{'Content-Type':'application/octet-stream', 'X-Upload-Offset':String(offset)},
        body:block,
      });
      job = await readJson(response);
      offset = job.received;
      progressValue.value = Math.round(100 * offset / file.size);
      message(`${file.name}: transferred ${progressValue.value}% — ${job.state === 'queued' ? 'processing will continue on server' : 'uploading'}`);
    }
    window.sessionStorage.removeItem(resumeKey);
    message(`${file.name} uploaded to server. Processing continues even if you leave this page.`);
    await refresh();
  }

  window.chimQueueFiles = async function (files) {
    if (!window.CHIM_IS_ADMIN || !files || !files.length || busy) return;
    busy = true;
    controls.forEach(btn => btn.disabled = true);
    progress.hidden = false;
    progressValue.value = 0;
    try {
      for (const file of Array.from(files)) await uploadOne(file);
    } catch (error) {
      message(`Upload paused: ${error.message || 'Network interrupted'}. Re-select the same file to resume; existing data is safe.`, true);
    } finally {
      busy = false;
      controls.forEach(btn => btn.disabled = false);
      await refresh();
    }
  };
  if (input) input.addEventListener('change', () => window.chimQueueFiles(input.files));
  root.addEventListener('dragover', e => { e.preventDefault(); root.classList.add('drag'); });
  root.addEventListener('dragleave', () => root.classList.remove('drag'));
  root.addEventListener('drop', e => {
    e.preventDefault(); root.classList.remove('drag');
    if (window.CHIM_IS_ADMIN) window.chimQueueFiles(e.dataTransfer.files);
  });
  refresh();
  window.setInterval(refresh, 4000);
})();
