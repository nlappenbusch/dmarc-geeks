---
title: Mail-Gateway vor Microsoft 365 — was DMARC, SPF und DKIM beim MX-Wechsel brauchen
slug: mail-gateway-vor-microsoft-365-dmarc-spf-dkim
description: Wenn der MX nicht mehr direkt auf Exchange Online zeigt, ändern sich SPF, DKIM und DMARC — inbound wie outbound. Enhanced Filtering for Connectors, ARC, Gateway-Signaturen und Weiterleitungen sauber gelöst.
date: 2026-10-13
author: Nils Lappenbusch
tags: [gateway, microsoft-365, m365, spf, dkim, dmarc, arc, migration]
---

Ein vorgelagertes Mail-Gateway vor Microsoft 365 ist Alltag: Archivierung, Verschlüsselung, ein zusätzlicher Filter, oder schlicht ein Anbieter, der das Paket «Mail-Security» als Managed Service liefert. Technisch ist der Wechsel schnell erledigt — MX umstellen, Connector anlegen, fertig. Was dabei regelmässig kaputtgeht, ist die **Mail-Authentifizierung**. Und zwar in beide Richtungen.

Dieser Artikel geht die drei Stellen durch, an denen ein Gateway SPF, DKIM und DMARC beeinflusst: eingehend, ausgehend und bei Weiterleitungen.

## Das Grundproblem: Exchange Online sieht nur noch das Gateway

Ohne Gateway nimmt Exchange Online die Mail direkt vom sendenden Server an. Es sieht dessen IP-Adresse, prüft sie gegen den SPF-Record der Absenderdomain, prüft die DKIM-Signatur und wertet DMARC aus.

Mit Gateway sieht Exchange Online nur noch die **letzte Station** — also das Gateway. Das ist kein Fehler von Microsoft, so funktioniert SMTP. Die Folgen:

| Prüfung | Ohne Gateway | Mit Gateway (ohne Anpassung) |
|---|---|---|
| **SPF des Absenders** | gegen die echte Absender-IP | gegen die Gateway-IP → schlägt fehl |
| **DKIM des Absenders** | intakt | bricht, sobald das Gateway den Inhalt ändert |
| **DMARC** | sauber auswertbar | fällt durch, weil SPF und DKIM fehlschlagen |
| **Spoof- und Phishing-Erkennung** | volle Datenbasis | arbeitet mit der falschen Quelle |

Ohne Gegenmassnahme hast du also zwei Filter hintereinander, von denen der zweite (Exchange Online Protection bzw. Defender for Office 365) halb blind ist.

## Inbound: Enhanced Filtering for Connectors

Microsoft hat dafür eine eigene Funktion: **Enhanced Filtering for Connectors**, auch *Skip Listing* genannt. Sie sagt Exchange Online: «Die IP des Gateways ist nicht die echte Quelle — schau eine Station weiter zurück.» Damit wird die Authentifizierung wieder **explizit** anhand der SPF-, DKIM- und DMARC-Records der Absenderdomain ausgewertet.

Konfiguriert wird das auf dem Inbound-Connector des Gateways — im Defender-Portal unter *Email & Collaboration → Policies & Rules → Threat policies → Enhanced filtering* oder per PowerShell:

```powershell
# Erst mit einigen Pilot-Postfächern testen
Set-InboundConnector -Identity "Von Gateway" `
  -EFSkipLastIP $true `
  -EFUsers "pilot1@deine-firma.ch","pilot2@deine-firma.ch"

# Danach für die ganze Organisation (EFUsers leeren)
Set-InboundConnector -Identity "Von Gateway" -EFSkipLastIP $true -EFUsers $null
```

Wenn dein Gateway über mehrere Hops mit öffentlichen IPs läuft, nimmst du statt `-EFSkipLastIP` eine explizite Liste mit `-EFSkipIPs`.

Worauf du achten musst:

