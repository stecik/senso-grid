# Firmware a inicializace spojení LT/CX0726B — 23. 10. 2026

## Ověřené verze zařízení

Jednorázové čtení z Windows přes Bleak, 20:19–20:21 CEST. Debian aplikace nebyla zastavena, změněna ani restartována. Dva scany (12 a 35 sekund); po nalezení jednotlivá krátká spojení. Nebyl odeslán reset, přepnutí jednotek, nastavení času, přepnutí do bootloaderu ani firmware.

| Místnost | BLE název | Verze LT (A4) | HW (2A27) | Software (2A28) |
| --- | --- | --- | --- | --- |
| Spíž | LT_4AF3 | V2.3 | 1.0.0.0 | 2.0.0.9 |
| Obývák | LT_831C | V2.3 | 1.0.0.0 | 2.0.0.9 |
| Kuchyně | LT_7506 | V2.3 | 1.0.0.0 | 2.0.0.9 |
| Ložnice | LT_5A0B | V2.3 | 1.0.0.0 | 2.0.0.9 |
| Koupelna | LT_530B | V2.3 | 1.0.0.0 | 2.0.0.9 |

Výrobce (2A29): `Beijing OnMicro Electronics Co., Ltd.`.
Standardní charakteristika Firmware Revision (2A26) nebyla vystavena. Proto odlišujeme **LT verzi V2.3**, kterou používá i původní aplikace, od standardního řetězce Software Revision **2.0.0.9**. Vztah těchto dvou verzí ani stáří sestavení neznáme.

PnP ID má na všech kusech hodnotu `01020304050607`; nevypadá jako spolehlivý identifikátor konkrétní desky. Výrobní čip nebyl fyzicky zkontrolován.

Evidence: [firmware-metadata-20261023.json](../diagnostics/ble/firmware-metadata-20261023.json). Původní scany, průběh a jednorázové skripty jsou lokálně v ignorovaném `.logs/firmware-20261023/`.

Dotaz na verzi je převzatý z původní aplikace: `ProtocolManager.getVersionInfo()` vrací `encapsulateData(164, new byte[2])`. Odeslaný rámec do FFE9:

```text
AA AA A4 00 02 00 00 FA 55
```

Odpověď A4 přes FFE8 obsahuje text `V2.3` (hex `56322e33`). Jde o dotaz na metadata, nikoliv o aktualizaci. Nenalezení čtyř zařízení v prvním krátkém scanu není důkaz jejich výpadku; druhý scan a následná čtení všechna čtyři ověřily.

## Dostupnost aktualizace

