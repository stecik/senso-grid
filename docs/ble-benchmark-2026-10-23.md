# SensoGrid: BLE benchmark Debian × Windows, 23. 10. 2026

## Závěr

- **Debian: nejlépe profil B, nejvýše dvě současná čtení.** Dodal 43/50 plánovaných vzorků (86 %), do jedné minuty 50 %. Sekvenční A 72 %, paralelní C 60 %. Jde o nejlepší výsledek tohoto pilotu, nikoliv záruku dlouhodobé stability.
- **Windows: C dodal nejvíce vzorků, 40/50 (80 %).** Všechny čtyři viditelné senzory přečetl 10/10. Obývák chyběl již před začátkem Windows části. A/B neměly chybu spojení po nalezení zařízení; C potřeboval opakování po deseti timeoutech. Rozdíl několika vzorků za deset minut neprokazuje jednoznačně nejstabilnější profil pro PC.
- **BlueZ znovu havaroval i s dočasným backportem.** Během D je potvrzen SIGSEGV; později se počet automatických restartů dále zvýšil. Zvýšení počtu pokusů neopraví pád Bluetooth služby.
- **Aplikace na Debianu obnovena v 12:13:50 CEST.** InfluxDB a ostatní aplikace nebyly naším testem zastavovány. Poslední kontrola v 14:23:37 CEST: app běží a je healthy, aktuálně čerstvé tři senzory; Obývák a Koupelna mají zastaralá měření. Obnovení procesu tedy neznamená vyřešenou dostupnost.

## Podmínky a prostředí

| | Debian server | Windows PC |
| --- | --- | --- |
| Adaptér | Realtek USB 0bda:b85b | Intel Wireless Bluetooth USB 8087:0029 |
| OS | Debian 13, kernel 6.12.96+deb13-amd64 | Windows 11, build 26300 |
| Bluetooth stack | BlueZ 5.82-1.1+sensogrid1 | Intel driver 23.70.0.2 / WinRT |
| Python / Bleak | 3.13.17 / 3.0.2 | 3.13.15 / 3.0.2 |
| Začátek | 10:49:59 CEST | 11:31:06 CEST |

Adaptéry byly podle uživatele ve stejné místnosti, diagonálně v opačných rozích. Poloha nebyla během měření měněna. Srovnáváme celé sestavy v těchto polohách; rozdíl nelze připsat samotnému řadiči nebo OS.

Každý host provedl A → B → C → D, každý profil 600 sekund, mezi profily 20 sekund klidu. Nejprve celý Debian, potom celý Windows; původní sběr zůstal po obě části zastavený. Bluetooth nebylo mezi profily resetováno. Pořadí není vyvážené, nelze vyloučit postupné zhoršování stavu.

| Profil | Limit současných čtení | Odstup zahájení |
| --- | ---: | ---: |
| A | 1 | 0 |
| B | 2 | 0 |
| C | 5 | 0 |
| D | 5 | 500 ms podle pozice |

Společné nastavení: 60sekundové plánované sloty, celkem tři pokusy, backoff 1/2 s, vstupní scan 15 s, retry scan 5 s, měření timeout 12 s plus existující rozpočet driveru na připojení. Scan a spojení se vzájemně vylučují. Pořadí senzorů se pro každý slot promíchá stejným seedem na obou hostech. Driver ani jeho protokol se neměnily.

Deset slotů × pět senzorů = 50 příležitostí na profil. Nové sloty se nezadlužují do fronty: pokud celý slot uplyne, je vynechaný. Čeká se na dokončení dávky. Produkce naproti tomu nyní odměřuje interval od dokončení a také čeká na dávku; noční počet vzorků není přímý ekvivalent tohoto testu.

## Celkové výsledky

Úspěch = skutečně dekódované měření. Dodáno / včas používá všech 50 plánovaných příležitostí jako jmenovatel. Včas = dokončeno do 60 sekund od plánovaného startu, včetně scanu, fronty a odpojení. „1. pokus“ používá pouze dokončená první volání driveru; zahrnuje také nenalezení zařízení ještě před připojením.

