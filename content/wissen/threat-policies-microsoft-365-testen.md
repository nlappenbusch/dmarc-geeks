---
title: Threat Policies in Microsoft 365 testen — so prüfst du, ob dein Mailfilter wirklich greift
slug: threat-policies-microsoft-365-testen
description: Anti-Spam, Anti-Malware, Anti-Phishing und Safe Links sind konfiguriert — aber greifen sie auch? Mit harmlosen Teststrings (EICAR, GTUBE, AMTSO) und einer festen Testmatrix prüfst du deinen Filter reproduzierbar.
date: 2026-10-13
author: Nils Lappenbusch
tags: [microsoft-365, m365, defender, threat-policies, eop, quarantäne, gateway]
---

Ein Defender-Portal voller grüner Häkchen sagt dir nur, dass Policies **existieren**. Ob sie bei einer echten Mail auch **greifen**, ist eine andere Frage. Policies haben Prioritäten, Preset-Policies überlagern eigene Policies, Ausnahmen wirken breiter als gedacht — und sobald ein Gateway vor Microsoft 365 sitzt, filtern zwei Systeme hintereinander, die sich gegenseitig beeinflussen.

Die einzige belastbare Antwort ist ein Test: definierte Mails von aussen schicken, nachsehen, wo sie landen, und das Ergebnis dokumentieren. Hier ist, wie du das machst.

## Spielregeln für einen sauberen Test

1. **Keine echte Schadsoftware.** Es gibt für genau diesen Zweck harmlose Industrie-Teststrings: EICAR für Virenscanner, GTUBE für Spamfilter. Scanner erkennen sie, als wären sie gefährlich — sie sind es aber nicht.
2. **Von aussen senden.** Interne Mails nehmen einen anderen Weg durch den Filter als Mails aus dem Internet. Der Test muss über den MX kommen, genau wie ein Angriff.
3. **Nur an eigene Postfächer.** Testmails an fremde Adressen sind keine Tests, sondern Spam.
4. **Immer mit Kontrollfall.** Eine saubere Mail ohne Payload zeigt, dass die Zustellung überhaupt funktioniert. Ohne sie weisst du bei einer fehlenden Mail nicht, ob der Filter gegriffen hat oder die Zustellung kaputt ist.
5. **Wiederholbar.** Gleiche Fälle, gleiche Benennung, vor und nach jeder Änderung.

## Die Testmatrix

Diese Fälle decken die wichtigsten Pfade von Exchange Online Protection (EOP) und Defender for Office 365 ab:

| Fall | Testet | Erwartung |
|---|---|---|
| Kontrollmail | Zustellung an sich | Posteingang |
| GTUBE im Body | Anti-Spam | Junk-Ordner oder Quarantäne, je nach Spam-Aktion |
| EICAR als `.txt` / `.com` | Anti-Malware, Signaturerkennung | Malware-Quarantäne |
| EICAR in `.zip` | Archiv-Scan | Malware-Quarantäne |
| EICAR in ZIP-in-ZIP | Scan-Tiefe verschachtelter Archive | Quarantäne — wenn zugestellt: Lücke |
| EICAR in Passwort-ZIP | Umgang mit nicht scanbaren Inhalten | Policy-Entscheid: Quarantäne oder Zustellung |
| Harmlose `.exe`, `.js`, `.hta` | Filter für gängige Anhangstypen | Blockiert/Quarantäne allein wegen Dateityp |
| Doppel-Endung `rechnung.pdf.exe` | Getarnte Dateitypen | Blockiert/Quarantäne |
| Link im Body | Safe Links | Zustellung, Link auf `safelinks.protection.outlook.com` umgeschrieben |
| AMTSO-Phishing-Testseite als Link | URL-Reputation, Anti-Phishing | Phishing-Verdikt — nicht deterministisch |
| Gefälschter `From:` deiner Domain | Spoof-Erkennung, DMARC | Junk, Quarantäne oder Reject — je nach DMARC-Policy |
| Anzeigename der Chefin, fremde Adresse | User-Impersonation | Quarantäne — nur mit Defender for Office 365 |

Zwei Hinweise zur Ehrlichkeit: Der AMTSO-Link ist eine vendor-neutrale, sichere Testseite der Anti-Malware Testing Standards Organization. Ob Microsoft sie als Phishing einstuft, hängt von der URL-Reputation zum Zeitpunkt des Tests ab — also kein harter Pass/Fail-Fall. Und Teststrings wie «GTPHISH» sind keine offiziellen Microsoft-Trigger; landen solche Mails «nur» als Spam, ist das kein Fehler deiner Policy.

## Wo du die Ergebnisse siehst

**Quarantäne:** im Defender-Portal unter `security.microsoft.com/quarantine`. Dort steht auch der Grund (Malware, Spam, Phishing, Impersonation).

**Nachrichtenkopf:** Für alles, was zugestellt wurde, ist der Header die Wahrheit. Die wichtigsten Felder im `X-Forefront-Antispam-Report`:

