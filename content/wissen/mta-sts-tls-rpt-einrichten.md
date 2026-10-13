---
title: TLS-Verschlüsselung für E-Mail erzwingen — MTA-STS und TLS-RPT einrichten
slug: mta-sts-tls-rpt-einrichten
description: STARTTLS ist nur ein Angebot, das ein Angreifer streichen kann. Mit MTA-STS (RFC 8461) erzwingst du TLS für eingehende Mails, mit TLS-RPT (RFC 8460) siehst du, wo es hakt. DNS-Einträge, Policy-Datei, testing vs. enforce.
date: 2026-10-13
author: Nils Lappenbusch
tags: [mta-sts, tls-rpt, tls, verschlüsselung, dns, microsoft-365, setup]
---

Zwischen Mailservern läuft heute fast alles verschlüsselt — aber nur **opportunistisch**. Der empfangende Server bietet `STARTTLS` an, der sendende nimmt es an. Fehlt das Angebot, wird eben unverschlüsselt zugestellt. Ein Angreifer im Netzwerkpfad muss das Angebot nur aus der Antwort streichen, und schon geht die Mail im Klartext über die Leitung. Ein gefälschtes Zertifikat fällt ebenfalls nicht auf, weil beim Mailversand Zertifikate traditionell nicht geprüft werden.

**MTA-STS** schliesst diese Lücke: Du veröffentlichst, dass deine Domain TLS verlangt und welche Mailserver gültig sind. **TLS-RPT** liefert dir die Rückmeldung, ob das bei den Absendern funktioniert.

## Die drei Bausteine

| Baustein | Wo | Zweck |
|---|---|---|
| TXT `_mta-sts.deine-firma.ch` | DNS | «Diese Domain hat eine MTA-STS-Policy, Version X» |
| `mta-sts.txt` | `https://mta-sts.deine-firma.ch/.well-known/mta-sts.txt` | die eigentliche Policy |
| TXT `_smtp._tls.deine-firma.ch` | DNS | wohin Absender ihre TLS-Reports schicken |

### 1. Der MTA-STS-Record

```dns
_mta-sts.deine-firma.ch.  3600  IN  TXT  "v=STSv1; id=20261013080000Z"
```

`v=STSv1` muss am Anfang stehen. Die `id` ist 1 bis 32 Buchstaben oder Ziffern und markiert die Version deiner Policy. Ändert sich die `id`, holen Absender die Policy neu. Ein bewährtes Muster ist ein UTC-Zeitstempel.

### 2. Die Policy-Datei

```text
version: STSv1
mode: testing
mx: mail.deine-firma.ch
mx: backup-mx.deine-firma.ch
max_age: 604800
```

- `mode`: `testing`, `enforce` oder `none` (dazu gleich mehr).
- `mx`: jeder Mailserver, der Mails für deine Domain annehmen darf. Wildcards sind nur als ganz linkes Label erlaubt (`*.example.net` passt auf `mx1.example.net`, aber nicht auf `a.b.example.net`).
- `max_age`: wie lange Absender die Policy zwischenspeichern, in Sekunden. Maximal 31'557'600 (ein Jahr). Die RFC rechnet mit Werten im Bereich von Wochen; 604800 ist eine Woche.

Die technischen Anforderungen an die Auslieferung sind streng — und genau hier scheitern viele Setups:

- **HTTPS mit gültigem Zertifikat** für `mta-sts.deine-firma.ch`, ausgestellt von einer vertrauenswürdigen CA.
- **Nur HTTP 200 zählt.** Absender folgen **keinen Weiterleitungen**. Ein Redirect von `mta-sts.` auf deine Hauptseite macht die Policy unbrauchbar.
- `Content-Type: text/plain`.
- Zeilen mit CRLF getrennt, Datei klein halten.

Für Exchange Online gilt eine Besonderheit: Microsoft hostet die Policy-Datei nicht für dich. Du brauchst einen eigenen Webserver, einen statischen Hoster oder z. B. eine Azure Static Web App. Zeigt dein MX direkt auf Exchange Online, lautet die `mx`-Zeile laut Microsoft:

```text
mx: *.mail.protection.outlook.com
```

Das ist ausdrücklich nur für Exchange Online gedacht. Sitzt ein Gateway vor Microsoft 365, gehören **die MX-Hosts des Gateways** in die Policy — und der Gateway-Anbieter muss gültige Zertifikate für diese Hostnamen ausliefern. Frag das vor dem Umstieg explizit nach.

### 3. Der TLS-RPT-Record

```dns
_smtp._tls.deine-firma.ch.  3600  IN  TXT  "v=TLSRPTv1; rua=mailto:tls-reports@deine-firma.ch"
```

Erlaubt sind `mailto:` und `https:` als Ziel, auch mehrere durch Komma getrennt. Nimm ein eigenes Postfach dafür — die Reports sind maschinenlesbar und nicht für Menschen gedacht.

## testing, enforce, none

| Modus | Was Absender tun |
|---|---|
| `testing` | Policy holen, prüfen, Fehler per TLS-RPT melden — aber trotzdem zustellen |
| `enforce` | Nicht zustellen, wenn TLS fehlt, das Zertifikat ungültig ist oder der MX nicht in der Policy steht |
| `none` | Domain hat keine aktive Policy mehr (für den geordneten Ausstieg) |

