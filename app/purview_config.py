"""Server-side Purview configuration. Credentials stay in Azure Identity/environment."""
import os
import re
from dataclasses import dataclass


@dataclass
class PurviewConfig:
    enabled: bool = False
    endpoint: str = ''
    collection_id: str = ''
    namespace: str = 'atlas-local'
    auth_mode: str = 'default'
    create_types: bool = True
    sync_after_scan: bool = False

    @property
    def display_endpoint(self):
        if not self.endpoint:
            return ''
        if re.fullmatch(r'https://[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.purview\.azure\.com', self.endpoint):
            return self.endpoint
        return '[invalid endpoint; inspect server configuration]'

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv('PURVIEW_ENABLED', 'false').lower() == 'true',
            endpoint=os.getenv('PURVIEW_ENDPOINT', '').rstrip('/'),
            collection_id=os.getenv('PURVIEW_COLLECTION_ID', ''),
            namespace=os.getenv('PURVIEW_NAMESPACE', 'atlas-local'),
            auth_mode=os.getenv('PURVIEW_AUTH_MODE', 'default'),
            create_types=os.getenv('PURVIEW_CREATE_TYPES', 'true').lower() == 'true',
            sync_after_scan=os.getenv('PURVIEW_SYNC_AFTER_SCAN', 'false').lower() == 'true',
        )

    def validate(self, live=True):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', self.namespace):
            raise ValueError('PURVIEW_NAMESPACE must contain 1-64 lowercase letters, digits, underscores or hyphens')
        if not live:
            return
        if not self.enabled:
            raise ValueError('Purview is disabled. Configure the server environment and enable it first.')
        # Avoid forwarding Azure tokens to arbitrary user-controlled URLs or redirects.
        if not re.fullmatch(r'https://[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.purview\.azure\.com', self.endpoint):
            raise ValueError('Use the HTTPS public-Azure account endpoint: https://ACCOUNT.purview.azure.com')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.collection_id):
            raise ValueError('Set PURVIEW_COLLECTION_ID to the target collection internal name')
        if self.auth_mode not in {'default', 'managed-identity'}:
            raise ValueError('PURVIEW_AUTH_MODE must be default or managed-identity')