- **Pilot zuerst.** `EFUsers` wirkt nur auf die exakt angegebenen Adressen — Aliase zählen einzeln. Und nur, wenn *alle* Empfänger einer Mail in der Liste stehen.
- **SCL-−1-Regeln abschalten.** Viele Gateway-Anleitungen empfehlen eine Transportregel «Spamfilter umgehen» für Mails vom Gateway. Mit Enhanced Filtering soll diese Regel laut Microsoft deaktiviert werden — sonst hebelst du die zweite Filterstufe wieder aus.
- **Keine privaten IPs.** RFC-1918-Adressen und Loopback werden nicht unterstützt (bzw. automatisch übersprungen). Ein Gateway hinter NAT braucht eine öffentliche Absender-IP.
- **Nur für Gateways *vor* Microsoft 365.** Für Dienste, die *nach* Exchange Online scannen, ist die Funktion nicht gedacht.
- **Kontrolle im Header.** Wenn es greift, steht in der Mail `X-MS-Exchange-ExternalOriginalInternetSender` mit der echten Quelle.

Ein Detail, das gern übersehen wird: Die Einstellung **«Honor DMARC record policy»** in der Anti-Phishing-Policy greift bei einem vorgelagerten Gateway **nur**, wenn Enhanced Filtering auf dem Connector aktiv ist. Ohne Skip Listing ignoriert Microsoft also faktisch das `p=reject` fremder Domains.

### Den Connector abriegeln

Wenn der MX auf das Gateway zeigt, sollte auch nur das Gateway direkt bei Exchange Online einliefern dürfen. Angreifer kennen die `*.mail.protection.outlook.com`-Adresse deines Tenants und können das Gateway sonst einfach umgehen. Lösung: den Partner-Inbound-Connector auf die IP-Adressen oder das TLS-Zertifikat des Gateways einschränken (`-RestrictDomainsToIPAddresses` bzw. `-RestrictDomainsToCertificate` am Inbound-Connector). Die genauen IPs bzw. den Zertifikatsnamen liefert der Gateway-Anbieter.

## ARC: wenn das Gateway Mails verändert

Viele Gateways verändern eingehende Mails: Betreff-Markierung `[EXTERN]`, Warnbanner im Body, umgeschriebene Links, entfernte Anhänge. Jede dieser Änderungen bricht die DKIM-Signatur des Absenders.

Hier hilft **ARC** (Authenticated Received Chain). Das Gateway hält das ursprüngliche Prüfergebnis in einer signierten Kette fest (`ARC-Seal`, `ARC-Message-Signature`, `ARC-Authentication-Results`). Microsoft 365 kann dieses Ergebnis übernehmen — aber nur von **vertrauenswürdigen ARC-Sealern**, die du explizit einträgst:

```powershell
Get-ArcConfig
# Achtung: ersetzt die bestehende Liste komplett
Set-ArcConfig -Identity Default -ArcTrustedSealers "gateway-anbieter.example"
```

Der Wert ist **nicht** deine eigene Domain, sondern der `d=`-Wert aus dem `ARC-Seal`-Header des Gateways. Am einfachsten: Testmail durchschicken, Header öffnen, `d=` ablesen. Ob es funktioniert, siehst du im Header `ARC-Authentication-Results` an `arc=pass` und `oda=1`, und in `Authentication-Results` an `compauth=pass reason=130`.

Zwei Grenzen: ARC überschreibt nur DMARC-Fehler, keine Spam-Bewertung. Und ARC hilft nur, wenn das Gateway **nach** seinen Änderungen versiegelt. Kann dein Gateway kein ARC, bleibt Enhanced Filtering der Weg.

## Outbound: SPF und DKIM über das Gateway

Viele Gateway-Projekte routen auch den ausgehenden Verkehr über das Gateway — für Verschlüsselung, Disclaimer, DLP oder Archivierung. Dann schickt Exchange Online über einen Outbound-Connector (Smart Host) ans Gateway, und das Gateway liefert an die Empfänger aus.

### SPF

Der Empfänger sieht jetzt die IP des Gateways. Die `MAIL FROM`-Adresse bleibt aber deine Domain. Also muss das Gateway in **deinen** SPF-Record:

```dns
; Vorher
deine-firma.ch.  IN TXT  "v=spf1 include:spf.protection.outlook.com -all"

; Nachher (Gateway-Include vom Anbieter)
deine-firma.ch.  IN TXT  "v=spf1 include:spf.protection.outlook.com include:spf.gateway-anbieter.example -all"
```

Den Microsoft-Include behältst du, solange noch irgendetwas direkt aus Exchange Online rausgeht — zum Beispiel, weil der Connector nur für einen Teil der Domains oder Empfänger gilt. Und denk an die [10-Lookup-Grenze von SPF](/blog/spf-microsoft-365-richtig): jedes `include:` zählt.

