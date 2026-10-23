# BlueZ, senzory a USB adaptér — šetření 23. 10. 2026

## Výsledek a hranice závěru

Příčina dalších pádů BlueZ zatím není prokázaná. Dřívější kernelový záznam
potvrzuje SIGSEGV i s BlueZ 5.82-1.1+sensogrid1; odpovídající symboly mapují
fault na `gatt_db_attribute_write`. Dřívější jiný záznam ukazoval na
`discovery_op_complete`. Samotná funkce na vrcholu zásobníku neurčuje místo,
kde vzniklo poškození paměti. Nelze z toho vyvodit vadný adaptér ani konkrétní
opravu use-after-free.

V tomto kole nebyl na Debian přenesen žádný kód, nic nebylo instalováno,
zastavováno ani restartováno. SSH příkazy pouze četly stav.

V 19:39 CEST: bluetooth.service aktivní, `NRestarts=10`, poslední start
19:31:41. Důvod tohoto posledního restartu není bez systémového journalu
potvrzený. Počet restartů není automaticky počet prokázaných SIGSEGV.

## Proč zatím nemáme použitelný crash dump

Živě ověřeno:

- Debian má BlueZ 5.82-1.1+sensogrid1, libbluetooth3 5.82-1.1 a
  firmware-realtek 20250410-2.
- `systemd-coredump` není nainstalován, `coredumpctl` ani `gdb` nejsou dostupné.
- `/proc/sys/kernel/core_pattern` obsahuje pouze `core`.
- bluetooth.service má `LimitCORE=infinity`, ale také `ProtectSystem=strict`
  a nemá nastavený WorkingDirectory. `/core` nenalezen.
- SSH uživatel nevidí systémové logy; „No entries“ zde neznamená prázdný journal.

