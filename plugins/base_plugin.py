from abc import ABC, abstractmethod
from PIL import Image

class BasePlugin(ABC):
    name: str = "Plugin Name"
    description: str = ""
    button_color: tuple = ("white", "#607d8b")
    needs_roi: bool = False

    @abstractmethod
    def process(self, image: Image.Image, roi=None, display_mode: str = "CMY") -> Image.Image:
        """display_mode を追加（CMY / RGB / BGR）"""
        pass