# iNELS IR pro Home Assistant

**Neoficiální komunitní projekt.** Tato integrace přidává vlastní podporu pro ELKO EP eLAN-IR-003 do Home Assistantu a nabízí moderní způsob ovládání a učení IR kódů jako náhradu za zastaralé mobilní aplikace iHC-MAIR a iHC-MIIR. Projekt vzniká nezávisle na společnosti ELKO EP i týmu Home Assistantu.

Vlastní integrace pro ELKO EP **eLAN-IR-003**. Home Assistant automaticky načítá zařízení, jejich pojmenované akce a uložené IR sloty z krabičky. Pojmenovaná tlačítka spouštějí akce podle konfigurace krabičky, včetně nastaveného IR výstupu. Samotné sloty se zobrazují pod krabičkou jako tlačítka **IR 1**, **IR 2** a podobně. Úspěšná odpověď potvrzuje přijetí požadavku krabičkou. Stav televize nebo jiného ovládaného zařízení přes IR nelze zjistit.

## Instalace z GitHubu

Vlastní kopii projektu uložte do veřejného GitHub repozitáře. Soubory `hacs.json` a `README.md` patří do kořene a integrace do `custom_components/inels_ir`. Na GitHub ukládejte soubory tohoto projektu. Přihlašovací údaje ke krabičce a konfiguraci zadávejte v Home Assistantu.

V Home Assistantu 2026.11 a novějším otevřete **Nastavení → Marketplace → Přidat z odkazu** a vložte adresu repozitáře. Pokud Marketplace vyžádá připojení GitHubu, dokončete ho v prohlížeči. Je-li potřeba zvolit typ, vyberte **Integrace**. Stáhněte **iNELS IR**, restartujte Home Assistant a pokračujte v **Nastavení → Zařízení a služby**.

Pro aktualizace můžete vydávat GitHub Releases s tagem odpovídajícím verzi v `manifest.json`. Ze soukromých repozitářů lze soubory stáhnout na počítač a použít ruční kopírování.

