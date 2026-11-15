from dataclasses import dataclass
from typing import Tuple, Dict

@dataclass(frozen=True)
class ToolConfig:
    name: str
    color_hex: str
    rgb: Tuple[int, int, int]
    default_width: float  # Normalized width [0.0, 1.0] relative to canvas


# Available standard palette colors
COLOR_PALETTE: Dict[str, Tuple[int, int, int]] = {
    "#FFFFFF": (255, 255, 255),  # Pure White (default)
    "#39FF14": (57, 255, 20),    # Neon Green
    "#00F0FF": (0, 240, 255),    # Cyan / Blue
    "#FFE600": (255, 230, 0),    # Bright Yellow
    "#FF3366": (255, 51, 102),   # Coral Red / Pink
    "#FF9900": (255, 153, 0),    # Orange
}

TOOL_PEN = ToolConfig(name="pen", color_hex="#FFFFFF", rgb=(255, 255, 255), default_width=0.004)
TOOL_ERASER = ToolConfig(name="eraser", color_hex="#000000", rgb=(0, 0, 0), default_width=0.025)
TOOL_HIGHLIGHTER = ToolConfig(name="highlighter", color_hex="#FFE600", rgb=(255, 230, 0), default_width=0.012)
