---
title: Weiterleiten oder umleiten? Was mit deiner Mail wirklich passiert (und warum SPF / DKIM / DMARC plötzlich böse werden)
slug: mail-weiterleiten-vs-umleiten
description: Der Unterschied zwischen Forward und Redirect — visuell erklärt, mit interaktiver Mail-Reise. Plus die 5 Heimtücken, an denen Helpdesks regelmässig verzweifeln.
date: 2026-05-21
author: Nils Lappenbusch
tags: [forwarding, redirect, spf, dkim, dmarc, support-wissen, basics]
---

<style>
/* ===== Custom styles für diesen Artikel ===== */
.demo-card {
  background: var(--card, #f8fafc);
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 14px;
  padding: 20px 22px;
  margin: 24px 0;
}
.demo-card h4 {
  margin: 0 0 14px;
  font-size: 15px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted, #64748b);
}

/* Toggle */
.fr-toggle {
  display: inline-flex; background: #fff; border: 1px solid var(--border, #e2e8f0);
  border-radius: 999px; padding: 4px; margin: 0 0 18px;
}
.fr-toggle button {
  border: 0; background: transparent; padding: 8px 18px; border-radius: 999px;
  font-size: 14px; font-weight: 600; cursor: pointer; color: var(--muted, #64748b);
  font-family: inherit;
}
.fr-toggle button.active {
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: white;
}

/* Mail-Reise Diagram */
.mail-trip {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto 1fr;
  gap: 10px;
  align-items: stretch;
  margin: 12px 0 18px;
}
@media (max-width: 640px) {
  .mail-trip { grid-template-columns: 1fr; }
  .mail-trip .arrow { transform: rotate(90deg); padding: 4px 0; }
}
.mail-trip .node {
  background: white;
  border: 1.5px solid var(--border, #e2e8f0);
  border-radius: 10px;
  padding: 12px 10px;
  text-align: center;
  font-size: 13px;
}
.mail-trip .node strong { display: block; font-size: 12px; color: var(--muted, #64748b); margin-bottom: 2px; }
.mail-trip .node .role { font-weight: 700; color: var(--text, #0f172a); }
.mail-trip .arrow {
  align-self: center;
  font-size: 22px;
  color: var(--brand, #2563eb);
  font-weight: 700;
}
.mail-trip .node.envelope-changed { border-color: #ef4444; background: #fef2f2; }
.mail-trip .node.envelope-kept { border-color: #10b981; background: #ecfdf5; }

/* Checks panel */
.checks {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 14px 0 4px;
}
@media (max-width: 540px) { .checks { grid-template-columns: 1fr; } }
.check {
  background: white;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
}
.check .name { font-weight: 700; font-size: 13px; margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center; }
.check .status { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.check .status.pass { background: #d1fae5; color: #065f46; }
.check .status.fail { background: #fee2e2; color: #991b1b; }
.check .status.warn { background: #fef3c7; color: #92400e; }
.check .detail { color: var(--muted, #64748b); line-height: 1.5; }

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
.pitfall .body p:first-child { margin-top: 0; }
.pitfall .severity {
  font-size: 10px; padding: 2px 8px; border-radius: 999px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .03em;
}
.pitfall .severity.high { background: #fee2e2; color: #991b1b; }
.pitfall .severity.med { background: #fef3c7; color: #92400e; }
.pitfall .severity.low { background: #dbeafe; color: #1e40af; }

/* Mini visual envelope */
.env {
  display: inline-block; font-family: "JetBrains Mono", monospace; font-size: 12px;
  background: #f1f5f9; padding: 8px 12px; border-radius: 6px; border-left: 3px solid var(--brand, #2563eb);
  margin: 6px 0; line-height: 1.6;
}
.env .label { color: var(--muted, #64748b); }
.env .changed { background: #fee2e2; padding: 1px 4px; border-radius: 3px; color: #991b1b; }
.env .same { background: #d1fae5; padding: 1px 4px; border-radius: 3px; color: #065f46; }

/* Glossar-Tooltip */
abbr[title] { text-decoration: underline dotted; cursor: help; text-decoration-color: var(--brand, #2563eb); }
</style>

## In einem Satz

**Weiterleiten** macht aus deiner Mail eine neue Mail (mit dir als Absender). **Umleiten** schickt die *gleiche* Mail einfach an eine andere Adresse weiter — Absender bleibt der Original-Absender. Und genau dieser Unterschied ist es, der SPF, DKIM und DMARC zur Achterbahn macht.

## Bevor wir reingehen: was ist eine Mail überhaupt?

Jede E-Mail hat **zwei Absender**. Das verwirrt erstmal, ist aber der Schlüssel zu allem:

<div class="demo-card">
<h4>📨 Eine Mail = Briefumschlag + Brief</h4>

<div class="env">
<span class="label">┌─ Briefumschlag (sieht nur der Mail-Server) ────┐</span><br>
<span class="label">│ MAIL FROM:</span> alice@firma-a.ch <span class="label">← der "Envelope-Sender"</span><br>
<span class="label">│ RCPT TO:</span>   bob@firma-b.ch<br>
<span class="label">└────────────────────────────────────────────────┘</span><br><br>
<span class="label">┌─ Brief (siehst du in Outlook/Gmail) ───────────┐</span><br>
<span class="label">│ From:</span>    Alice Schmid &lt;alice@firma-a.ch&gt; <span class="label">← der "Header-From"</span><br>
<span class="label">│ To:</span>      bob@firma-b.ch<br>
<span class="label">│ Subject:</span> Rechnung März<br>
<span class="label">│</span><br>
<span class="label">│</span> Hi Bob, anbei die Rechnung.<br>
<span class="label">└────────────────────────────────────────────────┘</span>
</div>

<p style="margin-top:14px; font-size:14px; color:var(--muted,#64748b);">
Im Alltag sind beide identisch. Aber genau wenn sie <em>auseinanderlaufen</em>, beginnt das DMARC-Drama.
</p>
</div>

Die drei Schutzmechanismen schauen jeweils woanders hin:

| Mechanismus | Prüft was? | Schaut auf |
|---|---|---|
| **<abbr title="Sender Policy Framework — DNS-Liste der erlaubten Absender-Server">SPF</abbr>** | Darf der **Server** im Namen dieser Domain senden? | Briefumschlag (MAIL FROM) |
| **<abbr title="DomainKeys Identified Mail — kryptografische Signatur der Mail">DKIM</abbr>** | Ist die Mail **unverändert** seit sie signiert wurde? | Brief (Inhalt + Signatur-Header) |
| **<abbr title="Domain-based Message Authentication, Reporting and Conformance — Policy auf dem sichtbaren Absender">DMARC</abbr>** | Passt das, was der Empfänger sieht (Header-From) zu mindestens **einer** der beiden Prüfungen? | Brief + Verbindung zum Umschlag |

Merksatz: SPF schaut auf den Briefumschlag, DKIM schaut in den Brief, DMARC schaut, ob Briefumschlag und Brief zur gleichen Familie gehören.

## Weiterleiten vs. Umleiten — der eigentliche Unterschied

<div class="demo-card">
<h4>🔁 Interaktiv: was passiert bei welcher Aktion?</h4>

<div class="fr-toggle" id="frToggle">
  <button class="active" onclick="setMode('fwd')">Weiterleiten (Forward)</button>
  <button onclick="setMode('red')">Umleiten (Redirect)</button>
</div>

<div class="mail-trip">
  <div class="node">
    <strong>Original-Absender</strong>
    <div class="role">alice@firma-a.ch</div>
    <div style="font-size:11px;color:var(--muted,#64748b);margin-top:4px">Schickt an<br>bob@firma-b.ch</div>
  </div>
  <div class="arrow">→</div>
  <div class="node" id="middleNode">
    <strong>Du / Mailserver</strong>
    <div class="role">bob@firma-b.ch</div>
    <div style="font-size:11px;color:var(--muted,#64748b);margin-top:4px" id="middleAction">leitet weiter an<br>privat@gmail.com</div>
  </div>
  <div class="arrow">→</div>
  <div class="node">
    <strong>Endempfänger</strong>
    <div class="role">privat@gmail.com</div>
    <div style="font-size:11px;color:var(--muted,#64748b);margin-top:4px">Gmail prüft<br>SPF / DKIM / DMARC</div>
  </div>
</div>

<div id="envBox">
  <div class="env" id="envContent"></div>
</div>

<div class="checks">
  <div class="check">
    <div class="name">SPF <span class="status" id="spfStatus">—</span></div>
    <div class="detail" id="spfDetail">—</div>
  </div>
  <div class="check">
    <div class="name">DKIM <span class="status" id="dkimStatus">—</span></div>
    <div class="detail" id="dkimDetail">—</div>
  </div>
  <div class="check">
    <div class="name">DMARC <span class="status" id="dmarcStatus">—</span></div>
    <div class="detail" id="dmarcDetail">—</div>
  </div>
</div>

<p id="resultLine" style="margin-top:14px; font-size:14px; padding:10px 14px; border-radius:8px; line-height:1.6;"></p>

</div>

<script>
function setMode(m) {
  const buttons = document.querySelectorAll('#frToggle button');
  buttons.forEach(b => b.classList.remove('active'));
  buttons[m === 'fwd' ? 0 : 1].classList.add('active');

  const env = document.getElementById('envContent');
  const result = document.getElementById('resultLine');
  const middleAction = document.getElementById('middleAction');

  if (m === 'fwd') {
    middleAction.innerHTML = 'erstellt <strong>neue</strong> Mail an<br>privat@gmail.com';
    env.innerHTML =
      '<span class="label">Vom Mailserver firma-b.ch rausgehender Umschlag:</span><br>' +
      '<span class="label">MAIL FROM:</span> <span class="changed">bob@firma-b.ch</span> <span class="label">← neu! (oder bounce-Adresse)</span><br>' +
      '<span class="label">RCPT TO:</span>   privat@gmail.com<br><br>' +
      '<span class="label">Brief-Header:</span><br>' +
      '<span class="label">From:</span> <span class="changed">"Bob (Fwd)" &lt;bob@firma-b.ch&gt;</span> <span class="label">oder original — Outlook-spezifisch</span><br>' +
      '<span class="label">Subject:</span> <span class="changed">"Fwd: Rechnung März"</span><br>' +
      '<span class="label">Body:</span> <span class="changed">"---------- Forwarded message ---------- ..."</span>';

    setCheck('spf', 'pass', 'firma-b.ch sendet im eigenen Namen — SPF passt.');
    setCheck('dkim', 'pass', 'Falls firma-b.ch DKIM signiert: passt. Original-DKIM ist eh egal weil neue Mail.');
    setCheck('dmarc', 'pass', 'Header-From = firma-b.ch, SPF/DKIM passen → DMARC ok.');
    result.style.background = '#d1fae5';
    result.style.color = '#065f46';
    result.innerHTML = '✅ <strong>Ankunft sauber.</strong> Aber: Gmail sieht <em>Bob</em> als Absender, nicht Alice. Wenn Bob antwortet, geht\'s an Bob — nicht an Alice. Das ist der Preis.';

  } else {
    middleAction.innerHTML = 'leitet <strong>gleiche</strong> Mail durch an<br>privat@gmail.com';
    env.innerHTML =
      '<span class="label">Vom Mailserver firma-b.ch rausgehender Umschlag:</span><br>' +
      '<span class="label">MAIL FROM:</span> <span class="same">alice@firma-a.ch</span> <span class="label">← original behalten!</span><br>' +
      '<span class="label">RCPT TO:</span>   privat@gmail.com<br><br>' +
      '<span class="label">Brief-Header:</span><br>' +
      '<span class="label">From:</span> <span class="same">Alice Schmid &lt;alice@firma-a.ch&gt;</span> <span class="label">← unverändert</span><br>' +
      '<span class="label">Subject:</span> <span class="same">Rechnung März</span> <span class="label">← unverändert</span><br>' +
      '<span class="label">Body:</span> <span class="same">"Hi Bob, anbei die Rechnung."</span> <span class="label">← unverändert</span>';

    setCheck('spf', 'fail', 'Gmail prüft: darf firma-b.ch im Namen von firma-a.ch senden? Nein. SPF: FAIL.');
    setCheck('dkim', 'pass', 'Inhalt unverändert → DKIM-Signatur von firma-a.ch ist noch gültig.');
    setCheck('dmarc', 'pass', 'Reicht: <strong>DKIM passt</strong> + Header-From = firma-a.ch → Alignment OK.');
    result.style.background = '#fef3c7';
    result.style.color = '#92400e';
    result.innerHTML = '⚠️ <strong>Knapp gerettet durch DKIM.</strong> Wenn jetzt aber unterwegs ein Footer "Diese Mail wurde weitergeleitet von..." angehängt würde, würde auch DKIM brechen → DMARC fail → Spam oder Reject.';
  }
}

function setCheck(id, status, detail) {
  const s = document.getElementById(id + 'Status');
  const d = document.getElementById(id + 'Detail');
  s.className = 'status ' + status;
  s.textContent = status === 'pass' ? 'PASS' : status === 'fail' ? 'FAIL' : 'WARN';
  d.textContent = detail;
  d.innerHTML = detail; // allow HTML
}

setMode('fwd');
</script>

### Übersetzung in Klartext

**Weiterleiten** ist wie: du nimmst den Brief raus, schreibst ihn ab in deinen eigenen Briefumschlag und schickst den los. Aus Sicht der Post bist *du* jetzt der Absender. Funktioniert technisch problemlos — aber der Kunde antwortet jetzt an dich, nicht an den Original-Absender.

**Umleiten** ist wie: du kriegst den Brief, schreibst eine neue Empfänger-Adresse drauf und wirfst ihn so wie er ist wieder in den Briefkasten. Der ursprüngliche Absender steht immer noch oben. Das ist *näher an dem, was Endnutzer eigentlich wollen* — aber technisch schwieriger.

> **In Outlook / Exchange heisst das wörtlich:** "Weiterleiten" = Forward (neue Mail), "Umleiten" = Redirect (gleiche Mail neu adressiert). In Outlook-Regeln stehen beide nebeneinander — und tun komplett verschiedene Dinge. Bei Gmail gibt es nur "Forward", was technisch oft eher einem Redirect entspricht.

## Wieso bricht SPF beim Umleiten so zuverlässig?

SPF ist im Grunde eine DNS-Liste: *"Diese Server-IPs dürfen im Namen meiner Domain senden."*

Beispiel SPF-Record von `firma-a.ch`:

```
v=spf1 include:spf.protection.outlook.com -all
```

Übersetzt: "Nur Microsoft 365-IPs dürfen für `firma-a.ch` senden. Alle anderen — rejecten."

Beim **Umleiten** rauscht die Mail aber jetzt durch `firma-b.ch`. Gmail schaut: MAIL FROM ist `alice@firma-a.ch`, Server-IP ist aber die von `firma-b.ch`. SPF fragt: *"Darf firma-b.ch für firma-a.ch?"* → nein. **SPF FAIL**.

Das ist nicht kaputt, das ist *by design*. SPF wurde 2003 entworfen, als Weiterleitungen über fremde Server noch die Ausnahme waren.

## Wieso DKIM den Tag oft rettet (aber nicht immer)

DKIM ist ein kryptografischer Stempel auf der Mail. Der Mailserver von `firma-a.ch` rechnet beim Versenden eine Signatur aus über:

- bestimmte Header (typisch: From, Subject, Date, To)
- den Body

…und packt die mit in den `DKIM-Signature`-Header. Gmail kann dann beim Empfang prüfen: *"Stimmt die Signatur noch mit dem aktuellen Inhalt überein?"*

**Beim Umleiten** ändert sich nichts am Brief — Signatur passt, DMARC ist gerettet, weil DMARC schon zufrieden ist, wenn *eines* von SPF oder DKIM stimmt.

**Aber:** sobald *irgendwer* zwischendrin am Brief schraubt, bricht DKIM. Klassische Schraubereien:

- Subject-Präfix `[EXTERN]` oder `[Mailingliste]`
- Footer-Disclaimer "Diese Mail wurde geprüft von …"
- Anti-Virus-Scanner, der die Mail neu verpackt
- Mailing-Listen-Software, die `List-Unsubscribe`-Footer reinschreibt

Sekunde danach: DKIM FAIL → kombiniert mit SPF FAIL → DMARC FAIL → bei `p=reject` fliegt die Mail raus.

## Die 5 Heimtücken, die Helpdesks zur Verzweiflung bringen

<details class="pitfall">
<summary><span>1. Der „leitet bei Outlook eingehende Mails an Gmail weiter"-Klassiker <span class="severity high">Hoch</span></span></summary>
<div class="body">
<p><strong>Symptom:</strong> "Ich kriege auf meinem Gmail nicht mehr alle Mails. Es sind sogar wichtige Kundenanfragen verschwunden."</p>

<p><strong>Was läuft:</strong> Outlook-Regel "an Gmail umleiten" (= Redirect). Manche Kunden senden aus Domains mit harter <code>p=reject</code> DMARC-Policy. Deren SPF erlaubt nur den eigenen Mailserver, nicht den der Firma. Outlook leitet weiter — Envelope-From bleibt der Original-Absender — SPF crasht — aber DKIM hält die Mail noch zusammen.</p>

<p><strong>Bis irgendeine Mail kommt, die kein DKIM hat</strong> (passiert noch bei vielen kleinen Firmen). Dann bricht auch das. Gmail rejected. Die Mail kommt nicht an. Es gibt <em>keine Fehlermeldung beim Empfänger</em>, weil der Absender den Bounce kriegt — und der wusste ja nicht, dass die Mail eigentlich an Gmail sollte.</p>

<p><strong>Helpdesk-Trick:</strong> Frag nicht "kommt sie nicht an?", frag "kommen <em>alle</em> nicht an oder nur <em>manche</em>?" — "nur manche" zeigt dir den DKIM/SPF-Forward-Bug.</p>
</div>
</details>

<details class="pitfall">
<summary><span>2. Mailing-Listen brechen DMARC seit 2014 systematisch <span class="severity high">Hoch</span></span></summary>
<div class="body">
<p><strong>Symptom:</strong> "Ich krieg Mails von einer Mailing-Liste, in der ein Kollege geantwortet hat — aber sein Mail-Provider <em>kickt mich</em> dann aus der Liste."</p>

<p><strong>Was läuft:</strong> Die Mailing-Liste (typisch Mailman, GroupWise, Google Groups) macht Folgendes mit der Mail:</p>
<ul>
<li>Setzt einen <code>[Liste-Name]</code>-Präfix vor das Subject</li>
<li>Hängt einen <code>List-Unsubscribe</code>-Footer an den Body</li>
<li>Versendet als List-Server, behält aber Header-From = Original-Absender</li>
</ul>

<p>→ DKIM kaputt (Inhalt geändert), SPF kaputt (anderer Server), DMARC fail. Wenn der Original-Absender <code>p=reject</code> hat (Google, Microsoft, Yahoo seit 2024 fast Pflicht), bouncen <em>alle Listenmitglieder</em>. Mailman erkennt zu viele Bounces — kickt sie raus.</p>

<p><strong>Lösung:</strong> Moderne Listen-Software macht "From-Munging" — schreibt den Header-From um auf <code>"Alice via Liste" &lt;liste@server.ch&gt;</code>. Hässlich, aber funktioniert. Oder: ARC (siehe unten).</p>
</div>
</details>

<details class="pitfall">
<summary><span>3. SRS — der unsichtbare Patch im Envelope <span class="severity med">Mittel</span></span></summary>
<div class="body">
<p><strong>Was es ist:</strong> <abbr title="Sender Rewriting Scheme">SRS</abbr> ist eine Technik, bei der der weiterleitende Mailserver den <em>Envelope-Sender</em> (MAIL FROM) umschreibt — aus <code>alice@firma-a.ch</code> wird sowas wie <code>SRS0=abc=xy=firma-a.ch=alice@firma-b.ch</code>.</p>

<p><strong>Effekt:</strong> SPF passt jetzt wieder (firma-b.ch sendet im Namen von firma-b.ch). Bounces kommen bei firma-b.ch an und werden zurück übersetzt zu firma-a.ch.</p>

<p><strong>Heimtücke:</strong> SRS muss aktiviert sein. Viele Mailserver können es theoretisch, haben es aber nicht eingeschaltet. Postfix? Geht. Exchange On-Prem? Über Connector möglich. Exchange Online? Aktiviert es seit 2020 automatisch beim Forward an externe Adressen — <em>nur beim Forward, nicht beim Redirect</em>. Genau hier wird's heimtückisch: <strong>"Umleiten" ohne SRS = SPF bricht. "Weiterleiten" mit SRS = SPF passt.</strong></p>

<p><strong>Helpdesk-Tipp:</strong> Bei "meine umgeleitete Mail kommt nicht an" zuerst prüfen ob die Outlook-Regel auf "Weiterleiten" oder "Umleiten" steht. Umstellen löst das Problem in ~70% der Fälle.</p>
</div>
</details>

<details class="pitfall">
<summary><span>4. ARC — die neue Hoffnung für Forwarder <span class="severity low">Niedrig (aber Pflichtwissen)</span></span></summary>
<div class="body">
<p><strong>Was es ist:</strong> <abbr title="Authenticated Received Chain">ARC</abbr> ist eine Erweiterung, bei der ein weiterleitender Server an die Mail dranschreibt: "Ich habe diese Mail empfangen, als sie noch SPF/DKIM-konform war. Vertrau mir, das war legitim." — signiert mit einem eigenen ARC-Schlüssel.</p>

<p><strong>Effekt:</strong> Wenn der Endempfänger (Gmail, Microsoft 365) dem ARC-Signierer vertraut, akzeptiert er die Mail trotz gebrochenem SPF/DKIM.</p>

<p><strong>Status 2026:</strong> Gmail und Microsoft 365 nutzen ARC und akzeptieren es vom jeweils anderen + von grossen Mailinglisten. Kleinere Mailserver: hit-and-miss. Es ist keine garantierte Rettung — aber für grosse Forwarder funktioniert es immer öfter.</p>

<p><strong>Was du als Support wissen musst:</strong> Wenn ein DMARC-Report fail anzeigt, aber die Mail trotzdem zugestellt wurde — das war wahrscheinlich ARC. Nicht panisch werden. Aber: ARC ist kein Ersatz für richtiges Setup.</p>
</div>
</details>

<details class="pitfall">
<summary><span>5. Catch-all + Forward — die Eskalation <span class="severity high">Hoch</span></span></summary>
<div class="body">
<p><strong>Symptom:</strong> Ein Kunde hat eine Catch-all-Adresse (<code>*@firma-b.ch</code>) und leitet alles an seine private Gmail um. Nach 2 Wochen: Gmail markiert alles als Spam, oder sperrt das Account temporär.</p>

<p><strong>Was läuft:</strong> Catch-all empfängt <em>jede</em> Mail an die Domain — inklusive massenhaft Spam, Phishing, Dictionary-Attacks. Wird alles brav weitergeleitet an Gmail. Gmail sieht: "firma-b.ch schickt mir ständig Spam und Phishing-Mails". Spam-Score deiner Domain crasht. Reputationschaden ist nicht das Forward — das ist <em>du als Forwarder</em>.</p>

<p><strong>Lösung:</strong> Catch-all sollte filtern <em>bevor</em> weitergeleitet wird. Oder: nur konkrete Adressen weiterleiten, kein Catch-all-Forward.</p>
</div>
</details>

## Die kurze Entscheidungshilfe

<div class="demo-card">
<h4>🧭 Was nimmst du wann?</h4>

<table style="width:100%; margin: 0;">
<thead><tr><th>Wenn du …</th><th>nimm</th></tr></thead>
<tbody>
<tr><td>… eine Mail an einen Kollegen schicken willst, der mit dem Sender weiterhin reden soll</td><td><strong>Umleiten</strong> (Redirect)</td></tr>
<tr><td>… eine Mail einem Kollegen zur Info weitergeben willst</td><td><strong>Weiterleiten</strong> (Forward)</td></tr>
<tr><td>… alle Mails einer alten Adresse auf eine neue umlegen willst (Migration)</td><td><strong>Umleiten</strong> + sicherstellen dass SRS auf dem Forwarder aktiv ist</td></tr>
<tr><td>… deine Firmen-Mails auf dein privates Gmail spiegeln willst</td><td>Eigentlich: <strong>IMAP-Abruf</strong> statt Forward. Verändert nichts auf dem Server, keine DMARC-Probleme.</td></tr>
<tr><td>… ein Catch-all auf eine andere Adresse leiten willst</td><td>Lieber <strong>filtern + spezifische Adressen</strong> als Catch-all-Forward</td></tr>
</tbody>
</table>
</div>

## Die TL;DR für deine Wissensdatenbank

1. **Weiterleiten ≠ Umleiten.** Forward macht eine neue Mail (du als Absender), Redirect lässt die alte Mail durch (Original-Absender bleibt).
2. **SPF bricht beim Umleiten fast immer.** Weil der weiterleitende Server nicht im SPF-Record des Original-Absenders steht.
3. **DKIM rettet das oft — aber nur wenn unterwegs nichts am Inhalt verändert wird.** Footer-Disclaimer, Subject-Präfixe, Anti-Spam-Stamps brechen DKIM.
4. **DMARC fail = Mail kann verschwinden.** Bei `p=reject` ohne Bounce-Mail an den Empfänger. Heimtückisch.
5. **SRS und ARC sind die modernen Pflaster.** SRS für Envelope-Sender-Umschrift, ARC für vertrauenswürdige Forwarder-Kette. Beide müssen aktiv konfiguriert sein.
6. **Mailing-Listen sind seit 2014 ein DMARC-Problem.** Wenn der Listen-Provider nicht From-Munging oder ARC macht, fliegen Mitglieder mit `p=reject`-Domains raus.

## Was als nächstes?

→ [Mail-Health-Check für deine Domain](/check) — siehst in 5 Sekunden, wie dein SPF, DKIM und DMARC aktuell stehen und ob du Forward-Probleme zu erwarten hast.

→ [DMARC-Reports lesen lernen](/wissen/dmarc-warum-ueberhaupt) — die XML-Reports von Google & Co. zeigen dir genau, welche Forwarder-Hops gerade Probleme machen.

→ Du betreibst einen Mailserver und brauchst SRS/ARC-Setup? [Schreib uns](/kontakt?topic=audit) — wir machen das als Festpreis-Audit.
