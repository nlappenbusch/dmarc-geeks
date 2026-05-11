---
title: DMARC — warum überhaupt? Erklärung für Geschäftsführer.
slug: dmarc-warum-ueberhaupt
description: Was DMARC für dein Unternehmen bedeutet, ohne Tech-Jargon. Plus die 3 konkreten Risiken wenn du es nicht hast.
date: 2026-05-10
author: Nils Lappenbusch
tags: [dmarc, basics, geschäftsführer]
---

## Die Kurzfassung in 30 Sekunden

DMARC sagt empfangenden Mail-Servern (Gmail, Microsoft 365, Yahoo …) **wer in deinem Namen Mails verschicken darf** und **was sie mit Fälschungen machen sollen** (durchlassen, in Spam stecken, ablehnen). Ohne DMARC kann praktisch jeder beliebige Person eine E-Mail unter `name@deine-firma.ch` verschicken — und sie kommt oft trotzdem zugestellt.

## Drei konkrete Risiken wenn du es nicht hast

### 1. Phishing in deinem Namen
Angreifer schicken Mails an deine Kunden, dein Logo unten, "Bitte hier klicken um die Rechnung zu bezahlen". Der Kunde glaubt, das kommt von dir. Wenn der dann auf einen Phishing-Link klickt, **trägt der Reputationsschaden deinen Namen**. Mit DMARC `p=reject` werden solche Mails von Gmail & Co. einfach abgelehnt.

### 2. Schlechte Zustellrate für deine echten Mails
Google und Yahoo haben 2024 die DMARC-Anforderungen verschärft. Wenn du **viel Mail-Volumen hast** (Newsletter, Transactional-Mails, Rechnungen) und kein DMARC, landen immer mehr deiner echten Mails im Spam. Statistik: ~25 % Zustellrate-Verlust ist normal.

### 3. Compliance-Lücke bei Audits
**NIS2** (Schweizer Cybersicherheitsgesetz ab 2026), **ISO 27001 Annex A.8**, **DSG/DSGVO Art. 32** — alle verlangen "angemessene Sicherheitsmassnahmen für Mail-Kommunikation". DMARC ist Stand der Technik. Ohne es: bei einem Vorfall hast du in der Pflichtdokumentation einen weissen Fleck.

## Was du als GF konkret brauchst

- **SPF-Record**: Liste der Server die in deinem Namen senden dürfen
- **DKIM-Signatur**: kryptographischer Stempel auf jeder Mail
- **DMARC-Policy**: was passiert mit Fälschungen, plus eine Adresse wohin Reports kommen
- **DMARC-Aggregator**: jemand der die Reports liest und in lesbare Form bringt (XML ist unbrauchbar)

Punkt 1–3 sind DNS-Einstellungen. Punkt 4 ist ein Tool (oder ein Dienstleister).

## Wer macht das?

Entweder dein IT-Verantwortlicher (mit ~1 Woche Einarbeitung) oder ein Dienstleister wie wir. Wir bieten das als [Mail-Health-Audit (CHF 490)](/kontakt?topic=audit) an — du weisst danach genau, wo du stehst, und kannst entscheiden was als nächstes passiert.

## Was als nächstes?

→ [Mail-Health-Check kostenlos für deine Domain](/check) — siehst in 5 Sekunden ob du DMARC schon hast und wie sauber es konfiguriert ist.

→ [Mail-Health-Audit buchen (CHF 490)](/kontakt?topic=audit) — wir machen einen vollständigen Befund deines Setups in 1 Tag und liefern dir eine konkrete Roadmap.
