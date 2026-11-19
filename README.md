# SensoGrid

Stabilní verze **1.0.1**. Docker image: `ghcr.io/stecik/sensogrid:1.0.1` (Linux amd64). [Poznámky k vydání](docs/releases/1.0.1.md).

Lokální monitor teploty a vlhkosti. Vue 3 PWA + FastAPI, SQLite pro nastavení, InfluxDB 3 Core pro historii. Dva runtime kontejnery. Xiaomi LYWSD03MMC s pvvx ATC firmwarem (ověřeno v5.9): teplota, vlhkost a baterie z nešifrovaných BTHome v2 reklam, bez BLE spojení.

## Co aplikace obsahuje

- Český/anglický mobilní dashboard, světlý/tmavý/systémový vzhled.
- SVG půdorys s plynulou teplotní/vlhkostní mapou a historickým časem. Barvy se interpolují mezi dvěma nastavitelnými hranicemi přes zelený střed komfortního pásma; za hranicemi zůstává krajní odstín. Teplotní hranice jsou v °C i při zobrazení °F. Starší trojice nastavení se načte se zachováním krajních hodnot.
- Editor polygonů, vrcholů a umístění senzorů; grid, snap, zoom/pan, undo/redo.
- Validovaný JSON import s náhledem a atomickým uložením; export s verzí schématu.
- Historické ECharts grafy, srovnání místností, rozsahy a agregace.
- Průběžný příjem BTHome reklam, hledání senzorů, náhled měření a diagnostika.
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

Rozšíření připojuje hostitelský systémový D-Bus socket; bez privileged a bez předávání celého /dev. Aplikace běží jako UID/GID 10001. Oprávnění k org.bluez musí dovolit hostitelská D-Bus policy pro tuto identitu. Nejprve ověř Bleak scan na hostu a logy app; neřeš problém globálním privileged. Některé distribuce budou vyžadovat cílenou D-Bus policy pro skupinu uživatele kontejneru. Mount /run/dbus zpřístupňuje systémový bus, proto používej důvěryhodný dedikovaný host.

Windows Docker Desktop nenahrazuje hostitelský BlueZ. Windows nativní Bleak je podporovaný; linuxový kontejner na Windows nemá automaticky přístup k adaptéru PC.

V Nastavení spusť hledání, přidej konkrétní ATC senzor a přiřaď místnost. Zařízení se identifikují podle MAC, ne názvu; cizí nalezené zařízení se samo nezaregistruje. Nový senzor dědí interval ukládání historie (výchozí 60 s); vlastní override lze zrušit null přes API. Podrobnosti: [Xiaomi / BTHome](docs/xiaomi-bthome.md).

### Historické pády při GATT čtení LT senzorů

Původní rozbor a dočasný balík BlueZ jsou [archivované zde](docs/legacy-lt-bluetooth.md). Nový sběrač neprovádí GATT discovery ani připojování; archivované výsledky nedokládají stabilitu nového příjmu reklam.

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

Při diagnostice nastav SENSOGRID_DIAGNOSTICS=true: loguje dekódované BTHome objekty podporovaných reklam. Diagnostický ZIP obsahuje počty přijatých/neplatných/duplicitních paketů, stav scanneru a hash nového dekodéru. Ve výchozím režimu je podrobné logování vypnuté. Hesla, session ani push klíče se nelogují.

## Časová data a výpadky

SQLite obsahuje uživatele, sessions, nastavení, senzory, místnosti, půdorys, alerty a push subscriptions. Historická měření v ní nejsou. Migrace probíhají při startu; ID místností/senzorů jsou stabilní.

