// Keep the POST/CSRF form usable when JavaScript is unavailable.
for (const form of document.querySelectorAll('.language-switch')) {
  const selector = form.querySelector('select[name="language"]');
  if (selector) {
    selector.addEventListener('change', () => {
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  }
}
