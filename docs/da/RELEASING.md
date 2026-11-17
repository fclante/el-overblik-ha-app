# Udgivelsesproces

[Read in English](../RELEASING.md) · [Projektoversigt](../../README.md)

Hvert push til `main`, også ændringer, der kun vedrører dokumentation, sætter hele udgivelsesworkflowet i kø (`queue: max 100`); pushes sammenlægges ikke lydløst. Fejlede kontroller blokerer udgivelsen. Automatiseringen bygger fra og kontrollerer præcis det kilde-commit, der er valgt til udgivelsen. En lokal prøvekørsel kan ikke kontrollere GitHub-indstillinger, workflowets faktiske funktion eller tilgængelighed i Marketplace.

## Versionsnumre

- Første udgivelse er **`v0.1.0`**.
- Derefter får hvert vellykket push til `main` automatisk det næste patch-versionsnummer.
- Ved en planlagt minor- eller major-udgivelse skal versionsnummeret opdateres ens i `custom_components/eloverblik_data/manifest.json`, `pyproject.toml` og `uv.lock` i samme kildeændring. Udgivelsesautomatiseringen skal kontrollere, at numrene stemmer, før den udgiver.
- Udgivelsesbotens efterfølgende commit ændrer kun versionsmetadata. GitHubs token-baserede beskyttelse mod rekursion forhindrer, at bot-committet starter endnu en udgivelse.

Udgivelsespublisheren kontrollerer indstillingen for GitHubs private rapportering af sikkerhedssårbarheder med en GitHub API `GET`-forespørgsel og blokerer, medmindre rapportering er aktiveret. Kontrollen udføres, før der oprettes et tag eller pushes fjernmetadata. Main-udgivelsesjobbet behøver `actions: read` for at undersøge workflow-kørsler og `contents: write` til udgivelsespublicering og den snævert afgrænsede versionsopdatering; valideringsjobs behøver ikke skriverettigheder.

Den endelige validering og arkivbygning skal bruge præcis det versionssatte kildesnapshot, der er valgt til udgivelsen. En versionsændring må ikke valideres på ét commit og derefter udgives fra et andet branch-tip.

Udgivelsestests bruger et isoleret syntetisk repository med en fast startversion, uafhængigt af kildesnapshottets version. Kontroller af arkivinstallation dækker startversionen samt senere patch- og major-versioner.

## Validering og udgivelsestransaktion

Standardvalideringen før udgivelse kører følgende, i rækkefølge:

```sh
uv sync --locked
uv run pytest -q
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components scripts
uv run python scripts/release.py check
```

Derudover køres den officielle Home Assistant hassfest-validator fra et digest-pinnet image. Image-digesten er indlejret i en shell-`run`-kommando i en composite action, så vedligeholdere skal gennemgå og opdatere den manuelt; Dependabot finder ikke image-referencer indlejret i shell-kommandoer. Et separat, uafhængigt skrivebeskyttet job kører den officielle HACS-validator fra et digest-pinnet image; der er ingen undtagelse baseret på brand. Offlinekontroller af manifestets skema og lokal brand-validering erstatter ikke de eksterne HACS-kontroller af det offentlige repository, dets metadata og kandidatcommittet. Udgivelsesjobbet har den nødvendige `actions: read`-tilladelse. GitHub Actions-tilladelser og fjernindstillinger skal fortsat følge princippet om mindst mulige rettigheder.

Den senest installerede actionlint er version 1.7.12 og genkender ikke GitHubs dokumenterede `queue: max`-nøgle. Den præcise køkonfiguration dækkes af tests; hvis actionlint bruges, udelades kun denne ikke-understøttede nøgleadvarsel. Der findes ikke et actionlint-CI-job.

Hold Python- og `uv`-pins/lås i trit med målversionen af Home Assistant Core, aktuelt 2026.11.2. Gennemgå og opdatér Core, Python, `uv`, action-referencer og validator-image-digests samlet, og kør derefter standardvalideringen. Dependabot dækker Actions/`uv` og action-referencer, men ikke image-referencer skrevet i shell-`run`-kommandoer.

Kilde-SHA, commit, workflow-run og version registreres i det annoterede tag og GitHub Release-beskrivelsen. Før publicering kontrolleres udgivelsesmetadata og filer mod denne proveniens. En delvis tag-/kladde-transaktion blokerer senere kørsler, indtil det oprindelige run genkøres og gendannes. En genkørsel af en allerede udgivet version verificerer dens uforanderlige filer og øger ikke versionsnummeret igen.

Alle kølagte runs behandles i rækkefølge. Hvis et tidligere kølagt run er ude af rækkefølge, bruger workflowet GitHub workflow API til at opdage det og fejler synligt for det senere run; runs må ikke lydløst sammenlægges eller springes over. Hvis en senere `main`-commit allerede eksplicit angiver en højere version, bevarer udgivelsen af det tidligere snapshot den afventende højere version og ruller ikke `main` tilbage. Ellers udfører udgivelsen et atomisk tag og en versionsopdatering af `main`, med op til tre compare-and-swap-forsøg (CAS). Den bruger aldrig force-push.

## Indhold i en udgivelse

