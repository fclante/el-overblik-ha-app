# El-Overblik HA

En skrivebeskyttet community-integration til Danmarks [ElOverblik Customer API](https://docs.eloverblik.dk/en/docs/api/customer).

**Kræver Home Assistant Core 2026.11.2 eller nyere.** Integrationstestene køres mod Core 2026.11.2, inklusive den faktiske recorder og entity-registre. Der kræves ingen separat Home Assistant OS-app/tilføjelse, MQTT-broker eller ekstern tjeneste.

[Read this page in English](../../README.md).

## Funktioner

- Flere eksplicit valgte målepunkter; én Home Assistant-enhed pr. måler.
- Forbrugs- og produktionshistorik som eksterne timebaserede statistikker til Energy-dashboardet.
- Senest rapporterede interval, seneste hele dag samt rapporterede energioversigter for måned og år.
- Målernummer, elleverandør, netselskab, afregningsmetode og tilgængelige årlige estimater/grænser.
- Rapporterede tariffplaner, abonnementer og gebyrer; forespørgsler på daterede afgifter, når den installerede API understøtter dem.
- Tidspunkter for seneste hentning/måling, kvalitet/dækning, importstatus og advarsler om forældede data.
- Genoptagelig historikimport, statistikker der håndterer rettelser, genautentificering og omkonfigurering af målere.
- Danske og engelske oversættelser via Home Assistants indbyggede sprogindstillinger.

**Data rapporteres med forsinkelse; dette er ikke en live-måler.** Målinger kan være flere dage forsinkede. Et vellykket cloud-kald betyder ikke, at dagens målinger er tilgængelige.

## Installation

### Home Assistant Marketplace

1. Åbn **Settings > Marketplace > Add from link** i Home Assistant.
2. Tilføj `https://github.com/fclante/el-overblik-ha-app`, og installér **El-Overblik HA**.
3. Genstart Home Assistant, hvis du bliver bedt om det.
4. Åbn **Settings > Devices & services > Add integration > El-Overblik HA**.

At projektet kan tilføjes via **Add from link** betyder ikke, at det er optaget i et standardkatalog.

### Manuel installation

Kopiér [`custom_components/eloverblik_data`](../../custom_components/eloverblik_data) til `custom_components/eloverblik_data` i Home Assistants konfigurationsmappe, genstart Home Assistant, og tilføj integrationen.

Visningsnavnet er **El-Overblik HA**. Det tekniske domæne, lagernøgler, statistik-ID'er og arkivfilnavnet beholder `eloverblik_data` af hensyn til eksisterende installationer. Eksisterende standardtitler opdateres ved opsætning; brugerdefinerede titler bevares.

## Konfiguration

Opret/aktivér et **Customer API refresh token** i [ElOverblik](https://eloverblik.dk), og sørg for, at målepunkterne allerede er knyttet til din konto.

Indtast:

- **Refresh token**: Customer API-refresh-tokenet, ikke et midlertidigt dataadgangstoken.
- **Målepunkts-ID'er**: kommaseparerede ID'er på 18 cifre, f.eks. `001234567890123456,001234567890123457` (syntetiske eksempler).

ID'er behandles som tekst, så indledende nuller bevares. Mellemrum fjernes, og dubletter normaliseres. Integrationen kontrollerer adgangen og afviser overlappende målere på tværs af dens egne konfigurationer. Den opretter eller sletter aldrig målerrelationer hos ElOverblik.

Brug **Reconfigure** til at ændre målere eller udskifte tokenet. Autentificeringsfejl tilbyder også Home Assistants genautentificeringsflow. Fjernede målere beholder deres historiske statistikker og integrationsadministrerede historikcache.

### Sprog

Vælg **Dansk** eller **English** i sprogindstillingerne for din Home Assistant-brugerprofil. Integrationsformularer, fejl, reparationer, enhedsoversættelser og handlingsbeskrivelser følger Home Assistants indbyggede oversættelsesadfærd. Engelsk bruges som reserve for andre sprog og manglende oversættelser.

Der findes bevidst ingen særskilt sprogindstilling for integrationen. Gemte enhedsnavne følger Home Assistants normale navngivningsadfærd; ændring af profilsprog genskaber ikke identiteter/statistikker og overskriver ikke brugerdefinerede enhedsnavne.

### Indstillinger

- Standardhistorik: de foregående 12 kalendermåneder ved første import.
- Vælg en bestemt startdato for historikken eller **Import all available history**.
- API-opbevaringsperiode: de foregående fem kalenderår plus indeværende år, yderligere begrænset af ejerskab/adgang og upstream-tilgængelighed.
- Opdatering: som standard hver sjette time, kan indstilles fra én til 24 timer.

Historikken importeres i baggrundsdele; opsætningen venter ikke på en fuld historikimport. Følg **Historical import** og **Data status**. En fejl for adgangsperioden stopper den berørte import i stedet for lydløst at springe utilgængelige datoer over. Vælg om nødvendigt en startdato, du har adgang til.

## El-Overblik HA-dashboard

Efter installation/genindlæsning åbnes **El-Overblik HA** i Home Assistants sidepanel. Dashboardet styres af integrationen, bruger indbyggede kort og tilpasser sig mobilskærme. Ingen ekstra kort eller separat app er nødvendig. Diagrammer bruger Home Assistants indbyggede History-integration, som er aktiveret i standardkonfigurationen.

- **Overblik:** kompakte energinøgletal, målingernes dækningsdato, månedsdækning og et diagram i fuld bredde for to uger pr. målepunkt. Priser og aftaleestimater vises efter opsætning; **Detaljer** åbner målepunktet.
- **Detaljer:** daglige/månedlige forbrugsdiagrammer, separat produktion, dækning, dagens/morgendagens prisplan, billigste kommende komplette time samt forbindelses- og importstatus.

Normal rapporteringsforsinkelse er information, ikke en advarsel om manglende data. Målinger over tre dage gamle udløser en aldersadvarsel; grænsen er ikke en leveringsgaranti fra kilden. Forbindelsesfejl, manglende måleradgang, måleroplysninger, tariffer og importfejl vises hver for sig. En fejlet tarifforespørgsel til ElOverblik påviser **ikke**, at forbrug eller offentlige priser mangler. Se kildefejl og importstatus under **Detaljer > Datastatus**; gemte målinger vises fortsat.

Markedspriser har selvstændig status: første hentning, manglende aktuel pris, fejlet opdatering med stadig gyldige gemte priser og morgendagens endnu ikke offentliggjorte priser skelnes fra hinanden. Før valg af DK1/DK2 viser overblikket en kort opsætningsbesked i stedet for tomme priskort. Aftaleestimater skjules, indtil en elaftale er indtastet. Deaktiverede entiteter respekteres og forveksles ikke med manglende områdevalg; administrér dem under **Indstillinger > Enheder og tjenester**.
- **Forsinkelser er synlige:** seneste hentning og seneste måling vises hver for sig. Delvise summer fremstår ikke komplette. Overlappende målepunkter lægges ikke sammen.

Åbn **Indstillinger > Enheder og tjenester > El-Overblik HA > Konfigurer**, og vælg **Indstil markedspriser og elaftale pr. målepunkt**:

1. Vælg **DK1** (vest for Storebælt) eller **DK2** (øst). Området gættes ikke; `none` deaktiverer priser for målepunktet.
2. Behold `benchmark` for kun markedspriser, eller vælg `fixed` (fast energipris) / `spot_markup` (spot plus tillæg).
3. Indtast den rene energipris eller spottillægget i **DKK/kWh**, om beløbet inkluderer 25 % moms, og aftalens startdato. Resultater normaliseres til **uden moms**.

Priser hentes fra [Energinets DayAheadPrices](https://www.energidataservice.dk/tso-electricity/DayAheadPrices) i 15-minutters intervaller. Begge danske prisområder deler en lokal, vedvarende cache på tværs af integrationsposter. Forespørgsler indeholder kun offentlige datoer/områder, aldrig token, målepunkts-ID, forbrug eller aftale. Integrationen kontrollerer omkring offentliggørelsen, respekterer fejl/hastighedsgrænser og opfinder ikke manglende priser for i morgen. Valutaomregningen kan afvige fra din leverandørs.

Anbefalingen af billigste time bruger fire sammenhængende fremtidige kvarterer. Den inkluderer aldrig et påbegyndt kvarter eller et hul i prisdata. Tidsstempler inkluderer UTC-forskydning, så gentagne timer ved sommertidsskift kan skelnes. Viste tider følger Home Assistants tidszone; dagssummer følger danske kalenderdage.

**Sammenligninger er estimater for ren energi, ikke din elregning eller en leverandøranbefaling.** For seneste komplette forbrugsdag sammenlignes din aftale med engrospriser for **samme forbrug og periode**. Hver forbrugstime bruger gennemsnittet af fire spotpriser med antaget jævnt forbrug inden for timen. Den faktiske kvartersprofil kan ikke genskabes. Positiv forskel betyder merpris mod engros; negativ betyder rabat, ikke en garanteret besparelse. Moms, nettariffer, elafgift, abonnementer og gebyrer er ikke inkluderet.

Sammenligningen kræver komplette matchende målinger/priser og gyldig aftaledato. Automatisk prishistorik er begrænset til de seneste 31 dage; prisdatasættet starter 1. oktober 2025. Manglende/ældre data og forbrug før aftalens startdato forbliver tydeligt utilgængelige. Ændringer af historiske aftalevilkår kræver ny startdato. Der gemmes ikke et historisk aftaleregister; ældre estimater uden for ny gyldighed bliver utilgængelige.

Fravælg **Vis El-Overblik HA i sidepanelet** i hver integrationspost for at skjule dashboardet. Eksisterende dashboards, herunder Energy, ændres aldrig. Dashboardet er skrivebeskyttet; kopiér kort til dit eget dashboard for at tilpasse dem. En eksisterende `/el-overblik-ha`-adresse efterlades urørt, og konflikten logges. Installationer uden Lovelace beholder entiteterne. Statiske overskrifter følger Home Assistants konfigurerede sprog (dansk/engelsk); indbyggede entiteter og kontroller følger normal sprogadfærd.

## Home Assistant Energy-dashboard

Når målingerne er importeret, skal du vælge den relevante **statistik**, ikke en oversigtssensor:

```text
eloverblik_data:<metering_point_id>_consumption
eloverblik_data:<metering_point_id>_production
```

Find dem under Home Assistants statistikværktøjer og blandt kilderne i Energy-dashboardet.

- Brug verificerede forbrugsmålere som kilder til netforbrug.
- Produktion er en separat strøm rapporteret af kilden. Kontrollér målepunktets formål, før du vælger det som neteksport eller solcelleproduktion: produktion, neteksport, inverterproduktion og egetforbrug er **ikke det samme**.
- Undermålere tilføjes ikke automatisk. Vælg ikke overlappende hoved-/undermålere eller den samme måler fra en anden ElOverblik-integration.
- Oversigtssensorer er øjebliksbilleder uden en statistik-state-class. De tilføjer med vilje ikke endnu en energisum til recorderen.
- Måneds-/årsoversigter viser rapporterede og forventede timer, fuldstændighed, estimerede timer og dækningsperioder. Begrænset historik præsenteres ikke som en komplet kalendersum.
- Manglende/ufuldstændige målinger udfyldes ikke med nul. Ikke-understøttede grove/profilerede intervaller markeres i stedet for at blive fordelt på opdigtede timeværdier.

Integrationen ændrer ikke konfigurationen af dit Energy-dashboard.

## Tariffer og omkostninger

**ElOverbliks afgifter bruges ikke til at beregne en fuld elregning eller en aktuel samlet DKK/kWh-pris.** Det aktuelle skema fastslår ikke alle betydninger af enheder, faktureringsperioder, moms og afgiftskategorier, som kræves til sikker beregning. De valgfrie, brugeropsatte estimater for ren energi ovenfor løser ikke disse afgiftsbegrænsninger.

I stedet tilbyder integrationen:

- Valgfrie, som standard deaktiverede tariff-entiteter, der identificerer rapporterede planer.
- Valgfrie abonnementer/gebyrer med kildens rapporterede DKK-pris samt mængde, gyldighed og periodemetadata. Beløbene antages ikke at skulle betales nu og omregnes ikke til dags-/månedsomkostninger.
- `get_charges`: cachelagrede tariffer, kildens prisarrayer, abonnementer og gebyrer.
- `get_charge_schedule`: daterede afgiftslinks, faktorer, klassifikationer og prisintervaller fra det nyere dated-charge-endpoint.

**Aktuel API-begrænsning:** Det dokumenterede dated-charge-endpoint returnerede HTTP 404 under en autoriseret skrivebeskyttet kontrol. Handlingen rapporterer begrænsningen tydeligt og erstatter ikke historiske afgifter med dagens afgifter. Aktuelle afgifter og timebaseret energi blev hentet og fortolket korrekt ved kontrollen.

`cost_status: unsupported_semantics` gør beregningsbegrænsningen tydelig. Tariff-entiteter hævder ikke, at en rapporteret pris er den aktuelt gældende sats. Fremtidige planer er kun tilgængelige, hvis ElOverblik returnerer dem.

Gang ikke gammelt forbrug med dagens tarif, og brug ikke en aktuel pris-entitet til at prissætte forsinkede historiske målinger. ElOverbliks afgifter fastslår ikke hele din spotpris-/leverandøraftale. Beregning fra kildeafgifter er fortsat deaktiveret, indtil kildens betydninger er verificeret; ukendte komponenter behandles aldrig som nul.

## Handlinger

Handlinger returnerer responsdata. Brug `response_variable` i en automatisering eller et script. Konfigurationspostens ID kan vælges i handlingsformularen under Developer Tools.

### Importér eller afstem historik

```yaml
action: eloverblik_data.import_history
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  start: "2026-01-01"
  end: "2026-02-01"
response_variable: import_job
```

Slutdatoen er eksklusiv. Handlingen returnerer straks et job-ID; importsensoren viser afslutning/fejl. Der kører ét historikjob pr. konfiguration. Brug handlingen til rettelser, der ligger uden for den automatiske afstemningsperiode.

### Hent rapporterede afgifter

```yaml
action: eloverblik_data.get_charges
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  metering_points:
    - "001234567890123456"
response_variable: reported_charges
```

Udelad `metering_points` for at medtage alle konfigurerede målere. Svaret er et cachelagret kildeøjebliksbillede, ikke en faktura.

### Hent oplysninger om daterede afgifter

```yaml
action: eloverblik_data.get_charge_schedule
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  metering_points:
    - "001234567890123456"
  start: "2026-11-01T00:00:00+01:00"
  end: "2026-11-02T00:00:00+01:00"
response_variable: charge_schedule
```

Brug tidsstempler med tidszone, højst 31 dage og højst 10 konfigurerede målere pr. kald. Fejl fra upstream pr. måler bevares tydeligt i svaret.

## Driftssikkerhed og privatliv

- Metadata/afgifter opdateres dagligt. Nylig energi kontrolleres ved hver polling.
- Normale polling-kald genbesøger 14 dage; ugentlig afstemning genbesøger 90 dage. Ældre rettelser kræver historikhandlingen.
- API-forespørgsler for tidsserier bruger højst 31 dage og batches på højst 10 målere.
- Alle konfigurationer deler afstand mellem forespørgsler og begrænsning af tokenudveksling. Adgangstokens genbruges i næsten 24 timer. HTTP 429/503-forsøg venter mindst ét minut og respekterer længere gyldige `Retry-After`-værdier.
- Internt bruges UTC; danske kalenderoversigter bruger Europe/Copenhagen, inklusive 23/25-timers dage ved sommertid.
- Kanoniske timemålinger og importkontrolpunkter gemmes med Home Assistants storage helpers. Statistikker opdateres idempotent; tidligere importer/rettelser genberegner efterfølgende kumulative værdier.
- Dit refresh-token gemmes i Home Assistants normale config-entry-lager, **ikke i et separat krypteret pengeskab**. Beskyt Home Assistants konfiguration og sikkerhedskopier.
- Målerhistorik/cache ligger også i Home Assistants konfigurationslager. Fjernelse af integrationen sletter ikke automatisk historiske statistikker eller målerspecifikke historikcacher.
- Diagnostikeksport bruger en tilladt liste med driftsmetadata og udelader tokens, fulde målepunkts-ID'er, kontaktdata og rå kundesvar. Logs indeholder ikke legitimationsoplysninger eller rå responsindhold.

## Fejlfinding

- **Ugyldigt token:** Kontrollér, at tokenet er aktivt og oprettet til Customer API. Opret et nyt i ElOverblik, og genautentificér.
- **Adgang til måler mistet:** Kontrollér målerrelationer og autoriserede datoer i ElOverblik. Integrationen kan ikke give adgang.
- **Ingen aktuelle målinger:** Undersøg seneste måling og fuldstændighed; forsinket rapportering er ikke nødvendigvis en fejl.
- **API utilgængelig/begrænset:** Vent på den begrænsede genforsøgsperiode. Gentagne opdateringer fremskynder ikke upstream-rapporteringen.
- **Historikimport fejlede:** Undersøg importfejl og målerstatus; prøv igen med en smallere, autoriseret periode.
- **Uklar produktionsmapping:** Verificér målepunktstype/topologi, før du vælger Energy-kilder.

## Udvikling og fællesskab

Dette er en uafhængig community-integration, der ikke er tilknyttet eller godkendt af ElOverblik eller Home Assistant. Projektet er MIT-licenseret, Copyright (c) 2026 fclante; se [LICENSE](../../LICENSE).

Se [CONTRIBUTING.md](../../CONTRIBUTING.md) for udviklingsopsætning, kontrolkommandoer og bidragsvejledning. Projektet har også en [sikkerhedspolitik](../../SECURITY.md), et [adfærdskodeks](../../CODE_OF_CONDUCT.md) og en [udgivelsesproces](../RELEASING.md).

Kræver Python 3.14.2+ og [uv](https://docs.astral.sh/uv/). Test bruger syntetiske API-svar og kræver ikke legitimationsoplysninger eller live netværksadgang. Del aldrig tokens, fulde målepunkts-ID'er, persondata eller rå kundesvar i issues eller pull requests. Privat rapportering af sikkerhedssårbarheder skal aktiveres af vedligeholderen før udgivelse; offentliggør ikke detaljer om sårbarheder i issues.
