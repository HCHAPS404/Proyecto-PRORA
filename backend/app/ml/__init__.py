"""Machine-learning primitives for PRORA outbreak forecasting.

The package deliberately has no dependency on the API layer.  It can therefore
be trained from a worker, a notebook or a command-line job and the resulting
artifacts can be consumed by the web service through :class:`ForecastService`.
"""

from .config import DISEASES, MLConfig
from .models import ModelBundle, train_model
from .registry import ModelRegistry
from .service import ForecastResult, ForecastService

__all__ = [
    "DISEASES",
    "MLConfig",
    "ModelBundle",
    "ModelRegistry",
    "ForecastResult",
    "ForecastService",
    "train_model",
]
