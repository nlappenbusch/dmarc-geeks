---
title: SPF bei Microsoft 365 richtig einrichten
slug: spf-microsoft-365-richtig
description: Wie der SPF-Record für M365 aussehen muss, was die 10-Lookup-Falle ist, und wie du beides ohne dass deine Mails ins Spam rutschen löst.
date: 2026-05-09
author: Nils Lappenbusch
tags: [spf, microsoft-365, m365, setup]
---

## Der Standard-Record reicht selten

Microsoft 365 sagt dir, du sollst diesen SPF-Record setzen:

```dns
v=spf1 include:spf.protection.outlook.com -all
```

Das funktioniert — aber nur wenn ausschliesslich M365 in deinem Namen verschickt. Sobald du **noch einen Drittsender** hinzunimmst (Mailchimp, Brevo, SendGrid, dein Newsletter-Tool, Pipedrive, Salesforce …) wird der Record komplex und gefährlich.

## Die 10-Lookup-Falle

Der SPF-Standard erlaubt **maximal 10 DNS-Lookups** pro Auflösung. Jedes `include:` ist ein Lookup. M365 selbst macht intern schon 1–2. Mailchimp braucht typisch 2. Pipedrive 1. SendGrid 1. Bevor du es merkst hast du 12 Lookups und das SPF wird komplett ignoriert — deine Mails werden behandelt als gäbe es keinen SPF-Record.

### So testest du das

Tool wie [unser Mail-Health-Check](/check) zeigt dir die SPF-Lookup-Anzahl rot, wenn du drüber bist. Oder per CLI:

```bash
dig +short TXT _spf.deine-domain.ch
```

Dann manuell zählen.

## Wie löst man das? SPF-Flattening

**SPF-Flattening** bedeutet: alle `include:`-Mechanismen werden zur Build-Zeit aufgelöst und durch konkrete IP-Adressen ersetzt. Statt 8 includes hast du dann eine Liste von 30 IPs — ein Lookup statt 12.

Beispiel — vorher:

```
v=spf1 include:spf.protection.outlook.com include:servers.mcsv.net include:mailgun.org include:sendgrid.net include:_spf.brevo.com -all
```

Nachher:

```
v=spf1 ip4:40.92.0.0/15 ip4:40.107.0.0/16 ip4:52.100.0.0/14 ip4:198.2.128.0/18 ip4:148.105.0.0/16 [usw...] -all
```

**Vorsicht:** Drittsender ändern ihre IPs gelegentlich. Wenn du flattest, brauchst du einen **Monitoring-Mechanismus** der bei Drift den Record updated. Kein Set-and-Forget.

## Pragmatische Alternative ohne Flattening

Wenn dein Setup nicht zu komplex ist, kannst du auch:

1. **Marketing-Subdomain trennen:** Newsletter senden über `news.deine-domain.ch`, transaktional über die Hauptdomain. Zwei separate SPF-Records mit weniger Lookups pro Domain.
2. **DKIM stärken statt SPF:** wenn DKIM sauber signiert, ist das Alignment-relevante Signal. SPF wird zweitrangig.

## Die Soft-Fail-vs-Hard-Fail-Frage

Am Ende steht entweder `~all` (Soft-Fail) oder `-all` (Hard-Fail).

- `~all`: empfangende Server *sollten* nicht-listete Sender als verdächtig markieren, aber Mail trotzdem zustellen
- `-all`: empfangende Server *sollten* Mail von nicht-listeten Sendern ablehnen

Für DMARC-Compliance ist beides ok — DMARC bewertet das Alignment, nicht den SPF-Strict-Mode direkt. Empfehlung: **mit `~all` starten**, nach 30 Tagen Monitoring auf `-all` wechseln wenn keine legitimen Sender im Auspuff sind.

## Was du jetzt tun kannst

→ [Sieh wie dein SPF aktuell aussieht](/check) — kostenlos, in 5 Sekunden Lookup-Counter inkl.

→ Wenn der Counter über 8 steht: [Audit-Buchung CHF 490](/kontakt?topic=audit) — wir machen Inventur deiner Sender und liefern einen Flatten- oder Subdomain-Split-Plan.
