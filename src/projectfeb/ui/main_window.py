"""Main GUI window for Rider."""

import ctypes
import sys
import tkinter as tk

import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any
from loguru import logger
import time
import json
import threading
import queue
import gc
from dataclasses import asdict
from PIL import Image, ImageTk

from ..core.config import Config, default_output_buses
from ..services.pco_service import (
    PlanningCenterService, PCOServicePlan, PCOFolder, PCOServiceType
)
from ..services.multitracks_service import MultitracksService, StemMatch, AudioStem
from ..services.ableton_service import AbletonService


RIDER_FONT_FAMILY = "Gotham Narrow"


RIDER_COLORS = {
    "corona_gold": "#D4AF37",
    "midnight_indigo": "#1A1C2C",
    "satchel_tan": "#A67C52",
    "stems_violet": "#8E44AD",
    "waveform_teal": "#16A085",
    "glow_amber": "#FFD700",
    "pure_white": "#FFFFFF",
    "obsidian_black": "#000000",
}

RIDER_THEME = {
    "app_bg": (RIDER_COLORS["pure_white"], RIDER_COLORS["midnight_indigo"]),
    "surface": ("#FBF7EF", "#242738"),
    "surface_alt": ("#F4E8D7", "#2C3145"),
    "surface_input": (RIDER_COLORS["pure_white"], "#202433"),
    "surface_overlay": ("#FFF7E3", "#2A2E42"),
    "border": ("#E3C768", RIDER_COLORS["satchel_tan"]),
    "text_primary": (RIDER_COLORS["obsidian_black"], RIDER_COLORS["pure_white"]),
    "text_muted": ("#5F4B32", "#D8CBAE"),
    "text_accent": ("#8A6A1F", RIDER_COLORS["corona_gold"]),
    "primary": ("#B78A1E", RIDER_COLORS["corona_gold"]),
    "primary_hover": ("#C99A27", RIDER_COLORS["glow_amber"]),
    "secondary": (RIDER_COLORS["satchel_tan"], RIDER_COLORS["satchel_tan"]),
    "secondary_hover": ("#B98A5A", "#C29463"),
    "accent": (RIDER_COLORS["stems_violet"], RIDER_COLORS["stems_violet"]),
    "accent_hover": ("#9B59B6", "#A66BC2"),
    "teal": (RIDER_COLORS["waveform_teal"], RIDER_COLORS["waveform_teal"]),
    "teal_hover": ("#1ABC9C", "#1ABC9C"),
    "warning": ("#B8860B", RIDER_COLORS["glow_amber"]),
    "success": (RIDER_COLORS["waveform_teal"], "#6FD2BF"),
    "button_text_primary": (RIDER_COLORS["pure_white"], RIDER_COLORS["pure_white"]),
    "button_text_dark": (RIDER_COLORS["obsidian_black"], RIDER_COLORS["obsidian_black"]),
    "button_text_light": (RIDER_COLORS["pure_white"], RIDER_COLORS["pure_white"]),
}


def register_rider_font_assets(fonts_path: Path) -> None:
    """Register bundled Gotham Narrow fonts so Tk can use them at runtime."""
    font_files = sorted(fonts_path.glob("*.otf")) + sorted(fonts_path.glob("*.ttf"))
    if not font_files:
        logger.debug(f"No Rider font files found in {fonts_path}")
        return

    if sys.platform == "darwin":
        try:
            cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            ct = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")

            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cf.CFRelease.restype = None

            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool

            for font_file in font_files:
                url = cf.CFURLCreateFromFileSystemRepresentation(
                    None,
                    str(font_file).encode("utf-8"),
                    len(str(font_file).encode("utf-8")),
                    False,
                )
                if not url:
                    continue
                error_ref = ctypes.c_void_p()
                ct.CTFontManagerRegisterFontsForURL(url, 1, ctypes.byref(error_ref))
                cf.CFRelease(url)
        except Exception as exc:
            logger.warning(f"Failed to register Rider font assets on macOS: {exc}")
    else:
        for font_file in font_files:
            try:
                ctk.FontManager.load_font(str(font_file))
            except Exception as exc:
                logger.warning(f"Failed to register Rider font asset {font_file.name}: {exc}")


def rider_font(size: int, *, weight: str = "normal", slant: str = "roman") -> ctk.CTkFont:
    return ctk.CTkFont(family=RIDER_FONT_FAMILY, size=size, weight=weight, slant=slant)


def rider_strong_label_font(size: int) -> ctk.CTkFont:
    return ctk.CTkFont(family="Gotham Bold", size=size, weight="bold")


def rider_card_style(*, elevated: bool = False) -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["surface_alt"] if elevated else RIDER_THEME["surface"],
        "border_color": RIDER_THEME["border"],
        "border_width": 1,
        "corner_radius": 16,
    }


def rider_button_style(role: str = "secondary") -> dict[str, object]:
    if role == "primary":
        return {
            "fg_color": RIDER_THEME["primary"],
            "hover_color": RIDER_THEME["primary_hover"],
            "text_color": RIDER_THEME["button_text_primary"],
            "font": rider_font(13, weight="bold"),
        }
    if role == "accent":
        return {
            "fg_color": RIDER_THEME["accent"],
            "hover_color": RIDER_THEME["accent_hover"],
            "text_color": RIDER_THEME["button_text_light"],
            "font": rider_font(13, weight="bold"),
        }
    if role == "teal":
        return {
            "fg_color": RIDER_THEME["teal"],
            "hover_color": RIDER_THEME["teal_hover"],
            "text_color": RIDER_THEME["button_text_light"],
            "font": rider_font(13, weight="bold"),
        }
    return {
        "fg_color": RIDER_THEME["secondary"],
        "hover_color": RIDER_THEME["secondary_hover"],
        "text_color": RIDER_THEME["button_text_light"],
        "font": rider_font(13, weight="bold"),
    }


def rider_entry_style() -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["surface_input"],
        "border_color": RIDER_THEME["border"],
        "text_color": RIDER_THEME["text_primary"],
        "placeholder_text_color": RIDER_THEME["text_muted"],
        "font": rider_font(13),
    }


def rider_combo_style() -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["surface_input"],
        "border_color": RIDER_THEME["border"],
        "button_color": RIDER_THEME["secondary"],
        "button_hover_color": RIDER_THEME["primary_hover"],
        "text_color": RIDER_THEME["text_primary"],
        "font": rider_font(13),
        "dropdown_font": rider_font(13),
        "dropdown_fg_color": RIDER_THEME["surface_input"],
        "dropdown_hover_color": RIDER_THEME["surface_alt"],
        "dropdown_text_color": RIDER_THEME["text_primary"],
    }


def rider_option_menu_style() -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["secondary"],
        "button_color": RIDER_THEME["secondary"],
        "button_hover_color": RIDER_THEME["primary_hover"],
        "text_color": RIDER_THEME["button_text_light"],
        "font": rider_font(12, weight="bold"),
        "dropdown_font": rider_font(12),
        "dropdown_fg_color": RIDER_THEME["surface_input"],
        "dropdown_hover_color": RIDER_THEME["surface_alt"],
        "dropdown_text_color": RIDER_THEME["text_primary"],
    }


def rider_checkbox_style() -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["accent"],
        "hover_color": RIDER_THEME["accent_hover"],
        "border_color": RIDER_THEME["border"],
        "checkmark_color": RIDER_THEME["button_text_light"],
        "text_color": RIDER_THEME["text_primary"],
        "font": rider_font(12),
    }


def rider_switch_style() -> dict[str, object]:
    return {
        "fg_color": RIDER_THEME["border"],
        "progress_color": RIDER_THEME["accent"],
        "button_color": RIDER_THEME["surface_input"],
        "button_hover_color": RIDER_THEME["primary_hover"],
        "text_color": RIDER_THEME["text_primary"],
        "font": rider_font(13),
    }


def rider_title_label_style() -> dict[str, object]:
    return {"text_color": RIDER_THEME["text_accent"]}


def rider_body_label_style() -> dict[str, object]:
    return {"text_color": RIDER_THEME["text_primary"]}

