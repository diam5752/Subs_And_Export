from abc import ABC, abstractmethod

import numpy as np


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