| Host | Profil | Dodáno / 50 | Dodáno | Včas | 1. pokus | Dokončené pokusy | Chybné pokusy | Selhané cykly | Vynechané | Ukončené limitem |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| debian | A | 36 | 72 % | 34 % | 60 % | 73 | 37 | 9 | 5 | 0 |
| debian | B | 43 | 86 % | 50 % | 73.33 % | 59 | 16 | 1 | 5 | 1 |
| debian | C | 30 | 60 % | 38 % | 31.11 % | 83 | 53 | 11 | 5 | 4 |
| debian | D | 22 | 44 % | 18 % | 27.5 % | 85 | 63 | 15 | 10 | 3 |
| windows | A | 38 | 76 % | 76 % | 74 % | 75 | 37 | 12 | 0 | 0 |
| windows | B | 37 | 74 % | 74 % | 74 % | 76 | 39 | 13 | 0 | 0 |
| windows | C | 40 | 80 % | 80 % | 58 % | 81 | 41 | 10 | 0 | 0 |
| windows | D | 34 | 68 % | 52 % | 44.44 % | 81 | 47 | 11 | 5 | 0 |

Selhaný cyklus vyčerpal pokusy. Vynechaný vůbec nezačal. Ukončený limitem začal, ale do uzavření profilu neměl konečný výsledek. Neúspěšný pokus se může později zotavit, proto není totožný se selhaným cyklem.

## Úspěšnost jednotlivých senzorů

V každé buňce úspěšná měření / 10; tedy 9/10 = 90 %.

| Senzor | Debian A | B | C | D | Windows A | B | C | D |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Koupelna | 6/10 | 9/10 | 6/10 | 3/10 | 9/10 | 9/10 | 10/10 | 8/10 |
| Ložnice | 9/10 | 8/10 | 8/10 | 8/10 | 10/10 | 9/10 | 10/10 | 8/10 |
| Obývák | 8/10 | 9/10 | 3/10 | 0/10 | 0/10 | 0/10 | 0/10 | 0/10 |
| Kuchyně | 9/10 | 9/10 | 7/10 | 6/10 | 10/10 | 10/10 | 10/10 | 9/10 |
| Spíž | 4/10 | 8/10 | 6/10 | 5/10 | 9/10 | 9/10 | 10/10 | 9/10 |

Obývák (02:00:00:5E:00:05) přestal být viditelný během linuxového C, v D ani v žádném Windows profilu nebyl nalezen. Následné nezávislé 20sekundové nefiltrující scany jej nezachytily na žádném hostu; všechny ostatní senzory našly. Debian v okamžiku kontroly nevykazoval aktivní spojení. Příčinu zmizení tím nelze určit.

LCD Obýváku podle uživatele dál aktualizovalo hodnoty; kolečko vedle °C svítilo trvale, zatímco na ostatních blikalo. Význam symbolu není ověřený. Po vyjmutí baterie se Obývák vrátil: produkce u stejné MAC uložila měření v 12:34:38 CEST. Při závěrečné kontrole už bylo znovu zastaralé. Není tedy prokázané trvalé zotavení ani konkrétní závada firmware.

Sekundární srovnání pouze čtyř ostatních senzorů (40 příležitostí):

| Host | A | B | C | D |
| --- | ---: | ---: | ---: | ---: |
| debian | 28/40 (70 %) | 34/40 (85 %) | 27/40 (67.5 %) | 22/40 (55 %) |
| windows | 38/40 (95 %) | 37/40 (92.5 %) | 40/40 (100 %) | 34/40 (85 %) |

Toto vyloučení je dodatečné, úplná pětisenzorová tabulka zůstává výše. Na Windows se reálně četla nejvýše čtyři dostupná zařízení; schopnost pěti současných spojení ani obecný hardwarový limit deseti spojení tento test neověřil.

## Zpoždění a typy chyb