[Dokumentace Marketplace](https://www.home-assistant.io/integrations/marketplace/#custom-repositories)

## Ruční instalace a první stisk

Integrace je určená pro Home Assistant 2026.11 a novější. Krabička se může objevit v **Nastavení → Zařízení a služby → Nalezené** po události DHCP na síti, kterou HA vidí. Automatické nalezení ověřuje model a MAC adresu přes místní API a vyžaduje potvrzení. Ruční přidání podle IP adresy funguje i bez discovery. Změnu adresy potvrďte přes **Přenastavit**.

1. Ověřte označení modelu na štítku.
2. Zkopírujte složku `custom_components/inels_ir` do složky `custom_components` vedle `configuration.yaml`. Výsledná cesta bývá `/config/custom_components/inels_ir/manifest.json`. Restartujte Home Assistant.
3. Potvrďte nalezenou krabičku, nebo v **Nastavení → Zařízení a služby → Přidat integraci** vyhledejte **iNELS IR** a zadejte její IP adresu. Tlačítka se načtou při přidání.

## Správa zařízení a kódů na krabičce

V prohlížeči otevřete IP adresu krabičky a přihlaste se jako správce. V **IR codes → + → Record** namiřte ovladač na čidlo **IR LEARN** a stiskněte požadované tlačítko. V nabídce **Devices** můžete založit spotřebič a jeho akcím přiřadit uložené sloty a výstupy **IR LED**. Home Assistant načítá katalog při přidání či načtení integrace, po učení v HA a na vyžádání. Po změně na webu otevřete v HA zařízení **iNELS IR** a v části **Konfigurace** stiskněte **Načíst konfiguraci z krabičky**. Samotné otevření stránky katalog nenačítá.

Po přechodu z verze 0.4.x se dřívější lokální přiřazení názvů a skupin nepoužívají. U existujících slotů integrace zachovává jejich interní identitu tlačítka. Pojmenované akce vytvořte na krabičce, pokud je tam ještě nemáte.

## Naučení kódu přímo v Home Assistantu

Po výměně složky integrace restartujte Home Assistant. V **Nastavení → Zařízení a služby → iNELS IR → Přenastavit** zadejte účet a heslo správce krabičky. Home Assistant je uloží v konfiguraci integrace. Do akce se zadávají jen údaje o tlačítku.

1. V **Nástroje pro vývojáře → Akce** otevřete **iNELS IR: Naučit IR kód** (`inels_ir.learn_code`).
2. Vyberte krabičku. Pro pojmenované tlačítko vyplňte název spotřebiče i tlačítka a zvolte výstup IR 1–3. Pokud názvy ponecháte prázdné, uloží se samotný IR slot.
3. Spusťte akci, namiřte ovladač na čidlo **IR LEARN** a stiskněte tlačítko. Akce na nahrání čeká nejvýše 60 sekund. Krabička uloží signál a případné zařízení s tlačítkem. Integrace pak načte aktuální katalog. V odpovědi akce je i číslo slotu.

Heslo na krabičce změníte přes **Accounts** v jejím webovém rozhraní. Pak zadejte nové heslo v HA přes **Přenastavit**. Prázdné pole hesla při stejné adrese a stejném účtu ponechá uloženou hodnotu. Vymazáním obou polí uložené údaje odstraníte.

Krabička používá nešifrované HTTP. Uložení do konfigurace HA omezuje šíření hesla přes parametry akcí, heslo je však součástí úložiště konfigurace i záloh HA. Učení vyžaduje privátní IP adresu a před přihlášením ověřuje model a uloženou MAC adresu. Údaje z API lze v místní síti podvrhnout. Krabičku používejte v důvěryhodné místní síti a nevystavujte její HTTP port do internetu.

Pokud se spojení během učení přeruší, zkontrolujte přes web krabičky, zda se signál nebo tlačítko stihly uložit. Pokud se uložil jen signál, můžete mu přiřadit tlačítko přes **Devices**.

Výstup **IR 1–3** se ukládá do pojmenované akce na krabičce. U existující akce jej lze změnit na webu krabičky. Samotné slotové tlačítko `IR 1` znamená slot s kódem číslo 1. Výstup u něj vybírá firmware a jeho chování při přímém vyslání slotu nebylo fyzicky ověřeno.

## Dashboard, automatizace a scény

Na dashboard přidejte kartu **Tlačítko** pro příslušnou entitu. V automatizaci nebo skriptu použijte akci `button.press`. Následující automatizace odešle IR kód při každé aktivaci scény **Film**. Upravte obě ID entit podle svého Home Assistantu.

```yaml
alias: Zapnout televizi při aktivaci scény Film
triggers:
  - trigger: state
    entity_id: scene.film
    not_to:
      - unknown
      - unavailable
conditions:
  - condition: template
    value_template: "{{ trigger.from_state is not none and trigger.to_state is not none }}"
actions:
  - action: button.press
    target:
      entity_id: button.inels_ir_zapnout_televizi
mode: single
```

Pro posloupnost IR příkazů přidejte další akce `button.press` a podle potřeby mezi ně vložte prodlevu. Pro samostatné zapnutí a vypnutí použijte samostatné kódy, pokud je ovladač nabízí. Kód Power Toggle při každém vyslání přepne aktuální stav.

## Když tlačítko nereaguje

Krabička musí být dostupná ze sítě Home Assistantu. Pro přímé ověření API lze z počítače v téže síti odeslat jeden známý kód. Příkaz skutečně vyšle IR signál.

```sh
curl --include --max-time 5 --request PUT http://192.168.1.50/api/ir/1
```

Při HTTP 404 porovnejte adresu a ID s exportem. Při HTTP 401, 403 nebo přesměrování na přihlášení si poznamenejte verzi firmwaru a stavový kód. Tato verze integrace používá volání bez přihlášení podle příkladu ELKO EP. Pokud HTTP požadavek projde a spotřebič nereaguje, ověřte tentýž kód ve webovém rozhraní krabičky a zkontrolujte umístění IR vysílače.

[Manuál ELKO EP](https://www.elkoep.cz/chytra-krabicka-elan-ir-003-/manual) · [Příklad HTTP ovládání a exportu kódu od ELKO EP](https://www.elkoep.pl/media/userfiles/pdf/iDM3_Tutorial26_iNELS_BUS_eLAN_IR.PDF) · [Dokumentace scén Home Assistantu](https://www.home-assistant.io/integrations/scene/)
