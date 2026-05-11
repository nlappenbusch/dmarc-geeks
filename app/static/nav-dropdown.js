/* Marketing-Nav Dropdown: Hover (Desktop) + Click/Tap-Toggle (Touch / Tastatur).
 *
 * Verhalten:
 *  - Desktop (mouse): Hover oeffnet/schliesst per CSS, JS ist transparent.
 *  - Touch: erster Tap auf Trigger oeffnet, zweiter Tap navigiert. Tap ausserhalb schliesst.
 *  - Tastatur: Trigger ist <a> -> Enter folgt Link wie immer. Aria-Expanded fuer Reader.
 */
(function() {
  'use strict';

  function isTouch() {
    return ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
  }

  const groups = document.querySelectorAll('.mkt-nav-group');
  if (!groups.length) return;

  // Aria-Setup
  groups.forEach(g => {
    const trigger = g.querySelector('.mkt-nav-trigger');
    if (!trigger) return;
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', 'false');
  });

  // Touch: erster Tap oeffnet, zweiter Tap navigiert.
  // Wir tracken pro Trigger ob er gerade "offen via Tap" ist.
  if (isTouch()) {
    groups.forEach(g => {
      const trigger = g.querySelector('.mkt-nav-trigger');
      if (!trigger) return;
      trigger.addEventListener('click', (ev) => {
        // Falls noch nicht offen -> oeffnen + Navigation verhindern
        if (!g.classList.contains('is-open')) {
          // Alle anderen schliessen
          groups.forEach(other => {
            if (other !== g) {
              other.classList.remove('is-open');
              const ot = other.querySelector('.mkt-nav-trigger');
              if (ot) ot.setAttribute('aria-expanded', 'false');
            }
          });
          g.classList.add('is-open');
          trigger.setAttribute('aria-expanded', 'true');
          ev.preventDefault();
        }
        // sonst (schon offen): nichts tun, Browser folgt dem Link
      });
    });

    // Klick ausserhalb der Nav -> alle Dropdowns zu
    document.addEventListener('click', (ev) => {
      const inside = ev.target.closest('.mkt-nav-group');
      if (!inside) {
        groups.forEach(g => {
          g.classList.remove('is-open');
          const t = g.querySelector('.mkt-nav-trigger');
          if (t) t.setAttribute('aria-expanded', 'false');
        });
      }
    });
  }

  // Desktop-Keyboard-A11y: Escape schliesst alle offenen Dropdowns
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      groups.forEach(g => {
        g.classList.remove('is-open');
        const t = g.querySelector('.mkt-nav-trigger');
        if (t) t.setAttribute('aria-expanded', 'false');
      });
    }
  });
})();