Délka cyklu zde znamená dobu od plánovaného startu do úspěšného dokončení, nikoli jen přenos dat. P95 je popisný odhad z malého počtu měření.

| Host | Profil | Cyklus medián s | Cyklus P95 s | LookupError | BleakError | BleakDBusError | TimeoutError |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| debian | A | 60.757 | 103.723 | 13 | 22 | 0 | 2 |
| debian | B | 57.691 | 87.705 | 0 | 4 | 2 | 10 |
| debian | C | 48.694 | 109.692 | 0 | 23 | 1 | 29 |
| debian | D | 66.689 | 128.686 | 23 | 16 | 3 | 21 |
| windows | A | 25.598 | 39.428 | 37 | 0 | 0 | 0 |
| windows | B | 23.058 | 32.898 | 39 | 0 | 0 | 0 |
| windows | C | 25.556 | 44.297 | 31 | 0 | 0 | 10 |
| windows | D | 37.238 | 109.754 | 27 | 0 | 0 | 20 |

- LookupError: zařízení nebylo v aktuálním discovery cache. Nejde o důkaz selhaného fyzického připojení. U Windows A/B jde o všechny zaznamenané chyby; velkou část tvoří trvale chybějící Obývák.
- Linux BleakError často obsahuje „device … not found“: zastaralý nebo již odstraněný objekt BlueZ. Retry musí obnovovat také aktuální BLEDevice/discovery stav, nikoliv pouze znovu volat připojení na starém objektu.
- Windows C: deset TimeoutError, přesto všechny čtyři viditelné senzory nakonec 10/10. D: dvacet TimeoutError, delší cykly a pět vynechaných příležitostí. Rozestup 500 ms v tomto běhu nepomohl.
- Linux B snížil oproti A čekání i ztráty. Nelze ale potvrdit příčinu jako „přetížený čip“; mění se souběh, sdílený scan, GATT stav i stav senzorů. RSSI je poslední advertisement, nikoli průběžný signál spojení.

## BlueZ a limity experimentu

V 11:25:26 CEST, během linuxového D a při zastavené produkční aplikaci, systemd zaznamenal status 11/SEGV a automatický restart bluetoothd. Kernel potvrzuje segfault. Symboly odpovídající nasazenému vlastnímu buildu mapují offset 0xf6fbe na gatt_db_attribute_write. Dřívější pád ukazoval do discovery_op_complete. Jiná adresa sama o sobě neprokazuje jinou kořenovou příčinu; chybí úplný backtrace/core.

Nasazeno BlueZ **5.82-1.1+sensogrid1**, původ Debian **5.82-1.1**; libbluetooth3 zůstává **5.82-1.1**. Dočasné backporty: 6cdb936ebb6a3906062605883470d6b3a4e8c89e a a338533f913bf42b267aeba30f1344d85459c13c. Jejich dřívější úspěšné testy nejsou důkazem vyřešeného provozního pádu. Viz [incident](incident-2026-10-23-bluez.md).

Po obnovení aplikace se NRestarts zvýšilo z 1 na 2 v 12:14:53; při závěrečné kontrole bylo **5**, poslední start 13:02:26 CEST. Pro tyto pozdější restarty nemá SSH uživatel přístup k systémovým logům, takže jejich důvod není potvrzený. Neoznačujeme je automaticky za další SIGSEGV.

Původní měřicí skript při ukončování Linuxu vypsal chybu zápisu po uzavření journalu: pomalý úklid zrušeného úkolu nebyl dokončen před uzavřením profilu. C a D měly po jedné zahájené příležitosti nesprávně označené jako vynechané. Souhrny byly přepočteny z nezměněných raw journalů na „ukončeno limitem“ (C: 6→5 vynechaných, 3→4 ukončené; D: 11→10, 2→3). Počty úspěchů a chyb ani procenta dodání/včas se nezměnily. Úplnou izolaci úklidu na hranicích těchto profilů nelze zpětně potvrdit; C/D proto slouží jako pilot, ne čistý kauzální důkaz.

