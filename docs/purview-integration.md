# Microsoft Purview Data Map integration

## Current status

The application includes a real HTTP connector to the Microsoft Purview Data Map Atlas API. It is **disabled by default**. No Azure account, endpoint or credentials were available during development, so live Azure publication has not been verified. Contract tests use a simulated HTTP service and Azure credential, not a real tenant. Offline export preview works without either.

An administrator can open **Microsoft Purview** in the sidebar to inspect configuration, preview the exact metadata payload, test authentication and publish the catalogue. Publishing records a persistent sync result and read-back verifies the returned entities and dataset links. A read-only connection test does not prove write permission. Configuration alone is never reported as a verified connection.

## What is published

| Local information | Purview representation |
| --- | --- |
| Dataset identity, name, description and owner | Custom DataSet subtype: atlas_local_dataset_v1 |
| Definitions, types, sensitivity and parent dataset | Custom Asset subtype: atlas_local_column_v1 |
| Source description, metadata revision and scan status | Dataset attributes |
| Access/retention considerations and quality rules | JSON-valued string attributes |
| Latest quality summary | Rule counts and failing rule IDs; no failing values or row contents |
| Executed transformation dependencies | Custom Process subtype: atlas_local_process_v1, with inputs and outputs |
| Detailed column mappings | columnLineageJson on the Process |

The default example exports 4 datasets, 14 columns and, after a successful transformation, 1 process. A first export before any scan omits the process because declared lineage is not evidence of execution. If a later scan fails, the last captured process retains its run ID/time and the current output status is marked blocked or failed.

Dataset rows, sample records, local file paths, passwords, session tokens, individual access requests and decision notes are excluded. Owner contacts, descriptions and free-text definitions are included as metadata: review the preview before sending real organisational metadata.

The connector creates custom entities rather than impersonating scanned Azure SQL or storage assets. It does not stitch into pre-existing scanned entities. The published sensitivity values are custom metadata, not Microsoft sensitivity labels. Owner team/contact attributes are not Entra-resolved Purview Owner contacts. Column definitions and mappings are exported, but native Schema-tab and column-lineage visualization have not been confirmed in a live portal. Dataset-level lineage uses the documented Process input/output model.

## Azure prerequisites when you have an account

1. Obtain a Microsoft Purview account exposing the Data Map API at `https://ACCOUNT.purview.azure.com`.
2. Identify the target collection's internal name/ID, not just its display label.
3. Choose an identity: managed identity on an Azure host, a service principal, or an Azure CLI developer sign-in through DefaultAzureCredential.
4. Have the collection administrator grant that identity **Data Curator** access on the target collection. Azure subscription/resource Contributor access alone does not replace Purview data-plane authorization. The connector may also need permission to create its custom types; an authorised operator can pre-provision them and set PURVIEW_CREATE_TYPES=false.
5. Ensure network access to the account and Microsoft Entra authentication endpoints. Private-endpoint deployments require correct routing and DNS from the application host.

The implementation supports the public Azure account endpoint only; sovereign-cloud/custom endpoints are intentionally rejected. It never accepts an endpoint or credentials from browser requests. HTTPS certificate validation stays enabled, and redirects are not followed, so bearer tokens are not forwarded to arbitrary destinations.

## Configure local PowerShell

Keep PURVIEW_ENABLED=false until the account and identity are ready. To use an existing Azure CLI developer login, install the Azure CLI separately and sign in to your intended tenant, then set these variables in the same terminal that starts Atlas:

```powershell
$env:PURVIEW_ENABLED = 'true'
$env:PURVIEW_ENDPOINT = 'https://YOUR-ACCOUNT.purview.azure.com'
$env:PURVIEW_COLLECTION_ID = 'YOUR-COLLECTION-INTERNAL-NAME'
$env:PURVIEW_NAMESPACE = 'sales-development'
$env:PURVIEW_AUTH_MODE = 'default'
./start.ps1
```

The local start script reads environment variables; it does not automatically load .env. For service-principal authentication, securely supply AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET to the server process through your chosen secret mechanism. Do not commit secrets, place them in the browser, or paste them into chat. On Azure, prefer PURVIEW_AUTH_MODE=managed-identity. Set AZURE_CLIENT_ID only for a user-assigned managed identity; omit it for a system-assigned identity. Azure Identity requests the scope `https://purview.azure.net/.default`.

Compose reads .env and forwards the variables listed in .env.example to the web container. The container does not inherit a developer's host Azure CLI login. Use service-principal environment variables for local Compose or an appropriately configured managed identity when deployed on Azure. Production secret injection and managed-identity hosting remain deployment responsibilities.