class ProjectFEBApp:
    """Main application window."""

    def __init__(self, config: Config):
        """Initialize the application.

        Args:
            config: Application configuration
        """
        self.config = config

        # Initialize services
        self.pco_service = PlanningCenterService(config.planning_center)
        self.multitracks_service = MultitracksService(config.multitracks)
        self.ableton_service = AbletonService(config.ableton)
        self.ableton_service.ui_thread_dispatcher = self._call_on_ui_thread_and_wait

        # Current data
        self.folders: list[PCOFolder] = []
        self.service_types: list[PCOServiceType] = []
        self.service_plans: list[PCOServicePlan] = []
        self.selected_folder: Optional[PCOFolder] = None
        self.selected_service_type: Optional[PCOServiceType] = None
        self.selected_plan: Optional[PCOServicePlan] = None
        self.stem_matches: Dict[str, StemMatch] = {}
        self.is_busy = False
        self.is_shutting_down = False
        self.loading_status_base = ""
        self.loading_status_pulse_on = False
        self.suppress_selection_callbacks = False
        self.pending_ui_callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
        self.assets_path = Path(__file__).parent.parent.parent.parent / "img"
        self.fonts_path = Path(__file__).parent.parent.parent.parent / "font"
        self.app_icon_image: Optional[ImageTk.PhotoImage] = None
        self.brand_logo_image: Optional[ctk.CTkImage] = None

        # Preferences file
        self.preferences_path = Path(__file__).parent.parent.parent.parent / "config" / "preferences.json"
        self.preferences = self._load_preferences()
        self.multitracks_service.set_stem_type_overrides(self._stem_type_override_preferences())

        # Setup GUI
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        register_rider_font_assets(self.fonts_path)
        ctk.ThemeManager.theme["CTkFont"]["family"] = RIDER_FONT_FAMILY

        self.root = ctk.CTk()
        self.root.configure(fg_color=RIDER_THEME["app_bg"])
        self.root.title("Rider: The Final Editing Bridge")
        self.root.geometry("1000x760")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self._apply_window_icon()

        self._create_widgets()
        self._fit_window_to_content()
        self.root.after(50, self._process_pending_ui_callbacks)
        self.root.after(4000, self._refresh_loading_status_heartbeat)
        self._load_initial_data()

    def _fit_window_to_content(self) -> None:
        """Ensure the launch window is tall and wide enough for the full landing layout."""
        self.root.update_idletasks()
        required_width = self.root.winfo_reqwidth() + 24
        required_height = self.root.winfo_reqheight() + 24
        fitted_width = max(1000, required_width)
        fitted_height = max(760, required_height)
        self.root.geometry(f"{fitted_width}x{fitted_height}")
        self.root.minsize(fitted_width, fitted_height)

    def _apply_window_icon(self) -> None:
        """Load the Rider app icon for the runtime window and dock."""
        icon_path = self.assets_path / "icon.png"
        if not icon_path.exists():
            logger.debug(f"Rider icon not found at {icon_path}")
            return

        try:
            padded_icon = self._build_padded_app_icon(icon_path)
            self.app_icon_image = ImageTk.PhotoImage(padded_icon)
            self.root.iconphoto(True, self.app_icon_image)
        except Exception as exc:
            logger.warning(f"Failed to load Rider icon from {icon_path}: {exc}")

    def _build_padded_app_icon(self, icon_path: Path) -> Image.Image:
        """Center the provided icon in a slightly roomier square so it matches macOS dock scale better."""
        canvas_size = 1024
        safe_area_ratio = 0.84

        with Image.open(icon_path) as image:
            rgba_image = image.convert("RGBA")
            alpha_bbox = rgba_image.getchannel("A").getbbox()
            if alpha_bbox is not None:
                rgba_image = rgba_image.crop(alpha_bbox)

            max_icon_size = int(canvas_size * safe_area_ratio)
            resized_width, resized_height = self._scaled_image_size(
                rgba_image.size,
                max_width=max_icon_size,
                max_height=max_icon_size,
            )
            resized_icon = rgba_image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        paste_x = (canvas_size - resized_width) // 2
        paste_y = (canvas_size - resized_height) // 2
        canvas.alpha_composite(resized_icon, (paste_x, paste_y))
        return canvas

    def _load_brand_logo(self) -> Optional[ctk.CTkImage]:
        """Load a cropped light/dark logo pair for the app header."""
        light_logo_path = self.assets_path / "blackLogo.png"
        dark_logo_path = self.assets_path / "whiteLogo.png"
        if not light_logo_path.exists() or not dark_logo_path.exists():
            logger.debug("Rider logo files are missing; falling back to text header")
            return None

        try:
            light_logo = self._load_cropped_rgba(light_logo_path)
            dark_logo = self._load_cropped_rgba(dark_logo_path)
        except Exception as exc:
            logger.warning(f"Failed to load Rider logos: {exc}")
            return None

        width, height = self._scaled_image_size(light_logo.size, max_width=460, max_height=150)
        self.brand_logo_image = ctk.CTkImage(
            light_image=light_logo,
            dark_image=dark_logo,
            size=(width, height),
        )
        return self.brand_logo_image

    def _load_cropped_rgba(self, image_path: Path) -> Image.Image:
        """Trim transparent padding so the provided logos render at a sensible size."""
        with Image.open(image_path) as image:
            rgba_image = image.convert("RGBA")
            alpha_bbox = rgba_image.getchannel("A").getbbox()
            if alpha_bbox is not None:
                rgba_image = rgba_image.crop(alpha_bbox)
            return rgba_image.copy()

    def _scaled_image_size(
        self,
        original_size: tuple[int, int],
        *,
        max_width: int,
        max_height: int,
    ) -> tuple[int, int]:
        """Scale an image to fit within the requested bounds without distorting it."""
        original_width, original_height = original_size
        if original_width <= 0 or original_height <= 0:
            return max_width, max_height

        scale = min(max_width / original_width, max_height / original_height, 1.0)
        scaled_width = max(1, int(original_width * scale))
        scaled_height = max(1, int(original_height * scale))
        return scaled_width, scaled_height

    def _create_widgets(self):
        """Create the main GUI widgets."""
        # Main container
        self.main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Brand header
        brand_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        brand_frame.pack(fill="x", pady=(20, 10))

        brand_logo = self._load_brand_logo()
        if brand_logo is not None:
            brand_logo_label = ctk.CTkLabel(
                brand_frame,
                text="",
                image=brand_logo,
            )
            brand_logo_label.pack()
        else:
            title_label = ctk.CTkLabel(
                brand_frame,
                text="Rider",
                font=rider_font(24, weight="bold"),
                **rider_title_label_style(),
            )
            title_label.pack(pady=(0, 8))

            subtitle_label = ctk.CTkLabel(
                brand_frame,
                text="The Final Editing Bridge",
                font=rider_font(14),
                **rider_body_label_style(),
            )
            subtitle_label.pack()

        # Selection section (Folder -> Service Type -> Plan)
        selection_frame = ctk.CTkFrame(self.main_frame, **rider_card_style())
        selection_frame.pack(fill="x", padx=20, pady=(0, 10))

        # Folder selection
        folder_label = ctk.CTkLabel(
            selection_frame,
            text="1. Select Campus/Folder:",
            font=rider_strong_label_font(13),
            **rider_title_label_style(),
        )
        folder_label.pack(anchor="w", padx=20, pady=(10, 2))

        self.folder_var = ctk.StringVar()
        self.folder_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.folder_var,
            state="readonly",
            command=self._on_folder_selected,
            **rider_combo_style(),
        )
        self.folder_combo.pack(fill="x", padx=20, pady=(0, 10))

        # Service type selection
        service_type_label = ctk.CTkLabel(
            selection_frame,
            text="2. Select Service Type:",
            font=rider_strong_label_font(13),
            **rider_title_label_style(),
        )
        service_type_label.pack(anchor="w", padx=20, pady=(10, 2))

        self.service_type_var = ctk.StringVar()
        self.service_type_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.service_type_var,
            state="readonly",
            command=self._on_service_type_selected,
            **rider_combo_style(),
        )
        self.service_type_combo.pack(fill="x", padx=20, pady=(0, 10))
        self.service_type_combo.configure(values=["Loading..."])
        self.service_type_combo.set("Select a folder first")

        # Service plan selection
        plan_label = ctk.CTkLabel(
            selection_frame,
            text="3. Select Service Plan:",
            font=rider_strong_label_font(13),
            **rider_title_label_style(),
        )
        plan_label.pack(anchor="w", padx=20, pady=(10, 2))

        self.service_var = ctk.StringVar()
        self.service_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.service_var,
            state="readonly",
            command=self._on_service_selected,
            **rider_combo_style(),
        )
        self.service_combo.pack(fill="x", padx=20, pady=(0, 10))
        self.service_combo.configure(values=["Loading..."])
        self.service_combo.set("Select a service type first")

        # Refresh button
        self.refresh_btn = ctk.CTkButton(
            selection_frame,
            text="Refresh",
            command=self._load_folders,
            width=100,
            **rider_button_style("teal"),
        )
        self.refresh_btn.pack(pady=(10, 14))

        # Stem matching section
        stems_frame = ctk.CTkFrame(self.main_frame, **rider_card_style())
        stems_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        stems_label = ctk.CTkLabel(
            stems_frame,
            text="Stem Matching Results:",
            font=rider_font(16, weight="bold"),
            **rider_title_label_style(),
        )
        stems_label.pack(pady=(10, 5))

        # Results text area
        self.results_text = ctk.CTkTextbox(
            stems_frame,
            wrap="word",
            fg_color=RIDER_THEME["surface_input"],
            border_color=RIDER_THEME["border"],
            border_width=1,
            text_color=RIDER_THEME["text_primary"],
            font=rider_font(13),
            scrollbar_button_color=RIDER_THEME["secondary"],
            scrollbar_button_hover_color=RIDER_THEME["primary_hover"],
        )
        self.results_text.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Action buttons
        buttons_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=20, pady=(0, 20))

        # Left side buttons
        left_buttons = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        left_buttons.pack(side="left")

        self.settings_btn = ctk.CTkButton(
            left_buttons,
            text="Settings",
            command=self._open_settings,
            **rider_button_style("secondary"),
        )
        self.settings_btn.pack(side="left", padx=(0, 10))

        # Right side buttons
        right_buttons = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        right_buttons.pack(side="right")

        self.generate_btn = ctk.CTkButton(
            right_buttons,
            text="Generate Setlist",
            command=self._generate_setlist,
            state="disabled",
            **rider_button_style("primary"),
        )
        self.generate_btn.pack(side="right")

        self.resolve_unknown_btn = ctk.CTkButton(
            right_buttons,
            text="Resolve Unknown Stems",
            command=lambda: self._resolve_unknown_stems(show_success_if_none=True),
            **rider_button_style("accent"),
        )
        self.resolve_unknown_btn.pack(side="right", padx=(0, 10))

        self.loading_overlay = ctk.CTkFrame(self.main_frame, **rider_card_style(elevated=True))
        self.loading_status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            self.loading_overlay,
            text="Working...",
            font=rider_font(18, weight="bold"),
            **rider_title_label_style(),
        ).pack(padx=24, pady=(20, 8))
        ctk.CTkLabel(
            self.loading_overlay,
            textvariable=self.loading_status_var,
            wraplength=320,
            justify="center",
            font=rider_font(13),
            **rider_body_label_style(),
        ).pack(padx=24, pady=(0, 12))
        self.loading_progress = ctk.CTkProgressBar(
            self.loading_overlay,
            mode="indeterminate",
            width=240,
            fg_color=RIDER_THEME["surface_input"],
            progress_color=RIDER_THEME["teal"],
            border_color=RIDER_THEME["border"],
        )
        self.loading_progress.pack(padx=24, pady=(0, 20))
        self.loading_overlay.place_forget()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        """Toggle loading UI and disable controls while background work runs."""
        self.is_busy = busy
        logger.debug(f"Busy state -> {busy} ({message or 'idle'})")

        combo_state = "disabled" if busy else "readonly"
        button_state = "disabled" if busy else "normal"

        self.folder_combo.configure(state=combo_state)
        self.service_type_combo.configure(state=combo_state)
        self.service_combo.configure(state=combo_state)
        self.refresh_btn.configure(state=button_state)
        self.settings_btn.configure(state=button_state)
        self.resolve_unknown_btn.configure(state=button_state)

        if busy:
            self.generate_btn.configure(state="disabled")
            self._set_loading_status(message or "Working...")
            self.loading_overlay.place(relx=0.5, rely=0.5, anchor="center")
            self.loading_overlay.lift()
            self.loading_progress.start()
        else:
            self.loading_status_base = ""
            self.loading_status_pulse_on = False
            self.loading_status_var.set("")
            self.loading_progress.stop()
            self.loading_overlay.place_forget()
            self._update_action_button_states()

    def _set_combo_value(self, combo: ctk.CTkComboBox, value: str) -> None:
        """Set a combo value without firing the selection handler twice."""
        self.suppress_selection_callbacks = True
        try:
            combo.set(value)
        finally:
            self.suppress_selection_callbacks = False

    def _process_pending_ui_callbacks(self) -> None:
        """Run worker-thread results safely on the Tk main thread."""
        try:
            while True:
                callback = self.pending_ui_callbacks.get_nowait()
                callback()
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(50, self._process_pending_ui_callbacks)

    def _call_on_ui_thread_and_wait(self, callback: Callable[[], Any]) -> Any:
        """Execute a callback on the Tk thread and block the worker until it completes."""
        if threading.current_thread() is threading.main_thread():
            return callback()

        done = threading.Event()
        result: Dict[str, Any] = {}

        def run_callback() -> None:
            try:
                result['value'] = callback()
            except Exception as exc:
                result['error'] = exc
            finally:
                done.set()

        self.pending_ui_callbacks.put(run_callback)
        done.wait()

        if 'error' in result:
            raise result['error']
        return result.get('value')

    def _set_loading_status(self, message: str) -> None:
        """Update the loading overlay text while background work is in progress."""
        self.loading_status_base = message
        self.loading_status_pulse_on = False
        self.loading_status_var.set(message)

    def _refresh_loading_status_heartbeat(self) -> None:
        """Refresh loading text periodically so long-running steps still look active."""
        if self.is_busy and self.loading_status_base:
            self.loading_status_pulse_on = not self.loading_status_pulse_on
            status_text = self.loading_status_base
            if self.loading_status_pulse_on:
                status_text = f"{status_text}\nStill working..."
            self.loading_status_var.set(status_text)

        if self.root.winfo_exists():
            self.root.after(4000, self._refresh_loading_status_heartbeat)

    def _run_background_task(
        self,
        message: str,
        worker: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """Run blocking work in a background thread and marshal results to the UI thread."""
        if self.is_busy:
            logger.debug(f"Skipping background task while already busy: {message}")
            return

        self._set_busy(True, message)

        def task() -> None:
            gc_was_enabled = gc.isenabled()
            if gc_was_enabled:
                # Tk objects must be finalized on the main thread on macOS.
                gc.disable()

            try:
                result = worker()
            except Exception as exc:
                def handle_error(error: Exception = exc) -> None:
                    if gc_was_enabled:
                        gc.enable()
                        gc.collect()
                    self._set_busy(False)
                    if on_error is not None:
                        on_error(error)
                    else:
                        logger.error(f"Background task failed: {error}")
                        messagebox.showerror("Error", str(error))

                self.pending_ui_callbacks.put(handle_error)
                return

            def handle_success() -> None:
                if gc_was_enabled:
                    gc.enable()
                    gc.collect()
                self._set_busy(False)
                if on_success is not None:
                    on_success(result)

            self.pending_ui_callbacks.put(handle_success)

        threading.Thread(target=task, daemon=True).start()

    def _update_action_button_states(self):
        """Enable generation only when the current plan has no unresolved stems."""
        can_generate = bool(
            not self.is_busy and self.selected_plan and self.stem_matches and not self._get_unknown_stems()
        )
        self.generate_btn.configure(state="normal" if can_generate else "disabled")

    def _clear_matching_state(self, message: Optional[str] = None):
        """Reset current match results and refresh action button state."""
        self.stem_matches = {}
        self.results_text.delete("0.0", "end")
        if message:
            self.results_text.insert("0.0", message)
        self._update_action_button_states()

    def _load_initial_data(self):
        """Load initial data when the app starts."""
        self._load_folders()

    def _load_preferences(self) -> Dict:
        """Load user preferences from file."""
        if self.preferences_path.exists():
            try:
                with open(self.preferences_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load preferences: {e}")
        return {}

    def _save_preferences(self):
        """Save user preferences to file."""
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.preferences_path, 'w') as f:
                json.dump(self.preferences, f, indent=2)
            logger.debug(f"Preferences saved: {self.preferences}")
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")

    def _stem_type_override_preferences(self) -> Dict[str, str]:
        """Return persisted stem-type override mappings from preferences."""
        overrides = self.preferences.get('stem_type_overrides', {})
        return overrides if isinstance(overrides, dict) else {}

    def _load_folders(self):
        """Load folders from Planning Center Online."""
        def worker() -> List[PCOFolder]:
            logger.info("=== STARTING _load_folders ===")
            folders = self.pco_service.get_folders()
            logger.info(f"Step 1: Service returned {len(folders) if folders else 0} folders")
            logger.debug(f"Folder IDs from service: {[f.id for f in folders] if folders else []}")
            return folders

        def on_success(folders: List[PCOFolder]) -> None:
            self.folders = folders

            if not self.folders:
                logger.error("No folders returned from PCO service!")
                self.folder_combo.configure(values=["No folders found"])
                self.folder_combo.set("No folders found")
                return

            logger.info(f"Step 2: UI received {len(self.folders)} folders from service")
            
            # Check if 1550568 is in the list BEFORE sorting
            smc_folders = [f for f in self.folders if f.id == '1550568']
            if smc_folders:
                logger.info(f"✓ Summers Corner Campus found BEFORE sort: {smc_folders[0].name}")
            else:
                logger.error("✗ Summers Corner Campus (1550568) NOT in folders BEFORE sort!")

            # Sort folders by name
            self.folders.sort(key=lambda x: x.name)
            logger.info(f"Step 3: After sorting, still have {len(self.folders)} folders")
            
            # Check if 1550568 is in the list AFTER sorting
            smc_folders_after = [f for f in self.folders if f.id == '1550568']
            if smc_folders_after:
                logger.info(f"✓ Summers Corner Campus found AFTER sort: {smc_folders_after[0].name}")
            else:
                logger.error("✗ Summers Corner Campus (1550568) NOT in folders AFTER sort!")

            # Format folder names for display
            folder_names = [f"{folder.name} (ID: {folder.id})" for folder in self.folders]
            logger.info(f"Step 4: Formatted {len(folder_names)} display names")
            
            # Check Summers Corner in formatted names
            summers_corner = [f for f in folder_names if "Summers Corner" in f]
            if summers_corner:
                logger.info(f"✓ Found Summers Corner in display names: {summers_corner[0]}")
            else:
                logger.error("✗ Summers Corner NOT in display names!")

            self.folder_combo.configure(values=folder_names)
            logger.info(f"Step 5: Set combo box with {len(folder_names)} values")
            
            # Restore last selected folder if available
            last_folder_id = self.preferences.get("last_folder_id")
            default_folder_name = folder_names[0]
            
            if last_folder_id:
                for folder in self.folders:
                    if folder.id == last_folder_id:
                        default_folder_name = f"{folder.name} (ID: {folder.id})"
                        logger.info(f"Restoring last selected folder: {folder.name}")
                        break
            
            if default_folder_name:
                self._set_combo_value(self.folder_combo, default_folder_name)
                logger.info(f"Step 6: Set default selection to: {default_folder_name}")
                self._on_folder_selected(default_folder_name)
            
            logger.info("=== COMPLETED _load_folders ===")

        def on_error(e: Exception) -> None:
            logger.error(f"Failed to load folders: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to load folders:\n{str(e)}")

        self._run_background_task("Loading Planning Center folders...", worker, on_success, on_error)

    def _on_folder_selected(self, selection: str):
        """Handle folder selection."""
        if self.suppress_selection_callbacks:
            return

        self.selected_service_type = None
        self.selected_plan = None
        self.service_plans = []
        self._clear_matching_state()

        if selection == "No folders found" or not selection:
            self.service_type_combo.configure(values=[])
            self.service_combo.configure(values=[])
            return

        # Find the selected folder
        self.selected_folder = None
        for folder in self.folders:
            if selection.startswith(folder.name):
                self.selected_folder = folder
                break

        if self.selected_folder:
            # Save folder preference
            self.preferences["last_folder_id"] = self.selected_folder.id
            self._save_preferences()
            
            self._load_service_types_for_folder()
        else:
            self.service_type_combo.configure(values=[])
            self.service_combo.configure(values=[])

    def _load_service_types_for_folder(self):
        """Load service types for the selected folder."""
        if not self.selected_folder:
            return

        selected_folder = self.selected_folder

        def worker() -> List[PCOServiceType]:
            return self.pco_service.get_service_types_for_folder(selected_folder.id)

        def on_success(service_types: List[PCOServiceType]) -> None:
            self.service_types = service_types
            if not self.service_types:
                self.service_type_combo.configure(values=["No service types found"])
                self._set_combo_value(self.service_type_combo, "No service types found")
                self.service_combo.configure(values=[])
                return

            # Sort by name
            self.service_types.sort(key=lambda x: x.name)

            # Format for display
            st_names = [st.name for st in self.service_types]

            self.service_type_combo.configure(values=st_names)
            
            # Restore last selected service type if available
            last_service_type_id = self.preferences.get("last_service_type_id")
            default_service_type = st_names[0] if st_names else None
            
            if last_service_type_id:
                for st in self.service_types:
                    if st.id == last_service_type_id:
                        default_service_type = st.name
                        logger.info(f"Restoring last selected service type: {st.name}")
                        break
            
            if default_service_type:
                self._set_combo_value(self.service_type_combo, default_service_type)
                self._on_service_type_selected(default_service_type)

        def on_error(e: Exception) -> None:
            logger.error(f"Failed to load service types: {e}")
            messagebox.showerror("Error", f"Failed to load service types:\n{str(e)}")

        self._run_background_task(
            f"Loading service types for {selected_folder.name}...",
            worker,
            on_success,
            on_error,
        )

    def _on_service_type_selected(self, selection: str):
        """Handle service type selection."""
        if self.suppress_selection_callbacks:
            return

        self.selected_plan = None
        self.service_plans = []
        self._clear_matching_state()

        if selection == "No service types found" or not selection:
            self.service_combo.configure(values=[])
            return

        # Find the selected service type
        self.selected_service_type = None
        for st in self.service_types:
            if st.name == selection:
                self.selected_service_type = st
                break

        if self.selected_service_type:
            # Save service type preference
            self.preferences["last_service_type_id"] = self.selected_service_type.id
            self._save_preferences()
            
            self._load_service_plans_for_service_type()
        else:
            self.service_combo.configure(values=[])

    def _load_service_plans_for_service_type(self):
        """Load service plans for the selected service type."""
        if not self.selected_service_type:
            return

        selected_service_type = self.selected_service_type

        def worker() -> List[PCOServicePlan]:
            start_time = time.time()
            logger.info(f"Starting to load plans for service type: {selected_service_type.name}")
            
            api_start = time.time()
            service_plans = self.pco_service.get_plans_for_service_type(selected_service_type.id)
            api_time = time.time() - api_start
            logger.info(f"API call took {api_time:.2f} seconds to fetch {len(service_plans) if service_plans else 0} plans")
            logger.info(f"Total _load_service_plans_for_service_type took {time.time() - start_time:.2f} seconds")
            return service_plans

        def on_success(service_plans: List[PCOServicePlan]) -> None:
            self.service_plans = service_plans
            if not self.service_plans:
                self.service_combo.configure(values=["No plans found"])
                self._set_combo_value(self.service_combo, "No plans found")
                self._clear_matching_state()
                return

            # Format plan names for display
            format_start = time.time()
            plan_names = []
            for plan in self.service_plans:
                date_str = plan.date.strftime("%Y-%m-%d")
                display_name = f"{date_str} - {plan.title}"
                plan_names.append(display_name)
            format_time = time.time() - format_start
            logger.info(f"Formatting plan names took {format_time:.2f} seconds")

            ui_start = time.time()
            self.service_combo.configure(values=plan_names)
            # Don't automatically select the first plan - let the user choose
            # This prevents expensive stem matching until a plan is actually selected
            self._clear_matching_state("Select a service plan from the dropdown above to begin matching stems.")
            ui_time = time.time() - ui_start
            logger.info(f"UI update took {ui_time:.2f} seconds")

        def on_error(e: Exception) -> None:
            logger.error(f"Failed to load service plans: {e}")
            messagebox.showerror("Error", f"Failed to load service plans:\n{str(e)}")

        self._run_background_task(
            f"Loading plans for {selected_service_type.name}...",
            worker,
            on_success,
            on_error,
        )

    def _on_service_selected(self, selection: str):
        """Handle service plan selection."""
        if self.suppress_selection_callbacks:
            return

        self.selected_plan = None
        self._clear_matching_state()

        if selection == "No plans found":
            return

        # Find the selected plan
        for plan in self.service_plans:
            date_str = plan.date.strftime("%Y-%m-%d")
            if selection.startswith(date_str):
                self.selected_plan = plan
                break

        if self.selected_plan:
            # Fetch songs for this plan if not already fetched
            if not self.selected_plan.songs and self.selected_service_type:
                self._fetch_plan_songs()
            else:
                self._match_stems_for_plan()

    def _fetch_plan_songs(self):
        """Fetch songs for the selected plan (deferred until plan is selected)."""
        if not self.selected_plan or not self.selected_service_type:
            return

        selected_plan = self.selected_plan
        selected_service_type = self.selected_service_type

        def worker() -> Dict[str, StemMatch]:
            fetch_start = time.time()
            logger.info(f"Starting to fetch songs for plan: {selected_plan.title}")
            self.pco_service._populate_plan_songs(selected_plan, selected_service_type.id)
            fetch_time = time.time() - fetch_start
            logger.info(f"Fetching plan songs took {fetch_time:.2f} seconds for {len(selected_plan.songs)} songs")
            song_titles = [song.title for song in selected_plan.songs]
            return self.multitracks_service.find_stems_for_songs(song_titles)

        def on_success(matches: Dict[str, StemMatch]) -> None:
            self.stem_matches = matches
            self._display_matching_results()

        def on_error(e: Exception) -> None:
            logger.error(f"Failed to fetch plan songs: {e}")
            messagebox.showerror("Error", f"Failed to fetch plan songs:\n{str(e)}")

        self._run_background_task(
            f"Loading songs and matching stems for {selected_plan.title}...",
            worker,
            on_success,
            on_error,
        )

    def _match_stems_for_plan(self):
        """Match stems for the selected service plan."""
        if not self.selected_plan:
            return

        selected_plan = self.selected_plan

        def worker() -> Dict[str, StemMatch]:
            song_titles = [song.title for song in selected_plan.songs]
            return self.multitracks_service.find_stems_for_songs(song_titles)

        def on_success(matches: Dict[str, StemMatch]) -> None:
            self.stem_matches = matches
            self._display_matching_results()

        def on_error(e: Exception) -> None:
            self._clear_matching_state()
            logger.error(f"Failed to match stems: {e}")
            messagebox.showerror("Error", f"Failed to match stems:\n{str(e)}")

        self._run_background_task(
            f"Matching stems for {selected_plan.title}...",
            worker,
            on_success,
            on_error,
        )

    def _display_matching_results(self):
        """Display the stem matching results in the text area."""
        self.results_text.delete("0.0", "end")

        if not self.selected_plan:
            return

        results = []
        results.append(f"Service: {self.selected_plan.title}")
        results.append(f"Date: {self.selected_plan.date.strftime('%Y-%m-%d')}")
        results.append("")

        total_songs = len(self.selected_plan.songs)
        matched_songs = len(self.stem_matches)
        unknown_stems = self._get_unknown_stems()

        results.append(f"Songs in plan: {total_songs}")
        results.append(f"Songs with stems found: {matched_songs}")
        if unknown_stems:
            results.append(f"Unknown stems needing review: {len(unknown_stems)}")
        results.append("")

        for song in self.selected_plan.songs:
            results.append(f"🎵 {song.title}")
            if song.title in self.stem_matches:
                match = self.stem_matches[song.title]
                confidence_pct = int(match.match_confidence * 100)
                results.append(f"   ✓ Found {len(match.stems)} stems (confidence: {confidence_pct}%)")

                for stem in match.stems:
                    stem_prefix = "⚠ Unknown" if stem.stem_type == 'unknown' else stem.stem_type.title()
                    results.append(f"     • {stem_prefix}: {stem.filename}")

                if match.missing_stems:
                    results.append(f"     ⚠ Missing: {', '.join(match.missing_stems)}")
            else:
                results.append("   ✗ No stems found")
            results.append("")

        self.results_text.insert("0.0", "\n".join(results))
        self._update_action_button_states()

    def _get_unknown_stems(self) -> List[tuple[str, AudioStem]]:
        """Return unresolved unknown stems for the current plan."""
        unknown_stems: List[tuple[str, AudioStem]] = []
        if not self.selected_plan:
            return unknown_stems

        for song in self.selected_plan.songs:
            match = self.stem_matches.get(song.title)
            if not match:
                continue
            for stem in match.stems:
                if stem.stem_type == 'unknown':
                    unknown_stems.append((song.title, stem))

        return unknown_stems

    def _resolve_unknown_stems(self, show_success_if_none: bool = False) -> bool:
        """Resolve unknown stems into remembered groups before generation."""
        unknown_stems = self._get_unknown_stems()
        if not unknown_stems:
            if show_success_if_none:
                messagebox.showinfo("Unknown Stems", "No unknown stems need review right now.")
            return True

        dialog = UnknownStemResolutionDialog(self.root, self.multitracks_service, unknown_stems)
        self.root.wait_window(dialog.dialog)
        if dialog.result is None:
            return False

        overrides = self._stem_type_override_preferences()
        overrides.update(dialog.result)
        self.preferences['stem_type_overrides'] = overrides
        self._save_preferences()
        self.multitracks_service.set_stem_type_overrides(overrides)
        self._match_stems_for_plan()
        return True

    def _generate_setlist(self):
        """Generate the Ableton Live setlist."""
        if not self.selected_plan or not self.stem_matches:
            messagebox.showwarning("Warning", "Please select a service plan with matched stems first.")
            return

        if self._get_unknown_stems():
            self._update_action_button_states()
            messagebox.showwarning("Resolve Unknown Stems", "Resolve all unknown stems before generating the setlist.")
            return

        service_type_name = self.selected_service_type.name if self.selected_service_type else "Service"
        service_date = self.selected_plan.date
        stem_matches = self.stem_matches
        plan_songs = self.selected_plan.songs

        def worker() -> Optional[Path]:
            self.ableton_service.status_reporter = self._set_loading_status
            return self.ableton_service.generate_setlist(
                service_type_name=service_type_name,
                service_date=service_date,
                stem_matches=stem_matches,
                plan_songs=plan_songs,
            )

        def on_success(output_path: Optional[Path]) -> None:
            self.ableton_service.status_reporter = None
            if output_path:
                messagebox.showinfo(
                    "Success",
                    f"Setlist generated successfully!\n\nSaved to: {output_path}"
                )
            else:
                messagebox.showerror("Error", "Failed to generate setlist.")

        def on_error(e: Exception) -> None:
            self.ableton_service.status_reporter = None
            logger.error(f"Failed to generate setlist: {e}")
            messagebox.showerror("Error", f"Failed to generate setlist:\n{str(e)}")

        self._run_background_task(
            f"Generating Ableton setlist for {service_date.strftime('%Y-%m-%d')}...",
            worker,
            on_success,
            on_error,
        )

    def _open_settings(self):
        """Open the settings dialog."""
        settings_window = SettingsDialog(self.root, self.config)
        self.root.wait_window(settings_window.dialog)
        
        # Reload config from file and reinitialize services
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "settings.json"
        self.config = Config(config_path)
        
        # Reinitialize services with updated config
        self.pco_service = PlanningCenterService(self.config.planning_center)
        self.multitracks_service = MultitracksService(self.config.multitracks)
        self.ableton_service = AbletonService(self.config.ableton)
        self.ableton_service.ui_thread_dispatcher = self._call_on_ui_thread_and_wait
        self.multitracks_service.set_stem_type_overrides(self._stem_type_override_preferences())
        
        # Reload folders after settings are potentially changed
        self._load_folders()

    def run(self):
        """Run the application main loop."""
        self.root.mainloop()

    def shutdown(self):
        """Best-effort application shutdown for GUI close or terminal interrupt."""
        if self.is_shutting_down:
            return

        self.is_shutting_down = True

        try:
            self.ableton_service.shutdown()
        except Exception as exc:
            logger.debug(f"Ableton service shutdown raised: {exc}")

        try:
            self.root.destroy()
        except Exception as exc:
            logger.debug(f"Tk shutdown raised: {exc}")


class SettingsDialog:
    """Settings dialog for configuring the application."""

    ROUTING_TAG_OPTIONS = [
        ('drums', 'Drums'),
        ('percussion', 'Percussion'),
        ('loops', 'Loops'),
        ('perc', 'Perc'),
        ('bass', 'Bass'),
        ('lead_line', 'Lead Line'),
        ('electric_guitar', 'Electric Gtr'),
        ('acoustic_guitar', 'Acoustic Gtr'),
        ('guitars', 'All Guitars'),
        ('orchestra', 'Orchestra'),
        ('strings', 'Strings'),
        ('piano', 'Piano'),
        ('pads', 'Pads'),
        ('synth', 'Synth'),
        ('keys', 'Keys'),
        ('lead_vocal', 'Lead Vocal'),
        ('bgvs', 'BGVs'),
        ('vocals', 'Vocals'),
    ]
    MONO_SLOT_VALUES = [str(index) for index in range(1, 9)]
    STEREO_SLOT_VALUES = ['1', '3', '5', '7']
    
    def __init__(self, parent, config: Config):
        """Initialize settings dialog.
        
        Args:
            parent: Parent window
            config: Application configuration to edit
        """
        self.config = config
        self.config_path = Path(__file__).parent.parent.parent.parent / "config" / "settings.json"
        self.content_bus_rows: list[dict] = []
        self.special_bus_rows: dict[str, dict] = {}
        
        # Create dialog window
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.configure(fg_color=RIDER_THEME["app_bg"])
        self.dialog.title("Settings")
        self.dialog.geometry("860x980")
        self.dialog.resizable(True, True)
        
        # Make it modal
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the settings dialog widgets."""
        main_frame = ctk.CTkScrollableFrame(self.dialog, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Title
        title = ctk.CTkLabel(
            main_frame,
            text="Application Settings",
            font=rider_font(18, weight="bold"),
            **rider_title_label_style(),
        )
        title.pack(pady=(0, 20))
        
        # Planning Center Section
        pc_frame = self._create_section(main_frame, "Planning Center Online")
        
        self.pco_app_id_entry = self._create_text_field(
            pc_frame,
            "Application ID:",
            self.config.planning_center.application_id
        )
        
        self.pco_secret_entry = self._create_text_field(
            pc_frame,
            "Secret:",
            self.config.planning_center.secret,
            show="*"
        )
        
        # Multitracks Section
        mt_frame = self._create_section(main_frame, "Multitracks")
        
        self.stems_folder_entry = self._create_file_field(
            mt_frame,
            "Stems Folder:",
            self.config.multitracks.stems_folder,
            is_directory=True
        )
        
        # Ableton Section
        ab_frame = self._create_section(main_frame, "Ableton Live")
        
        self.output_folder_entry = self._create_file_field(
            ab_frame,
            "Output Folder:",
            self.config.ableton.output_folder,
            is_directory=True
        )

        self.sub_master_switch = ctk.CTkSwitch(
            ab_frame,
            text="Enable internal Sub Master monitoring bus",
            **rider_switch_style(),
        )
        self.sub_master_switch.pack(anchor="w", pady=(0, 10))
        if self.config.ableton.enable_sub_master:
            self.sub_master_switch.select()
        else:
            self.sub_master_switch.deselect()

        self.sub_master_name_entry = self._create_text_field(
            ab_frame,
            "Sub Master Bus Name:",
            self.config.ableton.sub_master_bus_name,
        )
        self._create_output_bus_editor(ab_frame)
        
        # Action buttons
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(20, 0))
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save Settings",
            command=self._save_settings,
            **rider_button_style("primary"),
        )
        save_btn.pack(side="left", padx=(0, 10))
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self.dialog.destroy,
            **rider_button_style("secondary"),
        )
        cancel_btn.pack(side="left")
        
        test_btn = ctk.CTkButton(
            button_frame,
            text="Test Connection",
            command=self._test_connection,
            **rider_button_style("teal"),
        )
        test_btn.pack(side="right")
    
    def _create_section(self, parent, title: str) -> ctk.CTkFrame:
        """Create a settings section with a title."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(15, 0))
        
        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=rider_font(13, weight="bold"),
            **rider_title_label_style(),
        )
        title_label.pack(anchor="w", pady=(0, 10))
        
        content_card = ctk.CTkFrame(frame, **rider_card_style())
        content_card.pack(fill="x", padx=15)

        content_frame = ctk.CTkFrame(content_card, fg_color="transparent")
        content_frame.pack(fill="x", expand=True, padx=14, pady=14)

        return content_frame

    def _create_field_group(self, parent) -> ctk.CTkFrame:
        """Create a consistent container for one labeled field block."""
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(fill="x", pady=(0, 14))
        return group
    
    def _create_text_field(self, parent, label: str, value: str, show: str = None) -> ctk.CTkEntry:
        """Create a text input field."""
        group = self._create_field_group(parent)

        label_widget = ctk.CTkLabel(group, text=label, font=rider_font(11), **rider_body_label_style())
        label_widget.pack(anchor="w", pady=(0, 3))
        
        entry = ctk.CTkEntry(group, show=show, **rider_entry_style())
        entry.insert(0, value)
        entry.pack(fill="x")
        
        return entry
    
    def _create_file_field(self, parent, label: str, value: str, is_directory: bool = False) -> ctk.CTkFrame:
        """Create a file/folder selection field."""
        container = self._create_field_group(parent)
        
        label_widget = ctk.CTkLabel(container, text=label, font=rider_font(11), **rider_body_label_style())
        label_widget.pack(anchor="w", pady=(0, 3))
        
        input_frame = ctk.CTkFrame(container, fg_color="transparent")
        input_frame.pack(fill="x")
        
        entry = ctk.CTkEntry(input_frame, **rider_entry_style())
        entry.insert(0, value)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        browse_btn = ctk.CTkButton(
            input_frame,
            text="Browse",
            width=80,
            command=lambda: self._browse_path(entry, is_directory),
            **rider_button_style("secondary"),
        )
        browse_btn.pack(side="right")
        
        return entry
    
    def _browse_path(self, entry: ctk.CTkEntry, is_directory: bool):
        """Open file/folder browser dialog."""
        if is_directory:
            path = filedialog.askdirectory(
                title="Select Folder",
                initialdir=entry.get() or str(Path.home())
            )
        else:
            path = filedialog.askopenfilename(
                title="Select File",
                initialdir=entry.get() or str(Path.home()),
                filetypes=[("All Files", "*.*"), ("ALS Files", "*.als")]
            )
        
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _create_output_bus_editor(self, parent) -> None:
        """Create a structured editor for logical Ableton bus layout."""
        description = ctk.CTkLabel(
            parent,
            text=(
                "Logical Output Buses: create content buses, then place Click and Guide wherever you want in the return order.\n"
                "Content buses can use up to 6 total lanes. Stereo buses must start on 1, 3, 5, or 7."
            ),
            justify="left",
            wraplength=760,
            font=rider_font(11),
            **rider_body_label_style(),
        )
        description.pack(anchor="w", pady=(0, 8))

        self.output_bus_summary_label = ctk.CTkLabel(
            parent,
            text="",
            justify="left",
            font=rider_font(11, weight="bold"),
            **rider_body_label_style(),
        )
        self.output_bus_summary_label.pack(anchor="w", pady=(0, 10))

        try:
            output_buses = AbletonService.validate_output_buses(self.config.ableton.output_buses)
        except Exception:
            output_buses = AbletonService.validate_output_buses(default_output_buses())

        special_frame = ctk.CTkFrame(parent, **rider_card_style(elevated=True))
        special_frame.pack(fill="x", pady=(0, 12))

        special_title = ctk.CTkLabel(
            special_frame,
            text="Special Buses",
            font=rider_font(12, weight="bold"),
            **rider_title_label_style(),
        )
        special_title.pack(anchor="w", padx=12, pady=(10, 8))

        click_bus = next((bus for bus in output_buses if bus['role'] == 'click'), {'slot': 7, 'name': 'Click'})
        guide_bus = next((bus for bus in output_buses if bus['role'] == 'guide'), {'slot': 8, 'name': 'Guide'})
        self._create_special_bus_row(special_frame, 'click', click_bus)
        self._create_special_bus_row(special_frame, 'guide', guide_bus)

        content_frame = ctk.CTkFrame(parent, **rider_card_style(elevated=True))
        content_frame.pack(fill="both", expand=True, pady=(0, 12))

        header_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(10, 8))

        content_title = ctk.CTkLabel(
            header_frame,
            text="Content Buses",
            font=rider_font(12, weight="bold"),
            **rider_title_label_style(),
        )
        content_title.pack(side="left")

        add_bus_btn = ctk.CTkButton(
            header_frame,
            text="Add Content Bus",
            width=140,
            command=self._add_content_bus_row,
            **rider_button_style("teal"),
        )
        add_bus_btn.pack(side="right")

        helper_label = ctk.CTkLabel(
            content_frame,
            text="Pick a slot, mono/stereo mode, a freeform name, and the routing tags that should feed that bus.",
            justify="left",
            font=rider_font(11),
            **rider_body_label_style(),
        )
        helper_label.pack(anchor="w", padx=12, pady=(0, 8))

        self.content_bus_container = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.content_bus_container.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        content_buses = [bus for bus in output_buses if bus['role'] == 'content']
        for bus in content_buses:
            self._add_content_bus_row(bus)

        self._update_output_bus_summary()

    def _create_special_bus_row(self, parent, role: str, bus: dict) -> None:
        """Create a compact editor row for Click or Guide."""
        frame = ctk.CTkFrame(parent, **rider_card_style())
        frame.pack(fill="x", padx=12, pady=(0, 10))

        frame.grid_columnconfigure(5, weight=1)

        role_label = ctk.CTkLabel(
            frame,
            text=role.title(),
            width=80,
            anchor="w",
            font=rider_font(12, weight="bold"),
            **rider_title_label_style(),
        )
        role_label.grid(row=0, column=0, padx=(12, 10), pady=10, sticky="w")

        slot_label = ctk.CTkLabel(frame, text="Return Slot", width=80, **rider_body_label_style())
        slot_label.grid(row=0, column=1, padx=(0, 6), pady=10, sticky="w")

        slot_menu = ctk.CTkOptionMenu(
            frame,
            values=self.MONO_SLOT_VALUES,
            width=90,
            command=lambda _value: self._update_output_bus_summary(),
            **rider_option_menu_style(),
        )
        slot_menu.set(str(bus.get('slot', 7 if role == 'click' else 8)))
        slot_menu.grid(row=0, column=2, padx=(0, 12), pady=10, sticky="w")

        name_label = ctk.CTkLabel(frame, text="Bus Name", width=70, **rider_body_label_style())
        name_label.grid(row=0, column=3, padx=(0, 6), pady=10, sticky="w")

        name_entry = ctk.CTkEntry(frame, **rider_entry_style())
        name_entry.insert(0, bus.get('name', role.title()))
        name_entry.grid(row=0, column=5, padx=(0, 12), pady=10, sticky="ew")

        self.special_bus_rows[role] = {
            'slot_menu': slot_menu,
            'name_entry': name_entry,
            'role': role,
        }

    def _add_content_bus_row(self, bus: Optional[dict] = None) -> None:
        """Add an editable content bus card."""
        bus = bus or {
            'slot': 1,
            'mode': 'mono',
            'name': '',
            'tags': [],
        }

        frame = ctk.CTkFrame(self.content_bus_container, **rider_card_style())
        frame.pack(fill="x", pady=(0, 10))

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 6))

        slot_label = ctk.CTkLabel(header, text="Slot", **rider_body_label_style())
        slot_label.pack(side="left", padx=(0, 6))

        slot_values = self.STEREO_SLOT_VALUES if bus.get('mode') == 'stereo' else self.MONO_SLOT_VALUES
        slot_menu = ctk.CTkOptionMenu(
            header,
            values=slot_values,
            width=90,
            command=lambda _value: self._update_output_bus_summary(),
            **rider_option_menu_style(),
        )
        slot_menu.set(str(bus.get('slot', slot_values[0])))
        if slot_menu.get() not in slot_values:
            slot_menu.set(slot_values[0])
        slot_menu.pack(side="left", padx=(0, 12))

        mode_label = ctk.CTkLabel(header, text="Mode", **rider_body_label_style())
        mode_label.pack(side="left", padx=(0, 6))

        row: dict = {'frame': frame}
        mode_menu = ctk.CTkOptionMenu(
            header,
            values=['mono', 'stereo'],
            width=100,
            command=lambda value, row=row: self._on_content_mode_changed(row, value),
            **rider_option_menu_style(),
        )
        mode_menu.set(bus.get('mode', 'mono'))
        mode_menu.pack(side="left", padx=(0, 12))

        name_label = ctk.CTkLabel(header, text="Bus Name", **rider_body_label_style())
        name_label.pack(side="left", padx=(0, 6))

        name_entry = ctk.CTkEntry(header, **rider_entry_style())
        name_entry.insert(0, bus.get('name', ''))
        name_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))

        remove_btn = ctk.CTkButton(
            header,
            text="Remove",
            width=80,
            command=lambda row=row: self._remove_content_bus_row(row),
            **rider_button_style("secondary"),
        )
        remove_btn.pack(side="right")

        tags_frame = ctk.CTkFrame(frame, **rider_card_style(elevated=True))
        tags_frame.pack(fill="x", padx=10, pady=(0, 10))

        tags_label = ctk.CTkLabel(
            tags_frame,
            text="Routing Tags",
            font=rider_font(11, weight="bold"),
            **rider_title_label_style(),
        )
        tags_label.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 6))

        selected_tags = {tag.strip().lower() for tag in bus.get('tags', [])}
        tag_checkboxes: dict[str, ctk.CTkCheckBox] = {}
        for index, (tag_value, tag_label) in enumerate(self.ROUTING_TAG_OPTIONS):
            checkbox = ctk.CTkCheckBox(
                tags_frame,
                text=tag_label,
                command=self._update_output_bus_summary,
                **rider_checkbox_style(),
            )
            if tag_value in selected_tags:
                checkbox.select()
            row_index = 1 + index // 4
            column_index = index % 4
            checkbox.grid(row=row_index, column=column_index, sticky="w", padx=8, pady=(0, 6))
            tag_checkboxes[tag_value] = checkbox

        row.update({
            'slot_menu': slot_menu,
            'mode_menu': mode_menu,
            'name_entry': name_entry,
            'tag_checkboxes': tag_checkboxes,
        })
        self.content_bus_rows.append(row)
        self._on_content_mode_changed(row, mode_menu.get(), update_summary=False)
        self._update_output_bus_summary()

    def _on_content_mode_changed(self, row: dict, value: str, update_summary: bool = True) -> None:
        """Restrict valid slot choices when a content bus switches between mono and stereo."""
        slot_menu = row['slot_menu']
        allowed_slots = self.STEREO_SLOT_VALUES if value == 'stereo' else self.MONO_SLOT_VALUES
        slot_menu.configure(values=allowed_slots)
        if slot_menu.get() not in allowed_slots:
            slot_menu.set(allowed_slots[0])
        if update_summary:
            self._update_output_bus_summary()

    def _remove_content_bus_row(self, row: dict) -> None:
        """Remove a content bus card from the editor."""
        row['frame'].destroy()
        self.content_bus_rows = [existing_row for existing_row in self.content_bus_rows if existing_row is not row]
        self._update_output_bus_summary()

    def _update_output_bus_summary(self) -> None:
        """Refresh the live lane-usage summary for the bus editor."""
        content_lanes_used = 0
        occupied_slots: set[int] = set()
        overlaps: set[int] = set()

        for role, row in self.special_bus_rows.items():
            slot = int(row['slot_menu'].get())
            if slot in occupied_slots:
                overlaps.add(slot)
            occupied_slots.add(slot)

        for row in self.content_bus_rows:
            slot = int(row['slot_menu'].get())
            mode = row['mode_menu'].get()
            width = 2 if mode == 'stereo' else 1
            content_lanes_used += width

            for occupied_slot in range(slot, slot + width):
                if occupied_slot in occupied_slots:
                    overlaps.add(occupied_slot)
                occupied_slots.add(occupied_slot)

        summary_parts = [f"Content lanes used: {content_lanes_used} / 6"]
        if overlaps:
            summary_parts.append(f"Slot overlap: {', '.join(str(slot) for slot in sorted(overlaps))}")
        if content_lanes_used > 6:
            summary_parts.append("Too many content lanes selected")

        warning_state = bool(overlaps) or content_lanes_used > 6
        self.output_bus_summary_label.configure(
            text=" | ".join(summary_parts),
            text_color=RIDER_THEME["warning"] if warning_state else RIDER_THEME["success"]
        )
    
    def _save_settings(self):
        """Save settings to configuration file."""
        try:
            output_buses = self._parse_output_buses()

            # Update config objects with new values
            self.config.planning_center.application_id = self.pco_app_id_entry.get().strip()
            self.config.planning_center.secret = self.pco_secret_entry.get().strip()
            self.config.multitracks.stems_folder = self.stems_folder_entry.get().strip()
            self.config.ableton.output_folder = self.output_folder_entry.get().strip()
            self.config.ableton.output_buses = output_buses
            self.config.ableton.enable_sub_master = bool(self.sub_master_switch.get())
            self.config.ableton.sub_master_bus_name = self.sub_master_name_entry.get().strip() or "Sub Master"
            
            # Validate required fields
            if not self.config.planning_center.application_id:
                messagebox.showwarning(
                    "Validation Error",
                    "Planning Center Application ID is required."
                )
                return
            
            if not self.config.planning_center.secret:
                messagebox.showwarning(
                    "Validation Error",
                    "Planning Center Secret is required."
                )
                return
            
            if self.config.multitracks.stems_folder and not Path(self.config.multitracks.stems_folder).exists():
                messagebox.showwarning(
                    "Validation Error",
                    "Multitracks stems folder does not exist."
                )
                return
            
            if self.config.ableton.output_folder and not Path(self.config.ableton.output_folder).exists():
                messagebox.showwarning(
                    "Validation Error",
                    "Ableton output folder does not exist."
                )
                return
            
            # Save to file
            self.config.save(self.config_path)
            
            messagebox.showinfo(
                "Success",
                "Settings saved successfully!"
            )
            
            logger.info("Settings saved successfully")
            self.dialog.destroy()
            
        except Exception as e:
            logger.error(f"Failed to save settings: {e}", exc_info=True)
            messagebox.showerror(
                "Error",
                f"Failed to save settings:\n{str(e)}"
            )
    def _parse_output_buses(self) -> list[dict]:
        """Collect and validate the structured output bus editor state."""
        output_buses = []

        for role, row in self.special_bus_rows.items():
            output_buses.append({
                'slot': int(row['slot_menu'].get()),
                'role': role,
                'mode': 'mono',
                'name': row['name_entry'].get().strip(),
                'tags': [],
            })

        for row in self.content_bus_rows:
            selected_tags = [
                tag_value
                for tag_value, checkbox in row['tag_checkboxes'].items()
                if bool(checkbox.get())
            ]
            output_buses.append({
                'slot': int(row['slot_menu'].get()),
                'role': 'content',
                'mode': row['mode_menu'].get(),
                'name': row['name_entry'].get().strip(),
                'tags': selected_tags,
            })

        return AbletonService.validate_output_buses(output_buses)
    
    def _test_connection(self):
        """Test Planning Center Online connection."""
        try:
            app_id = self.pco_app_id_entry.get().strip()
            secret = self.pco_secret_entry.get().strip()
            
            if not app_id or not secret:
                messagebox.showwarning(
                    "Missing Credentials",
                    "Please enter both Application ID and Secret."
                )
                return
            
            # Create a temporary service to test connection
            from ..services.pco_service import PlanningCenterService
            from ..core.config import PlanningCenterConfig
            
            test_config = PlanningCenterConfig(
                application_id=app_id,
                secret=secret
            )
            test_service = PlanningCenterService(test_config)
            folders = test_service.get_folders()
            
            if folders:
                messagebox.showinfo(
                    "Connection Successful",
                    f"Successfully connected to Planning Center Online!\nFound {len(folders)} folders."
                )
            else:
                messagebox.showwarning(
                    "No Data",
                    "Connected successfully but no folders found."
                )
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}", exc_info=True)
            messagebox.showerror(
                "Connection Failed",
                f"Failed to connect to Planning Center Online:\n{str(e)}"
            )