### DKIM

Exchange Online signiert ausgehende Mails, **bevor** sie zum Gateway gehen. Solange das Gateway nichts am Inhalt ändert, bleibt die Signatur gültig. Sobald es aber einen Disclaimer, eine zentrale Signatur oder einen Banner anhängt, ist die Microsoft-Signatur kaputt.

Dann gibt es zwei saubere Wege:

1. **Das Gateway signiert selbst** — mit einem eigenen Selektor unter deiner Domain (`d=deine-firma.ch`). Den öffentlichen Schlüssel veröffentlichst du als TXT- oder CNAME-Record, den der Anbieter vorgibt. Mehrere Selektoren parallel sind kein Problem.
2. **Das Gateway verändert nichts** — Disclaimer und Signaturen werden dann in Exchange Online gesetzt, vor der Signatur.

Wichtig ist das **Alignment**: Für DMARC zählt nur eine DKIM-Signatur, deren `d=` zur Domain im sichtbaren `From:` passt. Eine Signatur mit `d=gateway-anbieter.example` ist zwar gültig, hilft deinem DMARC aber nicht.

Ob das Ergebnis stimmt, prüfst du in einer Minute mit dem [Mail-Tester](/mailtest): Mail an die angezeigte Testadresse schicken, und du siehst SPF, DKIM und DMARC so, wie ein externer Empfänger sie sieht.

## Weiterleitungen

Weiterleitungen sind der Klassiker für DMARC-Fehlalarme, auch ohne Gateway (siehe [Weiterleiten oder umleiten?](/blog/mail-weiterleiten-vs-umleiten)). Mit Gateway kommen zwei Aspekte dazu:

- **Automatische Weiterleitung aus Exchange Online nach extern:** Microsoft schreibt dabei die Envelope-Adresse per Sender Rewriting Scheme (SRS) um, damit SPF beim Ziel nicht an deiner Domain scheitert. DMARC hängt dann an DKIM — und DKIM überlebt nur, wenn unterwegs niemand den Inhalt ändert. Läuft die Weiterleitung über ein Gateway, das Banner oder Disclaimer einfügt, bricht genau diese Signatur.
- **Weiterleitungen *ins* Gateway:** Wenn Mails von externen Systemen erst an eine Adresse beim Gateway und dann weiter zu Exchange Online gehen, gilt wieder dasselbe wie oben: Enhanced Filtering für die Gateway-IPs, ARC wo möglich.

## Die Checkliste für den MX-Wechsel

| Bereich | Massnahme |
|---|---|
| Inbound | Enhanced Filtering for Connectors auf dem Gateway-Connector, erst Pilot, dann alle |
| Inbound | SCL-−1-Transportregeln für das Gateway deaktivieren |
| Inbound | Inbound-Connector auf Gateway-IPs oder -Zertifikat einschränken |
| Inbound | ARC-Sealer des Gateways als vertrauenswürdig eintragen (falls ARC unterstützt) |
| Outbound | Gateway in den SPF-Record, Lookup-Grenze prüfen |
| Outbound | DKIM: Gateway signiert mit eigenem Selektor unter deiner Domain — oder ändert nichts |
| Outbound | Testmail an den [Mail-Tester](/mailtest), SPF/DKIM/DMARC prüfen |
| Monitoring | DMARC-Reports vor, während und nach dem Cutover beobachten |
| Policy | DMARC-Policy nicht gleichzeitig mit dem MX-Wechsel verschärfen |

Der letzte Punkt verdient einen eigenen Artikel: [Ablösung des Mail-Gateways — DMARC-Reports als Frühwarnsystem](/blog/gateway-abloesung-dmarc-reports-fruehwarnsystem).

## Was als nächstes

→ [Domain jetzt prüfen](/check) — SPF, DKIM, DMARC, MX, MTA-STS und TLS-RPT auf einen Blick (kostenlos)

→ [Threat Policies in Microsoft 365 testen](/blog/threat-policies-microsoft-365-testen) — prüfen, ob der Filter nach dem Wechsel noch greift

→ [Gateway-Wechsel begleiten lassen](/kontakt?topic=m365-threat) — Connector, Enhanced Filtering, ARC und DMARC in einem Durchgang
