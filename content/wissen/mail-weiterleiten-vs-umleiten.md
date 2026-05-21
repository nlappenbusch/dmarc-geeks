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

/* Bastelkasten 2.0 */
.bk-step { margin: 18px 0; }
.bk-step-label {
  font-size: 13px; font-weight: 700; color: var(--text, #0f172a);
  margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
}
.bk-num {
  background: linear-gradient(135deg, #2563eb, #7c3aed); color: white;
  width: 24px; height: 24px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font-size: 13px; font-weight: 700;
}

.bk-mode-toggle {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
}
@media (max-width: 540px) { .bk-mode-toggle { grid-template-columns: 1fr; } }
.bk-mode {
  background: white; border: 2px solid var(--border, #e2e8f0); border-radius: 10px;
  padding: 12px 16px; cursor: pointer; text-align: left;
  font-family: inherit; transition: all .15s;
}
.bk-mode strong { display: block; font-size: 14px; color: var(--text, #0f172a); }
.bk-mode small { display: block; font-size: 12px; color: var(--muted, #64748b); margin-top: 3px; }
.bk-mode.active {
  border-color: var(--brand, #2563eb);
  background: rgba(37,99,235,.06);
}
.bk-mode.active strong { color: var(--brand, #2563eb); }

.bk-modifiers { display: grid; gap: 8px; }
.bk-mod {
  display: grid; grid-template-columns: 22px 1fr auto; gap: 12px; align-items: start;
  background: white; border: 1.5px solid var(--border, #e2e8f0);
  border-radius: 10px; padding: 12px 14px; cursor: pointer;
  transition: all .15s;
}
.bk-mod:hover { border-color: rgba(37,99,235,.4); }
.bk-mod input[type=checkbox] {
  width: 18px; height: 18px; cursor: pointer; margin-top: 2px;
  accent-color: var(--brand, #2563eb);
}
.bk-mod.on { background: rgba(37,99,235,.04); border-color: rgba(37,99,235,.4); }
.bk-mod-title { font-weight: 600; font-size: 14px; line-height: 1.4; }
.bk-mod-sub { font-size: 12.5px; color: var(--muted, #64748b); margin-top: 3px; line-height: 1.5; }
.bk-mod-effect {
  align-self: center; font-size: 11px; font-weight: 700;
  padding: 4px 10px; border-radius: 999px;
  white-space: nowrap; letter-spacing: .02em;
}
.bk-mod-effect.breaks { background: #fee2e2; color: #991b1b; }
.bk-mod-effect.heals { background: #d1fae5; color: #065f46; }
.bk-mod-effect.neutral { background: #f1f5f9; color: #475569; }
@media (max-width: 600px) {
  .bk-mod { grid-template-columns: 22px 1fr; }
  .bk-mod-effect { grid-column: 2; justify-self: start; margin-top: 4px; }
}

.bk-status-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  margin-bottom: 14px;
}
@media (max-width: 640px) { .bk-status-grid { grid-template-columns: 1fr; } }
.bk-status {
  background: white; border: 2px solid var(--border, #e2e8f0); border-radius: 10px;
  padding: 12px 14px; transition: all .25s;
}
.bk-status.pass { border-color: #10b981; background: #ecfdf5; }
.bk-status.fail { border-color: #ef4444; background: #fef2f2; }
.bk-status.warn { border-color: #f59e0b; background: #fffbeb; }
.bk-status-head {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 700; font-size: 14px; margin-bottom: 6px;
}
.bk-status-badge {
  font-size: 11px; padding: 3px 9px; border-radius: 999px; font-weight: 700;
  background: #e2e8f0; color: #475569;
}
.bk-status.pass .bk-status-badge { background: #10b981; color: white; }
.bk-status.fail .bk-status-badge { background: #ef4444; color: white; }
.bk-status.warn .bk-status-badge { background: #f59e0b; color: white; }
.bk-status-reason { font-size: 12.5px; color: var(--muted, #64748b); line-height: 1.55; }
.bk-status.pass .bk-status-reason, .bk-status.fail .bk-status-reason, .bk-status.warn .bk-status-reason {
  color: var(--text, #0f172a);
}
.bk-status-reason code { font-size: 11px; padding: 1px 5px; background: rgba(0,0,0,.05); border-radius: 3px; }

.bk-chain {
  background: #f8fafc; border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px; padding: 14px 16px;
}
.bk-chain-title {
  font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted, #64748b); font-weight: 700; margin-bottom: 10px;
}
.bk-chain-step {
  display: grid; grid-template-columns: 24px 1fr; gap: 10px;
  padding: 8px 0; font-size: 13.5px; line-height: 1.55;
  border-top: 1px dashed var(--border, #e2e8f0);
}
.bk-chain-step:first-of-type { border-top: 0; padding-top: 4px; }
.bk-chain-icon {
  width: 22px; height: 22px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
  background: #e2e8f0; color: #475569;
}
.bk-chain-step.ok .bk-chain-icon { background: #10b981; color: white; }
.bk-chain-step.bad .bk-chain-icon { background: #ef4444; color: white; }
.bk-chain-step.neutral .bk-chain-icon { background: #94a3b8; color: white; }
.bk-chain-step.final {
  margin-top: 8px; padding: 12px 14px; border-radius: 8px; border-top: 0;
  background: #f1f5f9; font-weight: 500;
}
.bk-chain-step.final.good { background: #ecfdf5; }
.bk-chain-step.final.meh { background: #fffbeb; }
.bk-chain-step.final.bad { background: #fef2f2; }
.bk-chain-step.final .bk-chain-icon { background: transparent; font-size: 18px; }
.bk-chain-step code { font-size: 11.5px; padding: 1px 5px; background: rgba(0,0,0,.06); border-radius: 3px; }

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

/* Zeilen-Erklär-Tabelle */
.line-explain {
  background: white;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  margin: 14px 0 20px;
  overflow: hidden;
}
.le-row {
  display: grid;
  grid-template-columns: minmax(180px, 30%) 1fr;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border, #e2e8f0);
  font-size: 13.5px;
  line-height: 1.55;
}
.le-row:last-child { border-bottom: 0; }
.le-row code {
  background: rgba(37,99,235,.08);
  color: var(--brand, #2563eb);
  padding: 2px 8px; border-radius: 4px;
  font: 12.5px/1.5 "JetBrains Mono", monospace;
  word-break: break-all;
  align-self: start;
}
.le-row span { color: var(--text, #0f172a); }
@media (max-width: 600px) {
  .le-row { grid-template-columns: 1fr; gap: 4px; }
}

/* Info-Box mit gelbem Akzent */
.info-box {
  background: linear-gradient(135deg, rgba(245,158,11,.05), rgba(245,158,11,.1));
  border: 1px solid rgba(245,158,11,.3);
  border-left: 4px solid #f59e0b;
  border-radius: 8px;
  padding: 12px 16px;
  margin: 14px 0 22px;
  font-size: 14px;
  line-height: 1.65;
}

/* Alignment-Tabelle */
.align-table {
  background: white;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
}
.align-row {
  display: grid;
  grid-template-columns: 28% 1fr 1fr;
  gap: 1px;
  background: var(--border, #e2e8f0);
}
.align-row > div {
  background: white;
  padding: 12px 14px;
  font-size: 13.5px;
  line-height: 1.5;
}
.align-row.align-header > div {
  background: #f8fafc;
  font-weight: 700;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted, #64748b);
}
.align-row small { color: var(--muted, #64748b); display: block; margin-top: 3px; font-size: 11.5px; }
.align-yes { background: #ecfdf5 !important; }
.align-no { background: #fef2f2 !important; }
.align-row.align-result > div { font-size: 15px; padding: 14px; }
@media (max-width: 640px) {
  .align-row { grid-template-columns: 1fr; }
}

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

## Und jetzt mal ehrlich: wie sieht das technisch aus?

Genug Analogien — jetzt der echte Code. Aber Zeile für Zeile erklärt. Du musst nichts auswendig lernen, aber wenn du das *einmal gesehen* hast, fluchst du beim nächsten Helpdesk-Ticket weniger.

### Der SPF-Record — eine Liste im DNS

Jede Domain hat (oder sollte haben) im DNS einen TXT-Record, der die Gästeliste ist:

```dns
firma-a.ch.    IN  TXT  "v=spf1 include:spf.protection.outlook.com ip4:185.12.7.42 -all"
```

<div class="line-explain">
<div class="le-row"><code>v=spf1</code><span>"Hallo, ich bin ein SPF-Record, Version 1."</span></div>
<div class="le-row"><code>include:spf.protection.outlook.com</code><span>"Microsoft 365 darf in meinem Namen senden." Dahinter steckt eine weitere DNS-Abfrage — Microsoft hat dort wieder eine Liste mit IPs.</span></div>
<div class="le-row"><code>ip4:185.12.7.42</code><span>"Dieser einzelne Server darf auch senden." (Z.B. dein eigener Mailserver)</span></div>
<div class="le-row"><code>-all</code><span>"Alle anderen? Strikt ablehnen." (Die wichtigste Zeile! <code>~all</code> wäre "Softfail = behandle als Spam". <code>-all</code> ist "Hardfail = ablehnen".)</span></div>
</div>

<div class="info-box">
<strong>🎯 Die 10-Lookup-Falle:</strong> SPF erlaubt <em>maximal 10 DNS-Lookups</em> pro Auflösung. Jedes <code>include:</code> ist ein Lookup. Microsoft braucht intern 1–2, Mailchimp 2, SendGrid 1 … schnell bist du bei 12. Dann wird der ganze SPF-Record ignoriert. Heimtückisch: es fällt nicht direkt auf.
</div>

### Der DKIM-Header — die Signatur im Brief

Wenn Alice's Mailserver eine Mail rausschickt, hängt er einen Header an die Mail an. Den siehst du normalerweise nicht, aber in jeder Mail steht das drin:

```email
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
    d=firma-a.ch; s=selector1; t=1716285600;
    h=From:To:Subject:Date:Message-ID;
    bh=47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=;
    b=K7nB9fLpQ2xZ8...vY3wT8oN==
```

<div class="line-explain">
<div class="le-row"><code>v=1</code><span>Version 1 von DKIM.</span></div>
<div class="le-row"><code>a=rsa-sha256</code><span>Welcher Krypto-Algorithmus benutzt wurde (RSA + SHA-256).</span></div>
<div class="le-row"><code>c=relaxed/relaxed</code><span>"Canonicalization". <em>relaxed</em> = Whitespace darf sich ändern, <em>simple</em> = byte-genau. Erkläre ich gleich.</span></div>
<div class="le-row"><code>d=firma-a.ch</code><span><strong>Die wichtigste Zeile.</strong> Mit welcher Domain wurde signiert. <em>Genau das prüft DMARC später auf Alignment.</em></span></div>
<div class="le-row"><code>s=selector1</code><span>Welcher öffentliche Schlüssel. Liegt unter <code>selector1._domainkey.firma-a.ch</code> im DNS.</span></div>
<div class="le-row"><code>h=From:To:Subject:Date:Message-ID</code><span><strong>Welche Header sind mitsigniert.</strong> Wenn unterwegs Subject oder From geändert werden → DKIM kaputt.</span></div>
<div class="le-row"><code>bh=47DEQp...</code><span>Hash des Bodys. Wenn auch nur 1 Zeichen im Body geändert wird → Hash stimmt nicht mehr → DKIM kaputt.</span></div>
<div class="le-row"><code>b=K7nB9...</code><span>Die eigentliche Signatur (über die in <code>h=</code> aufgeführten Header + den Body-Hash).</span></div>
</div>

Der Empfänger zieht den öffentlichen Schlüssel aus dem DNS (`selector1._domainkey.firma-a.ch`) und prüft: passt die Signatur? Wenn ja: DKIM PASS. Wenn nein: FAIL.

<div class="info-box">
<strong>🎯 Warum DKIM bei Forwarding rettet:</strong> Das Siegel ist <em>kryptografisch</em> — egal über wie viele Server die Mail wandert, solange der Inhalt nicht verändert wird, bleibt das Siegel gültig. Der Forwarder muss <em>nichts tun</em>, das Siegel reist mit.
</div>

### Der DMARC-Record — die Policy

Genau wie SPF, ein TXT-Record im DNS, aber unter einer speziellen Subdomain:

```dns
_dmarc.firma-a.ch.   IN  TXT  "v=DMARC1; p=reject; rua=mailto:reports@firma-a.ch; adkim=r; aspf=r; pct=100"
```

<div class="line-explain">
<div class="le-row"><code>v=DMARC1</code><span>Version.</span></div>
<div class="le-row"><code>p=reject</code><span><strong>Die Policy.</strong> Was soll passieren wenn was nicht passt? Drei Optionen: <code>none</code> (nur reporten, nichts tun), <code>quarantine</code> (Spam-Ordner), <code>reject</code> (ablehnen).</span></div>
<div class="le-row"><code>rua=mailto:reports@...</code><span>Wohin sollen die täglichen XML-Reports geschickt werden? <em>Hier kommen wir ins Spiel</em>: jemand muss diese XML lesen.</span></div>
<div class="le-row"><code>adkim=r</code><span>DKIM-Alignment: <em>relaxed</em> (Subdomain reicht) oder <em>strict</em> (exakt gleich). <strong>Gleich erklärt.</strong></span></div>
<div class="le-row"><code>aspf=r</code><span>SPF-Alignment: dito.</span></div>
<div class="le-row"><code>pct=100</code><span>Auf wieviel Prozent der Mails soll die Policy angewendet werden? <code>pct=10</code> bedeutet: nur 10% rejecten, 90% durchlassen — nützlich zum schrittweisen Hochziehen.</span></div>
</div>

### Das Wichtigste: Alignment

Das ist das Konzept, das *fast niemand* sauber erklärt kriegt — aber es ist der Knackpunkt. DMARC sagt: "SPF und DKIM müssen nicht nur passen, sie müssen auch zur *richtigen Domain* gehören."

<div class="demo-card">
<h4>🎯 Was Alignment bedeutet — visualisiert</h4>

<div class="align-table">
<div class="align-row align-header">
  <div>Wo schaut DMARC hin?</div>
  <div>Beispiel — sauberer Versand</div>
  <div>Beispiel — Spoofing</div>
</div>
<div class="align-row">
  <div><strong>Header-From</strong><br><small>Was du im Mail-Client siehst</small></div>
  <div class="align-yes">alice@<b>firma-a.ch</b></div>
  <div class="align-yes">alice@<b>firma-a.ch</b></div>
</div>
<div class="align-row">
  <div><strong>SPF-Domain</strong><br><small>Aus dem Envelope (MAIL FROM)</small></div>
  <div class="align-yes">bounce@<b>firma-a.ch</b><br><small>✓ Gleich = aligned</small></div>
  <div class="align-no">noreply@<b>boeser-server.tk</b><br><small>✗ Andere Domain = NICHT aligned</small></div>
</div>
<div class="align-row">
  <div><strong>DKIM-Domain</strong><br><small>Aus dem <code>d=</code>-Tag</small></div>
  <div class="align-yes">d=<b>firma-a.ch</b><br><small>✓ Gleich = aligned</small></div>
  <div class="align-no">d=<b>boeser-server.tk</b><br><small>oder gar keine Signatur</small></div>
</div>
<div class="align-row align-result">
  <div><strong>DMARC-Verdikt</strong></div>
  <div class="align-yes">✅ <strong>PASS</strong><br>Beide aligned</div>
  <div class="align-no">❌ <strong>FAIL</strong><br>Weder noch — Reject!</div>
</div>
</div>

<p style="margin-top:14px; font-size:13.5px; color:var(--muted,#64748b); line-height:1.6;">
<strong>relaxed (Standard):</strong> Subdomain reicht — <code>mail.firma-a.ch</code> ist aligned mit <code>firma-a.ch</code>.<br>
<strong>strict:</strong> Muss exakt gleich sein. Sehr selten benutzt.
</p>
</div>

**Warum das für Forwarding wichtig ist:** Wenn Bob's Mailserver eine Mail von Alice umleitet:

- Header-From bleibt `alice@firma-a.ch` (außen sichtbar)
- SPF-Domain wird `bob@firma-b.ch` (Bob's Server schickt jetzt) — **NICHT aligned**
- DKIM-Domain bleibt `d=firma-a.ch` (Alice's Siegel ist noch dran) — **aligned**

→ SPF fail, aber DKIM passes Alignment-Check → DMARC PASS. Genau das ist der Mechanismus, der Forwarding rettet.

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

Drei Schritte: **(1)** Modus wählen oben, **(2)** anhaken was unterwegs passiert, **(3)** unten ablesen was die drei Türsteher dazu sagen — und *warum*.

<div class="demo-card">
<h4>🔧 Setup-Bastelkasten</h4>

<!-- STEP 1: Modus -->
<div class="bk-step">
  <div class="bk-step-label"><span class="bk-num">1</span>Wie gibt Bob die Mail weiter?</div>
  <div class="bk-mode-toggle">
    <button class="bk-mode active" id="bkModeFwd" onclick="bkSetMode('fwd')">
      <strong>Weiterleiten (Forward)</strong>
      <small>Neue Mail, Bob = Absender</small>
    </button>
    <button class="bk-mode" id="bkModeRed" onclick="bkSetMode('red')">
      <strong>Umleiten (Redirect)</strong>
      <small>Gleiche Mail, Alice bleibt Absender</small>
    </button>
  </div>
</div>

<!-- STEP 2: Modifier -->
<div class="bk-step">
  <div class="bk-step-label"><span class="bk-num">2</span>Was passiert unterwegs?</div>
  <div class="bk-modifiers">
    <label class="bk-mod">
      <input type="checkbox" id="bk_footer" onchange="bkUpdate()">
      <div class="bk-mod-content">
        <div class="bk-mod-title">Mein Mailserver hängt einen Footer/Disclaimer an</div>
        <div class="bk-mod-sub">"Vertraulich. Falls Sie nicht der Empfänger..." / "[EXTERN]"-Tag im Subject / Anti-Spam-Stamp im Body</div>
      </div>
      <div class="bk-mod-effect breaks">→ bricht <b>DKIM</b></div>
    </label>

    <label class="bk-mod">
      <input type="checkbox" id="bk_listserv" onchange="bkUpdate()">
      <div class="bk-mod-content">
        <div class="bk-mod-title">Es geht über eine Mailing-Liste</div>
        <div class="bk-mod-sub">Mailman / Google Groups / GroupWise — Subject mit [Liste-XY]-Präfix, List-Unsubscribe-Footer im Body</div>
      </div>
      <div class="bk-mod-effect breaks">→ bricht <b>SPF + DKIM</b></div>
    </label>

    <label class="bk-mod">
      <input type="checkbox" id="bk_srs" onchange="bkUpdate()">
      <div class="bk-mod-content">
        <div class="bk-mod-title">SRS ist aktiv auf dem Forwarder</div>
        <div class="bk-mod-sub">Bob's Server schreibt den Envelope-Sender um auf <code>SRS0=...=alice=firma-a.ch@firma-b.ch</code> damit SPF wieder passt</div>
      </div>
      <div class="bk-mod-effect heals">→ rettet <b>SPF</b></div>
    </label>

    <label class="bk-mod">
      <input type="checkbox" id="bk_arc" onchange="bkUpdate()">
      <div class="bk-mod-content">
        <div class="bk-mod-title">Bob's Server signiert mit ARC</div>
        <div class="bk-mod-sub">Hängt eine Vertrauenskette an: "Ich bestätige dass die Mail bei mir noch SPF+DKIM-konform war" — signiert mit ARC-Schlüssel</div>
      </div>
      <div class="bk-mod-effect heals">→ rettet <b>DMARC</b> (wenn Empfänger vertraut)</div>
    </label>

    <label class="bk-mod">
      <input type="checkbox" id="bk_strict" onchange="bkUpdate()">
      <div class="bk-mod-content">
        <div class="bk-mod-title">Alice hat <code>p=reject</code> in DMARC</div>
        <div class="bk-mod-sub">Harte Policy: bei FAIL wird die Mail abgelehnt. Ohne Spam-Ordner. Ohne Warnung an den Endempfänger.</div>
      </div>
      <div class="bk-mod-effect neutral">→ entscheidet was bei FAIL passiert</div>
    </label>
  </div>
</div>

<!-- STEP 3: Live Status -->
<div class="bk-step">
  <div class="bk-step-label"><span class="bk-num">3</span>Was die drei Türsteher sagen — live</div>
  <div class="bk-status-grid">
    <div class="bk-status" id="bkSpf">
      <div class="bk-status-head"><span>🛡️ SPF</span><span class="bk-status-badge" id="bkSpfBadge">—</span></div>
      <div class="bk-status-reason" id="bkSpfReason">—</div>
    </div>
    <div class="bk-status" id="bkDkim">
      <div class="bk-status-head"><span>🔏 DKIM</span><span class="bk-status-badge" id="bkDkimBadge">—</span></div>
      <div class="bk-status-reason" id="bkDkimReason">—</div>
    </div>
    <div class="bk-status" id="bkDmarc">
      <div class="bk-status-head"><span>🏛️ DMARC</span><span class="bk-status-badge" id="bkDmarcBadge">—</span></div>
      <div class="bk-status-reason" id="bkDmarcReason">—</div>
    </div>
  </div>

  <div class="bk-chain" id="bkChain"></div>
</div>

</div>

<script>
let bkMode = 'fwd';

function bkSetMode(m) {
  bkMode = m;
  document.getElementById('bkModeFwd').classList.toggle('active', m === 'fwd');
  document.getElementById('bkModeRed').classList.toggle('active', m === 'red');
  bkUpdate();
}

function bkUpdate() {
  const footer = document.getElementById('bk_footer').checked;
  const listserv = document.getElementById('bk_listserv').checked;
  const srs = document.getElementById('bk_srs').checked;
  const arc = document.getElementById('bk_arc').checked;
  const strict = document.getElementById('bk_strict').checked;

  // Modifier-Labels visuell aktualisieren
  document.querySelectorAll('.bk-mod input').forEach(cb => {
    cb.closest('.bk-mod').classList.toggle('on', cb.checked);
  });

  let spfStatus, spfReason;
  let dkimStatus, dkimReason;
  let dmarcStatus, dmarcReason;
  let chainSteps = [];
  let outcome;

  if (bkMode === 'fwd') {
    // FORWARD: Bob erstellt komplett neue Mail, From = Bob
    spfStatus = 'pass';
    spfReason = 'Bob\'s Server sendet im Namen von firma-b.ch — der steht auf seiner eigenen Gästeliste.';
    chainSteps.push({ ok: true, text: 'Bob\'s Server erzeugt <strong>neue Mail</strong>, From-Header = bob@firma-b.ch' });

    if (footer) {
      dkimStatus = 'pass';
      dkimReason = 'Footer egal — Bob signiert eh die komplett neue Mail neu.';
      chainSteps.push({ ok: true, text: 'Footer wird hinzugefügt — DKIM-Signatur wird sowieso neu erzeugt' });
    } else {
      dkimStatus = 'pass';
      dkimReason = 'Falls Bob\'s Server DKIM macht: signiert die neue Mail mit firma-b.ch — alles passt.';
      chainSteps.push({ ok: true, text: 'Bob\'s Server signiert die neue Mail mit eigenem DKIM-Schlüssel' });
    }

    if (listserv) {
      chainSteps.push({ ok: null, text: 'Mailing-Liste-Häkchen ist im Forward-Modus weniger relevant — Forward macht eine eigene Mail.' });
    }

    dmarcStatus = 'pass';
    dmarcReason = 'Header-From = Bob, SPF-Domain = Bob, DKIM-Domain = Bob → alles aligned.';
    chainSteps.push({ ok: true, text: 'Alignment-Check: alle drei zeigen auf firma-b.ch → <strong>DMARC PASS</strong>' });

    outcome = 'good';
    chainSteps.push({ ok: true, special: 'Mail kommt an. Aber: <strong>Bob</strong> erscheint als Absender, nicht Alice. Reply geht an Bob.', final: true });

  } else {
    // REDIRECT: gleiche Mail, From bleibt Alice
    chainSteps.push({ ok: true, text: 'Mail bleibt wie sie ist — From-Header = alice@firma-a.ch, nur Empfänger geändert' });

    // SPF
    if (srs) {
      spfStatus = 'pass';
      spfReason = 'SRS hat den Envelope-Sender auf <code>...=firma-b.ch</code> umgeschrieben. SPF prüft jetzt firma-b.ch — passt.';
      chainSteps.push({ ok: true, text: 'SRS schreibt Envelope-Sender um → SPF prüft jetzt firma-b.ch statt firma-a.ch' });
    } else {
      spfStatus = 'fail';
      spfReason = 'Empfänger fragt: darf firma-b.ch im Namen von firma-a.ch senden? Nein — firma-b.ch steht nicht in Alice\'s SPF-Record.';
      chainSteps.push({ ok: false, text: 'Server-IP von firma-b.ch ist nicht in Alice\'s SPF-Record → <strong>SPF FAIL</strong>' });
    }

    // DKIM
    if (footer || listserv) {
      dkimStatus = 'fail';
      dkimReason = footer
        ? 'Footer im Body verändert den Body-Hash (<code>bh=</code>). Signatur passt nicht mehr → FAIL.'
        : 'Liste hat [Liste-XY]-Präfix in Subject und Footer im Body angehängt. Beide sind in <code>h=</code> mitsigniert → Hash kaputt → FAIL.';
      chainSteps.push({ ok: false, text: (footer ? 'Footer wird angehängt' : 'Liste verändert Subject + Body') + ' → DKIM-Hash stimmt nicht mehr → <strong>DKIM FAIL</strong>' });
    } else {
      dkimStatus = 'pass';
      dkimReason = 'Mail wurde unterwegs nicht angefasst. Alice\'s Signatur ist noch heil und prüft sich gegen <code>selector._domainkey.firma-a.ch</code>.';
      chainSteps.push({ ok: true, text: 'Inhalt unverändert → Alice\'s DKIM-Siegel hält → <strong>DKIM PASS</strong>' });
    }

    // DMARC
    const spfAligned = srs ? false : false; // SRS macht SPF "pass" aber NICHT aligned (Domain ist jetzt firma-b.ch, nicht firma-a.ch wie im Header-From)
    const dkimAligned = (dkimStatus === 'pass'); // DKIM signiert mit d=firma-a.ch, Header-From ist firma-a.ch → aligned

    if (srs) {
      chainSteps.push({ ok: false, text: 'Subtil aber wichtig: SRS rettet SPF technisch, aber <strong>nicht das Alignment</strong>. SPF zeigt jetzt auf firma-b.ch, Header-From auf firma-a.ch → SPF-aligned: nein.' });
    }

    if (dkimAligned) {
      dmarcStatus = 'pass';
      dmarcReason = 'DMARC braucht nur EINEN aligned Pass. DKIM-Domain = firma-a.ch = Header-From → aligned → PASS.';
      chainSteps.push({ ok: true, text: 'DKIM-Domain (d=firma-a.ch) = Header-From → aligned → <strong>DMARC PASS</strong>' });
      outcome = (srs || dkimStatus === 'pass') ? 'good' : 'meh';
    } else if (arc) {
      dmarcStatus = 'warn';
      dmarcReason = 'SPF und DKIM beide nicht aligned. ABER: ARC-Kette signalisiert "war bei mir noch konform". Wenn Empfänger Bob\'s Server vertraut → akzeptiert.';
      chainSteps.push({ ok: null, text: 'SPF + DKIM beide kaputt — aber ARC-Kette ist da. Empfänger entscheidet: vertraut er Bob\'s ARC-Signatur?' });
      outcome = 'meh';
    } else {
      dmarcStatus = 'fail';
      dmarcReason = 'Weder SPF noch DKIM sind aligned. Keine ARC-Rettung. DMARC sagt FAIL.';
      chainSteps.push({ ok: false, text: 'Weder SPF noch DKIM aligned, kein ARC → <strong>DMARC FAIL</strong>' });
      outcome = strict ? 'bad' : 'meh';
    }

    // Final outcome
    if (outcome === 'good') {
      chainSteps.push({ ok: true, special: 'Mail kommt sauber an. Aber: das hängt am DKIM-Strohhalm — wenn jemand am Inhalt schraubt, fliegt sie raus.', final: true });
    } else if (outcome === 'meh' && arc && dmarcStatus === 'warn') {
      chainSteps.push({ ok: null, special: 'Mail kommt wahrscheinlich an (ARC-Vertrauen). Hängt aber davon ab ob der Empfänger deinem ARC-Schlüssel traut. Bei Gmail/M365 untereinander funktioniert das, bei kleinen Servern oft nicht.', final: true });
    } else if (outcome === 'meh') {
      chainSteps.push({ ok: false, special: 'Mail landet im Spam-Ordner. Alice hat keine <code>p=reject</code>-Policy — sonst wäre die Mail komplett weg.', final: true });
    } else if (outcome === 'bad') {
      chainSteps.push({ ok: false, special: '🚨 <strong>Mail verschwindet komplett.</strong> Alice hat <code>p=reject</code>. Empfänger lehnt ab. Endempfänger merkt nichts (kein Bounce zu ihm). Alice glaubt ihre Mail kam an.', final: true });
    }
  }

  // Render checks
  setCheckBox('bkSpf', spfStatus, spfReason);
  setCheckBox('bkDkim', dkimStatus, dkimReason);
  setCheckBox('bkDmarc', dmarcStatus, dmarcReason);

  // Render kette
  const chainEl = document.getElementById('bkChain');
  chainEl.innerHTML = '<div class="bk-chain-title">📋 Was Schritt für Schritt passiert</div>' +
    chainSteps.map((s, i) => {
      const cls = s.final ? 'final ' + (outcome === 'good' ? 'good' : outcome === 'bad' ? 'bad' : outcome === 'meh' ? 'meh' : '') :
                  s.ok === true ? 'ok' : s.ok === false ? 'bad' : 'neutral';
      return `<div class="bk-chain-step ${cls}"><span class="bk-chain-icon">${s.final ? '🎯' : s.ok === true ? '✓' : s.ok === false ? '✗' : 'i'}</span><span>${s.text || s.special}</span></div>`;
    }).join('');
}

function setCheckBox(id, status, reason) {
  const box = document.getElementById(id);
  const badge = document.getElementById(id + 'Badge');
  const reasonEl = document.getElementById(id + 'Reason');
  box.className = 'bk-status ' + status;
  badge.textContent = status === 'pass' ? '✓ PASS' : status === 'fail' ? '✗ FAIL' : status === 'warn' ? '! WARN' : '—';
  reasonEl.innerHTML = reason;
}

bkUpdate();
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