Budoucí runner nyní výslovně ruší a dočká všechny sourozenecké úkoly před zavřením journalu. Osm regresních testů prošlo; měření se po této opravě neopakovalo. Linux D je navíc ovlivněn potvrzeným pádem BlueZ. Desetiminutová okna, pevné pořadí a výpadek Obýváku omezují závěry všech meziplatformních srovnání.

## Doporučený další postup

1. Pro další provozní ověření Debianu zvolit limit **2**, ne 5/10. Výsledek 86 % je nejlepší z tohoto běhu, stále nedostatečný pro tvrzení stabilního sběru.
2. Před další úpravou BlueZ zachytit core/full backtrace současného pádu. Automatický restart služby již zajišťuje systemd; častější restart z aplikace neřeší příčinu.
3. Opravit obnovu discovery objektu při chybě „device not found“ a oddělit termíny senzorů tak, aby jediný nedostupný senzor nezdržoval všechny. Následně samostatně změřit požadovaných **pět pokusů** s omezeným celkovým časem; více pokusů bez rozpočtu může zhoršit včasnost.
4. Po zotavení všech pěti zařízení zopakovat delší A/B/C ve střídavém pořadí, ideálně se zaměněnou polohou adaptérů. PC: C je kandidát na nejvyšší dodání, A/B na méně chyb spojení; současná data nevybírají jednoznačného dlouhodobého vítěze.

**Produkční počet pokusů ani souběh tento experiment nezměnil; původní tři pokusy zůstávají.** Změny runneru jsou pouze diagnostické. Nebyla instalována další verze BlueZ ani přidán trvalý watchdog.

## Obnovení služby a uložená evidence

Supervisor zastavil pouze sensogrid-app-1 v 10:49:59 CEST a obnovil jej v 12:13:50. Před/po snapshot potvrzuje všechny původně běžící ostatní kontejnery včetně InfluxDB se stejnými ID a stavem running. Benchmark skončil, Windows proces skončil, dočasná prevence uspání Windows byla uvolněna a její proces již neběží.

Po obnově byly nové skutečné vzorky všech čtyř tehdy viditelných senzorů ověřeny v SQLite i přímo v InfluxDB; Obývák se později vrátil po resetu. Závěrečná kontrola v 14:23:37 CEST:

| Senzor | Poslední skutečné měření CEST |
| --- | --- |
| Spíž | 14:22:18 |
| Kuchyně | 14:23:18 |
| Ložnice | 14:22:53 |
| Koupelna | 13:27:16 — zastaralé |
| Obývák | 12:34:38 — zastaralé |

Reprodukce a bezpečnost: [diagnostický návod](../diagnostics/ble-benchmark/README.md). Strojově čitelné výsledky včetně každého senzoru, chyb a intervalů: [CSV](../diagnostics/ble-benchmark/results-2026-10-23.csv).

Raw evidence v ignorované .logs/ble-benchmark-20261023/: debian/ a windows/ obsahují A–D.jsonl, původní summary.json, summary-corrected.json, metadata.json a complete.json; debian-host/ obsahuje systémové logy prvního pádu, snapshoty kontejnerů a supervisor.jsonl. Původní měřený skript je benchmark-used.py. Na serveru totéž měření: /home/marek/sensogrid-ble-benchmark-20261023/artifacts/debian/. Žádná měření experimentu nebyla zapisována do produkční historie.

Shodná měřená verze skriptu na obou hostech SHA256: f9ba231805e4ce42426c19638e7f5ab62ee4cdbebf20028aa44538225dec3d13. Shodný produkční LT driver SHA256: afe0848cc04ec3f6d7d2de9e7452946f570a1880259a9d8bf0c748d55e93310d. Aktuální runner již obsahuje výše uvedené následné opravy účetnictví a rušení úkolů.

Ověření kódu: backend 72 passed, 1 skipped; cílené testy benchmarku 8 passed; Ruff check a format check pro tři přidané Python soubory prošly. Bez commitu a bez změny produkčního image.
