# Verification record

## Latest verified status — 22 October 2026

The latest full regression run passed **55 tests**, followed by one additional passing endpoint-credential-redaction test: **56 distinct tests covered**. This does not mean a single 56-test full run was executed. Purview verification uses a simulated service; live Azure authentication/publication and native portal visualization remain unverified. The connector is disabled until an account, collection and identity are configured. Detailed evidence and earlier results follow.

## Original core application verification — 21 October 2026

Verified locally using Windows and Python 3.14.7 with the project virtual environment. The counts in this section describe the original application before the Purview integration.

| Check | Observed result |
| --- | --- |
| Full suite: python -m pytest -q | 28 passed |
| Access workflow and request privacy after final query refinement | 2 targeted tests passed |
| Dependency consistency: pip check | No broken requirements |
| Locked dependency resolution dry run | Satisfied by installed environment |
| JavaScript syntax check | Passed |
| Python compilation | Passed |
| Docker Compose configuration validation | Passed; configuration-only test |
| Live browser checks | Sign-in, catalogue search, metadata view, source-registration form, lineage and sales preview confirmed |
| Sales output | Two rows; revenue 200 and 100; email absent |
| Local backup/restore tests | Source data/history preserved; sessions/grants invalidated; assets require rescan |

The tests deliberately exercise unauthorized and expired access, approval/rejection/revocation, owner boundaries, CSRF/origin rejection, lockout, password-session invalidation, metadata revision conflicts, missing sources, bad references, schema drift, new CSV registration, malformed CSV cleanup, source persistence after restart, scheduler execution and concurrent scan denial. Existing six CLI behavioral tests also pass within the full suite.

The installed Starlette/httpx combination emits one deprecation warning concerning the test transport. It does not affect the passing tests; revisit the test client dependency when updating the pinned stack.

PostgreSQL execution, container image build, Docker Compose startup, cloud deployment, PostgreSQL backup/restore and load/security testing were not executed successfully here. Docker Desktop's Linux engine was unavailable even after startup was requested. PostgreSQL CI and container build jobs are supplied but have not run in a remote repository. Local tests use actual SQLite databases and files; this is not evidence of a PostgreSQL deployment.

The owned preview server was stopped after testing. The temporary local-admin browser-verification account was removed; no default passwords are shipped. Start the app and provision your own accounts using README. Development runtime state and local credentials are excluded from version control.

Screenshot: [verified lineage view](screenshots/lineage.png).


## Purview integration update — 22 October 2026

Added the optional Microsoft Purview Data Map HTTP adapter, Azure Identity authentication, custom dataset/column/Process types, stable qualified-name upserts, read-back verification, persistent publication history, administrator endpoints and browser controls. Configuration remains disabled because the user has no Azure account endpoint or collection.

The Purview-specific suite initially passed 27 tests using HTTPX MockTransport and a simulated credential; one endpoint-credential-redaction test was subsequently added and passed separately. These are contract/behavioral tests, not a live Azure deployment. They cover repeated publication, incompatible/missing types, collection routing, authorization and CSRF, disabled offline preview, historical lineage, overlapping publish denial, throttling/network errors, redirect refusal, response-error redaction, tampered fingerprints, mismatched metadata fields and wrong lineage links.

Browser verification confirmed the unconfigured state, disabled Azure controls and a working offline preview of 19 entities (4 datasets, 14 columns, 1 captured process). No Azure token or Data Map request was made. [Preview screenshot](screenshots/purview-preview.png).

Azure Identity credential constructors accepted the configured SDK timeout options without requesting tokens. Dependency checks, JavaScript syntax checks, Python compilation and Compose configuration validation passed. Real Azure authentication, account permissions, entity acceptance, private networking and native portal visualization remain unverified pending an account. Cloud access enforcement and retention deletion have not been added by this metadata integration.


Final regression result for this update: **55 tests passed** in the full suite, followed by **one additional passing endpoint-credential-redaction test** added after that collection (56 distinct tests now covered). The only warning is the previously documented Starlette/httpx test-transport deprecation. The preview server was stopped and the temporary purview-review account removed after browser verification. Azure publication remains disabled and unverified.
