# Governance brief

Atlas is a working governance application for a small multi-source sales dataset. It brings a CRM CSV and operational product/order database tables into a shared inventory and managed enriched-sales dataset. Administrators can register additional CSVs. Included data, owners and policies are illustrative.

**Discoverability.** Signed-in users search datasets, owners and column definitions. Records explain business meaning, sensitivity, source and purpose. Column lineage explains how identifiers, regions, product names and revenue reach enriched sales. Run provenance distinguishes historical transformation evidence from current source health.

**Quality management.** Scheduled and manual scans check schemas and execute rules. Eleven rules cover the initial four assets: keys, required values, positive numbers, email syntax and cross-source references. Failed inputs block sales publication and affected previews; history preserves failure and recovery. Schema changes require owner review and fresh access approval. Removing dependent fields requires an explicit code migration.

**Accountable access.** Administrators provision named users. Stewards manage assets owned by their exact team. Analysts state a business purpose before receiving owner-approved, seven-day preview access. Expired/revoked grants are denied by the API; reads and decisions generate audit records. Additive schema acceptance revokes old grants and labels new fields personal. Enforcement covers Atlas-served copies; external source permissions remain separate.

**Compliance readiness.** Ownership, sensitivity, purpose, decisions, quality results and transformation history become inspectable evidence for inventories and internal reviews. This does not establish legal compliance or implement retention deletion. Owners must approve applicable policies and review retention guidance. Database administrators can modify audit rows; independently protected logs are needed for stronger evidence.

**Operating responsibility.** Owners maintain definitions, investigate failures and approve access. Platform administrators operate connections, identity, schedules, backups and deployments. Review metadata when schemas or purposes change, and periodically review entitlements. Before real-data use, validate identity, security, encryption, recovery, retention implementation and workload in the intended environment. Connectors are bounded; sales uses current prices and excludes taxes, discounts and returns.


**Enterprise catalogue exchange.** An optional Microsoft Purview Data Map connector publishes documented assets, fields, quality summaries and captured dataset lineage into a configured Azure account. Offline preview makes the export reviewable before transmission; dataset rows and individual access requests are excluded. Stable identifiers and read-back evidence support repeatable updates. This is metadata exchange, not external permission enforcement, automated deletion or proof of compliance. Live account validation remains pending because no Azure account was supplied.
