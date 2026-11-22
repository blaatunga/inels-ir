# Bezpečnostní audit iNELS IR 0.4.0

Kontrola z 22. listopadu 2026 zahrnula zdrojový kód integrace, registraci akcí a entit, ukládání údajů, HTTP komunikaci, DHCP discovery a Python závislosti čisté instalace Home Assistant Core 2026.11.2.

| Oblast | Ověření a změna |
| --- | --- |
| Správce | Akci učení chrání oprávnění správce HA. Test přes službu HA ověřil zamítnutí uživatele bez oprávnění ještě před síťovým požadavkem. Úspěšná akce založila entitu tlačítka v testovacím HA. |
| Údaje správce | Akce nepřijímá heslo jako parametr. Konfigurační formulář uložené heslo nezobrazuje. Změna adresy nebo účtu vyžaduje nové zadání hesla. Před přihlášením integrace ověří model a uloženou MAC na privátní IP adrese. |
| HTTP | Integrace odmítá přesměrování, nepoužívá proxy z prostředí ani cookies a nepoužívá opakovaně TCP spojení. Tím snižuje riziko automatického opakování povelu po chybě na starém spojení. JSON odpovědi mají limit 8 KiB a požadavky časové limity. |
| Učení a zápis | Učení používá volný slot a přidá tlačítko až po potvrzení správného slotu krabičkou. Po dokončení nebo chybě se pokusí ukončit přihlášení. Integrace nepřepisuje obsazené sloty. Souběh povelů pro stejnou konfigurační položku je serializovaný. |
| Discovery | DHCP vybírá kandidáty podle prefixu MAC z testované krabičky. Integrace ověří model a shodu MAC přes veřejné `GET /api`, bez přihlašovacích údajů. Instalaci potvrdí uživatel. Discovery nikdy samo nezmění IP uložené konfigurace. |
| Závislosti | Manifest nepřidává vlastní balíčky ani přepis verzí HA. Testované verze jsou `aiohttp 3.14.5`, `yarl 1.25.1` a `probatio 0.13.0`. Po aktualizaci instalačního nástroje `pip` z 26.1.1 na 26.3 prošel `pip check` a `pip-audit` nenašel známé zranitelnosti ve 132 balíčcích testovacího prostředí včetně DHCP. Původní nálezy byly v nástroji `pip` a odkazovaly na PYSEC-2026-196 a PYSEC-2026-3721. |

Testy použily skutečný Home Assistant a místní HTTP simulátor krabičky. Na fyzické krabičce bylo ověřeno čtení údajů o modelu a naučení slotu přes její web. Čerstvou DHCP událost na síti uživatele a nahrávání bez přihlášení na fyzickém firmwaru zbývá ověřit. Sken se vztahuje na čisté testovací prostředí, skutečné balíčky uživatelovy instalace a firmware jsou mimo jeho dosah.

Verze 0.5.0 přidává pravidelné čtení katalogu a ukládání pojmenovaných akcí přes API krabičky. Integrace používá pouze vlastní cesty API, ignoruje URL vrácené krabičkou, ověřuje ID zařízení a odmítá názvy, které by mohly narušit vykreslení starého webu. Při neúspěšném čtení katalogu HA ponechá registr entit a označí tlačítka jako nedostupná. Učení znovu načte zařízení před zápisem a odmítne kolizi názvů. Firmware neposkytuje podmíněný zápis, proto může souběžná editace stejného zařízení z webu a HA způsobit přepsání úprav. Změny API nepřidávají Python závislosti.

## Zbývající rizika nasazení

Krabička přenáší heslo správce přes HTTP. Údaje o modelu a MAC lze podvrhnout a heslo je součástí konfigurace a záloh HA. Zařízení patří do důvěryhodné místní sítě, ideálně do odděleného segmentu s přístupem z HA. Výchozí hesla změňte přes web krabičky. Při změně hesla zadejte novou hodnotu v HA přes **Přenastavit**. Před přesunem IP adresy ověřte identitu krabičky a změnu potvrďte ve stejném formuláři.

[Verze balíčků HA Core 2026.11.2](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/package_constraints.txt) · [Bezpečnostní upozornění aiohttp](https://github.com/aio-libs/aiohttp/security/advisories) · [Databáze PyPA](https://github.com/pypa/advisory-database)