Influx tabulka measurements ukládá UTC čas přijetí měření od senzoru, sensor_id, room_id v okamžiku měření, teplotu, RH, zdroj, volitelné RSSI a samostatný ingested_at. BTHome klimatický rámec nepřenáší čas; timestamp je UTC čas přijetí teploty a vlhkosti, nikoli hardwarový čas měření. Pomocné pakety s napětím ani opakovaný packet ID jej neposouvají. Přesun senzoru historii nepřepíše; staré live hodnoty se nepřesunou do nové místnosti.

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
uv run ruff check .
uv run ruff format --check .
uv run ty check --error-on-warning
cd frontend
npm run lint
npm run test -- --run
npm run build
```

Ruff kontroluje chybějící anotace parametrů i návratových hodnot v celém Python kódu včetně testů a diagnostických skriptů (`ANN`). Pravidlo `ANN401` není zapnuté: explicitní `Any` je povolené na dynamických JSON a externích rozhraních. Statický checker [ty](https://docs.astral.sh/ty/) kontroluje kompatibilitu typů v backendu, testech i skriptech; CI selže i při jeho varování. Verze nástrojů jsou uzamčené v `uv.lock`. TypeScript ve frontendu kontroluje stávající `vue-tsc` při sestavení.

Testy mají explicitně dostupný kořen repozitáře i `backend`, takže `uv run pytest` i přímé spuštění `pytest` načítá pomocné moduly `scripts` stejně.

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

Aplikace běží na http://127.0.0.1:8000 v režimu BLE. V Nastavení vyhledej ATC/BTHome senzory, přidej vybrané zařízení a přiřaď místnost v Půdorysu. Scanner běží stále, sdílí se mezi discovery, náhledem a sběrem. „Počkat na nové vysílání“ čeká na další klimatický paket; neposílá teploměru žádný příkaz.

Dashboard zobrazuje nové přijaté hodnoty průběžně. Interval v Nastavení řídí pouze ukládání historie (výchozí 60 s pro nové instalace); stávající intervaly se nepřepisují. Žádná BLE spojení, concurrency ani připojovací retry. Zastarání řídí stáří klimatických dat. Windows/BlueZ používají aktivní scan reklam; scan request není GATT spojení. Nastavení teploměru: **BTHome v2**, **Encrypted beacon = 0**, **AdFlags = 1**. Stock Xiaomi MiBeacon ani šifrovaný BTHome se v této verzi nepřijímají.

## Záchranný restart Bluetooth — 23. 10. 2026

BLE sběr používá jediný scanner bez spojení. Historie propojuje chybějící úseky čarou mezi skutečnými vzorky; žádné náhradní vzorky se neukládají a statistiky se nemění.

Volitelný [hostitelský systemd timer](diagnostics/ble-rescue/README.md) restartuje pouze bluetooth.service, pokud všechny zapnuté BTHome senzory přestanou dodávat data nejméně na 10 minut (nebo trojnásobek nejdelšího intervalu měření). Stejná ochranná lhůta platí po startu aplikace. Další pokus nejdříve za 30 minut; jednotlivý nedostupný senzor restart nevyvolá. Instalace vyžaduje sudo; aplikace zůstává bez root oprávnění. Restart krátce přeruší i ostatní Bluetooth spojení hostitele. Jde o volitelnou dočasnou záchranu hostitele. Po aktualizaci skriptu zopakuj jeho instalátor; stará nainstalovaná kopie ještě započítává i LT senzory. Webová aplikace restart Bluetooth neprovádí.

Nastavení ukazuje poslední skutečné hodnoty a jejich čas i u nedostupných senzorů. API je při výpadku nevynuluje, takže je nenahradí starší náhled z prohlížeče. Dostupnost řídí příznak available; aktuální průměry a místnosti nadále používají pouze dostupné senzory.

## Diagnostika a baterie

V Nastavení lze stáhnout ZIP s posledními aplikačními logy a stavem senzorů. Pro systémové logy BlueZ je připraven volitelný čtecí helper; aplikace zůstává bez root oprávnění. [Nasazení a obsah diagnostiky](docs/diagnostics-and-battery.md).

Baterie se přijímá přímo jako procento z BTHome objektu `0x01`, včetně platných 0 %. Má vlastní čas přijetí; nepočítá se z napětí ani RSSI. Jde o odhad firmwaru, nikoli měření odebrané kapacity. Upozornění na baterii zatím nejsou přidána.

Další šetření pádů, chybějících core dumpů a výběru adaptéru: [stav a ověřovací postup](docs/ble-stability-investigation-2026-10-23.md).
