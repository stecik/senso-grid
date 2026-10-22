# SensoGrid: živý BLE test

Datum: 2026-10-22. Windows PC, Python 3.13, Bleak 3.0.2. Balíček instalován přes uv do diagnostics/.venv.

- Senzor: LT_7506, 02:00:00:5E:00:03.
- RSSI při druhém scanu: −61 dBm. Scan zaznamenal dvě skupiny hlášení vzdálené přibližně 6 s; skutečná perioda není určena.
- Spojení přes GATT úspěšné, MTU 128.
- Potvrzeny FFE5 service, FFE8 notify a FFE9 write-without-response.
- Dva dotazy A2 (AA AA A2 00 01 01 F8 55), tři platné odpovědi.
- Měření: 23,2 C; RH 53,0 %, 53,0 %, 52,0 %. Poslední vzorek 2026-10-22 17:48:25 Europe/Prague.
- Raw baterie 1; význam stupnice neověřen, nejde o potvrzené procento.
- Nebylo vyžadováno párování. Nebyly odeslány příkazy nastavení času, změny jednotek, historie ani resetu.
- Po dokončení vypnuty notifikace a spojení řádně uzavřeno.

## Surová odpověď

AAAAA2000600E802080100EF55

Teplota 00E8 = 232 / 10; RH 0208 = 520 / 10. Payload 6 B, checksum EF, konec 55.

## Ověření

Znovu zkontrolována délka, hlavička, konec a součet všech tří rámců. Log obsahuje connected, 2x query_sent, 3x measurement, notify_disabled a disconnected; žádný error/invalid_frame.

Zatím neověřeno: shoda s LCD, záporné teploty na skutečném zařízení, přesnost, historie, více senzorů, dlouhodobá stabilita, perioda nevyžádaných notifikací, odběr baterie a obsah advertisements.

Log: connection-attempt-2.jsonl. První scan: scan.jsonl. Krátký následný scan 8 s senzor nezachytil; druhý scan 20 s uspěl.