Relativní jméno core se zapisuje do pracovního adresáře procesu. Kombinace
s read-only prostředím služby je pravděpodobný důvod, proč nic použitelného
nezůstalo. Aktuální pracovní adresář procesu nebyl privilegovaně ověřen;
nejde o dodatečně prokázanou příčinu každého chybějícího dumpu.
Viz [Linux core(5)](https://man7.org/linux/man-pages/man5/core.5.html) a
[systemd-coredump](https://www.freedesktop.org/software/systemd/man/latest/systemd-coredump.html).

Další krok musí zachytit skutečný následující pád. Uživatel může na Debianu
vědomě zapnout systémový sběr dumpů a debugger:

```sh
sudo apt install systemd-coredump gdb
cat /proc/sys/kernel/core_pattern
```

Po instalaci ověřit, že core_pattern skutečně ukazuje na systemd-coredump,
nikoli zůstal `core` kvůli jinému sysctl override. Pro právě nasazenou vlastní
verzi už na serveru existuje přesný balík symbolů; použít jej pouze dokud
balík BlueZ zůstává na stejné verzi:

```sh
sudo dpkg -i /home/marek/sensogrid-bluez-5.82-fix-20261023/artifacts/bluez-dbgsym_5.82-1.1+sensogrid1_amd64.deb
```

Po přirozeném dalším pádu (nevyvolávat umělý pád produkce):

```sh
sudo coredumpctl --no-pager -1 info bluetoothd
sudo coredumpctl debug bluetoothd --debugger-arguments="-batch -ex 'thread apply all bt full' -ex 'info registers'"
```

Syntaxe odpovídá [coredumpctl](https://www.freedesktop.org/software/systemd/man/latest/coredumpctl.html).
Surová paměť dumpu zůstává na serveru; nový export aplikace ji nestahuje.
Hostitelský helper umí připojit dostupné `coredumpctl info` a systémové logy
do jednoho ZIPu. Bez nainstalovaného core handleru žádný helper paměť pádu
zpětně nevytvoří.

## Upstream a další hypotéza

Nasazené backporty 6cdb936ebb6a a a338533f913b řeší životnost GATT služeb,
ale nepokryly všechny pozorované pády. Nově nalezen další relevantní upstream
commit: [input/hog: Cancel pending report requests on detach](https://github.com/bluez/bluez/commit/ff4fae3f2d172de788b18fecba8cf75f8e3e9ce8)
z 22. 9. 2026. Řeší callbacky HID reportů, které mohou doběhnout po uvolnění
objektu. Není součástí našich dvou backportů.

Je to kandidát k ověření, nikoli diagnostikovaná oprava tohoto incidentu:
senzory inzerují UUID 1812 (HID), zatímco původní úplný GATT výpis HID službu
neobsahuje, a dřívější log měl `input-hog ... accept failed`. Z toho samotného
nelze doložit aktivní vadný callback. Přidání dalšího patche bez zásobníku by
opět neověřilo příčinu. Pokud backtrace potvrdí HoG cestu, porovnat příslušnou
verzi a reprodukovat její regresi před dalším backportem.

Upstream [issue 2486](https://github.com/bluez/bluez/issues/2486) také ukazuje,
že některé chyby discovery vyvolává pořadí či duplicita ATT/MTU odpovědí i při
dobrém signálu. Týká se jiného zařízení a není důkazem stejného problému
CX0726B. K rozlišení je potřeba konkrétní `btmon` stopa kolem výpadku;
dlouhodobý rádiový záznam nebyl v tomto kole zapnut.

## Zaseknutí teploměrů

Naše pozorování: některý senzor zmizel ze scanů obou adaptérů, displej dál
měřil a vyjmutí baterie jej vrátilo. V okamžicích kontroly Debian nedržel
aktivní spojení, Windows nehlásily známé LT zařízení připojené. To podporuje
hypotézu stavu Bluetooth části senzoru, není to ale důkaz, že jej nezpůsobila
předchozí nedokončená komunikace nebo že nejde o slabé napájení/RF podmínky.

Přesný význam trvale svítícího/blikajícího kolečka se nepodařilo ověřit
v důvěryhodném návodu pro konkrétní variantu. Veřejný rozcestník výrobce
[qaqa](https://d.ihunuo.com/app/dqwu) nabízí aplikaci, nikoli potřebný popis
indikátoru. Význam symbolu proto není prezentován jako potvrzený fakt.

Prvotní technický [rozbor CX0726B od pvvx](https://pvvx.github.io/CX0726B/)
uvádí pro jím rozebraný kus SoC OM6621DB, přenos hodnot jen po spojení a odběr
přibližně 80 µA při advertisingu / 0,8 mA při připojení k původní aplikaci.
Jeho závěr o krátké výdrži se nesmí automaticky přenést na naše jednotlivé
kusy: přesná hardwarová varianta a odběr zatím nebyly změřeny. Je to důvod
ověřit napětí baterie při vysílání a chování rozpojení, nikoli důvod tvrdit,
že reset vyřešil firmware nebo že je každá baterie vadná.

Doporučené další měření: při následujícím zaseknutí nejdřív uložit ZIP,
zaznamenat čas a stav symbolu; bez resetu ověřit HCI spojení a advertising.
Poté jediný senzor resetovat a porovnat návrat. Zdravé senzory ponechat
beze změny. Nespouštět současně původní mobilní aplikaci a sběr na serveru.

## Adaptér s anténou

Lepší RF cesta dává smysl, ale pád procesu bluetoothd ani chybný firmware
senzoru sama neopraví. Marketingových 30–100 m zpravidla znamená volný
prostor; negarantuje průchod stěnami a zůstává omezený i vysílačem senzoru.

Při koupi rozhoduje konkrétní čip, USB ID a revize, nikoli pouze Bluetooth
5.x na obalu. [Home Assistant — zkušenosti se stejným Linux BLE stackem](https://www.home-assistant.io/integrations/bluetooth/)
uvádí mezi použitelnými anténovými modely EDUP EP-B3536 a Feasycom FSC-BP119.
Současně upozorňuje na problémy UB500 při aktivních spojeních, nekompatibilní
ATS2851 modely a falešné CSR adaptéry. To není absolutní verdikt o každé
revizi, ale je to důvod nekupovat generický dongle naslepo.

| Kandidát | Hodnocení pro tento nákup |
| --- | --- |
| EDUP EP-B3536, skutečný RTL8761BU | Kandidát s externí anténou a popsanou Linux zkušeností. Spolehlivou aktuální českou nabídku do 250 Kč se nepodařilo ověřit. |
| Feasycom FSC-BP119 | Výrobce deklaruje Linux a anténu; [datasheet](https://www.feasycom.com/datasheet/fsc-bp119.pdf) uvádí dosah až 100 m ve volném prostoru. Aktuální nabídka do rozpočtu nebyla ověřena. |
| TP-Link UB500 Plus | Cenově blízko, [Heureka](https://prenasece-signalu.heureka.cz/tp-link-ub500-plus/) ukazovala od 271 Kč bez garantované dopravy. [Výrobce](https://www.tp-link.com/uk/home-networking/adapter/ub500-plus/) oficiálně uvádí Windows; bez ověření konkrétní revize bych jej pro Debian nesliboval. |

Ceny a dostupnost kontrolovány 23. 10. 2026, mohou se změnit. V rozpočtu
200–250 Kč není potvrzený nákup, který bych označil za jistotu pro Debian.
Externí USB adaptér je vhodné umístit na krátké USB 2.0 prodlužce mimo kovovou
skříň a blízkost USB 3 zařízení; [Intel popisuje rušení USB 3 v pásmu 2,4 GHz](https://www.intel.com/content/www/us/en/content-details/841692/usb-3-0-radio-frequency-interference-impact-on-2-4-ghz-wireless-devices-white-paper.html).
Nový adaptér bych následně porovnal s nynějším při stejném umístění senzorů,
stálém souběhu 2 a stejných retry. Výběr konkrétního hci adaptéru v aplikaci
není součástí této změny; se dvěma řadiči jej před testem ověřit.