- [CX0726B na pvvx](https://pvvx.github.io/CX0726B/) je rozbor zařízení s čipem **OM6621DB**, nikoliv stránka s aktualizací.
- [Adresář CX0726B v repozitáři](https://github.com/pvvx/pvvx.github.io/tree/master/CX0726B) obsahoval při kontrole pouze `index.html` a `img/`.
- [ATC_MiThermometer](https://github.com/pvvx/ATC_MiThermometer) podporuje uvedené čipy **Telink**. CX0726B není uveden mezi podporovanými modely. Z existence CX0726B na témže webu nelze vyvozovat kompatibilitu s TelinkMiFlasher.
- [Stránka výrobce aplikace](https://d.ihunuo.com/app/dqwu) odkazuje na mobilní aplikace; veřejný katalog firmware nebo changelog jsem na ní nenašel.
- V dostupném dekompilovaném **qaqa 1.2.3, versionCode 6** jsem v aplikačním balíku a zdrojích aplikace nenašel cestu pro OTA aktualizaci. To není audit případné jiné/novější verze.

Všech pět zařízení vystavuje službu FE59 s charakteristikami 8EC90001/8EC90002, odpovídajícími názvům Nordic Secure DFU. [Databáze UUID Nordic](https://github.com/nordicsemi/bluetooth-numbers-database/blob/master/v1/service_uuids.json) přiřazuje FE59 právě této službě. Samotné UUID neprokazuje konkrétní čip, funkčnost OTA, přijímaný formát souboru ani kompatibilitu s libovolným firmwarem.

**Výsledek:** nenašel jsem ověřený kompatibilní novější firmware. Nelze potvrdit, že V2.3 je nejnovější, ani provést bezpečně zvolený update bez dalšího podkladu od výrobce nebo projektu výslovně podporujícího tuto desku. Žádný firmware nebyl stažen ani instalován.

## Rozdíly inicializace původní aplikace a SensoGridu

Zdroje původní aplikace: `diagnostics/apk/decompiled/sources/com/ihunuo/lt/thermometer/`, především `manager/MyBleManager.java`, `utils/ProtocolManager.java` a `activity/SettingActivity.java`.

| Krok | Původní aplikace qaqa 1.2.3 | SensoGrid |
| --- | --- | --- |
| Navázání | BLE GATT spojení | BLE GATT spojení |
| MTU | Asi po 100 ms žádá MTU 500, používá vyjednanou hodnotu | Nevyžaduje vlastní pevné MTU |
| Notifikace | Po úspěšném MTU a další prodlevě zapne FFE8 | Zapne FFE8 |
| Inicializace | Po další prodlevě A1 nastavení času, po 100 ms A2 dotaz, po 200 ms A3 historie | A2 dotaz na aktuální měření |
| Baterie | Původní jednoduchý indikátor v odpovědi A2 | Standardní 2A19 přibližně jednou za hodinu |
| Verze | A4 při otevření nastavení | Jednorázově A4 při této diagnostice |
| Životnost | Z analyzované cesty neplyne automatické odpojení po jednom měření; aplikace spojení drží | Po vzorku vypne notifikace a ukončuje spojení |

A1/A3 ani MTU požadavek nejsou důkazem autentizačního handshake. V uvedené cestě jsem nenašel zvláštní příkaz „potvrdit aplikaci“ nebo „rozsvítit Bluetooth ikonu“. To nevylučuje vedlejší účinek některého příkazu ve firmwaru.

Platné odpovědi A2 v aplikaci a A4 při této diagnostice potvrzují fungující BLE a aplikační výměnu, nikoliv kompletní shodu inicializace s výrobcem ani dlouhodobou stabilitu.

## Ikona na LCD a další srovnání

Význam kolečka a jeho vztah k Bluetooth symbolu není potvrzený manuálem ani firmwarem. Možné příčiny: krátké versus trvalé spojení, jiné LCD/hardware revize nebo odlišná inicializační sekvence. Nejsou to prokázané příčiny.

Smysluplné srovnání na jednom senzoru:
1. Poznamenat stav LCD před připojením originální aplikace.
2. Připojit originální aplikaci, zaznamenat symbol ihned a po 30 sekundách.
3. Zaznamenat symbol po explicitním odpojení.
4. Pokud se chování liší, porovnat krátké/trvalé spojení samostatně od A1, MTU a ostatních příkazů. Neměnit všechny proměnné současně.

Telefon může během svého spojení konkurovat čtení SensoGridu. Po srovnání senzor odpojit, aby telefon nezkreslil další noční sledování. Android Bluetooth HCI snoop je pro případné srovnání BLE vhodnější než VPN/HTTP PCAP.

## Aplikace Google Play

[Oficiální listing qaqa](https://play.google.com/store/apps/details?id=com.ihunuo.lt.thermometer) má stejný identifikátor balíku a výrobce jako analyzované APK. Listing při kontrole uváděl poslední aktualizaci 9. 10. 2026. Není ověřeno, zda dodávaný soubor odpovídá dříve analyzovanému APK 1.2.3.

Předchozí statická kontrola konkrétního APK není záruka bezpečnosti aplikace ani případné novější verze.

## Fyzická identifikace desky — doplnění z fotografie 20261023_211039.jpg

Druhá strana uživatelovy desky má čitelné označení **0726B_V6**. Na U2 vedle antény je čitelné **OM6621DB**; tím je pro vyfotografovaný kus potvrzen dříve pouze předpokládaný Bluetooth SoC. Ostatní čtyři kusy nebyly fyzicky otevřeny.

Pod černou zalévací hmotou je další obvod; podle vedení k LCD a snímačům pravděpodobně zajišťuje měření a/nebo LCD. Jeho typ a propojení s OM6621DB zatím nejsou ověřené. Proto nelze předpokládat, že výměnou BLE firmwaru přímo ovládneme všechna čidla nebo odstraníme celý klidový odběr. Případné ponechání měřicí/LCD části a změna pouze BLE části závisí na zmapování jejich rozhraní.

Na desce jsou popisy GND, VCC, RST, 40/41 a propojky J1–J5. Samotné popisy 40/41 **nejsou ověřený SWD pinout**; žádný programátor nebyl připojen ani doporučeno konkrétní zapojení.

Výrobce pro OM6621D uvádí SWD a OTA: https://www.onmicro.com.cn/enBLE/85.html . Nalezen oficiální příspěvek k SDK User Guide pro správnou rodinu D: https://bbs.onmicro.com.cn/OM6621D/95.html a stručný datasheet: https://bbs.onmicro.com.cn/OM6621D/94.html . Odkazy na obě přílohy přesměrovaly na přihlášení; návody ani samotné použitelné SDK proto zatím nejsou získané.

## Veřejné podklady mimo fórum — průzkum 23. 10. 2026

Prohledány veřejné webové výsledky v angličtině a čínštině, GitHub repozitáře pro OM6621/HS6621 a nabídky distributorů. Nebyl nalezen a získán kompletní ověřený SDK pro OM6621D/OM6621DB. To není důkaz, že nikde veřejně neexistuje.

### Získaný datasheet správné rodiny

Veřejné zrcadlo výrobního dokumentu: [OM6621Dx datasheet V1.3](http://rafavi.com/images/chips/datasheet/OM6621Dx_datasheet_V1.3.pdf). Soubor byl skutečně stažen, otevřen PDF parserem a obálka vizuálně ověřena. Revize V1.3 je ze 4. 8. 2021. PDF má 182 fyzických stran: obálku a 181 číslovaných stran. Obsahuje OM6621DB/QFN20, registry periferií, paměťovou mapu a řízení napájení. Jde o starší dokument; jeho parametry se mohou lišit od novější produktové stránky výrobce.

Lokální pracovní kopie (ignorovaná Gitem): .logs/om6621-public-research/OM6621Dx-datasheet-V1.3.pdf, 8 781 283 B, SHA-256 8334e97c65c20ea594eb2800d90eaa66e526ce96c673e7a2dfa1446078270ae5. Původní zrcadlo fungovalo přes HTTP; nejde o kryptograficky ověřené vydání výrobce. Zrcadla yikouzu.com a bluetooth.com.cn se při pokusech nepodařilo stáhnout.

Datasheet neposkytuje hotový BLE stack/SDK ani ověřený OTA postup pro firmware konkrétního teploměru.

### SDK a příbuzné čipy

- [Shhmotion — HS6621 vývojové podklady](https://www.shhmotion.com/supportDetail.html?docId=2111121068351352): zveřejňuje odkaz na balík s dokumentací a SDK. Přesný odkaz v HTML je https://pan.baidu.com/s/1PE9iqcj96-0sWVzciEF1Lg?pwd=shhm . Přímé načtení vrátilo HTML s titulkem „百度网盘-链接不存在“ (odkaz neexistuje). Obsah balíku ani podporované varianty proto nebyly ověřeny.
- [OM6621E SDK User Guide V1.2, veřejná kopie výrobního manuálu](https://docs.gtai-tech.com/static-file/eb200d4b-e47d-45c1-b1a5-562700c54cd7/fbc01b51-c130-4eec-a6fe-b414f7c2110c.pdf): skutečně stažen a ověřen, 50 stran, 3 230 171 B. SHA-256 eff56bd8656a7b9f3009dbf23079f77adc6a64b527e0ed08abb3e204e374b901. Strana 50 uvádí rozdíly D/E v SRAM a umístění BLE stacku v ROM/flash. Manuál není SDK a neprokazuje použitelnost kódu nebo binárek pro řadu D.
- [SoCXin/OM6621](https://github.com/SoCXin/OM6621) a fork apache21/OM6621 jsou malé přehledové repozitáře pro OM6621EM, nikoliv nalezený SDK pro D.
- [kagaimiq/huntersun](https://github.com/kagaimiq/huntersun) obsahuje výzkum HS6620D a odkazy k dalším příbuzným čipům; není ověřeným SDK pro OM6621DB.

### Dopad na OTA-only postup

Získali jsme podrobný hardware dokument pro správnou rodinu. Pořád chybí ověřený SDK/BLE stack pro D a popis bootloaderu konkrétního teploměru (formát obrazu, případný podpis, obnova po chybě). Nelze slíbit vytvoření a bezpečné bezdrátové nahrání vlastního firmwaru pouze na základě datasheetu a přítomnosti DFU služby. Žádný firmware ani DFU aktivační příkaz nebyl při tomto průzkumu odeslán; na Debianu nebylo nic změněno.
