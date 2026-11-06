# První Xiaomi LYWSD03MMC: OTA a ověření BTHome

Ověřeno 6. 11. 2026 na jednom uživatelově kusu. SensoGrid zatím nemá přidanou podporu tohoto protokolu; v této etapě nebyl měněn jeho produkční komunikátor ani nasazení na Debianu.

## Identifikace

- Obal: LYWSD03MMC, SKU NUN4106CN, výroba 2025.10.
- Původní GATT metadata: HW B1.5, software 0159, firmware 2.1.1_0159.
- Po instalaci ATC: HW B1.1, firmware 5.9, identifikace github.com/pvvx.
- Aktuální BLE jméno: ATC_5E0001.
- MAC před i po aktualizaci: 02:00:00:5E:00:01.

Označení HW se mezi původním a alternativním firmwarem liší. Ve flasheru autora odpovídá označení B1.1 indexu 14, komentovanému jako varianta B1.6 z roku 2025. Nejde o fyzickou změnu desky; skutečný potisk PCB nebyl ověřen. Uživatel potvrdil správné zobrazení teploty a vlhkosti na LCD po aktualizaci.

## Provedený postup

1. Uživatel přidal jeden senzor do Xiaomi Home, region Česko/Evropa.
2. Xiaomi Cloud Tokens Extractor v1.5.1 byl stažen z oficiálního release; SHA-256 souhlasil s metadaty GitHub assetu. Přihlášení proběhlo přes QR, následně byl zvolen server de. Extraktor byl po získání údajů ukončen.
3. Device ID, dvanáctibajtový Mi Token a šestnáctibajtový BLE Bindkey byly přeneseny do TelinkMiFlasheru. Přihlášení skončilo hláškou Login successful. Dokument neobsahuje žádný z těchto údajů.
4. První OTA: Original_OTA_Xiaomi_LYWSD03MMC_v2.1.1_0159c.bin, 105 760 bajtů, dokončeno za 104,544 s. Po restartu se zařízení znovu připojilo.
5. Druhé přihlášení a OTA: bin/ATC_v59.bin, 86 308 bajtů před přidáním podpisového souboru, dokončeno za 88,22 s.
6. Po restartu a dvou automatických opakováních připojení flasher přečetl firmware V5.9. Krátký test notifikací potvrdil živé měření, potom byly notifikace zastaveny a spojení ukončeno.

Údaje do souboru s přihlašovacími klíči nebyly uloženy. Výchozí konfigurace ATC zůstala zachovaná; nebylo provedeno přepínání šifrování, mazání záznamů, změna MAC, PIN ani kalibrace.

## Aktuální konfigurace

- BTHome v2, UUID služby 0xFCD2.
- Výchozí reklamní pakety jsou nešifrované. Zařízení v Bluetooth dosahu je mohou přečíst.
- Reklamní interval 2 500 ms, měření po 10 s.
- Výkon přibližně 0 dBm; LE Long Range vypnutý.
- Příjem nevyžaduje trvalé ani periodické GATT spojení.

## Ověření reklam bez připojení

Samostatný Windows Bleak scanner používal pouze příjem reklam, bez BleakClient nebo GATT operací. Úspěšný 35sekundový záznam obsahoval osm zpracovaných paketů daného senzoru; nejde o měření rádiové ztrátovosti, protože Windows/Bleak mohou slučovat nebo filtrovat opakované reklamy. Scanner byl v aktivním režimu, tedy mohl vysílat scan request; nešlo o důkaz čistě pasivního rádiového režimu.

Příklad přijatého payloadu služby 0xFCD2:

```text
40 00 21 01 5a 02 63 09 03 dd 10
```

- BTHome v2, bez šifrování.
- Packet ID 33.
- Baterie 90 % (odhad firmwaru).
- Teplota 24,03 °C.
- Vlhkost 43,17 %.
- RSSI při příjmu přibližně -57 dBm; jde o polohu při tomto testu.

Přijat byl také pomocný paket s napětím 2,925 V a stavy power/opening. Pakety nemusí obsahovat všechny veličiny zároveň. Budoucí komunikátor musí slučovat jednotlivá pole podle MAC a nepřepisovat teplotu/vlhkost na prázdnou hodnotu při přijetí pomocného paketu. Čerstvost klimatického měření se nemá obnovovat jen paketem s napětím nebo stavem GPIO.

Dlouhodobá stabilita a výdrž baterie zatím nebyly změřeny. Test nedokládá, že současná aplikace SensoGrid už tato data ukládá.

## Podklady

- [Firmware a podpora zařízení](https://github.com/pvvx/ATC_MiThermometer)
- [První OTA pro 0159 a nové HW varianty](https://github.com/pvvx/ATC_MiThermometer/issues/602)
- [TelinkMiFlasher](https://pvvx.github.io/ATC_MiThermometer/TelinkMiFlasher.html)
- [Token extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor/releases/tag/v1.5.1)
- [BTHome v2 formát](https://bthome.io/format/)

Pracovní snímek obrazovky a dočasný ověřovací scanner jsou v ignorované složce .logs/xiaomi-tools/v1.5.1/. Přihlašovací údaje do repozitáře nepatří.
