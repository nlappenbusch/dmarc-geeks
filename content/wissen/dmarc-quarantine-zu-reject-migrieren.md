---
title: Von p=quarantine zu p=reject — sicher migrieren ohne legitime Mails zu killen
slug: dmarc-quarantine-zu-reject-migrieren
description: Schritt-für-Schritt-Anleitung wie du die DMARC-Policy verschärfst ohne dass Kunden-Bestellbestätigungen oder Rechnungen plötzlich verschwinden.
date: 2026-05-08
author: Nils Lappenbusch
tags: [dmarc, policy, migration, reject]
---

Du bist auf `p=quarantine`, alles läuft seit Wochen stabil, deine Reports sehen sauber aus. Frage: ist es Zeit für `p=reject` — und was, wenn nicht?

## Was sich konkret ändert

| | p=none | p=quarantine | p=reject |
|---|---|---|---|
| **Was passiert mit Fakes** | nichts — wird zugestellt | landet im Spam | wird abgelehnt, Sender bekommt Bounce |
| **Empfänger-Erlebnis bei legitimen Mails mit Auth-Fehler** | normal | im Spam-Ordner | Mail kommt nie an |
| **Schutz vor Phishing** | nur Monitoring, keine Action | mittel | hoch |
| **Risiko legitime Mails zu killen** | null | niedrig | hoch wenn Auth-Setup nicht sauber |

Der wichtige Punkt: **bei `p=reject` werden auch deine legitimen Mails geblockt, wenn DKIM oder SPF fehlschlagen** — z.B. weil ein neuer Marketing-Tool-Sender nicht im SPF steht oder DKIM noch nicht aktiviert ist. Bei `p=quarantine` landet die Mail im Spam und kann zurückgeholt werden; bei `p=reject` ist sie weg.

## Die 5-Stufen-Checkliste vor dem Switch

### 1. Pass-Rate stabil über 99 %

Schau in deinem DMARC-Aggregator. Wenn nicht 99.x % deiner authentifizierten Mails als "pass" durchgehen, ist `p=reject` riskant.

```text
30 Tage zurück:
  Pass:        99.4 %  ✓
  Quarantine:  0.5 %
  Reject:      0.1 %
```

Wenn deine Quote eher Richtung 95 % geht — erst die unauffälligen 5 % aufräumen.

### 2. Alle Sender im SPF und DKIM

Mach eine Inventur. Frag dich:

- Newsletter-Tool? SPF + DKIM?
- CRM (HubSpot, Salesforce, Pipedrive)? Signiert mit DKIM?
- Hosting-/Mailcow-Server für transaktionale Mails?
- IT-Support-Tools (Helpdesk, Confluence-Mails)?
- Marketing-Automation (ActiveCampaign, Mailchimp, Brevo)?
- Internes ERP (SAP-Mails, Sage)?

Jeder Sender braucht im DMARC-Report einen Eintrag mit `dkim=pass` ODER `spf=pass` UND dazu Alignment mit der Header-From-Domain.

### 3. Sub-Domain-Strategie geklärt

DMARC kennt `p=` (Hauptdomain) und `sp=` (Sub-Domain). Wenn du `sp=` nicht setzt, gilt automatisch dasselbe wie `p=`. Das ist meistens richtig — **ausser** du hast Sub-Domains die anders versenden:

- `marketing.deine-firma.ch` für Newsletter
- `transactional.deine-firma.ch` für Rechnungen
- `support.deine-firma.ch` für Helpdesk-Mails

Hast du sowas? Dann sicher noch nicht auf `sp=reject` springen, bevor jede Sub-Domain einzeln auditiert ist.

### 4. Monitoring-Mechanismus für Bounce-Spike

Wenn du nach dem Switch plötzlich 50 Bounces/Tag von Kunden bekommst die schreiben "ich konnte euch nichts schicken" — du musst das in 24h merken, nicht in 30 Tagen.

Setze:
- Spike-Alert im Aggregator (kommt automatisch bei uns)
- Manuelle Checks: 2× Tag in der ersten Woche
- Sales-Team aufmerksam machen, falls Kunden anrufen

### 5. Rollback-Plan im Kopf

DNS ist nicht magic — ein TTL-300-Record auf `p=quarantine` zurück und du bist innerhalb von 10 Minuten wieder im sicheren Zustand. **Aber:** bedenke dass empfangende Server zwischenzeitlich gecached haben. Reale Erholung dauert eher 1–2h.

## Der Switch selbst

```dns
# Vorher
_dmarc.deine-firma.ch.  IN TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc@deine-firma.ch; pct=100"

# Nachher
_dmarc.deine-firma.ch.  IN TXT  "v=DMARC1; p=reject; rua=mailto:dmarc@deine-firma.ch; pct=100"
```

Genau ein Wort ändert sich. TTL für die nächsten 7 Tage auf 300 senken, damit du schneller rollbacken kannst.

## Wenn du dich nicht traust

Das ist absolut OK. Viele Firmen bleiben dauerhaft auf `p=quarantine` — der praktische Schutz ist fast gleich, das Risiko aber niedriger. Wir haben Kunden die seit 2 Jahren stabil auf `p=quarantine` laufen und nie `p=reject` brauchten.

`p=reject` lohnt sich vor allem wenn:
- du eine bekannte Marke bist (Phishing-Ziel)
- du BIMI willst (BIMI verlangt `p=quarantine` oder `p=reject`, kein `p=none`)
- Compliance-Druck (NIS2, ISO Audit)

## Was als nächstes

→ [Pass-Rate jetzt checken](/check) deiner Domain (kostenlos)

→ [Mail-Security Foundation Paket](/kontakt?topic=foundation) — wir nehmen dich von `p=none` bis `p=quarantine` mit Monitoring (CHF 1'990)

→ [Pro+ Paket](/kontakt?topic=pro) — inkl. Reise bis `p=reject` und BIMI (CHF 4'990)
