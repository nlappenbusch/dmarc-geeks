---
title: Ablösung des Mail-Gateways — DMARC-Reports als Frühwarnsystem
slug: gateway-abloesung-dmarc-reports-fruehwarnsystem
description: Beim Wechsel des Mail-Gateways brechen selten die grossen Systeme, sondern der Scanner im Keller und das ERP mit SMTP-Relay. Wie du mit DMARC-Aggregate-Reports vor, während und nach dem Cutover siehst, was kaputtgeht — und warum p=reject erst danach kommt.
date: 2026-10-13
author: Nils Lappenbusch
tags: [dmarc, gateway, migration, monitoring, reject, spf, dkim]
---

Ein altes Mail-Gateway abzulösen klingt nach einem Infrastrukturthema: neuer Anbieter, neuer MX, Connector umbiegen, alte Appliance abschalten. In der Praxis ist es ein **Inventurthema**. Ein Gateway, das seit Jahren läuft, hat Aufgaben übernommen, die niemand mehr auf dem Schirm hat — und genau diese Aufgaben fallen beim Abschalten weg.

Die gute Nachricht: Wenn du DMARC-Reports sammelst, hast du bereits ein Messinstrument, das dir genau diese vergessenen Absender zeigt. Aus Sicht der Empfänger, unabhängig von deiner eigenen Logfile-Lage.

## Was DMARC-Reports hier leisten

Jeder grössere Mailanbieter, der DMARC auswertet, schickt dir auf Wunsch (`rua=` im DMARC-Record) einen **Aggregate-Report**: welche IP-Adressen in den letzten 24 Stunden mit deiner Domain im `From:` gesendet haben, wie viele Mails, und ob SPF und DKIM bestanden haben und zur Domain passen (Alignment). Das Standard-Intervall nach RFC 7489 ist ein Tag.

Damit siehst du:

- **jede Quelle**, die in deinem Namen sendet — auch die, die niemand dokumentiert hat,
- **ob sie authentifiziert ist**, und wenn nicht, ob SPF oder DKIM das Problem ist,
- **Veränderungen über die Zeit** — neue Quellen, verschwundene Quellen, steigende Fehlerquoten.

Genau das braucht ein Gateway-Wechsel.

## Wer beim Wechsel typischerweise bricht

Nicht Microsoft 365 selbst. Das ist meist sauber dokumentiert. Brechen tun die Randsysteme:

| Absender | Warum er bricht |
|---|---|
| **Multifunktionsgeräte, Scanner** | senden per SMTP-Relay über das alte Gateway, das bald weg ist |
| **ERP, Branchensoftware, Fachanwendungen** | eingetragener Smarthost ist das alte Gateway |
| **Monitoring, USV, Firewalls, Backup-Server** | Alarmmails über das alte Relay — fällt erst auf, wenn ein Alarm fehlt |
| **Mails mit DKIM-Signatur des alten Gateways** | Selektor wird mit dem alten Anbieter gelöscht |
| **Ausgehende Mails mit Disclaimer vom neuen Gateway** | Banner verändert den Body, die Microsoft-DKIM-Signatur bricht |
| **SPF-Record mit Include des alten Anbieters** | wird entfernt, bevor der letzte Absender umgestellt ist |

Externe SaaS-Dienste (Newsletter, CRM, Ticketsystem) senden meist direkt und sind vom Gateway-Wechsel nicht betroffen. Meist — prüfen musst du es trotzdem, weil manche Integrationen bewusst über den eigenen Relay laufen.

## Phase 1: Vor dem Cutover — die Ausgangslage messen

Bevor sich irgendetwas ändert, brauchst du eine Baseline.

1. **DMARC-Reports sammeln.** Falls noch nicht geschehen: `rua=` setzen und mindestens einige Wochen laufen lassen. So erfasst du auch Absender, die nur wöchentlich oder zum Monatsende senden — Rechnungsläufe, Lohnabrechnungen, Monatsreports.
2. **Quellen klassifizieren.** Jede Quelle aus den Reports bekommt eine von drei Kategorien:
   - *über das alte Gateway* (IP gehört zum alten Anbieter),
   - *direkt* (Microsoft 365, SaaS-Dienste),
   - *unbekannt* — das sind die wichtigsten.
3. **Relay-Nutzer identifizieren.** Die DMARC-Reports zeigen dir nur das Gateway als Quelle, nicht, wer *dahinter* sendet. Dafür brauchst du die Logs des alten Gateways: Welche internen IPs liefern per SMTP ein? Diese Liste ist dein Umstellungs-Backlog.
4. **Policy einfrieren.** Wenn du gerade auf dem Weg von `p=none` zu `p=reject` bist: Pause. Eine Änderung nach der anderen.

In DMARC Geeks hilft dir dabei die Quellen-Ansicht: Absender werden anhand von Reverse-DNS bekannten Anbietern zugeordnet (Microsoft 365, Google, Newsletter-Tools, …). Legitime eigene Server kannst du in die IP-Allowlist eintragen, damit sie im Rauschen nicht untergehen.

## Phase 2: Während des Cutovers — parallel statt hart

Ein Gateway-Wechsel gelingt am zuverlässigsten, wenn alt und neu eine Weile parallel gelten dürfen:

