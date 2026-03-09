"""
HiveMind Ingest Discovery Package

Provides modular discovery of repository contents:
- Repo type classification
- Service discovery
- Environment discovery
- Pipeline discovery
- Infrastructure layer discovery
- Secret pattern discovery
- Naming convention detection
- Profile building
"""

from ingest.discovery.discover_repo_type import discover_repo_type
from ingest.discovery.discover_services import discover_services
from ingest.discovery.discover_environments import discover_environments
from ingest.discovery.discover_pipelines import discover_pipelines
from ingest.discovery.discover_infra_layers import discover_infra_layers
from ingest.discovery.discover_secrets import discover_secrets
from ingest.discovery.discover_naming import discover_naming
from ingest.discovery.build_profile import build_profile

__all__ = [
    "discover_repo_type",
    "discover_services",
    "discover_environments",
    "discover_pipelines",
    "discover_infra_layers",
    "discover_secrets",
    "discover_naming",
    "build_profile",
]
