# Výpadek BLE — večer 23. 10. 2026

## Závěr

Diagnostika potvrzuje **opakované pády bluetoothd** a **přetrvávající nedostupnost dvou konkrétních senzorů**. Přesný mechanismus pádů a důvod, proč Obývák/Kuchyň přestaly být vidět, zatím prokázány nejsou. Záznam nedokazuje únik paměti ve firmwaru.

[Strojově čitelná evidence](../diagnostics/ble/incident-20261023-evening.json).

## Čas a úplnost archivu

Soubor se jmenuje `sensogrid-diagnostics-2026-10-23T17-52-35-533Z.zip`, ale interní manifest i snapshot byly vytvořeny **18:44:52 UTC / 20:44:52 CEST**. Host snapshot je z 20:44:32 CEST, tedy čerstvý přibližně 19 sekund. Časová osa vychází z interních záznamů, nikoliv názvu souboru.

Aplikační log: 264 záznamů od 19:49:12 do 20:44:51 CEST, bez ořezu. Bluetooth journal je oříznutý na posledních 48 000 bajtů; začátek je neúplný. Kernel journal oříznutý není. Chybí coredumpctl, sekce controller nedokáže otevřít mgmt_socket a sekce usb selhala při inicializaci libusb. Tyto chyby sběru nejsou samy o sobě důkaz vadného adaptéru.

## Stav při exportu

| Senzor | Poslední úspěšné měření CEST | Stav |
| --- | --- | --- |
| Spíž | 20:44:20 | ready, dostupná |
| Obývák | 20:23:23 | unavailable |
| Kuchyně | 20:23:48 | unavailable |
| Ložnice | 20:43:28 | ready, dostupná |
| Koupelna | 20:44:37 | ready, dostupná |

Spíž se tedy proti dřívějšímu screenshotu obnovila. Telefon mohl její čtení dočasně blokovat; přesná doba spojení telefonu není v archivu zaznamenaná.

Runtime: concurrency 2, **5 pokusů**, interval 60 s, zastarání 1000 s. Collector je degraded, úloha stále žije. Influx úloha žije, storage ready, outbox 0. Zde není evidence zahlceného zápisu nebo ukončeného sběrače.

## Potvrzené pády BlueZ

Host používá `bluez 5.82-1.1+sensogrid1`. Systemd i kernel potvrzují SIGSEGV:

- 19:31:41 CEST (před začátkem nynějšího aplikačního logu).
- **20:04:13, 20:08:32, 20:13:46, 20:15:53, 20:33:57, 20:39:14 CEST**.

Jde tedy o **šest pádů během této aplikační relace** a sedm zachycených v host logu. NRestarts=16 je kumulativní čítač, nikoliv šestnáct pádů v tomto časovém okně.

Poslední automatické spuštění bluetoothd: 20:39:15 CEST. U každé uvedené události systemd zaznamenal `Main process exited, code=killed, status=11/SEGV`. Nešlo o běžný úmyslný restart záchranným timerem. V zachyceném rescue journalu není zpráva skriptu o provedení restartu; při čerstvých měřeních některých zařízení navíc podmínka úplného výpadku není splněná.

Přes read-only SSH ověřen běžící binární soubor:
- Build ID `2ac9eba7f42650f9b5e888a2b314cde9e6878dce`.
- SHA-256 `855b151b4bfd0b3be14a6e946daa60c9e04574be651ddab1fc63f7c26a70a5d4`.

Odpovídající debug balík byl přečten do anonymní paměti (memfd), bez instalace nebo rozbalování na serverový filesystem. `addr2line` přeložil offsety **0xf7c1f / 0xf7c22 na gatt_db_attribute_read.part.0**. Úplný stack a zdrojový řádek chybí. Dva další zachycené pády jsou v libc.

Tím je zúžené místo části pádů, ne prokázán konkrétní use-after-free nebo jediná příčina všech pádů. Dřívější dvě backportované opravy tedy nejsou úplná oprava stability.

## Jak selhává čtení

Obývák po posledním úspěchu:
- 20:24:55 timeout, opakování.
- 20:25:17 další timeout.
- 20:25:31 po pěti pokusech `device 'dev_F1_51_5B_34_83_1C' not found`.

Kuchyně:
- 20:26:04 timeout.
- 20:26:36 další timeout.
- 20:26:50 po pěti pokusech `device 'dev_C4_ED_04_7D_75_06' not found`.

Kernel navíc zaznamenává `hci0: Opcode 0x200e failed: -16` v 20:24:57 a 20:26:06. Z těchto řádků samotných nelze určit vadný komponent nebo mechanismus zaseknutí senzoru.