- `eloverblik_data.zip`: installationsklare integrationsfiler direkte i arkivets rod (uden en ekstra overordnet mappe for hele repositoryet).
- `SHA256SUMS`: kontrolsumoplysninger for udgivelsesarkivet.
- GitHub Release-noter: den kanoniske ændringslog for versionen.

Arkivet skal bygges og kontrolleres mod præcis den validerede kilde-SHA. Erstat aldrig filer fra det nyeste branch-tip i det versionssnapshot.

## Lokal prøvekørsel for bidragydere

Ved lokal prøvekørsel skal den lokale kontrol køres før arkivbygningen:

```sh
uv sync --locked
uv run python scripts/release.py check
uv run python scripts/release.py build --output "$(mktemp -d)/eloverblik-dist"
```

`check` validerer lokale udgivelsesforudsætninger. `build` kontrollerer versioner og bygger arkivet lokalt; kommandoen committer ikke ændringer og tilgår ikke GitHub eller netværket. Brug en ny outputmappe frem for en fast sti, der kan kollidere med en tidligere kørsel. Kommandoerne tester **ikke** hele standardvalideringen, GitHubs fjernindstillinger, API-kontrollen for privat rapportering eller bekræfter, at installation via Marketplace virker.

Scriptets `prepare`- og `publish`-kommandoer er interne workflow-kommandoer. **Kør dem ikke manuelt for en lokal udgivelse.** Et lokalt arkiv er ikke en offentliggjort udgivelse.

## Valideringsgrene uden udgivelse

Push en valideringsgren, der ikke hedder `main`, for at køre GitHub-kontrollerne uden at oprette et tag eller en release. Efter vellykkede arkivkontroller uploades `validation-zip-<kilde-SHA>` som et artifact under workflow-kørslen. Det indeholder kun `eloverblik_data.zip` og `SHA256SUMS` og opbevares i syv dage. Download og kontrollér kontrolsummen, før ZIP-filen testes i en isoleret Home Assistant-konfiguration.

Dette validerer kandidatpakken, ikke udgivelsesprocessen eller Marketplaces installation af en offentliggjort release. HACS-kontrollen kræver stadig rigtige repository-metadata såsom beskrivelse, emner og en genkendelig licens. Den første gren, der pushes til et tomt repository, kan blive standardgren; det opretter ikke `main` og offentliggør ikke en release.

## Tjekliste for repository-administrator

Før første udgivelse skal en administrator gennemgå og anvende følgende GitHub-indstillinger:

1. Aktivér GitHubs private rapportering af sikkerhedssårbarheder, og kontrollér, at den private rapporteringsmulighed faktisk er tilgængelig. Udgiv ikke, mens den er deaktiveret. Se [SECURITY.md](../../SECURITY.md).
2. Aktivér Dependabot-sikkerhedsadvarsler/-opdateringer efter behov.
3. Angiv en tydelig repository-beskrivelse og relevante emner uden at antyde godkendelse fra ElOverblik eller Home Assistant. Når licensfilerne er på standardgrenen, skal du kontrollere, at GitHub registrerer den tilsigtede MIT-licens. Disse fjernmetadata er ikke verificeret lokalt.
4. Sørg for, at beskyttelsen af `main` tillader udgivelsesbotens snævert afgrænsede commit, der kun ændrer versionsmetadata, via GitHubs indbyggede token. Hvis branch-beskyttelsen ikke kan tillade denne begrænsede ændring, **så stop og afklar politikken før udgivelse**. Brug ikke et personligt adgangstoken eller en bred omgåelse af beskyttelsen.
5. Giv kun `contents: write` til udgivelsesjobbet, der skal oprette udgivelsesmetadata og den versionsbegrænsede `main`-opdatering. Giv dette job kun `actions: read` efter behov for at undersøge workflow-kørsler. Valideringsjobs må ikke have skriverettigheder.

Dette er fjernindstillinger, og lokale kontroller har ikke verificeret dem. Det første vellykkede push til `main` udløser den indledende `v0.1.0`-udgivelse. Denne dokumentation giver ikke tilladelse til at pushe.

## Fejl og genopretning

- Fejlet validering må ikke udgive en release.
- En delvis tag-/kladde-transaktion blokerer senere kørsler. Genforsøg eller gendan den ved at genkøre det samme oprindelige workflow-run og den samme kilde-SHA; start ikke en erstatningsudgivelse fra et andet branch-tip.
- Hvis en allerede udgivet version genkøres, skal den verificere de eksisterende uforanderlige filer og må ikke øge eller genudgive versionsnummeret.
- Slet, flyt eller retag ikke en allerede offentliggjort release for at rette rækkefølgen.
- Hvis workflow-API-kontrollen finder et tidligere kølagt run i forkert rækkefølge, skal det senere run fejle synligt frem for lydløst at springe over eller sammenlægge kørsler. Genopret udgivelserne i rækkefølge fra deres oprindelige, validerede kildecommits.
- Bevar en højere version, der eksplicit afventer på `main`, mens et tidligere snapshot udgives. Hvis ingen højere version afventer, skal den versionsbegrænsede opdatering bruge den atomiske CAS-mekanisme (op til tre forsøg). Brug aldrig force-push.
- Kontrollér workflow-run, kilde-SHA, arkivindhold, kontrolsum og udgivelsesnoter, før du beder en administrator om hjælp. Genforsøg ikke med bredere legitimationsoplysninger eller tilladelser.
