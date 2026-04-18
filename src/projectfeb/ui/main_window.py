"""Main GUI window for Project FEB."""

import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import Optional, Dict
from loguru import logger
import time
import json
from dataclasses import asdict

from ..core.config import Config
from ..services.pco_service import (
    PlanningCenterService, PCOServicePlan, PCOFolder, PCOServiceType
)
from ..services.multitracks_service import MultitracksService, StemMatch
from ..services.ableton_service import AbletonService

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

        # Current data
        self.folders: list[PCOFolder] = []
        self.service_types: list[PCOServiceType] = []
        self.service_plans: list[PCOServicePlan] = []
        self.selected_folder: Optional[PCOFolder] = None
        self.selected_service_type: Optional[PCOServiceType] = None
        self.selected_plan: Optional[PCOServicePlan] = None
        self.stem_matches: Dict[str, StemMatch] = {}

        # Preferences file
        self.preferences_path = Path(__file__).parent.parent.parent.parent / "config" / "preferences.json"
        self.preferences = self._load_preferences()

        # Setup GUI
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Project FEB - Planning Center to Ableton")
        self.root.geometry("1000x700")

        self._create_widgets()
        self._load_initial_data()

    def _create_widgets(self):
        """Create the main GUI widgets."""
        # Main container
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Title
        title_label = ctk.CTkLabel(
            main_frame,
            text="Project FEB",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.pack(pady=(20, 10))

        # Selection section (Folder -> Service Type -> Plan)
        selection_frame = ctk.CTkFrame(main_frame)
        selection_frame.pack(fill="x", padx=20, pady=(0, 10))

        # Folder selection
        folder_label = ctk.CTkLabel(
            selection_frame,
            text="1. Select Campus/Folder:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        folder_label.pack(anchor="w", pady=(10, 2))

        self.folder_var = ctk.StringVar()
        self.folder_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.folder_var,
            state="readonly",
            command=self._on_folder_selected
        )
        self.folder_combo.pack(fill="x", padx=20, pady=(0, 10))

        # Service type selection
        service_type_label = ctk.CTkLabel(
            selection_frame,
            text="2. Select Service Type:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        service_type_label.pack(anchor="w", pady=(10, 2))

        self.service_type_var = ctk.StringVar()
        self.service_type_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.service_type_var,
            state="readonly",
            command=self._on_service_type_selected
        )
        self.service_type_combo.pack(fill="x", padx=20, pady=(0, 10))
        self.service_type_combo.configure(values=["Loading..."])
        self.service_type_combo.set("Select a folder first")

        # Service plan selection
        plan_label = ctk.CTkLabel(
            selection_frame,
            text="3. Select Service Plan:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        plan_label.pack(anchor="w", pady=(10, 2))

        self.service_var = ctk.StringVar()
        self.service_combo = ctk.CTkComboBox(
            selection_frame,
            variable=self.service_var,
            state="readonly",
            command=self._on_service_selected
        )
        self.service_combo.pack(fill="x", padx=20, pady=(0, 10))
        self.service_combo.configure(values=["Loading..."])
        self.service_combo.set("Select a service type first")

        # Refresh button
        refresh_btn = ctk.CTkButton(
            selection_frame,
            text="Refresh",
            command=self._load_folders,
            width=100
        )
        refresh_btn.pack(pady=(10, 0))

        # Stem matching section
        stems_frame = ctk.CTkFrame(main_frame)
        stems_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        stems_label = ctk.CTkLabel(
            stems_frame,
            text="Stem Matching Results:",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        stems_label.pack(pady=(10, 5))

        # Results text area
        self.results_text = ctk.CTkTextbox(stems_frame, wrap="word")
        self.results_text.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Action buttons
        buttons_frame = ctk.CTkFrame(main_frame)
        buttons_frame.pack(fill="x", padx=20, pady=(0, 20))

        # Left side buttons
        left_buttons = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        left_buttons.pack(side="left")

        settings_btn = ctk.CTkButton(
            left_buttons,
            text="Settings",
            command=self._open_settings
        )
        settings_btn.pack(side="left", padx=(0, 10))

        # Right side buttons
        right_buttons = ctk.CTkFrame(buttons_frame, fg_color="transparent")
        right_buttons.pack(side="right")

        generate_btn = ctk.CTkButton(
            right_buttons,
            text="Generate Setlist",
            command=self._generate_setlist,
            fg_color="green",
            hover_color="dark green"
        )
        generate_btn.pack(side="right")

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

    def _load_folders(self):
        """Load folders from Planning Center Online."""
        try:
            logger.info("=== STARTING _load_folders ===")
            self.folders = self.pco_service.get_folders()
            logger.info(f"Step 1: Service returned {len(self.folders) if self.folders else 0} folders")
            logger.debug(f"Folder IDs from service: {[f.id for f in self.folders] if self.folders else []}")

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
                self.folder_combo.set(default_folder_name)
                logger.info(f"Step 6: Set default selection to: {default_folder_name}")
                self._on_folder_selected(default_folder_name)
            
            logger.info("=== COMPLETED _load_folders ===")

        except Exception as e:
            logger.error(f"Failed to load folders: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to load folders:\n{str(e)}")

    def _on_folder_selected(self, selection: str):
        """Handle folder selection."""
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

        try:
            self.service_types = self.pco_service.get_service_types_for_folder(
                self.selected_folder.id
            )

            if not self.service_types:
                self.service_type_combo.configure(values=["No service types found"])
                self.service_type_combo.set("No service types found")
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
                self.service_type_combo.set(default_service_type)
                self._on_service_type_selected(default_service_type)

        except Exception as e:
            logger.error(f"Failed to load service types: {e}")
            messagebox.showerror("Error", f"Failed to load service types:\n{str(e)}")

    def _on_service_type_selected(self, selection: str):
        """Handle service type selection."""
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

        try:
            start_time = time.time()
            logger.info(f"Starting to load plans for service type: {self.selected_service_type.name}")
            
            api_start = time.time()
            self.service_plans = self.pco_service.get_plans_for_service_type(
                self.selected_service_type.id
            )
            api_time = time.time() - api_start
            logger.info(f"API call took {api_time:.2f} seconds to fetch {len(self.service_plans) if self.service_plans else 0} plans")

            if not self.service_plans:
                self.service_combo.configure(values=["No plans found"])
                self.service_combo.set("No plans found")
                self.results_text.delete("0.0", "end")
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
            self.results_text.delete("0.0", "end")
            self.results_text.insert("0.0", "Select a service plan from the dropdown above to begin matching stems.")
            ui_time = time.time() - ui_start
            logger.info(f"UI update took {ui_time:.2f} seconds")
            
            total_time = time.time() - start_time
            logger.info(f"Total _load_service_plans_for_service_type took {total_time:.2f} seconds")

        except Exception as e:
            logger.error(f"Failed to load service plans: {e}")
            messagebox.showerror("Error", f"Failed to load service plans:\n{str(e)}")

    def _on_service_selected(self, selection: str):
        """Handle service plan selection."""
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
        
        try:
            fetch_start = time.time()
            logger.info(f"Starting to fetch songs for plan: {self.selected_plan.title}")
            
            self.pco_service._populate_plan_songs(self.selected_plan, self.selected_service_type.id)
            
            fetch_time = time.time() - fetch_start
            logger.info(f"Fetching plan songs took {fetch_time:.2f} seconds for {len(self.selected_plan.songs)} songs")
            
            self._match_stems_for_plan()
        except Exception as e:
            logger.error(f"Failed to fetch plan songs: {e}")
            messagebox.showerror("Error", f"Failed to fetch plan songs:\n{str(e)}")

    def _match_stems_for_plan(self):
        """Match stems for the selected service plan."""
        if not self.selected_plan:
            return

        try:
            song_titles = [song.title for song in self.selected_plan.songs]
            self.stem_matches = self.multitracks_service.find_stems_for_songs(song_titles)

            # Display results
            self._display_matching_results()

        except Exception as e:
            logger.error(f"Failed to match stems: {e}")
            messagebox.showerror("Error", f"Failed to match stems:\n{str(e)}")

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

        results.append(f"Songs in plan: {total_songs}")
        results.append(f"Songs with stems found: {matched_songs}")
        results.append("")

        for song in self.selected_plan.songs:
            results.append(f"🎵 {song.title}")
            if song.title in self.stem_matches:
                match = self.stem_matches[song.title]
                confidence_pct = int(match.match_confidence * 100)
                results.append(f"   ✓ Found {len(match.stems)} stems (confidence: {confidence_pct}%)")

                for stem in match.stems:
                    results.append(f"     • {stem.stem_type.title()}: {stem.filename}")

                if match.missing_stems:
                    results.append(f"     ⚠ Missing: {', '.join(match.missing_stems)}")
            else:
                results.append("   ✗ No stems found")
            results.append("")

        self.results_text.insert("0.0", "\n".join(results))

    def _generate_setlist(self):
        """Generate the Ableton Live setlist."""
        if not self.selected_plan or not self.stem_matches:
            messagebox.showwarning("Warning", "Please select a service plan with matched stems first.")
            return

        try:
            # Get service type name and plan date for proper naming
            service_type_name = self.selected_service_type.name if self.selected_service_type else "Service"
            service_date = self.selected_plan.date
            
            output_path = self.ableton_service.generate_setlist(
                service_type_name=service_type_name,
                service_date=service_date,
                stem_matches=self.stem_matches,
                plan_songs=self.selected_plan.songs
            )

            if output_path:
                messagebox.showinfo(
                    "Success",
                    f"Setlist generated successfully!\n\nSaved to: {output_path}"
                )
            else:
                messagebox.showerror("Error", "Failed to generate setlist.")

        except Exception as e:
            logger.error(f"Failed to generate setlist: {e}")
            messagebox.showerror("Error", f"Failed to generate setlist:\n{str(e)}")

    def _open_settings(self):
        """Open the settings dialog."""
        settings_window = SettingsDialog(self.root, self.config)
        self.root.wait_window(settings_window.dialog)
        
        # Reload folders after settings are potentially changed
        self._load_folders()

    def run(self):
        """Run the application main loop."""
        self.root.mainloop()


class SettingsDialog:
    """Settings dialog for configuring the application."""
    
    def __init__(self, parent, config: Config):
        """Initialize settings dialog.
        
        Args:
            parent: Parent window
            config: Application configuration to edit
        """
        self.config = config
        self.config_path = Path(__file__).parent.parent.parent.parent / "config" / "settings.json"
        
        # Create dialog window
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("Settings")
        self.dialog.geometry("700x750")
        self.dialog.resizable(True, True)
        
        # Make it modal
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the settings dialog widgets."""
        main_frame = ctk.CTkScrollableFrame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Title
        title = ctk.CTkLabel(
            main_frame,
            text="Application Settings",
            font=ctk.CTkFont(size=18, weight="bold")
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
        
        self.template_path_entry = self._create_file_field(
            ab_frame,
            "Template Path:",
            self.config.ableton.template_path,
            is_directory=False
        )
        
        self.output_folder_entry = self._create_file_field(
            ab_frame,
            "Output Folder:",
            self.config.ableton.output_folder,
            is_directory=True
        )
        
        self.version_entry = self._create_text_field(
            ab_frame,
            "Ableton Version:",
            self.config.ableton.version
        )
        
        # Action buttons
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(20, 0))
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save Settings",
            command=self._save_settings,
            fg_color="green",
            hover_color="dark green"
        )
        save_btn.pack(side="left", padx=(0, 10))
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self.dialog.destroy
        )
        cancel_btn.pack(side="left")
        
        test_btn = ctk.CTkButton(
            button_frame,
            text="Test Connection",
            command=self._test_connection
        )
        test_btn.pack(side="right")
    
    def _create_section(self, parent, title: str) -> ctk.CTkFrame:
        """Create a settings section with a title."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(15, 0))
        
        title_label = ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#4da6ff"
        )
        title_label.pack(anchor="w", pady=(0, 10))
        
        content_frame = ctk.CTkFrame(frame)
        content_frame.pack(fill="x", padx=15)
        
        return content_frame
    
    def _create_text_field(self, parent, label: str, value: str, show: str = None) -> ctk.CTkEntry:
        """Create a text input field."""
        label_widget = ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=11))
        label_widget.pack(anchor="w", pady=(0, 3))
        
        entry = ctk.CTkEntry(parent, show=show)
        entry.insert(0, value)
        entry.pack(fill="x", pady=(0, 12))
        
        return entry
    
    def _create_file_field(self, parent, label: str, value: str, is_directory: bool = False) -> ctk.CTkFrame:
        """Create a file/folder selection field."""
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", pady=(0, 12))
        
        label_widget = ctk.CTkLabel(container, text=label, font=ctk.CTkFont(size=11))
        label_widget.pack(anchor="w", pady=(0, 3))
        
        input_frame = ctk.CTkFrame(container)
        input_frame.pack(fill="x")
        
        entry = ctk.CTkEntry(input_frame)
        entry.insert(0, value)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        browse_btn = ctk.CTkButton(
            input_frame,
            text="Browse",
            width=80,
            command=lambda: self._browse_path(entry, is_directory)
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
    
    def _save_settings(self):
        """Save settings to configuration file."""
        try:
            # Update config objects with new values
            self.config.planning_center.application_id = self.pco_app_id_entry.get().strip()
            self.config.planning_center.secret = self.pco_secret_entry.get().strip()
            self.config.multitracks.stems_folder = self.stems_folder_entry.get().strip()
            self.config.ableton.template_path = self.template_path_entry.get().strip()
            self.config.ableton.output_folder = self.output_folder_entry.get().strip()
            self.config.ableton.version = self.version_entry.get().strip()
            
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
            
            if self.config.ableton.template_path and not Path(self.config.ableton.template_path).exists():
                messagebox.showwarning(
                    "Validation Error",
                    "Ableton template file does not exist."
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