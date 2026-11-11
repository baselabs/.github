# Base Labs package index

Choose a package by the job you need to do. Follow the links for installation and usage.

## Reliability and HTTP

| I need to… | Start with |
| --- | --- |
| Make Ash actions safe to retry or consume a nonce once | [AshOnetime](https://ash-onetime.hexdocs.pm/) |
| Receive, deduplicate, and deliver webhooks in an Ash app | [AshHooks](https://ash-hooks.hexdocs.pm/) |
| Sign or verify HTTP messages, including Web Bot Auth | [RequestSeal for Elixir](https://request-seal.hexdocs.pm/) or [RequestSeal for TypeScript](https://github.com/baselabs/request-seal-typescript/blob/main/README.md) |

## Change data capture

| I need to… | Start with |
| --- | --- |
| Stream committed PostgreSQL changes to an Elixir sink | [Replicant](https://replicant.hexdocs.pm/) |
| Stream committed MySQL binlog changes to an Elixir sink | [Capstan](https://capstan.hexdocs.pm/) |
| Mirror PostgreSQL changes into AshPostgres resources with tenant routing in Ash | [AshReplicant: install and run preflight](https://github.com/baselabs/ash_replicant/blob/main/README.md#install-and-run-preflight) · [HexDocs](https://ash-replicant.hexdocs.pm/) |

## Graph data

Use Apache AGE when you want the graph inside PostgreSQL and can enable the extension. Use ArcadeDB when you want a separate graph database. Check each data layer's supported operations, compatibility, and tenancy behavior before choosing.

| I need to… | Start with |
| --- | --- |
| Model Ash resources as a graph in PostgreSQL with Apache AGE | [AshAge](https://ash-age.hexdocs.pm/) |
| Connect to ArcadeDB from Elixir | [Arcadic](https://arcadic.hexdocs.pm/) |
| Back Ash resources with ArcadeDB | [AshArcadic](https://ash-arcadic.hexdocs.pm/) |

## Protocols and agents

| I need to… | Elixir | TypeScript |
| --- | --- | --- |
| Verify portable agent blueprints and deployment manifests | [Agent Blueprint Protocol](https://agent-blueprint-protocol.hexdocs.pm/) | [Verifier](https://github.com/baselabs/agent_blueprint_protocol/blob/main/documentation/typescript.md) |
| Verify bounded proof-of-possession authority | [Bounded Authority Protocol](https://bounded-authority-protocol.hexdocs.pm/) | [Verifier](https://github.com/baselabs/bounded_authority_protocol_typescript/blob/main/README.md) |
| Sign Bounded Authority artifacts through a key handle | [Bounded Authority Report Adapter](https://bounded-authority-report-adapter.hexdocs.pm/) | [Signer](https://github.com/baselabs/bounded_authority_signer_typescript/blob/main/README.md) |
| Verify signed agreement artifacts | [Charter Agreement Protocol](https://charter-agreement-protocol.hexdocs.pm/) | [Verifier](https://github.com/baselabs/charter_agreement_protocol_typescript/blob/main/README.md) |
| Sign Charter Agreement artifacts through a key handle | [Charter Agreement Signer](https://charter-agreement-signer.hexdocs.pm/) | [Signer](https://github.com/baselabs/charter_agreement_signer_typescript/blob/main/README.md) |
