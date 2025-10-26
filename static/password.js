(function() {
  const checkUrl = window.PASSWORD_CHECK_URL;
  const new1 = document.getElementById('new_password1');
  const new2 = document.getElementById('new_password2');
  const bar = document.getElementById('pw-strength-bar');
  const label = document.getElementById('pw-strength-label');
  const errorsEl = document.getElementById('pw-errors');
  const submit = document.getElementById('submit-btn');

  // Toggle show/hide
  document.querySelectorAll('[data-toggle-password]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-toggle-password');
      const input = document.getElementById(id);
      if (!input) return;
      const isPw = input.getAttribute('type') === 'password';
      input.setAttribute('type', isPw ? 'text' : 'password');
      btn.textContent = isPw ? (window.I18N?.hide || 'Hide') : (window.I18N?.show || 'Show');
    });
  });

  if (!checkUrl || !new1 || !bar || !label) return;

  let timer = null;
  const debounce = (fn, wait=300) => {
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  };

  const setBar = (score, strength) => {
    const pct = Math.max(0, Math.min(100, score));
    bar.style.width = pct + '%';
    // ranglarni tailwind orqali inline class o'rniga style bilan hal qilamiz
    let bg = '#e5e7eb'; // gray-200
    if (strength === 'weak') bg = '#ef4444';      // red-500
    else if (strength === 'medium') bg = '#f59e0b'; // amber-500
    else if (strength === 'strong') bg = '#10b981'; // emerald-500
    bar.style.backgroundColor = bg;

    const t = window.I18N || {};
    label.textContent = strength === 'weak' ? (t.weak || 'Weak')
                     : strength === 'medium' ? (t.medium || 'Medium')
                     : strength === 'strong' ? (t.strong || 'Strong')
                     : '-';
  };

  const setErrors = (errors=[]) => {
    if (!errorsEl) return;
    if (!errors.length) {
      errorsEl.classList.add('hidden');
      errorsEl.innerHTML = '';
      return;
    }
    errorsEl.classList.remove('hidden');
    errorsEl.innerHTML = errors.map(e => `<li>${e}</li>`).join('');
  };

  const syncSubmitDisabled = () => {
    // Yangi parol mosligi + kuch minimal prag (>=40)
    const okMatch = new1.value && new2 && new1.value === new2.value;
    const pct = parseInt(bar.style.width || '0', 10) || 0;
    submit && (submit.disabled = !(okMatch && pct >= 40));
  };

  const callCheck = async () => {
    const pw = new1.value || '';
    if (!pw) {
      setBar(0, 'weak');
      setErrors([]);
      syncSubmitDisabled();
      return;
    }
    try {
      const url = new URL(checkUrl, window.location.origin);
      url.searchParams.set('password', pw);
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('bad response');
      const data = await res.json();
      setBar(data.score || 0, data.strength || 'weak');
      setErrors(data.errors || []);
    } catch(e) {
      // sokin yutib yuboramiz
    } finally {
      syncSubmitDisabled();
    }
  };

  const onInput = debounce(callCheck, 250);
  new1.addEventListener('input', onInput);
  if (new2) new2.addEventListener('input', syncSubmitDisabled);

  // initial
  callCheck();
})();
