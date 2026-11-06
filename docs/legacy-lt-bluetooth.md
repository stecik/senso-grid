# Archiv: původní LT teploměry

Původní senzory byly vráceny. Runtime od 6. 11. 2026 používá pouze BTHome v2.
LT driver, framing a radio scheduler zůstávají v `backend/sensogrid/ble/` jen pro
historické benchmarky a jejich testy. Aplikace je neimportuje.

### Dočasná oprava BlueZ na HomeServeru (23. 10. 2026)

**Pozdější nález při BLE benchmarku: 23. 10. v 11:25:26 CEST se BlueZ automaticky restartoval i s tímto balíkem, zatímco produkční aplikace byla zastavená. Backport proto nelze považovat za ověřené úplné řešení. Systémové logy potvrzují SIGSEGV; odpovídající debug symboly ukazují na gatt_db_attribute_write. Přesný mechanismus zatím určen není.**

Při opakovaném čtení LT senzorů padá na HomeServeru `bluetoothd` během GATT discovery. Základ: Debian 13 amd64, kernel `6.12.96+deb13-amd64`, BlueZ `5.82-1.1`, adaptér Realtek `0bda:b85b`; aplikace používá Bleak `3.0.2` a dbus-fast `5.2.0`.

Dočasný lokální balík **`bluez 5.82-1.1+sensogrid1`** zachovává Debian build a přidává dvě upstream opravy z 19. 10. 2026:

- [`6cdb936ebb6a3906062605883470d6b3a4e8c89e`](https://github.com/bluez/bluez/commit/6cdb936ebb6a3906062605883470d6b3a4e8c89e): oznámení odstranění i neaktivní GATT služby, aby v discovery nezůstal uvolněný ukazatel.
- [`a338533f913bf42b267aeba30f1344d85459c13c`](https://github.com/bluez/bluez/commit/a338533f913bf42b267aeba30f1344d85459c13c): zabránění dvojímu zařazení služby do fronty discovery.

**Nasazeno 23. 10. 2026 v 10:23:49 CEST.** Build, 201 upstream testů a regresní test prošly. V 10:25:40 CEST ověřeno všech 5 nových BLE měření po nasazení, žádný nedostupný senzor a NRestarts=0. Jde o krátkou kontrolu; noční stabilita zatím ověřena není. Postup, testy a evidence jsou v [diagnostics/bluez-5.82-fixes/README.md](../diagnostics/bluez-5.82-fixes/README.md), rozbor výpadku v [docs/incident-2026-10-23-bluez.md](incident-2026-10-23-bluez.md). Restart BlueZ obnovil měření jen dočasně; tato oprava cílí na chybu životnosti GATT služeb. Trvalou stabilitu je potřeba ověřit delším během všech pěti senzorů.

Balíky a návratová verze jsou na hostiteli v `/home/marek/sensogrid-bluez-5.82-fix-20261023/artifacts/`. Instalátor zálohuje konfiguraci a párovací stav Bluetooth do neveřejného adresáře `backup-<UTC čas>`. Krátce zastaví pouze SensoGrid a Bluetooth; InfluxDB a data aplikace zachová. Nezavádí automatické restartování BlueZ ani oprávnění webového kontejneru spravovat hostitele.

**Pozdější odstranění:** až distribuční BlueZ prokazatelně obsahuje obě opravy, přejdi zpět na konkrétní ověřenou distribuční verzi podle podrobného návodu. Samotné vyšší číslo verze není důkaz; vydání 5.87 těmto commitům předcházelo. Není nastaven `apt hold` ani pinning, ale přípona `+sensogrid1` může být řazena výše než další aktualizace stejného Debian základu, proto návrat zkontroluj ručně. Patche, pomocné skripty a tuto sekci odeber až po ověřeném návratu a stabilním provozu; do té doby ponech původní balík `5.82-1.1` pro rollback.

