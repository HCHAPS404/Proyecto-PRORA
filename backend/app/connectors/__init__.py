"""External, read-only data source connectors for PRORA."""

from .dane import DANECNPVConnector, DANEConnector, DIVIPOLAConnector
from .errors import ConnectorConfigurationError, ConnectorError, UnsafeQueryError
from .ideam import IDEAMClimateConnector, IDEAMDeforestationConnector, IDEAMStationsConnector
from .pai import PAIConnector
from .sivigila import SIVIGILAConnector
from .sivigila_microdata import (
    SIVIGILA_2024_EVENT_FILES,
    SIVIGILA_MICRODATA_DISCOVERY_URL,
    SIVIGILA2024EventFile,
    SIVIGILAMicrodataMeasure,
    sivigila_2024_event_files,
)
from .territorial_sivigila import (
    FEDERATION_SOURCE_ID,
    TerritorialSourceProfile,
    territorial_profiles,
)
from .socrata import (
    Aggregate,
    Filter,
    Function,
    GroupExpression,
    Operator,
    SafeQuery,
    SelectExpression,
    SocrataClient,
)

__all__ = [
    "ConnectorConfigurationError",
    "ConnectorError",
    "DANEConnector",
    "DANECNPVConnector",
    "DIVIPOLAConnector",
    "FEDERATION_SOURCE_ID",
    "Filter",
    "Function",
    "GroupExpression",
    "IDEAMClimateConnector",
    "IDEAMDeforestationConnector",
    "IDEAMStationsConnector",
    "Operator",
    "Aggregate",
    "PAIConnector",
    "SIVIGILAConnector",
    "SIVIGILA2024EventFile",
    "SIVIGILA_MICRODATA_DISCOVERY_URL",
    "SIVIGILAMicrodataMeasure",
    "SIVIGILA_2024_EVENT_FILES",
    "SafeQuery",
    "SelectExpression",
    "SocrataClient",
    "TerritorialSourceProfile",
    "UnsafeQueryError",
    "sivigila_2024_event_files",
    "territorial_profiles",
]
