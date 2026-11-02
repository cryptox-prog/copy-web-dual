let requests = [], selected = null, signature = '', polling = false;
const $ = id => document.getElementById(id);
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message) { $('notice').textContent = message; }
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}
function draw() {
  $('pending').textContent = requests.filter(r => r.status === 'pending').length;
  $('count').textContent = requests.length;
  $('requests').innerHTML = requests.map(r => `<button class="request ${r.id === selected ? 'active' : ''}" data-id="${r.id}"><span class="badge ${r.reply === null ? '' : 'done'}">${r.reply === null ? 'WAITING' : 'REPLIED'}</span><strong>${r.images.length} image${r.images.length === 1 ? '' : 's'}</strong><small>${new Date(r.created * 1000).toLocaleString()} · ${r.id.slice(0, 6)}</small></button>`).join('');
  document.querySelectorAll('[data-id]').forEach(button => button.onclick = () => { selected = button.dataset.id; renderDetail(); draw(); });
}
function renderDetail() {
  const r = requests.find(r => r.id === selected);
  if (!r) return;
  const draft = sessionStorage.getItem(r.id) || '';
  $('detail').innerHTML = `<div class="detail-head"><div><h2>Request ${r.id.slice(0, 8)}</h2><p>${r.images.length} image${r.images.length === 1 ? '' : 's'} · ${new Date(r.created * 1000).toLocaleString()}</p></div></div><div class="images">${r.images.map((im, i) => `<figure><a href="${im.url}" target="_blank" rel="noopener"><img src="${im.url}" alt="${escape(im.name)}"></a><figcaption><span title="${escape(im.name)}">${escape(im.name)}</span><button data-copy="${i}">Copy image</button> <a class="save" href="${im.url}" download="${escape(im.name)}">Save</a></figcaption></figure>`).join('')}</div>${r.reply === null ? `<form id="reply-form"><label for="reply">Your reply</label><textarea id="reply" required maxlength="100000" placeholder="Paste or type the text to send back…">${escape(draft)}</textarea><div class="form-bottom"><span>Sent directly to the app that uploaded these images.</span><button class="primary" type="submit">Send reply ↗</button></div></form>` : `<label>Reply sent</label><div class="reply">${escape(r.reply)}</div>`}`;
  document.querySelectorAll('[data-copy]').forEach(button => button.onclick = async () => {
    try {
      if (!navigator.clipboard?.write || !window.ClipboardItem) throw Error('Clipboard unavailable. Use Save, or open the image and copy it from there.');
      const blob = await (await fetch(r.images[Number(button.dataset.copy)].url)).blob();
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height;
      canvas.getContext('2d').drawImage(bitmap, 0, 0); bitmap.close();
      const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      await navigator.clipboard.write([new ClipboardItem({'image/png': png})]); notice('Image copied to clipboard.');
    } catch (error) { notice(error.message || 'Could not copy image. Use Save instead.'); }
  });
  if ($('reply-form')) {
    $('reply').oninput = () => sessionStorage.setItem(r.id, $('reply').value);
    $('reply-form').onsubmit = async event => {
      event.preventDefault(); const button = event.submitter; button.disabled = true;
      try {
        await api(`/api/requests/${r.id}/reply`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:$('reply').value})});
        sessionStorage.removeItem(r.id); signature = ''; await poll(); notice('Reply sent to the app.');
      } catch (error) { notice(error.message); button.disabled = false; }
    };
  }
}
async function poll() {
  if (polling) return; polling = true;
  try {
    const data = await api('/api/requests'); const next = JSON.stringify(data);
    if (next !== signature) {
      const oldSelected = requests.find(r => r.id === selected);
      requests = data; signature = next;
      if (!selected && requests.length) selected = requests.find(r => r.status === 'pending')?.id || requests[0].id;
      draw();
      if (JSON.stringify(oldSelected) !== JSON.stringify(requests.find(r => r.id === selected))) renderDetail();
    }
    $('connection').textContent = 'Connected';
  } catch { $('connection').textContent = 'Reconnecting…'; }
  finally { polling = false; }
}
poll(); setInterval(poll, 1500);