```text
SFV:SPM      Spamfilter hat die Mail als Spam bewertet
CAT:SPM      Kategorie Spam  (HSPM = hochwahrscheinlich Spam)
CAT:PHSH     Phishing        (HPHSH = hochwahrscheinlich Phishing)
SCL:5        Spam Confidence Level
```

Dazu im `Authentication-Results`-Header `spf=`, `dkim=`, `dmarc=` und `compauth=`. Am bequemsten liest du das mit dem Message Header Analyzer von Microsoft.

**Nachrichtenablaufverfolgung:** Für Mails, die nie aufgetaucht sind, zeigt die Message Trace im Exchange Admin Center, ob die Mail abgelehnt, in Quarantäne gelegt oder gar nicht erst angekommen ist.

## Impersonation: der Fall, der am häufigsten «nicht greift»

User-Impersonation-Schutz («Chef-Masche») gibt es nur in **Defender for Office 365**, nicht im Basisschutz. Und er greift erst, wenn du ihn konfigurierst:

- Die zu schützenden Absender stehen in der Anti-Phishing-Policy unter «Users to protect» — maximal **350 pro Policy**.
- Die Standardaktion für erkannte User-Impersonation ist **«Don't apply any action»**. Wer sie nicht auf Quarantäne stellt, sieht im Test nur einen Sicherheitshinweis — oder gar nichts.
- Mit aktivierter Mailbox Intelligence greift der Schutz nicht, wenn Absender und Empfänger schon miteinander korrespondiert haben. Teste also mit einer Absenderadresse, die das Zielpostfach noch nie gesehen hat.

## Spoofing und DMARC

Der Spoof-Test zeigt, ob Microsoft die DMARC-Policy einer Absenderdomain respektiert. Gesteuert wird das in der Anti-Phishing-Policy über «Honor DMARC record policy when the message is detected as spoof». Mit `p=reject` auf der gefälschten Domain kann die Mail abgelehnt werden — oder in Quarantäne landen, je nach gewählter Aktion.

**Mit Gateway vor Microsoft 365** gilt: Diese Einstellung wirkt nur, wenn Enhanced Filtering for Connectors auf dem Gateway-Connector aktiv ist. Mehr dazu in [Mail-Gateway vor Microsoft 365](/blog/mail-gateway-vor-microsoft-365-dmarc-spf-dkim).

## Der Threat-Test von DMARC Geeks

Die Matrix oben musst du nicht von Hand bauen. Unter [dmarc-geeks.ch/threattest](/threattest) verschickt unser Threat-Test genau diese Fälle an ein Postfach deiner Wahl:

- **Fälle auswählen**, Zielpostfach eintragen. Spoof- und Impersonation-Fall sind optional und brauchen eine Absenderadresse bzw. einen Anzeigenamen.
- **Bestätigungscode:** Bevor ein einziger Testfall rausgeht, bekommt das Zielpostfach einen Code (30 Minuten gültig). Erst nach der Bestätigung startet der Versand. So kann niemand fremde Postfächer beschiessen.
- **Eindeutig markiert:** Jede Mail trägt im Betreff `[M365-TEST][Lauf-ID][Fall]` und die Header `X-M365Test-Run` und `X-M365Test-Case`. In Quarantäne und Message Trace findest du so jeden Fall sofort.
- **Harmlos:** nur EICAR-, GTUBE- und AMTSO-Teststrings bzw. harmlose Dateien mit auffälliger Endung.

Was das Tool bewusst **nicht** kann: in dein Postfach schauen. Wo die Mails gelandet sind, siehst du im eigenen Portal. Das ist Absicht — wir brauchen keinen Zugriff auf deinen Tenant.

## Vor und nach dem Gateway-Wechsel

Besonders wertvoll ist die Testmatrix bei Änderungen am Mailfluss: neues Gateway, MX-Wechsel, Umstellung auf Preset-Policies. Lass dieselben Fälle **vorher und nachher** laufen und vergleiche:

- Landet EICAR-im-ZIP jetzt beim Gateway in Quarantäne statt bei Microsoft? Dann weisst du, welche Stufe filtert — und wo Benutzer ihre Quarantäne-Mails künftig suchen.
- Kommt der Spoof-Fall plötzlich durch? Dann fehlt vermutlich Enhanced Filtering.
- Ist der Safe-Links-Fall nicht mehr umgeschrieben? Dann schreibt vielleicht das Gateway selbst um, oder die Mail nimmt einen anderen Weg.

## Was ein solcher Test nicht ersetzt

Teststrings prüfen Konfiguration, nicht Erkennungsqualität. Ob unbekannte Malware in der Sandbox von Safe Attachments auffällt, zeigt EICAR nicht — EICAR wird schon an der Signatur erkannt. Und ob Mitarbeitende auf einen echten Phishing-Link klicken, ist ein Fall für Awareness-Trainings, nicht für Policy-Tests.

## Was als nächstes

→ [Threat-Test starten](/threattest) — Testmatrix an dein eigenes Postfach (kostenlos, mit Bestätigungscode)

→ [Mail-Tester](/mailtest) — die Gegenrichtung: wie sehen Empfänger *deine* Mails?

→ [M365 Threat-Hardening](/services/m365) — Policies auf Strict-Niveau, dokumentiert und getestet
