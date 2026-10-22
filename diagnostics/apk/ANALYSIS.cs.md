# SensoGrid: statický rozbor LT_Thermometer 1.2.3

Datum: 2026-10-22. APK nebylo instalováno ani spuštěno. Tato část popisuje stav před živým testem. Následné spojení a čtení měření potvrzeno v diagnostics/ble/RESULT.cs.md.

## Výsledek

Komunikační cestu aplikace lze reprodukovat: BLE GATT, služba FFE5, notifikace FFE8, příkazy FFE9. Nalezeny rámce, kontrolní součet, aktuální měření a historie. V cestě připojení nejsou aplikační přihlášení, výměna klíčů ani šifrování. Žádná explicitní createBond v aplikačních třídách.

Jde o důkaz z kódu staženého APK. Shodu s konkrétními CX0726B musí potvrdit živý BLE scan a odpověď senzoru. Neověřeno: oprávnění GATT na zařízení, případná potřeba párování vyvolaná firmwarem, perioda notifikací, nutnost inicializace času, měření v advertisements, chování baterie a souběh více připojení.

## Soubor a původ

- Rozcestník: https://d.ihunuo.com/app/dqwu (název na webu: qaqa).
- Odkaz Android: https://newdownload.ihunuo.com/61c5338c57538b0aa31af962/LT_Thermometer-V1.2.3.apk
- HTTPS download selhal na ERR_TLS_CERT_ALTNAME_INVALID; certifikát neobsahoval newdownload.ihunuo.com.
- Staženo přes stejnou cestu HTTP. Transport tudíž neověřuje původ.
- Velikost: 3 285 388 B.
- SHA-256: 7ffd370999326caa60cc9847fc57ebed91555f6d9e5a5395b8bcef5077e585b9
- Package: com.ihunuo.lt.thermometer; versionName 1.2.3; versionCode 6.
- minSdk 21, targetSdk 34.
- Jediný classes.dex; bez assets a nativních knihoven lib/.
- JADX 1.5.6: dokončil s 6 hlášenými chybami. Markery chyb nalezeny v knihovních třídách AndroidX; žádný takový marker v aplikačním balíčku com.ihunuo. Dekompilovaný text zůstává interpretací bytecode.

## Omezené bezpečnostní posouzení

Manifest deklaruje BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN, ACCESS_COARSE_LOCATION, ACCESS_FINE_LOCATION a GET_TASKS. INTERNET nedeklaruje. Poloha souvisí i se staršími pravidly Android BLE skenování; sama nedokazuje sledování polohy. GET_TASKS je pro tuto funkci nadbytečné/starší oprávnění.

V prohlédnuté aplikační cestě nebyly nalezeny síťové endpointy, dynamické načítání DEX, spouštění procesů či nativní knihovny. Přibalené knihovny odpovídají Android UI, Material, FastBle a MPAndroidChart. Žádné služby, receivery ani providery v manifestu. Některé obrazovky jsou exported=true; allowBackup=true. Nejde o úplný bezpečnostní audit ani záruku nezávadnosti.

Android apksig 8.7.3: VERIFIED=true, V1=true, V2=true, V3=false. Certifikát self-signed CN=Hunuo, OU=Hunuo, O=Hunuo. Otisk certifikátu SHA-256:
720bfde9785307b0bbc25929dcea61d19937b84d44bdad8050f6f7f826c9fb44

JDK keytool hlásí 1024bit RSA klíč a SHA1withRSA podpis certifikátu. Platný podpis souboru není ověření identity výrobce; chybí nezávisle důvěryhodný referenční otisk. Obvyklý self-signed Android certifikát sám není důkaz malware.

Jarsigner navíc hlásil rozdíly ZIP/JAR čtení a řadu varování; proto byl použit Android APK verifier, který potvrdil v1/v2 bez chyb. Jeho úplný výstup je signature-verification.txt, včetně varování pro META-INF položky u v1. Tyto výsledky nenahrazují audit škodlivého chování.

## BLE identifikace

Aplikace filtruje zařízení, jejichž jméno obsahuje LT_ (nejde nutně o prefix).

| Účel | UUID |
|---|---|
| Service | 0000ffe5-0000-1000-8000-00805f9b34fb |
| Notify | 0000ffe8-0000-1000-8000-00805f9b34fb |
| Write | 0000ffe9-0000-1000-8000-00805f9b34fb |

Aplikace po spojení požaduje MTU 500. Za 100 ms po jeho vyjednání zapne notifikace. Za dalších 100 ms:
1. Nastaví aktuální místní datum/čas (A1).
2. Za 100 ms odešle A2 s payload 01.
3. Za 200 ms odešle A3 s aktuálním datem/časem.

MTU 500 je chování aplikace, nikoli ověřená podmínka firmware. Pro malé dotazy stačí délka rámce pod běžným ATT limitem; podporu fragmentace ověřit živě. Aplikace skládá přijaté bloky do bufferu.

## Rámec

AA AA CMD LEN_H LEN_L PAYLOAD CHECKSUM 55

