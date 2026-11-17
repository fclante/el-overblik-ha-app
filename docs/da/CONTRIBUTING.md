# Bidrag

[Read in English](../../CONTRIBUTING.md) · [Projektoversigt](README.md)

Tak, fordi du vil hjælpe med at forbedre ElOverblik Data. Dette er en uafhængig community-integration til Home Assistant, ikke et officielt ElOverblik- eller Home Assistant-projekt. Bidrag til kode, dokumentation, oversættelser og omhyggeligt beskrevne fejlrapporter er velkomne.

## Før du opretter et issue eller en pull request

- Søg efter eksisterende issues og pull requests for at undgå dubletter.
- Brug GitHubs fejlrapport- eller funktionsønskeformular. Formularerne er på dansk og engelsk.
- Hold rapporter korte og anonymiserede. **Medtag aldrig et ElOverblik refresh-/access-token, fuldt målepunkts-ID, person- eller kontodata eller et uredigeret API-svar.** Vedhæft ikke konfigurationseksporter, `.env`-filer, skærmbilleder med kontooplysninger eller rå logs. Beskriv den berørte adfærd, og brug syntetiske eksempler.
- **Rapportér ikke sikkerhedssårbarheder i offentlige issues eller pull requests.** Se [SECURITY.md](../../SECURITY.md); privat rapportering er aktuelt ikke tilgængelig og skal aktiveres før udgivelse.

## Udviklingsopsætning

Krav: Python 3.14.2 eller nyere og [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run pytest -q
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components scripts
uv run python scripts/release.py check
```

Ved en prøvekørsel af arkivet skal kontrollerne køres først, derefter bygges til en ny midlertidig outputmappe:

```sh
uv run python scripts/release.py build --output "$(mktemp -d)/eloverblik-dist"
```

Prøvekørslen validerer versioner og arkivet lokalt; den committer ikke ændringer og tilgår ikke netværket. Undgå at genbruge en fast outputmappe, der kan indeholde et tidligere build.

Testene bruger isoleret Home Assistant-lager og syntetiske API-svar. De kræver ikke rigtige legitimationsoplysninger, målepunkter eller adgang til live API. Læg aldrig hemmeligheder i tests, fixtures, logs, skærmbilleder, issues eller pull requests.

## Pull requests

1. Lav en afgrænset ændring, og forklar hvorfor den er nyttig for brugeren.
2. Tilføj eller opdatér tests for ændret adfærd; brug syntetiske og privatlivssikre data.
3. Kør de relevante kontroller ovenfor, og beskriv præcist, hvilke kommandoer der bestod. Påstå ikke, at live API, Marketplace, GitHub-indstillinger eller eksterne workflows er verificeret, medmindre det faktisk er sket.
4. Opdatér den engelske dokumentation og dens danske modstykke, når adfærd, opsætning eller begrænsninger ændres.
5. Opret en pull request med den tosprogede skabelon. Beskriv kendte begrænsninger og eventuelle migrationshensyn.

Der kræves ingen Contributor License Agreement (CLA) eller Developer Certificate of Origin (DCO). Ved at indsende et bidrag bekræfter du, at du har ret til at indsende det, og accepterer, at det kan distribueres under projektets MIT-licens.

## Versionsstyring ved udgivelser

Udgivelser planlægges automatiseret fra vellykkede pushes til `main`, også ændringer, der kun vedrører dokumentation. Se [RELEASING.md](RELEASING.md) for versionsregler, sikkerhedsforanstaltninger, administratorforudsætninger og gendannelsesprocedurer. Kør ikke workflowets interne `prepare`- eller `publish`-kommandoer manuelt.
