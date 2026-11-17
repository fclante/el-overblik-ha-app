# Security Policy

[Læs på dansk](docs/da/SECURITY.md) · [Project overview](README.md)

ElOverblik Data is an independent community integration. Please use this policy to help protect users and their account information.

## Reporting a vulnerability

**GitHub private vulnerability reporting is currently disabled for this repository. The maintainer must enable it in the repository's security settings before the first release.**

Until private reporting is enabled, there is no private reporting channel advertised here. **Do not post vulnerability details, proof-of-concept material, affected credentials, or exploit instructions in public issues, discussions, pull requests, or other public channels.** Wait until GitHub's private vulnerability reporting option is available for this repository. The issue tracker is not a security reporting channel.

The release must not proceed until private vulnerability reporting has been enabled and verified. Do not infer that a private channel is active merely because this policy exists.

## Sensitive data

Never include refresh or access tokens, full metering-point IDs, account/personal information, `.env` files, or unredacted API responses in reports. Remove sensitive values before sharing diagnostic output. This integration stores its refresh token in Home Assistant's normal config-entry storage, not in an independently encrypted vault; protect Home Assistant configuration and backups.

## Supported versions

Security fixes are intended for the latest released version. Keep Home Assistant Core updated; this integration requires Core 2026.11.2 or newer.