Die sichere Reihenfolge, die auch Microsoft empfiehlt:

1. TLS-RPT-Record setzen.
2. Policy mit `mode: testing` veröffentlichen, dann den `_mta-sts`-Record.
3. Reports mehrere Wochen beobachten. Erst wenn keine unerwarteten Fehler mehr auftauchen:
4. Policy auf `mode: enforce` stellen **und** die `id` im TXT-Record ändern.

Bei jeder Änderung gilt: **erst die Policy-Datei aktualisieren, dann die `id`**. Sonst holen Absender bei neuer `id` noch die alte Datei und speichern sie für `max_age`.

## Die Falle beim Gateway-Wechsel

MTA-STS und ein MX-Wechsel vertragen sich nur mit Planung. Absender haben deine Policy bis zu `max_age` im Cache. Steht dort nur der alte MX und du schaltest auf das neue Gateway um, verweigern Absender mit `enforce` die Zustellung an den neuen Server — bis ihr Cache abläuft oder sie die neue `id` sehen.

So geht es ohne Unterbruch:

1. Einige Tage vor dem Cutover: Policy mit **alten und neuen** MX-Hosts veröffentlichen, `id` ändern.
2. Optional für die Umstellungsphase auf `testing` zurückgehen und die `id` ändern.
3. MX umstellen.
4. Nach dem Cutover die alten MX-Hosts aus der Policy entfernen, `id` ändern, später wieder `enforce`.

## TLS-RPT-Reports lesen

Absender, die TLS-RPT unterstützen, schicken einmal pro Tag (UTC) einen JSON-Report, meist gzip-komprimiert. Die wichtigsten Felder:

```json
{
  "organization-name": "Beispiel-Mailprovider",
  "date-range": { "start-datetime": "2026-10-12T00:00:00Z",
                  "end-datetime":   "2026-10-12T23:59:59Z" },
  "policies": [{
    "policy": { "policy-type": "sts", "policy-domain": "deine-firma.ch" },
    "summary": { "total-successful-session-count": 0,
                 "total-failure-session-count": 0 },
    "failure-details": [
      { "result-type": "certificate-host-mismatch",
        "receiving-mx-hostname": "mail.deine-firma.ch",
        "failed-session-count": 0 }
    ]
  }]
}
```

(Werte im Beispiel absichtlich auf null gesetzt.)

Die `result-type`-Werte zeigen dir die Ursache:

| result-type | Bedeutung |
|---|---|
| `starttls-not-supported` | Dein Server bietet kein STARTTLS an |
| `certificate-host-mismatch` | Zertifikat passt nicht zum MX-Hostnamen |
| `certificate-expired` / `certificate-not-trusted` | Zertifikat abgelaufen bzw. keine vertrauenswürdige CA |
| `validation-failure` | allgemeiner Validierungsfehler |
| `sts-policy-fetch-error` | Policy-Datei nicht abrufbar (Redirect? Zertifikat? Timeout?) |
| `sts-policy-invalid` | Policy-Datei syntaktisch falsch |
| `sts-webpki-invalid` | Zertifikat des Policy-Hosts `mta-sts.` ungültig |

`policy-type: no-policy-found` heisst übrigens: Der Absender hat keine MTA-STS-Policy gefunden — vor dem Einrichten normal, danach ein Warnsignal.

## Selbst prüfen

```bash
# Records
dig +short TXT _mta-sts.deine-firma.ch
dig +short TXT _smtp._tls.deine-firma.ch

# Policy: muss 200 liefern, ohne Redirect, text/plain
curl -sS -D - https://mta-sts.deine-firma.ch/.well-known/mta-sts.txt
```

Unser [Domain-Check](/check) zeigt dir zusätzlich, ob der `_mta-sts`- und der `_smtp._tls`-Record gesetzt sind — zusammen mit SPF, DKIM, DMARC und MX. Die Policy-Datei selbst prüfst du am besten mit dem `curl`-Befehl oben.

## Und in die andere Richtung?

Exchange Online prüft beim **Versand** automatisch die MTA-STS-Policies der Empfängerdomains — ohne Konfiguration. Scheitert die Prüfung bei einer Empfängerdomain mit `enforce`, bekommt der Absender einen Unzustellbarkeitsbericht, etwa mit `5.4.8` (MX nicht in der Policy) oder `5.7.5` (Zertifikat ungültig). Läuft dein Versand über ein Gateway als Smart Host, prüft Exchange Online gegen das Gateway, nicht gegen die Zieldomain — dann ist das Gateway für MTA-STS zuständig.

## MTA-STS oder DANE?

DANE (TLSA-Records) erreicht ein ähnliches Ziel, setzt aber durchgehend DNSSEC voraus. MTA-STS funktioniert ohne DNSSEC und ist deshalb für viele Domains der schnellere Einstieg. Beides schliesst sich nicht aus.

## Was als nächstes

→ [Domain prüfen](/check) — MTA-STS, TLS-RPT, SPF, DKIM, DMARC in einem Durchgang

→ [Mail-Gateway vor Microsoft 365](/blog/mail-gateway-vor-microsoft-365-dmarc-spf-dkim) — was sich beim MX-Wechsel sonst noch ändert

→ [MTA-STS und TLS-RPT einrichten lassen](/kontakt?topic=general) — Setup, Policy-Hosting und Validierung
