(function () {
  'use strict';

  async function submit(e) {
    e.preventDefault();
    const email = $('forgotEmail').value.trim();
    const btn = $('forgotSubmit');
    const msg = $('forgotMsg');
    if (!email) return;

    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = 'Отправка…';
    msg.className = 'pw-reset-msg';
    msg.textContent = '';

    // No bearer token on this endpoint, so we use raw ``fetch`` rather
    // than ``apiFetch`` - but mirror its 15s abort so a stalled
    // connection doesn't leave the "Отправка…" button hanging forever.
    const ctl = new AbortController();
    const timeout = setTimeout(() => ctl.abort(), 15000);
    try {
      const r = await fetch(`${window.API}/api/password-reset/request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
        signal: ctl.signal,
      });
      if (r.ok) {
        const data = await r.json();
        msg.className = 'pw-reset-msg ok';
        msg.textContent = (data && data.message) ||
          'Если этот email зарегистрирован, мы отправили на него ссылку.';
        $('forgotEmail').value = '';
      } else if (r.status === 429) {
        msg.className = 'pw-reset-msg err';
        msg.textContent = 'Слишком много запросов. Попробуйте позже.';
      } else {
        let detail = 'Не удалось отправить запрос.';
        try {
          detail = window.formatError(await r.json(), detail);
        } catch (_) {}
        msg.className = 'pw-reset-msg err';
        msg.textContent = detail;
      }
    } catch (_) {
      msg.className = 'pw-reset-msg err';
      msg.textContent = 'Нет связи с сервером. Попробуйте позже.';
    } finally {
      clearTimeout(timeout);
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('forgotForm').addEventListener('submit', submit);
  });
})();
