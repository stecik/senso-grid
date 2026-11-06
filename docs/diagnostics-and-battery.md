# Diagnostika a baterie, 23. 10. 2026

## Nasazení

Kód se mění pouze ve Windows repozitáři. Commit/push, pull a nasazení provádí
uživatel. Tato změna nebyla vzdáleně nasazena.

Na Debianu po pullu:

```sh
docker compose -f compose.yaml -f compose.ble.yaml up -d --build --no-deps app
sudo sh diagnostics/host-logs/install.sh
```

Druhý krok je jednorázová instalace čtecího hostitelského helperu. Při změně jeho
kódu jej zopakovat. Timer ani instalátor nic nerestartují. Docker automaticky
vytvoří adresář pro hostitelský snapshot, je-li dosud prázdný; chybějící helper
tedy neblokuje start aplikace. Kontejner dostává pouze read-only mount
`/var/lib/sensogrid-diagnostics` → `/app/host-diagnostics`, nikoli Docker socket
nebo oprávnění k systémovým službám.

## Stáhnout diagnostiku

V Nastavení je tlačítko **Stáhnout diagnostiku**. Přihlášený správce stáhne ZIP
z `GET /api/diagnostics`. Odpověď není cachovaná; povoleny jsou tři exporty za
minutu. Stahování neprovádí scan, nové BLE spojení ani restart.

Archiv obsahuje:

- `snapshot.json`: verze Pythonu a knihoven, hash skutečného zdrojového kódu,
  režim, protokol, počet spojení (0), statistiky scanneru, intervaly, stav sběru/úložiště, počet souborů
  outboxu, senzory a jejich poslední hodnoty, baterii, čas a dostupnost.
- `application/app.jsonl*`: rotované logy aplikace, chyby Bleak/D-Bus,
  start/stop a chyby scanneru včetně úplných výjimek.
  Uchovávají se přes restart v datovém volume; přibližně 4 × 512 KiB.
- `host.json`, je-li helper nainstalován: poslední dvě hodiny logů Bluetooth a
  vybraných kernelových zpráv, stav a počet restartů BlueZ, USB topologie,
  řadič, aktivní spojení, verze balíků, stav záchranného restartu a informace
  o posledním dostupném core dumpu. Počet řádků, velikost i doba jednotlivých
  příkazů jsou omezené. Chybějící příkaz/timeout se uvede zvlášť.
- `manifest.json`: dostupnost a stáří hostitelského snapshotu a oříznutí logů.
  Snapshot starší než tři minuty je označen jako zastaralý. Dostupný soubor
  neznamená, že na daném systému existují všechny příkazy nebo core dump.

Nevkládá se SQLite databáze, účet, hash hesla, sessions, `.env`, soukromé VAPID
klíče, push subscriptions, půdorys ani úplná historie. Známá tajemství,
Authorization/Cookie a hodnoty password/token se odstraňují; z URL se odstraní
přihlašovací údaje, query a fragment. Archiv přesto obsahuje názvy, MAC adresy
a hodnoty senzorů; před veřejným sdílením jej zkontrolovat.

Logování začíná až po nasazení této verze. Starší nezaznamenané chyby nelze
zpětně vytvořit. Export neobsahuje paměť core dumpu ani průběžný rádiový záznam
`btmon`. Pro hlubší analýzu pádu může být nadále potřeba explicitně získat
core/backtrace s odpovídajícími debug symboly.

Kontrola a vypnutí pouze čtecího helperu:

```sh
systemctl status sensogrid-diagnostics.timer
sudo journalctl -u sensogrid-diagnostics.service
sudo systemctl disable --now sensogrid-diagnostics.timer
```

## Baterie — BTHome od 6. 11. 2026

Xiaomi s ATC firmwarem posílá procento v BTHome objektu `0x01`, napětí v `0x0C`.
Aplikace používá přímo procento (i 0 %), vlastní čas baterie a žádné GATT spojení.
Pomocný paket pouze s napětím neobnovuje stáří teploty/vlhkosti.
Procento je odhad firmwaru a nelze z něj samotného odvodit denní spotřebu.

### Archiv: původní LT baterie

Dřívější GATT výpis skutečného senzoru obsahuje službu `180F` a čitelnou
charakteristiku `2A19` (diagnostics/ble/connection-attempt-2.jsonl, řádek 11).
To je standardní Battery Level: jeden bajt 0–100 % podle
[Bluetooth SIG Battery Service](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/BAS_v1.1/out/en/index-en.html).

Driver ji přečte ve stejném spojení jako teplotu/vlhkost, nejvýše jednou za
hodinu. Po neúspěchu ji zkusí nejdříve za pět minut. Čtení má vlastní dvousekundový
limit; chyba či neplatná hodnota baterie nezahodí platné klimatické měření.
Celkový rozpočet spojení je rozšířen o tyto nejvýše dvě sekundy.

API předává `battery_percent` a `battery_timestamp`; poslední úspěšný údaj
přežije restart prostřednictvím uložených posledních měření. Nastavení ukazuje
procenta, v titulku čas jejich načtení. Pokud se standardní údaj dosud nenačetl,
zobrazí se „—“. Jde o odhad senzoru, nikoli laboratorní měření kapacity.

`battery_raw` z proprietární A2 odpovědi není procento a nekonvertuje se na něj.
Původní Android aplikace tento bajt mapuje pouze na High/Low
(`SettingActivity.refreshTemperatureUnit`, `Resource.analyseHygrometer`).
Nepřidávají se bateriové alerty ani push notifikace.