- **MX-TTL vorher senken**, damit die Umstellung schnell greift und schnell rückgängig gemacht werden kann.
- **SPF mit beiden Gateways.** Altes und neues Include parallel, bis die Reports zeigen, dass über das alte nichts mehr kommt. Die [10-Lookup-Grenze](/blog/spf-microsoft-365-richtig) im Auge behalten.
- **DKIM-Selektoren parallel.** Den Selektor des alten Gateways erst löschen, wenn in den Reports keine Signatur mit diesem Selektor mehr auftaucht. Den neuen Selektor vor dem ersten produktiven Versand veröffentlichen.
- **Relay-Nutzer einzeln umstellen** — Scanner, ERP, Monitoring — und jede Umstellung mit einer Testmail an den [Mail-Tester](/mailtest) belegen.
- **MTA-STS beachten**, falls aktiv: Neue MX-Hosts müssen *vor* dem Cutover in die Policy. Details im Artikel zu [MTA-STS und TLS-RPT](/blog/mta-sts-tls-rpt-einrichten).

Die Aggregate-Reports kommen mit Verzögerung — typischerweise ein Tag Berichtszeitraum plus Versandzeit. Für die ersten Stunden nach dem Cutover brauchst du deshalb schnellere Signale: Message Trace in Exchange Online, die Logs des neuen Gateways und gezielte Testmails. Die DMARC-Reports sind dein **Netz unter dem Netz**: Sie zeigen dir in den Folgetagen, was durch die direkte Kontrolle gerutscht ist.

## Phase 3: Nach dem Cutover — beobachten, dann verschärfen

Jetzt arbeiten die Reports für dich. Worauf du achtest:

- **Neue Quelle aus deinem eigenen IP-Bereich mit SPF-Fail und DKIM-Fail** → ein Gerät oder eine Anwendung, die nach dem Wegfall des alten Relays direkt ins Internet sendet. Umstellen auf den neuen Relay-Weg.
- **Neues Gateway mit SPF-Fail** → ausgehender Verkehr läuft schon über das neue Gateway, dessen IPs fehlen aber noch im SPF-Record.
- **Neues Gateway mit DKIM-Fail** → das Gateway verändert Mails nach der Microsoft-Signatur (Disclaimer, Banner) und signiert nicht selbst mit deiner Domain.
- **Alte Gateway-IPs tauchen weiter auf** → irgendetwas sendet noch über die alte Infrastruktur. Nicht abschalten, bevor das geklärt ist.

DMARC Geeks verschickt einen **Spike-Alarm**, wenn die Fehlerquote einer Domain in den letzten 24 Stunden deutlich über der der Vorwoche liegt. Standardmässig bei einem Anstieg um 10 Prozentpunkte und erst ab 100 Nachrichten pro Zeitraum, damit kleine Domains keinen Fehlalarm auslösen. Schwelle und Mindestvolumen sind pro Mandant einstellbar. In der Woche nach einem Cutover ist genau dieser Alarm Gold wert.

## Erst danach: p=quarantine und p=reject

Die Versuchung ist gross, den Gateway-Wechsel gleich mit «und jetzt DMARC auf reject» zu verbinden. Tu es nicht. Zwei gleichzeitige Änderungen bedeuten: Wenn Mails verschwinden, weisst du nicht, welche schuld ist. Und bei `p=reject` verschwinden sie wirklich — der Empfänger lehnt ab, es gibt keinen Spam-Ordner zum Zurückholen.

Die Reihenfolge:

1. Gateway-Wechsel abschliessen, altes Gateway abschalten.
2. Reports beobachten, bis die Quellenliste stabil ist und alle eigenen Quellen aligned bestehen. Mindestens über einen kompletten Monatszyklus, damit auch seltene Absender erfasst sind.
3. Dann den Weg über `p=quarantine` zu `p=reject` gehen — wie in [Von p=quarantine zu p=reject](/blog/dmarc-quarantine-zu-reject-migrieren) beschrieben.

Ein Hinweis zum Standard: DMARC ist 2026 mit RFC 9989 neu gefasst worden und ersetzt RFC 7489. Der `pct`-Tag für die schrittweise Einführung ist dort entfallen; stattdessen gibt es `t=y` als Testmodus, bei dem Empfänger eine Stufe milder handeln sollen. Bestehende `v=DMARC1`-Records bleiben gültig. Plane trotzdem nicht damit, dass jeder Empfänger `pct` oder `t` gleich auswertet — die saubere Vorbereitung ersetzt keiner der beiden Tags.

## Die Kurzfassung

| Phase | Was die DMARC-Reports dir sagen |
|---|---|
| Vorher | wer in deinem Namen sendet — inklusive der Vergessenen |
| Während | ob alte und neue Wege beide sauber authentifiziert sind |
| Nachher | was durch die Umstellung gebrochen ist, bevor es ein Kunde meldet |
| Danach | ob die Datenlage für `p=reject` reicht |

## Was als nächstes

→ [Live-Demo ansehen](/demo) — Quellen, Alignment und Verlauf mit Beispieldaten, ohne Anmeldung

→ [Mail-Gateway vor Microsoft 365](/blog/mail-gateway-vor-microsoft-365-dmarc-spf-dkim) — Enhanced Filtering, ARC und DKIM beim MX-Wechsel

→ [Gateway-Wechsel mit DMARC-Monitoring begleiten lassen](/kontakt?topic=dmarc-reise) — von der Inventur bis `p=reject`
