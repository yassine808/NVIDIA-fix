(function () {
  var $ = function (s) { return document.querySelector(s); };
  var api = window.nvidiaFix;

  // Tick strip: one motif for drop zone, progress and result.
  function strip(el, lost) {
    var n = 72, cut = lost > 0 ? Math.max(1, Math.round(n * lost / 100)) : 0;
    el.innerHTML = '';
    for (var i = 0; i < n; i++) {
      var t = document.createElement('i');
      t.style.height = (30 + 70 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * .55))) + '%';
      if (lost != null) t.className = i < cut ? 'bad' : 'ok';
      el.appendChild(t);
    }
    return el.children;
  }
  document.querySelectorAll('.strip[data-lost]').forEach(function (el) { strip(el, +el.dataset.lost); });

  function tc(v) {
    if (v == null || Number.isNaN(v)) return '—';
    var m = Math.floor(v / 60);
    return m + ':' + (v - m * 60).toFixed(2).padStart(5, '0');
  }
  function filesize(n) {
    if (!n) return '';
    return n >= 1e9 ? (n / 1e9).toFixed(2) + ' GB' : (n / 1e6).toFixed(1) + ' MB';
  }

  // Copy a saved path to the clipboard with the old API and the new one.
  function copyPath(input) {
    input.select();
    var ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (e) {
      // execCommand("copy") is removed in newer Chromium; the async API below
      // is the supported path and runs whenever it reports false.
    }
    if (!ok && navigator.clipboard) {
      navigator.clipboard.writeText(input.value).catch(function () {
        // Clipboard access can be denied without a user gesture; the text
        // stays selected so the reader can copy it by hand.
      });
    }
  }

  // Result page: copy buttons.
  document.querySelectorAll('.copy').forEach(function (b) {
    b.addEventListener('click', function () {
      copyPath(b.parentElement.querySelector('.path'));
      b.textContent = 'Copied';
      setTimeout(function () { b.textContent = 'Copy'; }, 1400);
    });
  });

  var home = $('#home'), result = $('#result');
  var form = $('#fix-form');
  var zone = $('#zone'), picker = $('#file'), path = $('#video_path'), go = $('#go'), note = $('#note');
  var ticks = strip($('#strip'));
  var calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var file = null, scan, advance;

  function size(n) { return n >= 1e9 ? (n / 1e9).toFixed(2) + ' GB' : Math.max(1, Math.round(n / 1e6)) + ' MB'; }
  function base(v) { return v.trim().replace(/^["']|["']$/g, '').split(/[\\/]/).pop(); }
  function error(msg) { note.textContent = msg; note.hidden = !msg; }

  function sync() {
    var name = file ? file.name : base(path.value);
    zone.dataset.state = name ? 'ready' : 'idle';
    $('#name').textContent = name;
    $('#size').textContent = file ? size(file.size) : 'On this PC';
    $('#out').textContent = name.replace(/\.[^.]+$/, '') + '.clean.mp4';
    go.disabled = !name;
  }

  function take(f) {
    if (!f) return;
    if (!/\.(mp4|mov|m4v)$/i.test(f.name)) { error('Drop an MP4, MOV or M4V file.'); return; }
    file = f; path.value = ''; error(''); sync();
  }

  // Electron: real file paths, no upload.
  window.setVideoPath = function (p) {
    delete zone.dataset.over;
    if (!/\.(mp4|mov|m4v)$/i.test(p)) { error('Drop an MP4, MOV or M4V file.'); return; }
    file = null; picker.value = ''; path.value = p; error(''); sync();
  };
  function browse() {
    if (api && api.pickVideo) {
      api.pickVideo().then(function (p) { if (p) window.setVideoPath(p); });
      return;
    }
    var pw = window.pywebview && window.pywebview.api;
    if (pw && pw.browse) { pw.browse().then(function (p) { if (p) window.setVideoPath(p); }); return; }
    picker.click();
  }
  $('#browse').addEventListener('click', function (e) { e.stopPropagation(); browse(); });
  zone.addEventListener('click', function (e) {
    if (zone.dataset.state === 'idle' && !e.target.closest('button')) browse();
  });
  picker.addEventListener('change', function () { take(picker.files[0]); });
  $('#clear').addEventListener('click', function () { file = null; picker.value = ''; path.value = ''; sync(); });
  path.addEventListener('input', function () { file = null; error(''); sync(); });
  var sample = $('#use-sample');
  if (sample) sample.addEventListener('click', function () { file = null; path.value = sample.dataset.path || ''; sync(); path.focus(); });

  // Drop anywhere on the page.
  ['dragenter', 'dragover'].forEach(function (t) {
    addEventListener(t, function (e) { e.preventDefault(); if (zone.dataset.state !== 'working') zone.dataset.over = ''; });
  });
  addEventListener('dragleave', function (e) { if (!e.relatedTarget) delete zone.dataset.over; });
  addEventListener('drop', function (e) {
    e.preventDefault(); delete zone.dataset.over;
    if (zone.dataset.state !== 'working') take(e.dataTransfer.files[0]);
  });

  function stop() {
    clearInterval(scan); clearInterval(advance);
    Array.prototype.forEach.call(ticks, function (t) { t.className = ''; });
  }

  function showResult(r) {
    home.hidden = true;
    result.hidden = false;
    window.scrollTo(0, 0);

    var chip = $('#res-chip'), title = $('#res-title'), name = $('#res-name');
    var warning = $('#res-warning'), legend = $('#res-legend'), stats = $('#res-stats');
    var filesWrap = $('#res-files-wrap'), caveat = $('#res-caveat'), details = $('#res-details');
    var lostStrip = $('#res-strip'), fileBox = $('#res-files');
    var okMark = $('#res-ok'), okNote = $('#res-ok-note');
    var isHealthy = r.status === 'healthy';
    result.classList.toggle('healthy', isHealthy);
    okMark.hidden = !isHealthy; okNote.hidden = !isHealthy; chip.hidden = isHealthy;

    if (isHealthy) {
      title.textContent = 'No corruption detected.';
      name.textContent = r.original_name || '';
      [lostStrip, legend, stats, filesWrap, caveat, details, warning].forEach(function (el) { el.hidden = true; });
      return;
    }

    var c = r.corruption, rec = r.recovery, video = rec.video;
    chip.className = r.status === 'success' ? 'chip' : 'chip warn';
    chip.textContent = r.status === 'success' ? 'Verified clean' : 'Recovered with warnings';
    title.textContent = 'Clean video recovered.';
    name.textContent = r.original_name || '';

    if (r.warning) {
      warning.hidden = false;
      warning.className = 'notice ' + (r.status === 'success' ? 'good' : 'warn');
      warning.textContent = r.warning;
    } else {
      warning.hidden = true;
    }

    var total = (c.clean_start_seconds + video.duration_seconds) || 1;
    var lostPct = c.clean_start_seconds / total * 100;
    strip(lostStrip, lostPct);
    $('#res-lost').textContent = tc(c.clean_start_seconds);
    $('#res-recovered').textContent = tc(video.duration_seconds);
    $('#res-damaged').textContent = Number(c.bad_samples).toLocaleString();
    $('#res-errors').textContent = video.decode_errors;

    fileBox.innerHTML = '';
    (r.outputs || []).forEach(function (entry) {
      var tpl = $('#file-template').content.cloneNode(true);
      var input = tpl.querySelector('.path');
      tpl.querySelector('.file-label').textContent = entry.label;
      tpl.querySelector('.file-size').textContent = filesize(entry.size_bytes);
      tpl.querySelector('.fn').textContent = entry.name;
      input.value = entry.path;
      tpl.querySelector('.fd').textContent = entry.detail;
      input.addEventListener('click', function () { input.select(); });
      tpl.querySelector('.copy').addEventListener('click', function (e) {
        copyPath(e.target.parentElement.querySelector('.path'));
        e.target.textContent = 'Copied';
        setTimeout(function () { e.target.textContent = 'Copy'; }, 1400);
      });
      fileBox.appendChild(tpl);
    });
    $('#res-note').textContent = r.saved_note || '';
    $('#res-dir').textContent = r.output_dir || '';

    caveat.textContent = 'The first ' + tc(c.last_bad_seconds) + " was overwritten in the recorder's file and can't be rebuilt. Only its surviving audio is kept.";

    var list = $('#res-evidence');
    list.innerHTML = '';
    [
      'Every video sample after the boundary passed the H.264 header check.',
      'The first output packet matches the source byte for byte (SHA-256 ' + (video.first_packet_sha256 || '').slice(0, 16) + '…).',
      video.decode_errors === 0 ? 'A full decode reported zero errors.' : 'A full decode reported ' + video.decode_errors + ' error line(s).',
      Number(video.packets).toLocaleString() + ' video packets were stream-copied, not re-encoded.'
    ].forEach(function (text) {
      var li = document.createElement('li');
      li.textContent = text;
      list.appendChild(li);
    });

    [lostStrip, legend, stats, filesWrap, caveat, details].forEach(function (el) { el.hidden = false; });
  }

  function reset() {
    result.hidden = true;
    home.hidden = false;
    file = null;
    picker.value = '';
    path.value = '';
    error('');
    sync();
    window.scrollTo(0, 0);
  }
  $('#res-again').addEventListener('click', function (e) { e.preventDefault(); reset(); });

  // Class for one step in the "Recovering" list.
  function stepClass(index, current) {
    if (index < current) return 'done';
    return index === current ? 'on' : '';
  }

  // Class for one tick while the scan animation runs.
  function tickClass(index, head, cut) {
    if (index === head) return 'hd';
    if (index >= head) return '';
    return index < cut ? 'bad' : 'ok';
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (go.disabled) return;
    var full = form.full_decode.checked;

    var target = path.value.trim();
    if (file) {
      target = api && api.pathForFile ? api.pathForFile(file) : '';
    }
    if (!target) { error('Choose a video file first.'); return; }

    var steps = ['Scanning samples', 'Finding the boundary', 'Cutting the tail'].concat(full ? ['Verifying'] : []);
    var listEl = $('#steps'), k = 0;
    listEl.innerHTML = steps.map(function (s) { return '<li>' + s + '</li>'; }).join('');
    function mark() {
      Array.prototype.forEach.call(listEl.children, function (li, i) { li.className = stepClass(i, k); });
    }
    mark();
    zone.dataset.state = 'working'; error('');

    var cut = Math.round(ticks.length * .38), h = 0;
    if (calm) {
      Array.prototype.forEach.call(ticks, function (t, i) { t.className = tickClass(i, i + 1, cut); });
    } else {
      scan = setInterval(function () {
        Array.prototype.forEach.call(ticks, function (t, i) { t.className = tickClass(i, h, cut); });
        h = (h + 1) % (ticks.length + 10);
      }, 50);
    }

    function stepFor(message) {
      if (/Reading the container|Scanning/.test(message)) return 0;
      if (/damaged samples|keyframe/.test(message)) return 1;
      if (/Cutting/.test(message)) return 2;
      if (/No corruption detected/.test(message)) return steps.length - 1;
      if (/Verifying|Checking|Decoding|Exporting/.test(message)) return full ? 3 : 2;
      return -1;
    }
    function advanceTo(index) {
      if (index > k) { k = Math.min(index, steps.length - 1); mark(); }
    }

    if (!api || !api.recover) {
      setTimeout(function () { stop(); sync(); error('Preview only. Run the app to recover videos.'); }, 1600);
      return;
    }

    var off = api.onProgress(function (message) { advanceTo(stepFor(message)); });
    api.recover({ path: target, fullDecode: full }).then(function (r) {
      off(); stop();
      showResult(r);
    }).catch(function (err) {
      off(); stop();
      zone.dataset.state = 'ready';
      error((err && err.message ? err.message : String(err)).replace(/^Error invoking remote method '[^']+':\s*(Error:\s*)?/, ''));
    });
  });

  if (api && api.info) {
    api.info().then(function (info) {
      $('#version').textContent = 'v' + info.engineVersion;
      if (info.samplePath) {
        sample.dataset.path = info.samplePath;
        sample.hidden = false;
      }
    }).catch(function () {
      // The version banner is optional; a missing bridge is handled above.
    });
  }

  try {
    var remembered = localStorage.getItem('nvidiaFix.lastPath');
    if (remembered) path.value = remembered;
  } catch (e) {
    // localStorage can be disabled in a sandboxed renderer; the field just
    // starts empty in that case.
  }
  path.addEventListener('input', function () {
    try {
      localStorage.setItem('nvidiaFix.lastPath', path.value.trim());
    } catch (e) {
      // Same as above: remember the path only when storage is available.
    }
  });

  sync();
})();
