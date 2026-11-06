# Xiaomi LYWSD03MMC / pvvx ATC / BTHome v2

Od 6. 11. 2026 sbírá aplikace BLE měření pouze z **nešifrovaného BTHome v2**.
První kus je ověřený s **pvvx ATC v5.9**, původní HW string B1.5.
[Záznam OTA](xiaomi-ota-2026-11-06.md).

## Nastavení teploměru

- Advertising type: **BTHome v2**.
- Encrypted beacon: **0**.
- AdFlags: **1** (potřebuje zejména BlueZ).
- Ověřený výchozí profil: reklama každých 2,5 s, měření každých 10 s.
- Odpoj flasher/Xiaomi Home po konfiguraci. Aplikace nevyžaduje spojení, token ani bindkey.

Stock Xiaomi MiBeacon, šifrované BTHome a jiné reklamní formáty zatím nejsou podporované.
Nešifrované hodnoty může přijmout kdokoli v rádiovém dosahu.

## Přechod existující instalace

1. Nasaď vlastní commit/build. Debian potřebuje stejné D-Bus oprávnění a
   `compose.ble.yaml` jako dosud; Windows používá nativní Bleak.
2. Nastavení → Hledat BLE senzory (15 s). Zobrazí se skutečně přijatá data.
3. Přidej svůj `ATC_…` senzor a přiřaď jej místnosti v editoru půdorysu.
4. Staré LT záznamy můžeš smazat v UI. Aplikace je automaticky nepřepisuje ani
   nepřipojuje; stará historie zůstává zachovaná. Nové zařízení má jinou MAC/ID.
5. Nastav interval **ukládání historie**, například 60 s. Existující uložené intervaly
   se nezmění; staré zvýšení na 300 s už se neprovádí.

`SENSOGRID_BLE_CONCURRENCY` již nemá účinek a může se odstranit z `.env`.
Volitelný BlueZ rescue helper nyní započítává jen BTHome senzory; máš-li jej
nainstalovaný, pro aktualizaci hostitelské kopie spusť jeho původní instalátor.
Změny v repozitáři samy nainstalovanou kopii ani běžící server nemění.

## Chování a diagnostika

Jeden scanner přijímá reklamy všech senzorů současně. Aktivní scan může posílat
BLE scan requests, nevytváří však spojení, nepáruje ani neprovádí GATT operace.
Hledání a ruční náhled jej sdílejí. „Počkat na nové vysílání“ čeká nejvýše 30 s
na novou teplotu/vlhkost; žádné měření nevynucuje a interval historie neobchází.

Živé hodnoty se aktualizují na novém klimatickém paketu. Historie zaznamená první
nový paket po uplynutí intervalu. Ukládá UTC čas přijetí, skutečné hodnoty a RSSI.
Duplicitní paket není nové měření. Packet ID se může přetočit z 255 na 0.
Pakety s napětím/GPIO se sloučí podle MAC, ale neposunou stáří klimatických dat.
Krátce oddělená teplota a vlhkost se sloučí, jejich časový rozdíl smí být nejvýše 30 s.

Chybějící reklamy nevytvářejí náhradní vzorky. Poslední hodnoty zůstanou viditelné
s původním časem; dostupnost skončí podle nastaveného zastarání. Nový paket obnoví
dostupnost bez cooldownu. Po změně místnosti se čeká na nová klimatická data.
Chyba scanneru vede k jeho opakovanému spuštění po 15 s, nikoli k restartu BlueZ.
Pokud nepřijde žádný BTHome paket 120 s, watchdog uzavře a znovu spustí scanner.
Tím pokrývá i tiché zastavení adaptéru po úspěšném startu. Platí to i v prázdném
okolí; restartuje se pouze scan, žádné zařízení ani systémová služba.

ZIP diagnostiky obsahuje hash dekodéru, stav scanneru, počet BTHome paketů,
neplatných/šifrovaných rámců, duplicit a klimatických rámců. S
`SENSOGRID_DIAGNOSTICS=true` se logují i dekódované objekty a MAC/RSSI.

Původní LT driver/protokol/radio scheduler zůstávají pouze pro historické benchmarky;
produkční runtime je neimportuje. [Archiv incidentů](legacy-lt-bluetooth.md).

## Ověření 6. 11. 2026

Nový produkční driver a collector při odděleném Windows testu přijaly z prvního
flashnutého kusu 23,94 °C, 42,67 % RH, 95 % baterie, 2,962 V, RSSI −53 dBm.
Vzorek se uložil do testovacího outboxu se zdrojem `bthome_v2`. Za běhu bylo
zpracováno 6 paketů, 1 duplicita, 0 neplatných rámců. Test nezapisoval do
produkčních dat ani InfluxDB; dokládá skutečný příjem a lokální frontu, nikoli
nasazení, zápis do skutečné historické databáze nebo dlouhodobou výdrž.

První živý pokus odhalil nevhodný filtr `service_uuids` ve WinRT: FCD2 Service Data
nemusí znamenat přítomnost FCD2 v seznamu inzerovaných služeb. Scanner proto
nepoužívá UUID filtr backendu; kontroluje FCD2 až v callbacku. Tento případ je
pokryt regresním testem.

Protokol: [BTHome v2](https://bthome.io/format/).
Scanner: [Bleak](https://bleak.readthedocs.io/en/latest/api/scanner.html).
