# SensoGrid

Lokální monitor teploty a vlhkosti. Vue 3 PWA + FastAPI, SQLite pro nastavení, InfluxDB 3 Core pro historii. Dva runtime kontejnery. Ověřený BLE driver pro LT_7506 / teploměry používající protokol aplikace LT_Thermometer.

## Co aplikace obsahuje

- Český/anglický mobilní dashboard, světlý/tmavý/systémový vzhled.
- SVG půdorys s plynulou teplotní/vlhkostní mapou a historickým časem. Barvy se interpolují mezi dvěma nastavitelnými hranicemi přes zelený střed komfortního pásma; za hranicemi zůstává krajní odstín. Teplotní hranice jsou v °C i při zobrazení °F. Starší trojice nastavení se načte se zachováním krajních hodnot.
- Editor polygonů, vrcholů a umístění senzorů; grid, snap, zoom/pan, undo/redo.
- Validovaný JSON import s náhledem a atomickým uložením; export s verzí schématu.
- Historické ECharts grafy, srovnání místností, rozsahy a agregace.
- BLE discovery, dotaz na aktuální měření, diagnostika, opakování po chybě.
- Pravidla teploty/vlhkosti/neaktivity s dobou trvání, hysterezí a historií.
- Lokální přihlášení, nastavení napříč zařízeními, volitelný Web Push.
- Explicitní demo režim. Simulace se nikdy nepoužije jako náhrada výpadku reálného úložiště.

## Rychlý start: lokální demo

Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```sh
uv sync --frozen --group dev
uv run uvicorn sensogrid.main:app --host 127.0.0.1 --port 8000
```

Druhý terminál:

```sh
cd frontend
npm ci
npm run dev
```

