import asyncio
import base64
from io import BytesIO
import io
import os
import shlex
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Literal, Tuple, TypedDict
from uuid import uuid4
from PIL import Image, ImageGrab
import pyautogui
import streamlit as st

from anthropic.types.beta import BetaToolComputerUse20241022Param

from .base import BaseAnthropicTool, ToolError, ToolResult
from .run import run

OUTPUT_DIR = "/tmp/outputs"

TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

IMAGE_MAX_WIDTH = 1200

Action = Literal[
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "screenshot",
    "cursor_position",
]


class Resolution(TypedDict):
    width: int
    height: int


class ScalingSource(StrEnum):
    COMPUTER = "computer"
    API = "api"


class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None


def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


class ComputerTool(BaseAnthropicTool):
    """
    A tool that allows the agent to interact with the screen, keyboard, and mouse of the current computer.
    The tool parameters are defined by Anthropic and are not editable.
    """

    name: Literal["computer"] = "computer"
    api_type: Literal["computer_20241022"] = "computer_20241022"
    width: int
    height: int
    display_num: int | None

    _screenshot_delay = 2.0
    _scaling_enabled = True

    @property
    def options(self) -> ComputerToolOptions:
        width, height = self.scale_coordinates(
            ScalingSource.COMPUTER, self.width, self.height
        )
        return {
            "display_width_px": width,
            "display_height_px": height,
            "display_number": self.display_num,
        }

    def to_params(self) -> BetaToolComputerUse20241022Param:
        return {"name": self.name, "type": self.api_type, **self.options}

    def __init__(self):
        super().__init__()

        self.width = int(os.getenv("WIDTH", 1920))
        self.height = int(os.getenv("HEIGHT", 1080))
        assert self.width and self.height, "WIDTH, HEIGHT must be set"
        if (display_num := os.getenv("DISPLAY_NUM")) is not None:
            self.display_num = int(display_num)
            self._display_prefix = f"DISPLAY=:{self.display_num} "
        else:
            self.display_num = None
            self._display_prefix = ""

        self.xdotool = f"{self._display_prefix}xdotool"

    async def __call__(
            self,
            *,
            action: str,
            text: str | None = None,
            coordinate: tuple[int, int] | list[int] | None = None,
            **kwargs,
        ):
        if action in ("mouse_move", "left_click_drag"):
            if coordinate is None:
                raise ToolError(f"coordinate is required for {action}")
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")
            
            # Allow both tuple and list
            if not (isinstance(coordinate, (tuple, list)) and len(coordinate) == 2):
                raise ToolError(f"{coordinate} must be a tuple or list of length 2")
            
            # Ensure the coordinate is a tuple
            coordinate = tuple(coordinate)  # Convert to tuple if it's a list
    
            if not all(isinstance(i, int) and i >= 0 for i in coordinate):
                raise ToolError(f"{coordinate} must be a tuple of non-negative ints")
    
            x, y = self.scale_coordinates(
                ScalingSource.API, coordinate[0], coordinate[1]
            )
    
            if action == "mouse_move":
                pyautogui.moveTo(x, y)
                return
            elif action == "left_click_drag":
                pyautogui.mouseDown(x, y)
                return
    
        if action in ("key", "type"):
            if text is None:
                raise ToolError(f"text is required for {action}")
            if coordinate is not None:
                raise ToolError(f"coordinate is not accepted for {action}")
            if not isinstance(text, str):
                raise ToolError(output=f"{text} must be a string")
    
            if action == "key":
                pyautogui.press(text.lower())  # Simulate a key press
                return
            elif action == "type":
                pyautogui.typewrite(text)  # Type the given text
                return
    
        if action in (
            "left_click",
            "right_click",
            "double_click",
            "middle_click",
            "screenshot",
            "cursor_position",
        ):
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")
            if coordinate is not None:
                raise ToolError(f"coordinate is not accepted for {action}")
            
            def pil_image_to_bytes(image: Image.Image, format: str = 'PNG') -> bytes:
                # Create an in-memory bytes buffer
                byte_arr = io.BytesIO()
                # Save the image to this buffer in the specified format (e.g., 'PNG', 'JPEG')
                image.save(byte_arr, format=format)
                # Retrieve the byte data
                byte_data = byte_arr.getvalue()
                return byte_data
    
            if action == "screenshot":
                screenshot = pyautogui.screenshot()  # Take a screenshot
                screenshot.save("screenshot.png")
                screenshot_bytes=pil_image_to_bytes(screenshot,format='PNG')
                return screenshot_bytes # Return the path or you could return the image in a different format
            elif action == "cursor_position":
                x, y = pyautogui.position()  # Get the current mouse cursor position
                return f"X={x},Y={y}"
            else:
                click_arg = {
                    "left_click": pyautogui.click,
                    "right_click": lambda: pyautogui.click(button='right'),
                    "middle_click": lambda: pyautogui.click(button='middle'),
                    "double_click": pyautogui.doubleClick,
                }[action]
                click_arg()  # Execute the click action
                return
    
        raise ToolError(f"Invalid action: {action}")

    async def screenshot(self):
        """Take a screenshot of the current screen and return the base64 encoded image."""
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"

        # Take a screenshot using Pillow
        screenshot = ImageGrab.grab()
        screenshot.save(path)

        # Optionally resize if scaling is enabled
        if self._scaling_enabled:
            x, y = self.scale_coordinates(ScalingSource.COMPUTER, self.width, self.height)
            screenshot = screenshot.resize((x, y))
            screenshot.save(path)

    # Convert to base64 if the screenshot was saved successfully
        if path.exists():
            with path.open("rb") as image_file:
                image_bytes = BytesIO(image_file.read())
            return image_bytes

    # Raise an error if screenshot failed
        raise ToolError("Failed to take screenshot")

    async def shell(self, command: str, take_screenshot=True) -> ToolResult:
        """Run a shell command and return the output, error, and optionally a screenshot."""
        _, stdout, stderr = await run(command)
        base64_image = None

        if take_screenshot:
            # delay to let things settle before taking a screenshot
            await asyncio.sleep(self._screenshot_delay)
            base64_image = (await self.screenshot())

        return ToolResult(output=stdout, error=stderr, base64_image=base64_image)

    def scale_coordinates(self, source: ScalingSource, x: int, y: int):
        """Scale coordinates to a target maximum resolution."""
        if not self._scaling_enabled:
            return x, y
        ratio = self.width / self.height
        target_dimension = { "width": IMAGE_MAX_WIDTH, "height": IMAGE_MAX_WIDTH / ratio }
        # should be less than 1
        x_scaling_factor = target_dimension["width"] / self.width
        y_scaling_factor = target_dimension["height"] / self.height
        if source == ScalingSource.API:
            if x > self.width or y > self.height:
                raise ToolError(f"Coordinates {x}, {y} are out of bounds")
            # scale up
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        # scale down
        return round(x * x_scaling_factor), round(y * y_scaling_factor)