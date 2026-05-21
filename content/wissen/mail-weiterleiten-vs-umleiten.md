---
title: Weiterleiten oder umleiten? Was mit deiner Mail wirklich passiert (für Menschen erklärt)
slug: mail-weiterleiten-vs-umleiten
description: Der Unterschied zwischen Forward und Redirect — mit Briefträger-Analogie, animierter Mail-Reise und Bastelkasten zum Selber-Ausprobieren. Plus die 5 Heimtücken, an denen Helpdesks regelmässig verzweifeln.
date: 2026-05-21
author: Nils Lappenbusch
tags: [forwarding, redirect, spf, dkim, dmarc, support-wissen, basics]
---

<style>
/* ========== Custom styles ========== */
.demo-card {
  background: var(--card, #f8fafc);
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 14px;
  padding: 22px 24px;
  margin: 28px 0;
}
.demo-card h4 {
  margin: 0 0 14px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted, #64748b);
  font-weight: 700;
}

/* Story-Card */
.story {
  background: linear-gradient(135deg, rgba(37,99,235,.05), rgba(124,58,237,.05));
  border: 1px solid rgba(37,99,235,.2);
  border-radius: 14px;
  padding: 20px 24px;
  margin: 24px 0;
  font-size: 16px;
  line-height: 1.7;
}
.story strong { color: var(--brand, #2563eb); }

/* Briefumschlag SVG-style */
.envelope-visual {
  display: flex; gap: 16px; align-items: stretch; flex-wrap: wrap;
  margin: 16px 0;
}
.envelope-half {
  flex: 1; min-width: 240px;
  background: white;
  border: 2px dashed var(--border, #e2e8f0);
  border-radius: 10px;
  padding: 14px 18px;
  font-family: "JetBrains Mono", monospace;
  font-size: 12.5px;
  line-height: 1.7;
}
.envelope-half.outer { border-color: #f59e0b; background: #fffbeb; }
.envelope-half.inner { border-color: #2563eb; background: #eff6ff; }
.envelope-half h5 {
  font-family: inherit;
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text, #0f172a);
}
.envelope-half .who-sees {
  font-family: inherit;
  font-size: 11px;
  color: var(--muted, #64748b);
  margin-bottom: 8px;
  font-style: italic;
}

/* Animierte Mail-Reise */
.trip-stage {
  background: white;
  border-radius: 12px;
  padding: 20px;
  margin: 12px 0;
}
.trip-controls {
  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
  margin-bottom: 16px;
}
.btn-play {
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: white; border: 0; padding: 10px 18px; border-radius: 999px;
  font-weight: 700; cursor: pointer; font-family: inherit; font-size: 14px;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn-play:hover { transform: translateY(-1px); }
.btn-mode {
  background: white; border: 1.5px solid var(--border, #e2e8f0);
  padding: 8px 14px; border-radius: 999px; cursor: pointer;
  font-family: inherit; font-size: 13px; font-weight: 600;
  color: var(--muted, #64748b);
}
.btn-mode.active {
  border-color: var(--brand, #2563eb);
  background: rgba(37,99,235,.08);
  color: var(--brand, #2563eb);
}
.btn-reset {
  background: transparent; border: 0; color: var(--muted, #64748b);
  font-family: inherit; font-size: 12px; cursor: pointer; text-decoration: underline;
  margin-left: auto;
}

.trip-track {
  display: grid;
  grid-template-columns: 1fr 30px 1fr 30px 1fr;
  gap: 8px;
  align-items: center;
  margin: 20px 0;
  min-height: 120px;
  position: relative;
}
@media (max-width: 640px) {
  .trip-track { grid-template-columns: 1fr; gap: 16px; }
  .trip-track .arrow { display: none; }
}
.trip-node {
  background: #f8fafc;
  border: 2px solid var(--border, #e2e8f0);
  border-radius: 12px;
  padding: 14px 12px;
  text-align: center;
  font-size: 13px;
  transition: all .3s ease;
  position: relative;
}
.trip-node.active {
  border-color: var(--brand, #2563eb);
  background: rgba(37,99,235,.06);
  box-shadow: 0 0 0 4px rgba(37,99,235,.1);
}
.trip-node.done { border-color: #10b981; background: #ecfdf5; }
.trip-node .icon { font-size: 28px; margin-bottom: 4px; }
.trip-node strong { display: block; font-size: 14px; color: var(--text, #0f172a); margin-bottom: 2px; }
.trip-node small { display: block; color: var(--muted, #64748b); font-size: 11.5px; line-height: 1.4; }
.trip-track .arrow {
  text-align: center; font-size: 24px; color: var(--brand, #2563eb);
  font-weight: 700; opacity: 0.4; transition: opacity .3s;
}
.trip-track .arrow.active { opacity: 1; animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.2); } }

/* "Mail fliegt" Animation */
.flying-mail {
  position: absolute;
  font-size: 26px;
  transition: left 1.5s cubic-bezier(0.4, 0, 0.2, 1), top 1.5s, opacity .3s;
  pointer-events: none;
  z-index: 5;
}

/* Status panel */
.trip-status {
  background: #f8fafc;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  padding: 14px 18px;
  margin-top: 16px;
  font-size: 14px;
  line-height: 1.6;
  min-height: 70px;
  transition: background .3s;
}
.trip-status.success { background: #ecfdf5; border-color: #10b981; }
.trip-status.fail { background: #fef2f2; border-color: #ef4444; }
.trip-status.warn { background: #fffbeb; border-color: #f59e0b; }
.trip-status .step-num {
  display: inline-block; background: var(--brand, #2563eb); color: white;
  width: 24px; height: 24px; border-radius: 50%; text-align: center;
  font-size: 12px; line-height: 24px; font-weight: 700; margin-right: 8px;
}

/* Checks */
.checks {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  margin: 14px 0 4px;
}
@media (max-width: 540px) { .checks { grid-template-columns: 1fr; } }
.check {
  background: white;
  border: 1.5px solid var(--border, #e2e8f0);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
  transition: all .3s;
}
.check.pending { opacity: 0.5; }
.check.pass { border-color: #10b981; background: #ecfdf5; }
.check.fail { border-color: #ef4444; background: #fef2f2; }
.check.warn { border-color: #f59e0b; background: #fffbeb; }
.check .check-head {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 700; margin-bottom: 4px;
}
.check .badge {
  font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 700;
  background: #e2e8f0; color: #64748b;
}
.check.pass .badge { background: #10b981; color: white; }
.check.fail .badge { background: #ef4444; color: white; }
.check.warn .badge { background: #f59e0b; color: white; }
.check .what { font-size: 12.5px; color: var(--muted, #64748b); line-height: 1.5; }

/* Setup-Bastelkasten */
.builder {
  background: white;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 12px;
  padding: 16px 18px;
  margin: 14px 0;
}
.builder label {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin: 4px 0;
  transition: background .15s;
  border: 1px solid transparent;
}
.builder label:hover { background: #f8fafc; }
.builder label.checked { background: rgba(37,99,235,.06); border-color: rgba(37,99,235,.25); }
.builder input[type=checkbox] {
  margin-top: 3px; width: 18px; height: 18px; cursor: pointer;
  accent-color: var(--brand, #2563eb);
}
.builder .opt-title { font-weight: 600; font-size: 14px; }
.builder .opt-sub { display: block; font-size: 12.5px; color: var(--muted, #64748b); margin-top: 2px; line-height: 1.5; }

.verdict {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
}
.verdict.good { background: #d1fae5; color: #065f46; border-left: 4px solid #10b981; }
.verdict.bad { background: #fee2e2; color: #991b1b; border-left: 4px solid #ef4444; }
.verdict.meh { background: #fef3c7; color: #92400e; border-left: 4px solid #f59e0b; }
.verdict strong { font-size: 15px; }

/* Heimtücken */
.pitfall {
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  margin: 10px 0;
  background: white;
  overflow: hidden;
}
.pitfall summary {
  padding: 14px 18px;
  cursor: pointer;
  font-weight: 600;
  font-size: 15px;
  list-style: none;
  display: flex; justify-content: space-between; align-items: center;
  gap: 10px;
}
.pitfall summary::-webkit-details-marker { display: none; }
.pitfall summary::after { content: "+"; font-size: 22px; color: var(--brand, #2563eb); font-weight: 400; transition: transform .2s; }
.pitfall[open] summary::after { transform: rotate(45deg); }
.pitfall summary:hover { background: var(--card, #f8fafc); }
.pitfall .body { padding: 0 18px 16px; color: var(--text, #0f172a); font-size: 14.5px; line-height: 1.7; }
.pitfall .dau {
  background: linear-gradient(135deg, rgba(37,99,235,.06), rgba(124,58,237,.06));
  padding: 10px 14px; border-radius: 8px; margin: 0 0 14px;
  font-size: 14px; line-height: 1.6;
}
.pitfall .severity {
  font-size: 10px; padding: 2px 8px; border-radius: 999px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .03em;
}
.pitfall .severity.high { background: #fee2e2; color: #991b1b; }
.pitfall .severity.med { background: #fef3c7; color: #92400e; }
.pitfall .severity.low { background: #dbeafe; color: #1e40af; }

/* Quiz */
.quiz {
  background: white;
  border: 1.5px solid var(--border, #e2e8f0);
  border-radius: 12px;
  padding: 18px 20px;
  margin: 14px 0;
}
.quiz .scenario {
  background: #f8fafc; border-left: 3px solid var(--brand, #2563eb);
  padding: 12px 14px; border-radius: 0 8px 8px 0;
  font-size: 14px; line-height: 1.6; margin-bottom: 14px;
}
.quiz .options { display: grid; gap: 8px; }
.quiz .options button {
  text-align: left; padding: 10px 14px;
  background: white; border: 1.5px solid var(--border, #e2e8f0);
  border-radius: 8px; cursor: pointer; font-family: inherit; font-size: 14px;
  transition: all .15s;
}
.quiz .options button:hover { border-color: var(--brand, #2563eb); background: rgba(37,99,235,.04); }
.quiz .options button.right { border-color: #10b981; background: #ecfdf5; color: #065f46; font-weight: 600; }
.quiz .options button.wrong { border-color: #ef4444; background: #fef2f2; color: #991b1b; }
.quiz .options button:disabled { cursor: default; }
.quiz .explain {
  margin-top: 12px; padding: 12px 14px; border-radius: 8px;
  font-size: 13.5px; line-height: 1.6;
  display: none;
}
.quiz .explain.show { display: block; }

abbr[title] { text-decoration: underline dotted; cursor: help; text-decoration-color: var(--brand, #2563eb); }

/* Glossar-Card */
.glossar {
  display: grid; gap: 10px; margin: 14px 0;
}
.glossar .term {
  background: white; border: 1px solid var(--border, #e2e8f0); border-radius: 8px;
  padding: 10px 14px;
}
.glossar .term b { color: var(--brand, #2563eb); font-size: 14px; }
.glossar .term .ex { font-size: 13px; color: var(--muted, #64748b); line-height: 1.5; margin-top: 3px; }
</style>

## In einem Satz

**Weiterleiten** macht aus deiner Mail eine *neue* Mail (mit dir als Absender). **Umleiten** schickt die *gleiche* Mail einfach an eine andere Adresse durch (Original-Absender bleibt). Und genau dieser kleine Unterschied entscheidet, ob Mails ankommen oder im Nirvana verschwinden.

## Eine kleine Geschichte zum Start

<div class="story">
<p style="margin:0 0 10px"><strong>Stell dir vor:</strong> Alice schickt Bob einen Brief. Bob ist gerade im Urlaub und will, dass die Post zu ihm nach Hause kommt.</p>

<p style="margin:0 0 10px"><strong>Möglichkeit 1 — Bob leitet weiter:</strong> Bob holt den Brief aus dem Briefkasten, packt ihn in einen <em>neuen</em> Umschlag, schreibt seinen Namen oben drauf ("von: Bob") und seine Heimadresse als Absender, und schickt das ab. Beim Empfänger steht jetzt <em>Bob</em> als Absender, nicht Alice.</p>

<p style="margin:0 0 10px"><strong>Möglichkeit 2 — Bob leitet um:</strong> Bob nimmt den <em>gleichen</em> Brief (mit Alice's Absender vorne drauf), streicht seine Adresse durch, schreibt seine Heimadresse drüber und wirft den Brief so wieder ein. Der Postbote schaut: "Absender Alice, neuer Empfänger." Beim Empfänger steht immer noch <em>Alice</em> als Absender.</p>

<p style="margin:0"><strong>Die Post (= dein Mailserver) macht in beiden Fällen unterschiedliche Sicherheits-Checks. Und das ist, wo's spannend wird.</strong></p>
</div>

## Bevor wir reingehen: jede Mail hat ZWEI Absender

Das verwirrt am Anfang, ist aber das wichtigste Konzept hier.

<div class="demo-card">
<h4>📨 Eine Mail = Briefumschlag + Brief</h4>

<div class="envelope-visual">
  <div class="envelope-half outer">
    <h5>🟡 Aussen: der Briefumschlag</h5>
    <div class="who-sees">Sieht nur der Briefträger (Mailserver). Du als Empfänger siehst das nie.</div>
    <div><b>Absender:</b> alice@firma-a.ch</div>
    <div><b>Empfänger:</b> bob@firma-b.ch</div>
  </div>

  <div class="envelope-half inner">
    <h5>🔵 Drinnen: der Brief selbst</h5>
    <div class="who-sees">Das siehst du in Outlook / Gmail.</div>
    <div><b>Von:</b> Alice Schmid &lt;alice@firma-a.ch&gt;</div>
    <div><b>An:</b> bob@firma-b.ch</div>
    <div><b>Betreff:</b> Rechnung März</div>
    <div style="margin-top:4px;color:#64748b">Hi Bob, anbei die Rechnung. ...</div>
  </div>
</div>

<p style="margin:14px 0 0; font-size:14px; color:var(--muted,#64748b);">
Im Alltag steht in beiden dasselbe — Alice ist sowohl außen als auch innen der Absender. <em>Wenn beide auseinanderlaufen</em>, fängt das DMARC-Drama an.
</p>
</div>

## Die drei Wächter: SPF, DKIM, DMARC

Jede Mail wird beim Empfänger (Gmail, Microsoft 365, …) durch drei Sicherheits-Schleusen geschickt. Stell sie dir wie drei Türsteher vor:

<div class="glossar">
  <div class="term">
    <b>🛡️ SPF — der Türsteher mit der Gästeliste</b>
    <div class="ex">Schaut auf den <em>Briefumschlag</em>. Prüft: "Darf dieser Mailserver überhaupt im Namen dieser Firma Briefe verschicken?" Wenn nein → SPF-Fail.</div>
  </div>
  <div class="term">
    <b>🔏 DKIM — der Türsteher mit der Lupe</b>
    <div class="ex">Schaut auf den <em>Brief selbst</em>. Prüft: "Ist der Brief unterwegs verändert worden?" Beim Versenden wird ein kryptografisches Siegel draufgepappt — wenn jemand was ändert, ist das Siegel kaputt.</div>
  </div>
  <div class="term">
    <b>🏛️ DMARC — der Chef-Türsteher</b>
    <div class="ex">Schaut, ob <em>Briefumschlag und Brief zusammenpassen</em> (gleiche Firma außen wie innen) — und ob mindestens einer der beiden Vor-Türsteher (SPF oder DKIM) ein "OK" gegeben hat.</div>
  </div>
</div>

**Merksatz für Helpdesk:** SPF schaut auf den Umschlag, DKIM schaut in den Brief, DMARC schaut auf beides zusammen.

## Die Mail-Reise: drück auf Play und schau zu

<div class="demo-card">
<h4>🎬 Was passiert Schritt für Schritt</h4>

<div class="trip-stage">
  <div class="trip-controls">
    <button class="btn-play" onclick="playTrip()" id="playBtn">▶ Play</button>
    <button class="btn-mode active" onclick="setTripMode('fwd')" id="modeFwd">Weiterleiten</button>
    <button class="btn-mode" onclick="setTripMode('red')" id="modeRed">Umleiten</button>
    <button class="btn-reset" onclick="resetTrip()">↺ Zurücksetzen</button>
  </div>

  <div class="trip-track" id="tripTrack">
    <div class="trip-node" id="node1">
      <div class="icon">👩‍💼</div>
      <strong>Alice</strong>
      <small>alice@firma-a.ch<br>schreibt an Bob</small>
    </div>
    <div class="arrow" id="arrow1">→</div>
    <div class="trip-node" id="node2">
      <div class="icon">📬</div>
      <strong>Bob</strong>
      <small>bob@firma-b.ch<br><span id="bobAction">leitet weiter</span></small>
    </div>
    <div class="arrow" id="arrow2">→</div>
    <div class="trip-node" id="node3">
      <div class="icon">📥</div>
      <strong>Gmail</strong>
      <small>privat@gmail.com<br>prüft alles</small>
    </div>
    <div class="flying-mail" id="flyingMail" style="opacity:0">✉️</div>
  </div>

  <div class="trip-status" id="tripStatus">
    Drück <strong>▶ Play</strong> um zu sehen wie eine Mail durchwandert. Wechsle oben zwischen <em>Weiterleiten</em> und <em>Umleiten</em> um den Unterschied zu sehen.
  </div>

  <div class="checks" id="checks">
    <div class="check pending" id="checkSpf">
      <div class="check-head">🛡️ SPF <span class="badge" id="spfBadge">wartet</span></div>
      <div class="what" id="spfWhat">Gästeliste-Check</div>
    </div>
    <div class="check pending" id="checkDkim">
      <div class="check-head">🔏 DKIM <span class="badge" id="dkimBadge">wartet</span></div>
      <div class="what" id="dkimWhat">Siegel-Check</div>
    </div>
    <div class="check pending" id="checkDmarc">
      <div class="check-head">🏛️ DMARC <span class="badge" id="dmarcBadge">wartet</span></div>
      <div class="what" id="dmarcWhat">Chef-Entscheidung</div>
    </div>
  </div>
</div>
</div>

<script>
let tripMode = 'fwd';
let tripRunning = false;

function setTripMode(mode) {
  if (tripRunning) return;
  tripMode = mode;
  document.getElementById('modeFwd').classList.toggle('active', mode === 'fwd');
  document.getElementById('modeRed').classList.toggle('active', mode === 'red');
  document.getElementById('bobAction').textContent = mode === 'fwd' ? 'leitet weiter' : 'leitet um';
  resetTrip();
}

function resetTrip() {
  ['node1','node2','node3'].forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove('active', 'done');
  });
  ['arrow1','arrow2'].forEach(id => document.getElementById(id).classList.remove('active'));
  ['checkSpf','checkDkim','checkDmarc'].forEach(id => {
    const el = document.getElementById(id);
    el.className = 'check pending';
  });
  document.getElementById('spfBadge').textContent = 'wartet';
  document.getElementById('dkimBadge').textContent = 'wartet';
  document.getElementById('dmarcBadge').textContent = 'wartet';
  document.getElementById('spfWhat').textContent = 'Gästeliste-Check';
  document.getElementById('dkimWhat').textContent = 'Siegel-Check';
  document.getElementById('dmarcWhat').textContent = 'Chef-Entscheidung';
  const status = document.getElementById('tripStatus');
  status.className = 'trip-status';
  status.innerHTML = 'Drück <strong>▶ Play</strong> um zu sehen wie eine Mail durchwandert. Wechsle oben zwischen <em>Weiterleiten</em> und <em>Umleiten</em> um den Unterschied zu sehen.';
  document.getElementById('flyingMail').style.opacity = '0';
}

function setStatus(html, type) {
  const s = document.getElementById('tripStatus');
  s.className = 'trip-status ' + (type || '');
  s.innerHTML = html;
}

function setCheck(which, status, what) {
  const el = document.getElementById('check' + which);
  el.className = 'check ' + status;
  const badge = document.getElementById(which.toLowerCase() + 'Badge');
  badge.textContent = status === 'pass' ? '✓ PASS' : status === 'fail' ? '✗ FAIL' : status === 'warn' ? '! WARN' : 'wartet';
  document.getElementById(which.toLowerCase() + 'What').textContent = what;
}

function flyMail(fromNodeId, toNodeId, duration) {
  return new Promise((resolve) => {
    const from = document.getElementById(fromNodeId);
    const to = document.getElementById(toNodeId);
    const track = document.getElementById('tripTrack');
    const trackRect = track.getBoundingClientRect();
    const fromRect = from.getBoundingClientRect();
    const toRect = to.getBoundingClientRect();
    const mail = document.getElementById('flyingMail');

    const startX = fromRect.left - trackRect.left + fromRect.width/2 - 13;
    const startY = fromRect.top - trackRect.top + fromRect.height/2 - 13;
    const endX = toRect.left - trackRect.left + toRect.width/2 - 13;
    const endY = toRect.top - trackRect.top + toRect.height/2 - 13;

    mail.style.transition = 'none';
    mail.style.left = startX + 'px';
    mail.style.top = startY + 'px';
    mail.style.opacity = '1';

    requestAnimationFrame(() => {
      mail.style.transition = `left ${duration}ms cubic-bezier(0.4, 0, 0.2, 1), top ${duration}ms`;
      mail.style.left = endX + 'px';
      mail.style.top = endY + 'px';
      setTimeout(resolve, duration);
    });
  });
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function playTrip() {
  if (tripRunning) return;
  tripRunning = true;
  resetTrip();
  document.getElementById('playBtn').disabled = true;

  // Step 1: Alice
  document.getElementById('node1').classList.add('active');
  setStatus('<span class="step-num">1</span><strong>Alice schreibt</strong> eine Mail an Bob. Ihr Mailserver pappt ein DKIM-Siegel drauf.');
  await sleep(1400);
  document.getElementById('arrow1').classList.add('active');
  await flyMail('node1', 'node2', 1400);

  // Step 2: Bob empfängt
  document.getElementById('node1').classList.remove('active');
  document.getElementById('node1').classList.add('done');
  document.getElementById('arrow1').classList.remove('active');
  document.getElementById('node2').classList.add('active');
  setStatus('<span class="step-num">2</span><strong>Bei Bob angekommen.</strong> Alles ok. Aber Bob hat eine Regel: alles soll auf sein privates Gmail gehen.');
  await sleep(1600);

  // Step 3: Bob agiert
  if (tripMode === 'fwd') {
    setStatus('<span class="step-num">3</span><strong>Bob leitet weiter:</strong> Sein Mailserver erstellt eine <em>neue</em> Mail — Absender ist jetzt <code>bob@firma-b.ch</code>. Subject kriegt "Fwd:" davor. Body wird umgepackt.');
  } else {
    setStatus('<span class="step-num">3</span><strong>Bob leitet um:</strong> Sein Mailserver nimmt die <em>gleiche</em> Mail, ändert nur die Empfänger-Adresse auf <code>privat@gmail.com</code> — Absender bleibt Alice.');
  }
  await sleep(2200);
  document.getElementById('arrow2').classList.add('active');
  await flyMail('node2', 'node3', 1400);

  // Step 4: Gmail prüft
  document.getElementById('node2').classList.remove('active');
  document.getElementById('node2').classList.add('done');
  document.getElementById('arrow2').classList.remove('active');
  document.getElementById('node3').classList.add('active');
  setStatus('<span class="step-num">4</span><strong>Gmail empfängt die Mail</strong> und ruft die drei Türsteher rein …');
  await sleep(1400);

  // Step 5: Türsteher arbeiten
  if (tripMode === 'fwd') {
    setCheck('Spf', 'pass', 'firma-b.ch sendet im eigenen Namen — Server ist auf der Gästeliste von firma-b.ch. ✓');
    await sleep(900);
    setCheck('Dkim', 'pass', 'Falls firma-b.ch signiert hat: Siegel passt zur eigenen neuen Mail. ✓');
    await sleep(900);
    setCheck('Dmarc', 'pass', 'Außen = Bob, Innen = Bob, SPF passt → DMARC sagt OK. ✓');
    await sleep(600);
    setStatus('<span class="step-num">✓</span><strong>Mail ist da.</strong> Gmail zeigt aber <em>Bob</em> als Absender — wenn das private Gmail antwortet, geht\'s an Bob, nicht an Alice. <em>Das ist der Preis für\'s saubere Forwarding.</em>', 'success');
  } else {
    setCheck('Spf', 'fail', 'Gmail fragt: darf firma-b.ch im Namen von firma-a.ch senden? Nein. Server steht nicht auf Alice\'s Gästeliste. ✗');
    await sleep(900);
    setCheck('Dkim', 'pass', 'Brief wurde nicht angefasst → Alice\'s Siegel ist noch heil. ✓');
    await sleep(900);
    setCheck('Dmarc', 'pass', 'DMARC braucht nur EINEN Pass. DKIM passt → noch mal Glück gehabt. ✓');
    await sleep(600);
    setStatus('<span class="step-num">✓</span><strong>Knapp gerettet durch DKIM.</strong> Wenn Bob\'s Mailserver einen Footer "weitergeleitet von Bob" eingefügt hätte → DKIM kaputt → DMARC kaputt → Mail fliegt im schlimmsten Fall raus, ohne dass Alice das je erfährt.', 'warn');
  }
  document.getElementById('node3').classList.remove('active');
  document.getElementById('node3').classList.add('done');

  document.getElementById('playBtn').disabled = false;
  tripRunning = false;
}
</script>

### Übersetzung in Mensch

**Weiterleiten:** Bob schreibt einen *neuen* Brief, schreibt sich selbst oben drauf, packt Alice's Brief als Anhang rein und schickt los. Aus Sicht der Post bist du jetzt Bob — alle Sicherheits-Checks passen, aber bei Antworten antwortet Gmail an Bob, nicht an Alice.

**Umleiten:** Bob streicht nur die Adresse durch und schreibt eine neue drüber. Absender bleibt Alice. *Aus Sicht des Empfängers ist das die Mail, die er eigentlich wollte* — aber die Post wird misstrauisch: "Moment, das ist Alice's Brief, aber er kommt aus Bob's Briefkasten?" → SPF-Fail.

> **In Outlook / Exchange heisst das wörtlich:** "Weiterleiten" = Forward (neue Mail), "Umleiten" = Redirect (gleiche Mail neu adressiert). In Outlook-Regeln stehen beide nebeneinander — und tun komplett verschiedene Dinge. Bei Gmail gibt es nur "Forward", das technisch oft eher einem Redirect entspricht.

## Bastelkasten: bau dein eigenes Setup zusammen

Hier kannst du Häkchen setzen und siehst sofort, was passieren würde. Real-Life-Szenarien aus dem Helpdesk-Alltag.

<div class="demo-card">
<h4>🔧 Was hast du gerade live? Häkchen setzen, Status ablesen.</h4>

<div class="builder" id="builder">
  <label id="optMode"><input type="checkbox" id="opt_redirect"><span><span class="opt-title">Es wird umgeleitet (statt weitergeleitet)</span><span class="opt-sub">"Umleiten" in Outlook-Regel, ".forward"-Datei, cPanel-Forwarder, M365-Mailbox-Forwarding, Catch-all</span></span></label>

  <label><input type="checkbox" id="opt_footer"><span><span class="opt-title">Mein Mailserver hängt einen Disclaimer/Footer an</span><span class="opt-sub">"Vertraulich. Falls Sie nicht der Empfänger sind…" / "[EXTERN]"-Tag im Subject / Anti-Spam-Stamp</span></span></label>

  <label><input type="checkbox" id="opt_listserv"><span><span class="opt-title">Es geht über eine Mailing-Liste</span><span class="opt-sub">Mailman, Google Groups, GroupWise — Subject kriegt [Liste]-Präfix, List-Unsubscribe-Footer wird angehängt</span></span></label>

  <label><input type="checkbox" id="opt_srs"><span><span class="opt-title">SRS ist aktiv auf meinem Mailserver</span><span class="opt-sub">Schreibt den Absender auf dem Umschlag um, damit SPF wieder passt. Exchange Online kann das, on-prem oft nicht.</span></span></label>

  <label><input type="checkbox" id="opt_arc"><span><span class="opt-title">Mein Mailserver signiert mit ARC</span><span class="opt-sub">Sagt dem Empfänger: "Vertrau mir, ich habe die Mail vorher geprüft, sie war legit." Gmail/M365 akzeptieren das von vertrauenswürdigen Quellen.</span></span></label>

  <label><input type="checkbox" id="opt_strict"><span><span class="opt-title">Der Original-Absender hat <code>p=reject</code></span><span class="opt-sub">Harte DMARC-Policy. Bei FAIL wird die Mail vom Empfänger einfach abgelehnt — ohne Spam-Ordner, ohne Warnung.</span></span></label>
</div>

<div class="verdict" id="verdict">
  Klick ein paar Häkchen oben — ich sag dir was passiert.
</div>
</div>

<script>
function updateBuilder() {
  const r = document.getElementById('opt_redirect').checked;
  const f = document.getElementById('opt_footer').checked;
  const l = document.getElementById('opt_listserv').checked;
  const srs = document.getElementById('opt_srs').checked;
  const arc = document.getElementById('opt_arc').checked;
  const strict = document.getElementById('opt_strict').checked;

  // Visuelles Feedback an Labels
  document.querySelectorAll('#builder label').forEach(lbl => {
    const cb = lbl.querySelector('input');
    lbl.classList.toggle('checked', cb && cb.checked);
  });

  const verdict = document.getElementById('verdict');

  if (!r && !f && !l) {
    verdict.className = 'verdict good';
    verdict.innerHTML = '<strong>✅ Direkter Versand, kein Forward.</strong> Hier gibt\'s nichts zu fürchten. SPF, DKIM, DMARC laufen sauber durch.';
    return;
  }

  // Berechnen
  // Forward (kein Redirect, kein Listserv): macht eine neue Mail, Header-From = du → alles ok
  if (!r && !l) {
    verdict.className = 'verdict good';
    verdict.innerHTML = '<strong>✅ Klassisches Weiterleiten (Forward).</strong> Mail kommt sauber an, aber unter <em>deinem</em> Namen — Antworten gehen an dich, nicht an den Original-Absender. Footer macht nichts, weil sowieso neue Mail.';
    return;
  }

  // Redirect/Listserv
  const dkimBricht = f || l; // Footer oder Liste → Inhalt geändert → DKIM kaputt
  const spfOk = srs; // Nur SRS rettet SPF
  const dmarcOk = spfOk || !dkimBricht || arc; // Eines muss passen, oder ARC rettet

  if (dmarcOk && !dkimBricht && spfOk) {
    verdict.className = 'verdict good';
    verdict.innerHTML = '<strong>✅ Bestcase: SRS rettet SPF, keine Inhalts-Änderung → DKIM bleibt.</strong> Das ist das, was ein moderner Mailserver tun sollte.';
  } else if (dmarcOk && !dkimBricht && !spfOk) {
    verdict.className = 'verdict meh';
    verdict.innerHTML = '<strong>⚠️ Hängt am DKIM-Strohhalm.</strong> SPF bricht, aber das DKIM-Siegel des Original-Absenders rettet die Mail. Solange unterwegs nichts am Inhalt geändert wird, bleibt das stabil. <em>Heimtückisch:</em> jeder Anti-Virus-Scanner, der den Body neu verpackt, kann das brechen.';
  } else if (dmarcOk && arc) {
    verdict.className = 'verdict meh';
    verdict.innerHTML = '<strong>⚠️ ARC rettet den Tag.</strong> SPF und DKIM beide kaputt, aber dein Mailserver signiert mit ARC und der Empfänger vertraut dir. Funktioniert mit Gmail ↔ M365 gut, mit kleinen Mailservern unzuverlässig.';
  } else if (!dmarcOk && strict) {
    verdict.className = 'verdict bad';
    verdict.innerHTML = '<strong>🚨 Mail verschwindet.</strong> SPF: kaputt. DKIM: kaputt (' + (l ? 'Mailing-Liste hat Footer angehängt' : 'dein Server hat Footer angehängt') + '). Original-Absender hat <code>p=reject</code> → Gmail/M365 werfen die Mail weg. <em>Ohne Bounce zum Endempfänger.</em> Der Endkunde merkt es nie, der Original-Absender denkt es kam an.';
  } else if (!dmarcOk && !strict) {
    verdict.className = 'verdict meh';
    verdict.innerHTML = '<strong>⚠️ Mail landet im Spam-Ordner.</strong> SPF und DKIM beide kaputt, aber Original-Absender hat (noch) keinen <code>p=reject</code> — wahrscheinlich <code>p=none</code> oder <code>p=quarantine</code>. Spam-Ordner ist das wahrscheinliche Ziel.';
  } else {
    verdict.className = 'verdict good';
    verdict.innerHTML = '<strong>✅ Geht durch.</strong> Mindestens eine Prüfung passt.';
  }
}

document.querySelectorAll('#builder input[type=checkbox]').forEach(cb => {
  cb.addEventListener('change', updateBuilder);
});
updateBuilder();
</script>

## Die 5 Heimtücken, an denen Helpdesks verzweifeln

Jede mit einem **"in einem Satz für DAUs"** Vorspann.

<details class="pitfall">
<summary><span>1. Outlook leitet auf Gmail um, Mails verschwinden <span class="severity high">Hoch</span></span></summary>
<div class="body">
<div class="dau">💡 <strong>In einem Satz:</strong> Wenn du in Outlook eine Regel hast "alle Mails an mein Gmail umleiten", verlierst du irgendwann Mails — und kriegst <em>nicht mit, dass du sie verloren hast.</em></div>

<p><strong>Was technisch läuft:</strong> Outlook-Regel "an Gmail umleiten" (= Redirect). Manche Kunden senden aus Domains mit harter <code>p=reject</code> DMARC-Policy. Deren SPF erlaubt nur den eigenen Mailserver, nicht den der Firma. Outlook leitet weiter — Envelope-From bleibt der Original-Absender — SPF crasht — aber DKIM hält die Mail noch zusammen.</p>

<p><strong>Bis irgendeine Mail kommt, die kein DKIM hat</strong> (passiert noch bei vielen kleinen Firmen). Dann bricht auch das. Gmail rejected. Die Mail kommt nicht an. <em>Es gibt keine Fehlermeldung beim Endempfänger</em>, weil der Bounce zum Original-Absender geht — und der wusste ja nicht, dass die Mail eigentlich an Gmail sollte.</p>

<p><strong>Helpdesk-Trick:</strong> Frag nicht "kommt sie nicht an?", frag <em>"kommen alle nicht an oder nur manche?"</em> — "nur manche" zeigt dir den DKIM/SPF-Forward-Bug.</p>
</div>
</details>

<details class="pitfall">
<summary><span>2. Mailing-Listen brechen DMARC seit 2014 systematisch <span class="severity high">Hoch</span></span></summary>
<div class="body">
<div class="dau">💡 <strong>In einem Satz:</strong> Wenn du auf einer Mailing-Liste antwortest und dein Mail-Provider hat strenge DMARC, kickt die Liste dich raus — weil deine eigenen Mails als "Fälschung" gelten.</div>

<p><strong>Was technisch läuft:</strong> Die Mailing-Liste (Mailman, Google Groups, GroupWise) macht das hier mit deiner Mail:</p>
<ul>
<li>Setzt <code>[Liste-Name]</code> vor das Subject → DKIM kaputt (Subject ist mitsigniert)</li>
<li>Hängt einen <code>List-Unsubscribe</code>-Footer an den Body → DKIM nochmal kaputt</li>
<li>Versendet als List-Server, behält aber Header-From = dich</li>
</ul>

<p>→ SPF kaputt (anderer Server), DKIM kaputt (Inhalt geändert), DMARC fail. Wenn dein Provider <code>p=reject</code> hat (Google, Microsoft, Yahoo seit 2024 fast Pflicht), bouncen <em>alle Listenmitglieder</em>. Mailman erkennt zu viele Bounces — kickt sie raus.</p>

<p><strong>Lösung:</strong> Moderne Listen-Software macht "From-Munging" — schreibt den Header-From um auf <code>"Alice via Liste" &lt;liste@server.ch&gt;</code>. Hässlich, aber funktioniert. Oder: ARC.</p>
</div>
</details>

<details class="pitfall">
<summary><span>3. SRS — der unsichtbare Patch im Briefumschlag <span class="severity med">Mittel</span></span></summary>
<div class="body">
<div class="dau">💡 <strong>In einem Satz:</strong> SRS ist ein Trick, bei dem dein Mailserver beim Weiterleiten die Absender-Adresse auf dem Umschlag fälscht — auf eine gute Weise, damit der nächste Türsteher zufrieden ist.</div>

<p><strong>Was es genau ist:</strong> <abbr title="Sender Rewriting Scheme">SRS</abbr> ist eine Technik, bei der der weiterleitende Mailserver den <em>Envelope-Sender</em> (MAIL FROM) umschreibt — aus <code>alice@firma-a.ch</code> wird sowas wie <code>SRS0=abc=xy=firma-a.ch=alice@firma-b.ch</code>.</p>

<p><strong>Effekt:</strong> SPF passt jetzt wieder (firma-b.ch sendet im Namen von firma-b.ch). Bounces kommen bei firma-b.ch an und werden zurück übersetzt zu firma-a.ch.</p>

<p><strong>Heimtücke:</strong> SRS muss aktiviert sein. Viele Mailserver können es theoretisch, haben es aber nicht eingeschaltet. Postfix? Geht. Exchange On-Prem? Über Connector möglich. Exchange Online? Aktiviert es seit 2020 automatisch beim Forward an externe Adressen — <em>nur beim Forward, nicht beim Redirect</em>. Genau hier wird's heimtückisch: <strong>"Umleiten" ohne SRS = SPF bricht. "Weiterleiten" mit SRS = SPF passt.</strong></p>

<p><strong>Helpdesk-Tipp:</strong> Bei "meine umgeleitete Mail kommt nicht an" zuerst prüfen ob die Outlook-Regel auf "Weiterleiten" oder "Umleiten" steht. Umstellen löst das Problem in ~70% der Fälle.</p>
</div>
</details>

<details class="pitfall">
<summary><span>4. ARC — die neue Hoffnung für Forwarder <span class="severity low">Niedrig (aber Pflichtwissen)</span></span></summary>
<div class="body">
<div class="dau">💡 <strong>In einem Satz:</strong> ARC ist wie ein Notarstempel — dein Mailserver bestätigt: "Ich hab die Mail vorher gesehen, sie war ok". Wenn der Empfänger dir vertraut, akzeptiert er die Mail, auch wenn unterwegs was kaputt gegangen ist.</div>

<p><strong>Was es genau ist:</strong> <abbr title="Authenticated Received Chain">ARC</abbr> ist eine Erweiterung, bei der ein weiterleitender Server an die Mail dranschreibt: "Ich habe diese Mail empfangen, als sie noch SPF/DKIM-konform war. Vertrau mir, das war legitim." — signiert mit einem eigenen ARC-Schlüssel.</p>

<p><strong>Status 2026:</strong> Gmail und Microsoft 365 nutzen ARC und akzeptieren es vom jeweils anderen + von grossen Mailinglisten. Kleinere Mailserver: hit-and-miss. Es ist keine garantierte Rettung — aber für grosse Forwarder funktioniert es immer öfter.</p>

<p><strong>Was du als Support wissen musst:</strong> Wenn ein DMARC-Report fail anzeigt, aber die Mail trotzdem zugestellt wurde — das war wahrscheinlich ARC. Nicht panisch werden. Aber: ARC ist kein Ersatz für richtiges Setup.</p>
</div>
</details>

<details class="pitfall">
<summary><span>5. Catch-all + Forward — die Eskalation <span class="severity high">Hoch</span></span></summary>
<div class="body">
<div class="dau">💡 <strong>In einem Satz:</strong> Wenn du "alles, was an irgendeine Adresse meiner Firma kommt" an dein Gmail weiterleitest, leitest du auch den ganzen Spam, Phishing und Bot-Müll weiter — und Gmail schiebt am Ende <em>dich</em> in den Spam.</div>

<p><strong>Was technisch läuft:</strong> Catch-all empfängt <em>jede</em> Mail an die Domain — inklusive massenhaft Spam, Phishing, Dictionary-Attacks. Wird alles brav weitergeleitet an Gmail. Gmail sieht: "firma-b.ch schickt mir ständig Spam und Phishing-Mails". Spam-Score deiner Domain crasht. Reputationsschaden ist nicht das Forward — das ist <em>du als Forwarder</em>.</p>

<p><strong>Lösung:</strong> Catch-all sollte filtern <em>bevor</em> weitergeleitet wird. Oder: nur konkrete Adressen weiterleiten, kein Catch-all-Forward.</p>
</div>
</details>

## Mini-Quiz — bist du fit?

Klick auf die richtige Antwort. Ohne Druck, ist nur zum Spass.

<div class="demo-card">
<h4>🧪 Drei Szenarien</h4>

<div class="quiz" id="quiz1">
<div class="scenario"><strong>Szenario 1:</strong> Eine Kundin meldet sich: "Ihr habt mir was geschickt aber ich kriege nichts." Du checkst — sie hat in Outlook eine Regel "alle Mails von eurer Firma an meine private Gmail umleiten" eingestellt. Eure Firma hat DMARC <code>p=reject</code>.</div>
<div class="options">
  <button onclick="quizAnswer(this, 1, true)">Ihre Mail-Regel ist das Problem. Das "Umleiten" bricht SPF, und wenn unsere Mail nicht DKIM-signiert ist, fliegt sie raus, bevor sie ihr Gmail sieht.</button>
  <button onclick="quizAnswer(this, 1, false)">Unser Mailserver ist kaputt — wenn ihre Outlook-Regel die Mail nicht durchlässt, muss bei uns was falsch sein.</button>
  <button onclick="quizAnswer(this, 1, false)">Gmail blockt alles aus der Schweiz neuerdings.</button>
</div>
<div class="explain" id="explain1"></div>
</div>

<div class="quiz" id="quiz2">
<div class="scenario"><strong>Szenario 2:</strong> Ein Mitarbeiter beschwert sich: "Ich war auf einer Mailing-Liste, und plötzlich bin ich rausgeflogen — angeblich zu viele Bounces."</div>
<div class="options">
  <button onclick="quizAnswer(this, 2, false)">Die Mailing-Liste ist Spam, deshalb wurde sie automatisch geblockt.</button>
  <button onclick="quizAnswer(this, 2, true)">Sein Mail-Provider hat <code>p=reject</code>. Die Liste verändert den Subject und Body — bricht DKIM — DMARC fail — andere Listenmitglieder können seine Mails nicht empfangen, ihre Server bouncen, Mailman kickt ihn als "Bounce-Quelle".</button>
  <button onclick="quizAnswer(this, 2, false)">Sein Postfach ist voll, deshalb bouncen die Mails.</button>
</div>
<div class="explain" id="explain2"></div>
</div>

<div class="quiz" id="quiz3">
<div class="scenario"><strong>Szenario 3:</strong> "Ich will, dass mir wer auf einen alten Account immer noch alle Mails an mein neues Postfach weitergibt, aber so, dass ich sehe, von wem es ursprünglich kam und auch direkt antworten kann."</div>
<div class="options">
  <button onclick="quizAnswer(this, 3, false)">Klassisches Weiterleiten (Forward) einrichten.</button>
  <button onclick="quizAnswer(this, 3, true)">Umleiten (Redirect) einrichten — der Original-Absender bleibt sichtbar, du kannst direkt antworten. Stell sicher dass der alte Server SRS macht, sonst SPF-Probleme.</button>
  <button onclick="quizAnswer(this, 3, false)">Das geht technisch nicht.</button>
</div>
<div class="explain" id="explain3"></div>
</div>

</div>

<script>
function quizAnswer(btn, num, correct) {
  const explanations = {
    1: 'Genau. <strong>"Umleiten" + Original-Absender mit <code>p=reject</code> + Original-Mail ohne DKIM = Mail verschwindet.</strong> Bonus-Wissen: Sie sollte ihre Regel auf "Weiterleiten" umstellen (akzeptiert dass dann sie als Absender steht). Oder besser: IMAP-Abruf von Gmail aus.',
    2: 'Richtig. <strong>Mailing-Listen + <code>p=reject</code> = automatischer Rauswurf.</strong> Workaround: Listen-Anbieter muss "From-Munging" aktivieren oder ARC signieren. Manche Listenbetreiber haben das bis heute nicht.',
    3: 'Korrekt. <strong>Umleiten ist hier die richtige Wahl</strong> — sonst geht jede Antwort an den alten Account. SRS ist der wichtige Detail-Punkt: ohne SRS bricht SPF, und wenn die Original-Mails kein DKIM haben, kommt nichts an.'
  };
  const wrongReasons = {
    1: '<strong>Nicht ganz.</strong> Unser Mailserver ist wahrscheinlich fine — das Problem ist die Umleitungsregel der Kundin, die SPF bricht. Wenn unsere Mails kein DKIM haben, scheitert auch das letzte Schutzschild.',
    2: '<strong>Nicht ganz.</strong> Die Mailing-Liste ist wahrscheinlich legitim — das Problem ist das Zusammenspiel aus <code>p=reject</code> und Listen-Servern, die den Mail-Inhalt verändern. Klassisches DMARC-Problem seit 2014.',
    3: '<strong>Nicht ganz.</strong> Forward macht aus dir den Absender, du kannst nicht direkt an den Original-Sender antworten. Umleiten ist hier die korrekte Wahl.'
  };

  const quiz = btn.closest('.quiz');
  quiz.querySelectorAll('button').forEach(b => b.disabled = true);
  if (correct) {
    btn.classList.add('right');
  } else {
    btn.classList.add('wrong');
    quiz.querySelectorAll('button').forEach(b => {
      if (b.getAttribute('onclick').includes('true')) b.classList.add('right');
    });
  }
  const explain = document.getElementById('explain' + num);
  explain.className = 'explain show';
  explain.style.background = correct ? '#ecfdf5' : '#fef2f2';
  explain.style.color = correct ? '#065f46' : '#991b1b';
  explain.innerHTML = (correct ? '✅ ' : '❌ ') + (correct ? explanations[num] : wrongReasons[num] + '<br><br>Richtige Antwort: ' + explanations[num]);
}
</script>

## TL;DR — die Punkte für deine Wissensdatenbank

1. **Weiterleiten ≠ Umleiten.** Forward macht eine neue Mail (du als Absender), Redirect lässt die alte Mail durch (Original-Absender bleibt).
2. **SPF bricht beim Umleiten fast immer.** Weil der weiterleitende Server nicht im SPF-Record des Original-Absenders steht.
3. **DKIM rettet das oft — aber nur wenn unterwegs nichts am Inhalt verändert wird.** Footer-Disclaimer, Subject-Präfixe, Anti-Spam-Stamps brechen DKIM.
4. **DMARC fail = Mail kann verschwinden.** Bei `p=reject` ohne Bounce-Mail an den Empfänger. Heimtückisch.
5. **SRS und ARC sind die modernen Pflaster.** SRS für Envelope-Sender-Umschrift, ARC für vertrauenswürdige Forwarder-Kette. Beide müssen aktiv konfiguriert sein.
6. **Mailing-Listen sind seit 2014 ein DMARC-Problem.** Wenn der Listen-Provider nicht From-Munging oder ARC macht, fliegen Mitglieder mit `p=reject`-Domains raus.
7. **Bei "Mail kam nicht an":** zuerst fragen "alle Mails oder nur manche?" — "nur manche" deutet auf Forward-Probleme.

## Was als nächstes?

→ [Mail-Health-Check für deine Domain](/check) — siehst in 5 Sekunden, wie dein SPF, DKIM und DMARC aktuell stehen und ob du Forward-Probleme zu erwarten hast.

→ [Wozu eigentlich DMARC?](/wissen/dmarc-warum-ueberhaupt) — der Geschäftsführer-Einstieg ohne Tech-Jargon.

→ Du betreibst einen Mailserver und brauchst SRS/ARC-Setup? [Schreib uns](/kontakt?topic=audit) — wir machen das als Festpreis-Audit.