Všech **38 terminálních Python tracebacků** končí v Bleak `manager._check_device`: objekt zařízení v BlueZ neexistuje. Jde o chybu při navazování spojení, ještě před LT dotazem a příjmem odpovědi. Odpovídá to opakovanému použití dříve nalezeného zařízení, které se nepodařilo znovu objevit; neprokazuje to samotné selhání dekodéru nebo vadná teplotní data.

## Nezávislá kontrola z Windows

Bez navazování spojení proběhly dva scany:
- 20 sekund, konec **20:49:05 CEST**.
- 45 sekund, konec **20:51:14 CEST**.

Oba zachytily Spíž, Ložnici a Koupelnu. **Obývák ani Kuchyň nezachytil ani jeden.** Záchyt jiných zařízení potvrzuje fungující scan, ale samotná absence reklamy nerozlišuje uvázlý firmware, spojení s jiným klientem nebo jinou rádiovou překážku.

Uživatel současně pozoruje trvale svítící kolečko právě na Obýváku a Kuchyni; ostatní blikají a posílají data. Trvalé svícení samo není univerzální indikátor poruchy: uživatel ho dříve viděl také během funkčního trvalého spojení s qaqa. Jeho kombinace s neviditelností a chybějícími daty podporuje hypotézu uvázlého stavu spojení/rádia.

Kontext: v 20:19–20:21 CEST proběhla z Windows jednorázová krátká spojení pro čtení verze, viz [report firmware](firmware-and-connection-investigation-2026-10-23.md). Obývák i Kuchyň poté ještě úspěšně měřily na Debianu v 20:23. Nelze z jediné sekvence vyloučit podíl střídání klientů na vzniku uvázlého stavu. Pády BlueZ probíhaly už před tímto čtením.

## Živá kontrola před resetem

Následná read-only kontrola přes SSH potvrdila stále stejné poslední měření Obýváku a Kuchyně (20:23 CEST), zatímco ostatní měřily ještě v 20:52–20:55 CEST. BlueZ měl stále NRestarts=16 a běžel od 20:39:15. `bluetoothctl info` pro Obývák i Kuchyň vracel `not available`. Nejde tedy pouze o starý export nebo okamžitý výpadek celé služby.

## Další postup

1. Izolovaný reset pouze Obýváku; Kuchyň ponechat jako kontrolu. Následný scan a nové uložené měření mají ukázat, zda návrat senzoru vyžaduje zásah na serveru. Výsledek je zaznamenán v následující sekci.
2. Zajistit skutečný coredump bluetoothd a úplný backtrace se shodnými symboly. Nyní je core_pattern pouze `core`, core_uses_pid=1 a nástroj coredumpctl chybí. Další změna počtu retry nenahradí diagnostiku pádu procesu.
3. V journalu jsou opakované chyby profilu input-hog pro všechny senzory. [Upstream oprava zrušení čekajících HoG požadavků při detach](https://github.com/bluez/bluez/commit/ff4fae3f2d172de788b18fecba8cf75f8e3e9ce8) je kandidát k prověření pomocí backtrace, nikoliv prokázaná oprava tohoto případu.

Žádný serverový soubor, balík, služba ani firmware nebyl při této analýze změněn. Nevznikla ani změna aplikačního kódu; pouze tento report a souhrnná evidence ve Windows repozitáři.

## Výsledek resetu Obýváku

Uživatel potvrdil vyjmutí baterie pouze z Obýváku na 10 sekund. Kuchyň zůstala beze změny. Následný 20sekundový scan z Windows (konec 20:57:09 CEST) Obývák zachytil s RSSI -69 dBm; Kuchyň opět ne.

SensoGrid uložil nové měření Obýváku **20:57:46 CEST — 26,8 °C, 58 %**. Stejný konkrétní vzorek je ověřený dotazem do Influxu, nejde pouze o scan nebo starou UI cache. V kontrole 20:59:38 CEST je Obývák dostupný, Kuchyň má stále poslední měření z 20:23:48 a je unavailable. Koupelna v této kontrole rovněž hlásí unavailable, poslední vzorek 20:55:16; nelze tedy tvrdit, že je celý systém stabilní.

**Důležitý souběh:** v 20:56:27 CEST bluetoothd znovu spadl (kernel SIGSEGV, offset 0xf7c1f, gatt_db_attribute_read.part.0). Systemd ho spustil v 20:56:28, NRestarts vzrostl z 16 na 17. Žádný restart nebyl vyvolán diagnostikou. Test proto není striktně izolovaný od restartu BlueZ. Rozdíl mezi resetovaným Obývákem a nezměněnou Kuchyní podporuje přínos resetu senzoru, ale nedokazuje konkrétní mechanismus jeho uváznutí ani únik paměti.