| Variable | Default | Meaning |
| --- | --- | --- |
| PURVIEW_ENABLED | false | Enables authenticated remote operations |
| PURVIEW_ENDPOINT | empty | HTTPS Data Map account endpoint |
| PURVIEW_COLLECTION_ID | empty | Required target collection internal name |
| PURVIEW_NAMESPACE | atlas-local | Stable identity prefix; choose separately for each environment |
| PURVIEW_AUTH_MODE | default | default credential chain or managed-identity |
| PURVIEW_CREATE_TYPES | true | Create missing connector types; incompatible existing types are never overwritten |
| PURVIEW_SYNC_AFTER_SCAN | false | Opt in to publication after manual/scheduled source scans |

## Publish and verify

1. Run a local source scan to capture quality evidence and executed sales lineage.
2. Preview the exact metadata payload under Microsoft Purview.
3. Test the Azure connection. This reads the built-in DataSet, Asset and Process type definitions; it creates nothing.
4. Publish the catalogue. The connector creates missing custom types, upserts datasets, columns and processes, then reads each entity back by its stable qualifiedName.
5. Inspect publication history. A successful record contains a payload hash, target account/collection, verified entity count and qualifiedName-to-GUID mapping. A failure is recorded separately from local source quality; it does not convert a healthy local scan into a failed data-quality run.
6. In Purview, find a published dataset by its name or qualifiedName. Check owner/definition attributes, columns and process inputs/outputs in your portal. This live acceptance step remains outstanding.

Entity names follow `atlas-local://NAMESPACE/datasets/ASSET_ID`, with column names below `/columns/` and process names below `/processes/`. Repeated publishes use the same qualified names to update the same entities. Do not change the namespace just to retry a failed request: that creates a separate inventory. Changing collection ID can move these entities because it is passed to the bulk upsert API.

Read-back checks verify active status, GUIDs, type, qualified name, export fingerprint, column parent and process dataset links. The service stores evidence for the submitted snapshot, not an assertion that local metadata has never changed since then. Re-publish after subsequent edits. Verification checks connector-owned attributes; it is not a complete audit of the remote account.

## Failure recovery and limits

HTTP 429 and transient network/server failures have bounded retries; authorization failures stop immediately. Raw response bodies and credential exception details are excluded from user-facing messages and stored summaries. Requests use a three-minute operation budget plus bounded Azure Identity network/subprocess timeouts. A database lease prevents simultaneous publishers and expires after ten minutes after a crash.

Purview and the local database do not share a transaction. Failed publication may leave partially created/updated types or entities. Retry with the same namespace; upserts converge without intentionally duplicating entities. Interrupted runs are marked when a later publisher acquires the expired lease. Existing incompatible types require a reviewed schema migration; the connector never overwrites them automatically.

The small-project limit is 200 exported entities or 2 MB per snapshot. Writes are batched in groups of up to 50; a read-back request verifies every entity. No remote deletion or garbage collection is implemented. Restoring a local backup does not roll back Azure metadata. Keep automatic publication disabled while restoring/reviewing a workspace, then deliberately re-publish.

This is a one-way catalogue publisher, not a Purview scanner, bidirectional editor, Unified Catalog data-product integration, cloud provisioning system, external access-policy writer or retention-deletion engine. Existing Atlas approvals continue to control only Atlas data previews.

## API and tests

All routes require an administrator session; POST routes also require CSRF tokens:

- GET /api/purview/status
- POST /api/purview/preview (offline; no Azure requests)
- POST /api/purview/test (read-only authenticated check)
- POST /api/purview/sync (publishes and verifies)

Run `python -m pytest -q tests/test_purview.py`. Tests use the real client with HTTPX MockTransport and a fake Azure credential. They exercise repeated upserts, type provisioning/conflicts, retries, raw-error redaction, read-back/lineage mismatches, disabled operation, authorization, CSRF, stale execution evidence and overlapping-publication denial. Passing them is not proof of a live Azure connection.

Microsoft references: [bulk entity upsert and collection routing](https://learn.microsoft.com/en-us/rest/api/purview/datamapdataplane/entity/bulk-create-or-update?view=rest-purview-datamapdataplane-2023-09-01), [custom types](https://learn.microsoft.com/en-us/rest/api/purview/datamapdataplane/type/bulk-create?view=rest-purview-datamapdataplane-2023-09-01), [data-plane authentication and roles](https://learn.microsoft.com/en-us/purview/data-gov-api-rest-data-plane), [Azure Identity](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential?view=azure-python), and [custom Process lineage](https://learn.microsoft.com/en-us/purview/legacy/how-to-purview-custom-lineage-api-user-guide).