Otevři adresu Vite (standardně http://localhost:5173). Při prvním otevření vytvoř lokálního administrátora, heslo alespoň 8 znaků s velkým i malým písmenem a symbolem. Výchozí účet ani heslo neexistují. API při startu v režimu demo vytvoří vzorové místnosti a senzory.

Pro jednu adresu bez Vite:

```sh
cd frontend
npm ci
npm run build
cd ..
uv run uvicorn sensogrid.main:app --host 127.0.0.1 --port 8000
```

Pak http://127.0.0.1:8000. Lokální data v ./data. Demo historie vzniká deterministicky na vyžádání; do databáze měření se nezapisuje. API samo soubor .env nenačítá; pro nativní běh nastav proměnné v prostředí nebo použij uvicorn --env-file .env.

## Docker Compose: dva kontejnery

```sh
python scripts/bootstrap.py
docker compose build
docker compose up -d
```

Bootstrap vytvoří soukromou .env a offline admin token pro InfluxDB v .secrets/. Existující přihlašovací údaje nepřepisuje. Necommitovat tyto soubory. Tokeny při startu nevypisujeme.

- Aplikace: http://127.0.0.1:8097.
- InfluxDB nemá publikovaný port; přístup má aplikace v Docker síti.
- Režim se řídí SENSOGRID_MODE v .env: ble / demo / off.
- Standardní Compose počítá s Linux BLE rozšířením pro reálné senzory. Pro demo nastav SENSOGRID_MODE=demo.
- Výchozí bind je localhost. Nejdřív vytvoř účet; pro LAN pak nastav SENSOGRID_BIND nebo připoj existující HTTPS reverse proxy.
- Health endpoint /health není autentizovaný. Data a konfigurace vyžadují session.
- PWA/offline instalace a Web Push potřebují HTTPS nebo vývojovou výjimku localhost.

### Debian 13 / N100: reálné BLE

Host musí mít funkční Bluetooth LE adaptér a běžící BlueZ:

```sh
sudo apt-get install bluez
sudo systemctl enable --now bluetooth
bluetoothctl show
# dbus-daemon odpojí UID, které hostitel nezná; kontejner běží jako 10001.
sudo groupadd --system --gid 10001 sensogrid
sudo useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sensogrid
sudo usermod -aG bluetooth sensogrid
sudo systemctl reload dbus
docker compose -f compose.yaml -f compose.ble.yaml up -d --build
```

Rozšíření připojuje hostitelský systémový D-Bus socket; bez privileged a bez předávání celého /dev. Aplikace běží jako UID/GID 10001. Oprávnění k org.bluez musí dovolit hostitelská D-Bus policy pro tuto identitu. Nejprve ověř běžné Bleak připojení na hostu a logy app; neřeš problém globálním privileged. Některé distribuce budou vyžadovat cílenou D-Bus policy pro skupinu uživatele kontejneru. Mount /run/dbus zpřístupňuje systémový bus, proto používej důvěryhodný dedikovaný host.

Windows Docker Desktop nenahrazuje hostitelský BlueZ. Windows nativní Bleak je podporovaný; linuxový kontejner na Windows nemá automaticky přístup k adaptéru PC.

V Nastavení spusť hledání, přidej konkrétní LT_ senzor a přiřaď místnost. Neprobíhá automatické párování cizích zařízení. Nový senzor dědí globální interval (výchozí 900 s); vlastní override lze zrušit null přes API.

### Dočasná oprava BlueZ na HomeServeru (23. 10. 2026)

**Pozdější nález při BLE benchmarku: 23. 10. v 11:25:26 CEST se BlueZ automaticky restartoval i s tímto balíkem, zatímco produkční aplikace byla zastavená. Backport proto nelze považovat za ověřené úplné řešení. Systémové logy potvrzují SIGSEGV; odpovídající debug symboly ukazují na gatt_db_attribute_write. Přesný mechanismus zatím určen není.**

Při opakovaném čtení LT senzorů padá na HomeServeru `bluetoothd` během GATT discovery. Základ: Debian 13 amd64, kernel `6.12.96+deb13-amd64`, BlueZ `5.82-1.1`, adaptér Realtek `0bda:b85b`; aplikace používá Bleak `3.0.2` a dbus-fast `5.2.0`.

Dočasný lokální balík **`bluez 5.82-1.1+sensogrid1`** zachovává Debian build a přidává dvě upstream opravy z 19. 10. 2026:

- [`6cdb936ebb6a3906062605883470d6b3a4e8c89e`](https://github.com/bluez/bluez/commit/6cdb936ebb6a3906062605883470d6b3a4e8c89e): oznámení odstranění i neaktivní GATT služby, aby v discovery nezůstal uvolněný ukazatel.
- [`a338533f913bf42b267aeba30f1344d85459c13c`](https://github.com/bluez/bluez/commit/a338533f913bf42b267aeba30f1344d85459c13c): zabránění dvojímu zařazení služby do fronty discovery.

**Nasazeno 23. 10. 2026 v 10:23:49 CEST.** Build, 201 upstream testů a regresní test prošly. V 10:25:40 CEST ověřeno všech 5 nových BLE měření po nasazení, žádný nedostupný senzor a NRestarts=0. Jde o krátkou kontrolu; noční stabilita zatím ověřena není. Postup, testy a evidence jsou v [diagnostics/bluez-5.82-fixes/README.md](diagnostics/bluez-5.82-fixes/README.md), rozbor výpadku v [docs/incident-2026-10-23-bluez.md](docs/incident-2026-10-23-bluez.md). Restart BlueZ obnovil měření jen dočasně; tato oprava cílí na chybu životnosti GATT služeb. Trvalou stabilitu je potřeba ověřit delším během všech pěti senzorů.

Balíky a návratová verze jsou na hostiteli v `/home/marek/sensogrid-bluez-5.82-fix-20261023/artifacts/`. Instalátor zálohuje konfiguraci a párovací stav Bluetooth do neveřejného adresáře `backup-<UTC čas>`. Krátce zastaví pouze SensoGrid a Bluetooth; InfluxDB a data aplikace zachová. Nezavádí automatické restartování BlueZ ani oprávnění webového kontejneru spravovat hostitele.

**Pozdější odstranění:** až distribuční BlueZ prokazatelně obsahuje obě opravy, přejdi zpět na konkrétní ověřenou distribuční verzi podle podrobného návodu. Samotné vyšší číslo verze není důkaz; vydání 5.87 těmto commitům předcházelo. Není nastaven `apt hold` ani pinning, ale přípona `+sensogrid1` může být řazena výše než další aktualizace stejného Debian základu, proto návrat zkontroluj ručně. Patche, pomocné skripty a tuto sekci odeber až po ověřeném návratu a stabilním provozu; do té doby ponech původní balík `5.82-1.1` pro rollback.

### Portainer

Sestav a označ image z repozitáře, případně ho nahraj do vlastní registry. Portainer obvykle nesestavuje Dockerfile při vložení samotného YAML; použij již sestavený image (SENSOGRID_IMAGE). Pro Git stack musí existovat .secrets/influxdb-admin.json na hostu přístupném správci stacku. Vlož proměnné z lokální .env do prostředí stacku. Pro BLE použij sloučenou konfiguraci compose.yaml + compose.ble.yaml a bind /run/dbus.

```sh
docker compose -f compose.yaml -f compose.ble.yaml config > /secure/path/sensogrid-stack.yaml
```

Výstup config obsahuje prostředí včetně tokenu. Ulož ho soukromě, nepřikládej do issue. Absolutní cestu secret souboru v něm přizpůsob hostu Portaineru. Dva runtime services: app a influxdb.

### HTTPS reverse proxy

Proxy zachová Host a nastaví X-Forwarded-Proto. SENSOGRID_PROXY_IPS nastav na skutečnou adresu/adresy důvěryhodné proxy; jinak Uvicorn správně ignoruje předané schéma a kontrola Origin odmítne zápis z HTTPS. Za HTTPS nastav SENSOGRID_SECURE_COOKIES=true. API nepovoluje wildcard CORS.

## Nativní sběr na PC

Použij samostatný data_dir pro reálné nasazení; demo místnosti/senzory nepřenášej automaticky.

PowerShell:

```powershell
$env:SENSOGRID_MODE = "ble"
$env:SENSOGRID_DATA_DIR = "./data-live"
$env:SENSOGRID_INFLUX_URL = "http://localhost:8181"
# Nastav SENSOGRID_INFLUX_TOKEN podle vlastního InfluxDB; nevkládej token do historie shellu.
uv run uvicorn sensogrid.main:app --host 127.0.0.1 --port 8000
```

Při diagnostice nastav SENSOGRID_DIAGNOSTICS=true: loguje raw advertisement/service/manufacturer data a GATT charakteristiky/notifikace podporovaného zařízení. Ve výchozím režimu je podrobné logování vypnuté. Hesla, session ani push klíče se nelogují.

## Časová data a výpadky

SQLite obsahuje uživatele, sessions, nastavení, senzory, místnosti, půdorys, alerty a push subscriptions. Historická měření v ní nejsou. Migrace probíhají při startu; ID místností/senzorů jsou stabilní.

Influx tabulka measurements ukládá UTC čas přijetí měření od senzoru, sensor_id, room_id v okamžiku měření, teplotu, RH, zdroj, volitelné RSSI a samostatný ingested_at. Senzorový A2 rámec vlastní čas nemá; timestamp tedy není hardwarový čas měření. Přesun senzoru historii nepřepíše; staré live hodnoty se nepřesunou do nové místnosti.

Core má limit přibližně 72 h na dotaz. Aplikace používá nejvýše 48h SQL okna, serverovou agregaci a vážené sloučení přes hranice oken. Dny/týdny/měsíce jsou kalendářní UTC; UI zobrazuje místní čas. Raw rozsah je limitovaný počtem bodů; větší rozsah vyžaduje agregaci. Chybějící hodnoty se nedoplňují nulou.

Při výpadku DB sběrač ukládá čekající zápisy do trvalého data_dir/outbox, opakuje je a UI hlásí problém. Fronta má limit 10 000 měření, po naplnění hlásí chybu. Zápis je opakovatelný podle sensor/room/source/time. Čekající soubory neztrácej při záloze. Není nastavena automatická retence; výkon dlouhých rozsahů Core se s množstvím dat může zhoršovat.

## Volitelný Web Push

Monitoring žádný cloud nepotřebuje. Doručení Web Push však používá push server prohlížeče (např. Mozilla/Google/Apple); tuto síťovou závislost uživatel výslovně zvolil jako volitelnou.

```sh
uv run scripts/vapid_keys.py
```

Příkaz vytvoří identitu do .secrets/ a doplní klíče do .env. Nastav platný SENSOGRID_VAPID_SUBJECT (mailto kontakt nebo HTTPS URL) a restartuj app. Klíče zachovej při upgradech, jinak stávající subscriptions přestanou fungovat. V Nastavení pro každý prohlížeč samostatně povol oznámení a odešli test. Backend doručuje i při zavřené PWA; neplatné subscriptions odstraňuje. Bez klíčů je Push nedostupný, lokální alerty fungují dál.

## Záloha a upgrade

Zachovej volumes app_data (SQLite + outbox) a influx_data (WAL/Parquet/catalog), .env a .secrets. Pro konzistentní souborovou zálohu zastav aplikaci a InfluxDB, zazálohuj oba volumes, potom je spusť. Samotná kopie otevřeného SQLite souboru nemusí být konzistentní. Před upgradem InfluxDB zazálohuj katalog a ověř dokumentaci verze; rollback může vyžadovat obnovu. Docker image InfluxDB je připnutý na 3.12.0-core.

## Ověření vývoje

```sh
uv run pytest
uv run ruff check backend scripts
uv run ruff format --check backend scripts
cd frontend
npm run lint
npm run test -- --run
npm run build
```

Opt-in test skutečného InfluxDB: nastav SENSOGRID_TEST_INFLUX_URL a SENSOGRID_TEST_INFLUX_TOKEN; pytest vytvoří oddělenou databázi sensogrid_integration. Standardní unit testy síť ani skutečné senzory nepotřebují.

API schéma je po přihlášení na /api/openapi.json. Návrh a rozhraní: docs/contract.md; původní požadavky: docs/requirements.md; evidence BLE: docs/ble-protocol.cs.md a docs/ble-hardware-test.cs.md.

## Zdroje technických omezení

- [InfluxDB 3 Core SQL/time range](https://docs.influxdata.com/influxdb3/core/get-started/query/)
- [Offline admin token a konfigurace](https://docs.influxdata.com/influxdb3/core/reference/config-options/)
- [Bleak Windows backend](https://bleak.readthedocs.io/en/latest/backends/windows.html)

### Windows s fyzickými senzory

Bluetooth sběr běží nativně ve Windows, InfluxDB v Dockeru. Po instalaci závislostí, buildu frontendu a bootstrapu spusť v PowerShellu:

~~~powershell
./scripts/start-local.ps1
~~~

Aplikace běží na http://127.0.0.1:8000 v režimu BLE. V Nastavení vyhledej senzory; nalezená zařízení načtou teplotu a vlhkost asynchronně ještě před přidáním. Při neúspěchu použij Změřit znovu. Potom vybrané senzory přidej. Nalezená zařízení zůstávají v seznamu i při výpadku nebo dalším hledání; lze je přidat a upravit offline. Poslední hodnoty mají vlastní čas měření. Seznam si pamatuje tento prohlížeč pro přihlášený účet. Seznam ukazuje poslední teplotu, vlhkost a čas měření, obnovuje se každých 5 sekund; fyzické měření řídí interval sběru (výchozí 900 sekund). Při identifikaci lze dočasně nastavit kratší interval. V Půdorysu importuj vlastní JSON a vyber senzor a místnost. Import podporuje export SensoGridu i formát s `schemaVersion: 1`, `units: "meters"`, `canvas: {width, height}` a `rooms`; před použitím zobrazí validovaný náhled. Měření zůstává uložené podle ID senzoru i bez přiřazené místnosti.

Sběr BLE při chybě provede celkem pět pokusů s prodlevami 1, 2, 4 a 8 sekund. Po vyčerpání pokusů následuje nový cyklus za 30 sekund; běžný interval tento retry neodkládá. Při změně přiřazení senzoru se nové měření spustí bez čekání na běžný interval. Poslední skutečné hodnoty přežijí restart, stále platí nastavená hranice zastarání a přiřazení k místnosti.

Senzory v Nastavení tvoří jediný seznam podle MAC adresy. Uložený název, ID a přiřazení mají přednost před BLE názvem; opakované hledání nevytváří další záznam. MAC se porovnává bez ohledu na velikost písmen, dvojtečky, pomlčky a mezery; API brání duplicitní registraci.

Sběr i náhledy používají asynchronní čtení. Limit souběžných BLE spojení nastavuje `SENSOGRID_BLE_CONCURRENCY` (1–10, výchozí 2); konkrétní adaptér/Windows může skutečná spojení omezovat. Při problémech lze limit snížit. Stejná MAC se nikdy nečte dvěma spojeními současně; scan se provádí odděleně od připojených klientů. Nativní test 5 senzorů uspěl, ale v tomto běhu byl pozorován pouze jeden současně plně navázaný GATT klient; deset fyzických spojení nebylo ověřeno. Viz [BleakClient](https://bleak.readthedocs.io/en/latest/api/client.html).

## BLE benchmark Debian / Windows — 23. 10. 2026

[Celý report a výsledky po senzorech](docs/ble-benchmark-2026-10-23.md). Debian: nejlepší pilotní výsledek dvě současná čtení (86 %). Windows: nejvíce dodaných vzorků při limitu pět (80 %), ale Obývák už chyběl a reálně byla dostupná pouze čtyři zařízení. Linuxový profil D obsahuje potvrzený další pád BlueZ 5.82-1.1+sensogrid1; backport stabilitu nezajistil. Produkční retry/souběh se při experimentu neměnily.

## Záchranný restart Bluetooth — 23. 10. 2026

Výchozí souběh BLE je nyní 2. Historie propojuje chybějící úseky čarou mezi skutečnými vzorky; žádné náhradní vzorky se neukládají a statistiky se nemění.

Volitelný [hostitelský systemd timer](diagnostics/ble-rescue/README.md) restartuje pouze bluetooth.service, pokud všechny zapnuté senzory přestanou dodávat data nejméně na 10 minut (nebo trojnásobek nejdelšího intervalu měření). Stejná ochranná lhůta platí po startu aplikace. Další pokus nejdříve za 30 minut; jednotlivý nedostupný senzor restart nevyvolá. Instalace vyžaduje sudo; aplikace zůstává bez root oprávnění. Restart krátce přeruší i ostatní Bluetooth spojení hostitele. Jde o dočasnou záchranu, ne opravu příčiny pádu BlueZ 5.82-1.1+sensogrid1.

Nastavení ukazuje poslední skutečné hodnoty a jejich čas i u nedostupných senzorů. API je při výpadku nevynuluje, takže je nenahradí starší náhled z prohlížeče. Dostupnost řídí příznak available; aktuální průměry a místnosti nadále používají pouze dostupné senzory.

## Diagnostika a baterie

V Nastavení lze stáhnout ZIP s posledními aplikačními logy a stavem senzorů. Pro systémové logy BlueZ je připraven volitelný čtecí helper; aplikace zůstává bez root oprávnění. [Nasazení a obsah diagnostiky](docs/diagnostics-and-battery.md).

Baterie se zobrazuje v procentech ze standardní charakteristiky Bluetooth 2A19, nikoli přepočtem battery_raw. Pokud hodnotu firmware neposkytne, zobrazí se „—“. Čte se ve stejném spojení nejvýše jednou za hodinu; upozornění na baterii zatím nejsou přidána.

Další šetření pádů, chybějících core dumpů a výběru adaptéru: [stav a ověřovací postup](docs/ble-stability-investigation-2026-10-23.md).