- LEN: délka payload, unsigned 16bit big endian.
- CHECKSUM: součet všech předchozích bajtů modulo 256.
- Celková délka: LEN + 7.
- Příjemce má skládat fragmenty, rozdělovat více rámců a kontrolovat délku/checksum/koncový bajt.
- Originální parser kontroluje hlavičku a checksum; kontrolu koncového 55 v něm nenalézám.

| CMD | Význam a payload |
|---|---|
| A1 | Nastavit čas: rok−2000, měsíc 1–12, den, hodina, minuta, sekunda |
| A2 | 01 = dotaz, odpověď obsahuje aktuální měření a jednotku; 02 UNIT = změna jednotky (0 C, 1 F) |
| A3 | Historie, payload stejného formátu data/času jako A1 |
| A4 | Verze, payload 00 00; odpověď aplikace interpretuje jako text |
| A5 | Factory reset — pro diagnostiku NEPOUŽÍVAT |

Dotaz aktuálního stavu:
AA AA A2 00 01 01 F8 55

Dotaz verze:
AA AA A4 00 02 00 00 FA 55

Název metody getTemperatureUnit je zavádějící: parser odpovědi A2 čte i teplotu, vlhkost a stav baterie.

## Odpověď A2

Offsety od začátku celého rámce, číslování od nuly:

| Offset | Význam |
|---|---|
| 0–1 | AA AA |
| 2 | A2 |
| 3–4 | Délka payload |
| 5–6 | Signed int16 big endian / 10: teplota |
| 7–8 | Unsigned int16 big endian / 10: relativní vlhkost |
| 9 | Raw stav baterie; rozsah ani jednotka neověřeny, neoznačovat automaticky jako % |
| 10 | Jednotka displeje: 0 C, jinak aplikace používá F |
| LEN+5 | Checksum |
| LEN+6 | 55 |

Teplota se v grafickém formatteru převádí na F výrazem C*1.8+32; to podporuje interpretaci přenosu v C i při F na displeji. Potvrdit na zařízení.

Uměle sestavený příklad, nikoli zachycený paket:
AA AA A2 00 06 FF CC 01 C8 03 00 93 55
Dekóduje −5,2 C, 45,6 % RH, raw baterie 3, jednotka C.

## Historie A3

Payload odpovědi aplikace rozděluje po 4 bajtech:
- Signed int16 big endian / 10: teplota.
- Unsigned int16 big endian / 10: vlhkost.

Aplikace rekonstruuje hodinové timestampy relativně k datu dotazu: pro N záznamů nejprve odečte N hodin, před přidáním každého záznamu přičte hodinu. Poslední proto dostane čas dotazu. Žádné samostatné timestampy záznamů v tomto parseru nejsou. Skutečnou přesnost, retenci, pořadí a význam koncového času ověřit; nepovažovat tento odhad aplikace za přesný UTC čas měření.

## První test bez výrobní aplikace

Použít nRF Connect for Mobile od Nordic Semiconductor. Jeden senzor poblíž.

1. Scan: najít LT_ a zaznamenat jméno, adresu, raw advertisements, hodnotu displeje a čas.
2. Connect: ověřit FFE5, FFE8, FFE9 a jejich vlastnosti.
3. Zapnout notifikace na FFE8.
4. Do FFE9 zapsat HEX AA AA A2 00 01 01 F8 55; typ zápisu vybrat podle skutečných vlastností charakteristiky.
5. Uložit notifikace. Lehce zahřát senzor a porovnat několik hodnot s displejem.
6. Odpojit.

Dotaz A2 podle kódu žádá stav; nemění jednotky, čas ani historii. Pokud neodpoví, uložit GATT dump a log; nezkoušet náhodné příkazy. Potřebu A1, MTU či jiné inicializace posoudíme podle výsledku. Neprovádět factory reset ani aktualizaci firmware.

Tento test nebyl spuštěn. PCAPdroid není pro tuto BLE cestu potřeba.

## Zdrojové důkazy

Cesty relativní k decompiled/sources/com/ihunuo/lt/thermometer/:
- manager/MyBleManager.java:37–41 — UUID.
- manager/MyBleManager.java:115–120 — LT_ filtr.
- manager/MyBleManager.java:294–295 — MTU.
- manager/MyBleManager.java:330–337 — inicializační posloupnost.
- manager/MyBleManager.java:348–361 — notifikace a zápis.
- utils/ProtocolManager.java:28–81 — příkazy, datum, rámec, checksum.
- analysis/Resource.java:82–125 — buffer a validace.
- analysis/Resource.java:152–195 — aktuální a historická měření.
- utils/TemperatureFormatter.java:11 — převod C na F.
- decompiled/resources/AndroidManifest.xml — oprávnění a komponenty.

Ověřeno lokálně: opětovný SHA-256, APK podpis v1/v2, absence INTERNET v manifestu, výpočty dotazů A2/A4, signed záporná teplota a unsigned RH na syntetickém rámci. Není to integrační test zařízení.
