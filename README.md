# Atlas — Data Governance and Lineage

Atlas brings information about your datasets into one workspace. It helps you find relevant data, understand what it means, trace where it came from, and request access from the people responsible for it.

The workspace combines a searchable catalogue with quality monitoring, lineage, access approvals and a history of changes and decisions.

## Your data, explained

| Feature | What it means for you |
| --- | --- |
| Catalogue | A shared directory of datasets, their columns, business definitions and responsible teams. |
| Search | A way to find datasets by name, field, owner or description, such as data containing customer regions. |
| Lineage | A view of where data came from and how it was transformed. Revenue, for example, comes from order quantity multiplied by product price. |
| Quality monitoring | Checks for duplicate identifiers, missing values, invalid prices and broken references between datasets. Results show which datasets need attention. |
| Governance information | Details about sensitive fields, intended uses, approval owners and retention considerations. |
| Access approvals | Requests with a business purpose, owner decisions and time-limited access to data previews. |
| Change and audit history | Records of metadata revisions, access decisions, sign-ins and data-preview activity. |
| Microsoft Purview integration | Optional publication of catalogue metadata and captured lineage to a configured Microsoft Purview account, with an export preview and publication history. |

## Inside the workspace

### Data catalogue

Each dataset has a profile covering its description, owner, source, fields, sensitivity and quality status. Field definitions explain the meaning of individual columns. The profile also identifies downstream datasets that may be affected by a source change.

Data previews display up to 25 rows and are available only when both access permissions and quality requirements are satisfied.

### Lineage explorer

Lineage connects source datasets to the outputs they produce. Column mappings explain how individual fields are copied, joined or calculated. Captured transformations retain their execution reference and timestamp, making the relationship between historical lineage and current dataset health visible.

### Quality monitor

Quality checks cover unique identifiers, required values, email formats, positive numbers and references between datasets. Scheduled and administrator-triggered scans retain results over time, showing failures and subsequent recovery.

A failed quality check blocks the affected dataset's preview. A source failure also blocks dependent sales output. Changes to source columns require owner review before the affected dataset returns to use.

### Access requests

Access requests record the dataset and business purpose. An authorised owner or administrator can approve or reject a request and record the reason for the decision.

Approved preview access lasts seven days and can be revoked earlier. Expired or revoked access is denied on subsequent preview requests. Users cannot approve their own requests.

### Source connections

The workspace supports managed CSV imports and read-only scans of the included operational database. Imported datasets have an assigned owner and key column. Fields begin with a personal classification and the dataset begins as confidential, providing a conservative starting point for owner review.

CSV imports create managed copies. They do not automatically track changes to the original uploaded file. Sources support up to 5,000 rows, with a 5 MB limit for CSV files.

### Microsoft Purview

The optional Microsoft Purview connector shares dataset descriptions, ownership information, column definitions, quality summaries and captured transformation lineage with a configured Azure account.

An export preview shows the metadata included before publication. Dataset rows, passwords, sessions and individual access requests are excluded. Stable identifiers support repeat publication to the same catalogue entries, while publication history records outcomes and remote entity references.

Azure publication is available when an account endpoint, target collection and authorised Azure identity are configured. The export preview is available without an Azure connection.

## Roles and responsibilities

| Role | Workspace access |
| --- | --- |
| Analyst | Discovers datasets, reviews definitions and quality information, requests access and views data with an active approval. |
| Steward | Maintains definitions, reviews schema changes and manages access requests for datasets owned by their team. |
| Administrator | Manages accounts and source connections, runs scans, reviews audit records and manages Purview publication. |

Steward ownership follows the team assigned to each dataset. Owners and administrators can preview data within their authority, subject to the same quality requirements as other users.

## Included sales example

The included workspace contains synthetic customer, product and order data, along with an enriched sales dataset.

| Dataset | Information |
| --- | --- |
| CRM customers | Customer identifiers, contact addresses and sales regions. |
| Product master | Product identifiers, names and current unit prices in INR. |
| Sales orders | Order identifiers, customer and product references, and quantities. |
| Enriched sales | Order identifiers, customer regions, product names and calculated revenue. |

For an order containing two notebooks priced at 100 INR each, calculated revenue is 200 INR. The calculation uses current product prices and excludes taxes, discounts and returns. Customer email addresses are omitted from enriched sales.

The initial catalogue documents four datasets and fourteen fields, with eleven quality rules across the datasets.

## Access, retention and data handling

Atlas permissions control previews served by this application. Permissions in external source systems are managed separately.

Retention information records policy considerations. Expiring preview access does not delete source records, stored snapshots or backups, and automatic retention deletion is not part of the application.

Purview publication shares metadata rather than dataset contents. Atlas sensitivity values are catalogue attributes; they do not apply Microsoft sensitivity labels or grant access to external data sources.

## Further information

- [Governance brief](docs/governance-brief.md)
- [Microsoft Purview integration](docs/purview-integration.md)
- [Architecture and permissions](docs/architecture.md)
- [Operations and recovery](docs/operations.md)
