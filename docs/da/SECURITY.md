# Sikkerhedspolitik

[Read in English](../../SECURITY.md) · [Projektoversigt](README.md)

El-Overblik HA er en uafhængig community-integration. Følg denne politik for at hjælpe med at beskytte brugere og deres kontooplysninger.

## Rapportering af en sårbarhed

**GitHubs private rapportering af sikkerhedssårbarheder er aktuelt deaktiveret for dette repository. Vedligeholderen skal aktivere funktionen i repositoryets sikkerhedsindstillinger før første udgivelse.**

Indtil privat rapportering er aktiveret, annonceres der ingen privat rapporteringskanal her. **Offentliggør ikke detaljer om sårbarheder, proof-of-concept-materiale, berørte legitimationsoplysninger eller udnyttelsesinstruktioner i offentlige issues, diskussioner, pull requests eller andre offentlige kanaler.** Vent, indtil GitHubs private rapporteringsmulighed er tilgængelig for dette repository. Issue-trackeren er ikke en kanal til sikkerhedsrapportering.

Udgivelsen må ikke gå videre, før privat rapportering er aktiveret og verificeret. Antag ikke, at en privat kanal er aktiv, blot fordi denne politik findes.

## Følsomme oplysninger

Medtag aldrig refresh-/access-tokens, fulde målepunkts-ID'er, konto-/personoplysninger, `.env`-filer eller uredigerede API-svar i rapporter. Fjern følsomme værdier, før diagnostikuddata deles. Integrationen gemmer refresh-tokenet i Home Assistants normale config-entry-lager, ikke i et separat krypteret pengeskab; beskyt Home Assistants konfiguration og sikkerhedskopier.

## Understøttede versioner

Sikkerhedsrettelser tilstræbes til den nyeste udgivne version. Hold Home Assistant Core opdateret; denne integration kræver Core 2026.11.2 eller nyere.
