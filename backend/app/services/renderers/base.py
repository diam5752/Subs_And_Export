from abc import ABC, abstractmethod
from typing import List, Optional, Any
import numpy as np
from PIL import Image

class AbstractRenderer(ABC):
    """
    Abstract base strategy for rendering subtitle frames.
    """
    
    @abstractmethod
    def render_frame(self, t: float) -> np.ndarray:
        """
        Produce a single video frame (as numpy array) for timestamp t.
        """
        pass