class UnknownStemResolutionDialog:
    """Modal dialog for resolving unknown stems into remembered stem groups."""

    STEM_TYPE_OPTIONS = [
        ('perc', 'Perc'),
        ('bass', 'Bass'),
        ('leads', 'Lead'),
        ('strings', 'Strings'),
        ('keys', 'Keys'),
        ('vocals', 'Vocals'),
        ('guide', 'Guide'),
    ]

    def __init__(self, parent, multitracks_service: MultitracksService, unknown_stems: List[tuple[str, AudioStem]]):
        self.multitracks_service = multitracks_service
        self.result: Optional[Dict[str, str]] = None
        self.rows: List[Dict[str, object]] = []

        grouped_unknowns: Dict[str, Dict[str, object]] = {}
        for song_title, stem in unknown_stems:
            suggested_keyword = multitracks_service.suggest_override_keyword(stem)
            normalized_keyword = multitracks_service._normalize_stem_override_keyword(suggested_keyword)
            group_key = normalized_keyword or stem.filename.lower()
            group = grouped_unknowns.setdefault(
                group_key,
                {
                    'keyword': group_key,
                    'examples': [],
                },
            )
            examples = group['examples']
            if len(examples) < 3:
                examples.append(f"{song_title}: {stem.filename}")

        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.configure(fg_color=RIDER_THEME["app_bg"])
        self.dialog.title("Resolve Unknown Stems")
        self.dialog.geometry("920x640")
        self.dialog.resizable(True, True)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        main_frame = ctk.CTkScrollableFrame(self.dialog, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        title = ctk.CTkLabel(
            main_frame,
            text="Resolve Unknown Stem Types",
            font=rider_font(18, weight="bold"),
            **rider_title_label_style(),
        )
        title.pack(anchor="w", pady=(0, 8))

        subtitle = ctk.CTkLabel(
            main_frame,
            text=(
                "Assign each unknown instrument to a routing group. "
                "The app will remember the filename pattern automatically for next time."
            ),
            justify="left",
            wraplength=820,
            font=rider_font(13),
            **rider_body_label_style(),
        )
        subtitle.pack(anchor="w", pady=(0, 16))

        combo_values = [label for _, label in self.STEM_TYPE_OPTIONS]
        for group in grouped_unknowns.values():
            row_frame = ctk.CTkFrame(main_frame, **rider_card_style())
            row_frame.pack(fill="x", pady=(0, 10))

            ctk.CTkLabel(
                row_frame,
                text="\n".join(group['examples']),
                justify="left",
                anchor="w",
                **rider_body_label_style(),
            ).pack(fill="x", padx=12, pady=(10, 6))

            controls = ctk.CTkFrame(row_frame, fg_color="transparent")
            controls.pack(fill="x", padx=12, pady=(0, 10))

            ctk.CTkLabel(
                controls,
                text="Return group",
                width=120,
                anchor="w",
                **rider_body_label_style(),
            ).pack(side="left", padx=(0, 8))

            combo = ctk.CTkComboBox(controls, values=combo_values, state="readonly", width=140, **rider_combo_style())
            combo.set('Strings')
            combo.pack(side="left")

            self.rows.append({
                'keyword': group['keyword'],
                'combo': combo,
            })

        button_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(12, 0))

        ctk.CTkButton(
            button_row,
            text="Cancel",
            command=self.dialog.destroy,
            **rider_button_style("secondary"),
        ).pack(side="right")
        ctk.CTkButton(
            button_row,
            text="Save and Continue",
            command=self._save,
            **rider_button_style("primary"),
        ).pack(side="right", padx=(0, 8))

    def _save(self) -> None:
        resolved: Dict[str, str] = {}
        label_to_type = {label: stem_type for stem_type, label in self.STEM_TYPE_OPTIONS}

        for row in self.rows:
            keyword = self.multitracks_service._normalize_stem_override_keyword(str(row['keyword']))
            if not keyword:
                messagebox.showwarning("Unknown Stems", "Could not determine a filename pattern for one of the unknown stems.")
                return

            selected_label = row['combo'].get()
            selected_type = label_to_type.get(selected_label)
            if not selected_type:
                messagebox.showwarning("Unknown Stems", "Choose a group for each unknown stem.")
                return

            resolved[keyword] = selected_type

        self.result = resolved
        self.dialog.destroy()