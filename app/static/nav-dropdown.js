/* Marketing-Nav Dropdown: Hover (Maus/Trackpad) + Click-Toggle (Touch).
 *
 * Wir nutzen Pointer-Events um zu erkennen womit der User gerade interagiert
 * (Maus oder Touch). Das vermeidet das Problem auf Hybrid-Laptops (Surface,
 * Lenovo Yoga, etc.), wo sowohl Touchscreen ALS AUCH Maus vorhanden sind und
 * das alte 'ontouchstart' immer truthy ist.
 *
 * Maus/Pen: Hover-CSS macht alles. JS ist no-op.
 * Touch:    erster Tap auf Trigger oeffnet Menu (preventDefault),
 *           zweiter Tap navigiert.
 */
(function() {
  'use strict';

  const groups = document.querySelectorAll('.mkt-nav-group');
  if (!groups.length) return;

  // Aria-Setup
  groups.forEach(g => {
    const trigger = g.querySelector('.mkt-nav-trigger');
    if (!trigger) return;
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', 'false');
  });

  // Tracke den letzten Pointer-Typ. Mausbewegung setzt auf 'mouse', Touch auf 'touch'.
  let lastPointerType = 'mouse';
  if ('PointerEvent' in window) {
    document.addEventListener('pointerdown', (ev) => {
      lastPointerType = ev.pointerType || 'mouse';
    }, true);
  }

  function closeAll() {
    groups.forEach(g => {
      g.classList.remove('is-open');
      const t = g.querySelector('.mkt-nav-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }

  function openOnly(g) {
    closeAll();
    g.classList.add('is-open');
    const t = g.querySelector('.mkt-nav-trigger');
    if (t) t.setAttribute('aria-expanded', 'true');
  }

  groups.forEach(g => {
    const trigger = g.querySelector('.mkt-nav-trigger');
    if (!trigger) return;
    trigger.addEventListener('click', (ev) => {
      // Nur bei TOUCH: erster Tap oeffnet, zweiter navigiert.
      if (lastPointerType === 'touch' || lastPointerType === 'pen') {
        if (!g.classList.contains('is-open')) {
          openOnly(g);
          ev.preventDefault();
        }
        // sonst: schon offen -> Browser folgt dem Link normal
      }
      // Bei Maus/Trackpad: nichts machen, Link folgt normal.
      // Hover-CSS hat schon dafuer gesorgt dass das Menu offen war.
    });
  });

  // Klick ausserhalb -> alle Dropdowns zu (nur fuer Touch relevant, schadet aber nicht)
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('.mkt-nav-group')) {
      closeAll();
    }
  });

  // Escape schliesst alle offenen Dropdowns
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeAll();
  });
})();
