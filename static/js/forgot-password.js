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

    try {
      const r = await fetch(`${window.API}/api/password-reset/request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
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
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('forgotForm').addEventListener('submit', submit);
  });
})();
