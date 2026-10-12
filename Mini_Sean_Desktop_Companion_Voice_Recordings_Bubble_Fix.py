import tkinter as tk
from tkinter import simpledialog, messagebox, ttk
from PIL import Image, ImageTk
from pathlib import Path
import threading
import random
import time
import webbrowser
import urllib.parse
import winsound
import wave
import json
from datetime import datetime, timedelta

# -----------------------------
# SETTINGS
# -----------------------------

BASE_DIR = Path(__file__).resolve().parent
ASSET_DIR = BASE_DIR / "assets"
DANCE_ASSET_DIR = ASSET_DIR / "dance_break"
VOICE_DIR = BASE_DIR / "voice"
SETTINGS_FILE = BASE_DIR / "mini_sean_settings.json"

# Larger display
WINDOW_WIDTH = 390
WINDOW_HEIGHT = 435
CHARACTER_SIZE = 300

# Movement
WALK_SPEED = 3
ANIMATION_DELAY = 180

MIN_WAIT = 4000
MAX_WAIT = 11000

MIN_WALK = 1000
MAX_WALK = 3500

# Natural idle behavior
MIN_IDLE_BEHAVIOR_WAIT = 100
MAX_IDLE_BEHAVIOR_WAIT = 1000

# How slowly idle poses change
IDLE_POSE_MIN = 500
IDLE_POSE_MAX = 500

TRANSPARENT_COLOR = "#ff00ff"


# -----------------------------
# LOAD IMAGES
# -----------------------------

def load_image(filename):
    path = ASSET_DIR / filename

    if not path.exists():
        print(f"Missing image: {path}")
        return None

    try:
        image = Image.open(path).convert("RGBA")
        image.thumbnail((CHARACTER_SIZE, CHARACTER_SIZE))
        return ImageTk.PhotoImage(image)
    except Exception as error:
        print(f"Couldn't load {filename}: {error}")
        return None


def load_dance_images():
    """Load dance frames from assets/dance_break in filename order."""
    frames = []
    if not DANCE_ASSET_DIR.is_dir():
        print(f"Dance image folder not found yet: {DANCE_ASSET_DIR}")
        return frames

    supported_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
    for path in sorted(
        (item for item in DANCE_ASSET_DIR.iterdir()
         if item.is_file() and item.suffix.lower() in supported_extensions),
        key=lambda item: item.name.casefold(),
    ):
        try:
            with Image.open(path) as source:
                # If a GIF is used, use its first frame. For a dance animation,
                # numbered individual image files are recommended.
                source.seek(0)
                image = source.convert("RGBA")
                image.thumbnail((CHARACTER_SIZE, CHARACTER_SIZE))
                frames.append(ImageTk.PhotoImage(image))
        except Exception as error:
            print(f"Couldn't load dance image {path.name}: {error}")
    print(f"Loaded {len(frames)} dance frame(s) from {DANCE_ASSET_DIR}")
    return frames


def create_rounded_bubble(canvas, x1, y1, x2, y2, radius=15):
    """Draw a rounded rectangle with a white fill and black outline."""
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1
    ]

    return canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=24,
        fill="white",
        outline="black",
        width=2
    )

# -----------------------------
# MINI ME ASSISTANT
# -----------------------------

class MiniMe:

    def __init__(self, root):
        self.root = root

        self.root.title("Mini Me")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)

        try:
            self.root.wm_attributes(
                "-transparentcolor", TRANSPARENT_COLOR
            )
        except tk.TclError:
            print("Transparent background unavailable.")

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0
        )
        self.canvas.pack()

        # Load your existing eight images.
        self.images = {
            "idle_stand": load_image("idle_stand.png"),
            "idle_crouch": load_image("idle_crouch.png"),
            "talk_half": load_image("talk_half.png"),
            "talk_full": load_image("talk_full.png"),
            "walk_left": load_image("walk_left.png"),
            "walk_left_half": load_image("walk_left_half.png"),
            "walk_right": load_image("walk_right.png"),
            "walk_right_half": load_image("walk_right_half.png"),
        }

        self.animations = {
            "walk_right": [
                self.images[name]
                for name in ("walk_right", "walk_right_half")
                if self.images[name] is not None
            ],
            "walk_left": [
                self.images[name]
                for name in ("walk_left", "walk_left_half")
                if self.images[name] is not None
            ],
            "talk": [
                self.images[name]
                for name in ("talk_half", "talk_full")
                if self.images[name] is not None
            ],
        }

        # Keep separate idle poses so they don't alternate constantly.
        self.animations["idle_stand"] = (
            [self.images["idle_stand"]]
            if self.images["idle_stand"] is not None else []
        )

        self.animations["idle_crouch"] = (
            [self.images["idle_crouch"]]
            if self.images["idle_crouch"] is not None else []
        )

        if not any(self.animations.values()):
            messagebox.showerror(
                "No images found",
                "Put your PNG images inside the assets folder."
            )
            root.destroy()
            return

        # Fallbacks if an image is missing.
        if not self.animations["idle_stand"]:
            available = next(
                frames for frames in self.animations.values()
                if frames
            )
            self.animations["idle_stand"] = available

        if not self.animations["idle_crouch"]:
            self.animations["idle_crouch"] = (
                self.animations["idle_stand"]
            )

        for name in ("walk_left", "walk_right", "talk"):
            if not self.animations[name]:
                self.animations[name] = self.animations["idle_stand"]

        # Use custom dance images from assets/dance_break when provided.
        # If the folder is empty, fall back to the existing walking frames.
        self.dance_frames = load_dance_images()
        self.animations["dance"] = self.dance_frames or (
            self.animations["walk_right"] + self.animations["walk_left"]
        )

        # Screen and character position.
        self.screen_width = root.winfo_screenwidth()
        self.screen_height = root.winfo_screenheight()

        self.x = 100
        self.y = max(0, self.screen_height - WINDOW_HEIGHT - 35)

        self.direction = random.choice([-1, 1])
        self.walking = False
        self.auto_wander = True

        self.mode = "idle_stand"
        self.frame_index = 0
        self.walk_end_time = 0

        # A short dance uses the existing walk frames and a gentle side-to-side shuffle.
        self.dance_active = False
        self.dance_end_time = 0
        self.dance_origin_x = self.x
        self.dance_after_id = None

        self.behavior_after_id = None
        self.idle_pose_after_id = None

        self.speaking = threading.Event()
        self.current_text = ""

        # User preferences are saved beside this script.
        self.settings = self.load_settings()
        self.settings_window = None
        self.idle_reaction_after_id = None
        self.last_activity = time.monotonic()
        self.control_was_minimized = False

        # Character image, positioned in the larger window.
        self.character = self.canvas.create_image(
            WINDOW_WIDTH // 2,
            WINDOW_HEIGHT - 10,
            anchor="s"
        )

        # White speech bubble background

        self.bubble_bg = create_rounded_bubble(
            self.canvas,
            15, 8,
            WINDOW_WIDTH - 15, 65,
            radius=15
        )

        # Small triangular pointer at the bottom of the bubble
        self.bubble_tail = self.canvas.create_polygon(
            WINDOW_WIDTH // 2 - 8, 65,
            WINDOW_WIDTH // 2 + 8, 65,
            WINDOW_WIDTH // 2, 78,
            fill="white",
            outline="#333333"
        )

        # Speech text starts near the top; the bubble grows to fit it.
        self.bubble = self.canvas.create_text(
            WINDOW_WIDTH // 2,
            18,
            anchor="n",
            text="",
            width=WINDOW_WIDTH - 45,
            font=("Arial", 10),
            fill="black",
            justify="center"
        )

        # Hide the bubble when he isn't speaking
        self.canvas.itemconfigure(self.bubble_bg, state="hidden")
        self.canvas.itemconfigure(self.bubble_tail, state="hidden")
        self.canvas.itemconfigure(self.bubble, state="hidden")

        # Mouse controls.
        self.root.bind("<ButtonPress-1>", self.start_drag)
        self.root.bind("<B1-Motion>", self.drag)
        self.root.bind("<Double-Button-1>", self.ask_to_speak)

        # Keyboard controls.
        self.root.bind("<space>", self.toggle_walking)
        self.root.bind("<Escape>", self.quit)
        self.root.bind("q", self.quit)
        self.root.bind("<Button-3>", lambda event: self.show_control_window())
        self.root.bind("m", lambda event: self.show_control_window())
        # Activity detection is limited to Mini Sean's own app windows.
        self.root.bind_all("<KeyPress>", self.note_user_activity, add="+")
        self.root.bind_all("<ButtonPress>", self.note_user_activity, add="+")

        self.drag_start_x = 0
        self.drag_start_y = 0
        self.window_start_x = 0
        self.window_start_y = 0

        self.update_position()
        self.animate()

        # Start with a relaxed idle pose.
        self.schedule_idle_pose_change()
        self.schedule_next_behavior()
        self.reminder_jobs = []
        self.build_control_window()
        self.schedule_idle_reaction()

        # The startup greeting can be disabled in Settings.
        if self.settings.get("startup_greeting", True):
            self.root.after(
                1000,
                lambda: self.speak("Hey, I'm Mini Sean nice to see you.")
            )


    # -------------------------
    # MINI SEAN CONTROL WINDOW
    # -------------------------

    def build_control_window(self):
        """Create a decorated, vintage-inspired control panel."""
        self.control_window = tk.Toplevel(self.root)
        self.control_window.title("Mini Sean's Desktop Parlour")
        self.control_window.geometry("580x700")
        self.control_window.minsize(520, 620)
        self.control_window.configure(bg="#e8dcc2")
        self.control_window.protocol("WM_DELETE_WINDOW", self.hide_control_window)

        # Warm, old-fashioned palette: parchment, ink, and burgundy.
        parchment = "#e8dcc2"
        paper_light = "#f5eddb"
        ink = "#35271f"
        muted_ink = "#6c5947"
        burgundy = "#743b3b"
        burgundy_dark = "#542929"
        brass = "#b08a48"

        style = ttk.Style(self.control_window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Vintage.TFrame", background=parchment)
        style.configure("Paper.TFrame", background=paper_light)
        style.configure(
            "Vintage.TLabel", background=parchment, foreground=ink,
            font=("Georgia", 10)
        )
        style.configure(
            "SmallVintage.TLabel", background=parchment, foreground=muted_ink,
            font=("Georgia", 9)
        )
        style.configure(
            "SectionVintage.TLabel", background=parchment, foreground=burgundy,
            font=("Georgia", 12, "bold")
        )
        style.configure(
            "Vintage.TButton", font=("Georgia", 10), padding=(9, 7),
            background=paper_light, foreground=ink, borderwidth=1,
            relief="raised"
        )
        style.map(
            "Vintage.TButton",
            background=[("active", "#e0cda9"), ("pressed", burgundy)],
            foreground=[("pressed", "#fff6e5"), ("active", ink)]
        )
        style.configure(
            "AccentVintage.TButton", font=("Georgia", 10, "bold"),
            padding=(9, 7), background=burgundy, foreground="#fff6e5",
            borderwidth=1, relief="raised"
        )
        style.map(
            "AccentVintage.TButton",
            background=[("active", burgundy_dark), ("pressed", burgundy_dark)],
            foreground=[("active", "#fff6e5"), ("pressed", "#fff6e5")]
        )
        style.configure("Vintage.TSeparator", background=brass)

        outer = ttk.Frame(self.control_window, style="Vintage.TFrame", padding=14)
        outer.pack(fill="both", expand=True)

        # Decorative masthead.
        masthead = tk.Frame(
            outer, bg=ink, highlightbackground=brass,
            highlightthickness=2, padx=14, pady=12
        )
        masthead.pack(fill="x", pady=(0, 12))
        tk.Label(
            masthead, text="MINI SEAN", bg=ink, fg="#f5e7c8",
            font=("Georgia", 23, "bold")
        ).pack(anchor="w")
        tk.Label(
            masthead, text="THE LITTLE DESKTOP COMPANION",
            bg=ink, fg="#d4b879", font=("Georgia", 9, "italic")
        ).pack(anchor="w", pady=(2, 0))

        ttk.Label(
            outer, text="Good day! What shall we do?",
            style="SmallVintage.TLabel"
        ).pack(anchor="w", pady=(0, 10))

        ttk.Label(outer, text="PARLOUR & ENTERTAINMENT", style="SectionVintage.TLabel").pack(anchor="w", pady=(0, 5))
        quick = ttk.Frame(outer, style="Vintage.TFrame")
        quick.pack(fill="x")
        for label, command in [
            ("Say something", self.ask_to_speak),
            ("Tell me a joke", self.tell_joke),
            ("Amazing fact", self.tell_fact),
            ("Read a short story", self.tell_story),
            ("Mini Sean's song", self.sing_song),
        ]:
            ttk.Button(quick, text=label, command=command, style="Vintage.TButton").pack(fill="x", pady=2)

        ttk.Separator(outer, style="Vintage.TSeparator").pack(fill="x", pady=10)
        ttk.Label(outer, text="DESKTOP CONTROLS", style="SectionVintage.TLabel").pack(anchor="w", pady=(0, 5))
        controls = ttk.Frame(outer, style="Vintage.TFrame")
        controls.pack(fill="x")
        ttk.Button(controls, text="Pause / resume wandering", command=self.toggle_walking, style="Vintage.TButton").grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=2)
        ttk.Button(controls, text="Show character", command=self.show_character, style="Vintage.TButton").grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=2)
        ttk.Button(
            controls, text="Make Mini Sean dance!", command=self.start_dance,
            style="Vintage.TButton"
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(
            controls, text="Settings & reactions", command=self.open_settings_window,
            style="AccentVintage.TButton"
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(
            controls, text="Exit Mini Sean", command=self.quit,
            style="AccentVintage.TButton"
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        ttk.Separator(outer, style="Vintage.TSeparator").pack(fill="x", pady=10)
        ttk.Label(outer, text="USEFUL DESK TOOLS", style="SectionVintage.TLabel").pack(anchor="w", pady=(0, 5))
        tools = ttk.Frame(outer, style="Vintage.TFrame")
        tools.pack(fill="x")
        tool_buttons = [
            ("Web search", self.web_search),
            ("Search the news", self.open_news),
            ("Compare prices", self.compare_prices),
            ("Calendar / reminder", self.add_reminder),
            ("Open Downloads folder", self.open_downloads),
            ("Email shortcut", self.email_shortcut),
        ]
        for i, (label, command) in enumerate(tool_buttons):
            ttk.Button(tools, text=label, command=command, style="Vintage.TButton").grid(
                row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3
            )
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="Privacy: activity reactions only notice input and window events inside Mini Sean. He does not monitor other apps or collect browsing data.",
            wraplength=510, style="SmallVintage.TLabel"
        ).pack(anchor="w", pady=(12, 8))

        bottom = ttk.Frame(outer, style="Vintage.TFrame")
        bottom.pack(fill="x", pady=(4, 0))
        ttk.Button(bottom, text="Hide this window", command=self.hide_control_window, style="Vintage.TButton").pack(side="left")
        ttk.Button(bottom, text="Quit Mini Sean", command=self.quit, style="AccentVintage.TButton").pack(side="right")

        self.control_window.bind("<Unmap>", self.on_control_window_unmap, add="+")
        self.control_window.bind("<Map>", self.on_control_window_map, add="+")

    # -------------------------
    # SETTINGS AND DESKTOP REACTIONS
    # -------------------------

    def load_settings(self):
        defaults = {
            "startup_greeting": True,
            "muted": False,
            "idle_chatter": False,
            "window_reactions": True,
            "idle_minutes": 5,
            "voice_speed_percent": 100,
            "letter_pause_ms": 5,
            "word_pause_ms": 80,
        }
        try:
            if SETTINGS_FILE.is_file():
                with SETTINGS_FILE.open("r", encoding="utf-8") as file:
                    saved = json.load(file)
                for key in defaults:
                    if key in saved:
                        defaults[key] = saved[key]
        except (OSError, json.JSONDecodeError, TypeError) as error:
            print(f"Could not load Mini Sean settings: {error}")
        defaults["idle_minutes"] = max(1, min(30, int(defaults["idle_minutes"])))
        defaults["voice_speed_percent"] = max(75, min(175, int(defaults["voice_speed_percent"])))
        defaults["letter_pause_ms"] = max(0, min(100, int(defaults["letter_pause_ms"])))
        defaults["word_pause_ms"] = max(0, min(500, int(defaults["word_pause_ms"])))
        return defaults

    def save_settings(self):
        try:
            with SETTINGS_FILE.open("w", encoding="utf-8") as file:
                json.dump(self.settings, file, indent=2)
        except OSError as error:
            messagebox.showerror(
                "Could not save settings", str(error), parent=self.control_window
            )

    def open_settings_window(self):
        if self.settings_window is not None:
            try:
                if self.settings_window.winfo_exists():
                    self.settings_window.deiconify()
                    self.settings_window.lift()
                    return
            except tk.TclError:
                pass

        window = tk.Toplevel(self.control_window)
        self.settings_window = window
        window.title("Mini Sean Settings & Reactions")
        window.geometry("500x760")
        window.minsize(460, 680)
        window.configure(bg="#e8dcc2")
        window.transient(self.control_window)
        window.protocol("WM_DELETE_WINDOW", self.close_settings_window)

        parchment = "#e8dcc2"
        ink = "#35271f"
        burgundy = "#743b3b"
        paper = "#f5eddb"

        tk.Label(
            window, text="SETTINGS & REACTIONS", bg=ink, fg="#f5e7c8",
            font=("Georgia", 17, "bold"), padx=12, pady=12
        ).pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(
            window,
            text="Choose how Mini Sean behaves. Changes are saved on this computer.",
            bg=parchment, fg=ink, wraplength=390, justify="left",
            font=("Georgia", 10)
        ).pack(anchor="w", padx=16, pady=(0, 10))

        self.startup_var = tk.BooleanVar(value=self.settings["startup_greeting"])
        self.muted_var = tk.BooleanVar(value=self.settings["muted"])
        self.idle_chatter_var = tk.BooleanVar(value=self.settings["idle_chatter"])
        self.window_reactions_var = tk.BooleanVar(value=self.settings["window_reactions"])
        self.idle_minutes_var = tk.IntVar(value=self.settings["idle_minutes"])
        self.voice_speed_var = tk.IntVar(value=self.settings["voice_speed_percent"])
        self.letter_pause_var = tk.IntVar(value=self.settings["letter_pause_ms"])
        self.word_pause_var = tk.IntVar(value=self.settings["word_pause_ms"])

        # Scrollable settings area with a fixed footer, so the save controls
        # remain visible even when Windows display scaling is large.
        options_area = tk.Frame(window, bg=parchment)
        options_area.pack(fill="both", expand=True, padx=16)
        options_canvas = tk.Canvas(
            options_area, bg=parchment, highlightthickness=0, borderwidth=0
        )
        options_scrollbar = ttk.Scrollbar(
            options_area, orient="vertical", command=options_canvas.yview
        )
        options_canvas.configure(yscrollcommand=options_scrollbar.set)
        options_scrollbar.pack(side="right", fill="y")
        options_canvas.pack(side="left", fill="both", expand=True)
        options = tk.Frame(options_canvas, bg=parchment)
        options_window_id = options_canvas.create_window(
            (0, 0), window=options, anchor="nw"
        )

        def update_settings_scroll_region(event=None):
            options_canvas.configure(scrollregion=options_canvas.bbox("all"))
            options_canvas.itemconfigure(
                options_window_id, width=options_canvas.winfo_width()
            )

        options.bind("<Configure>", update_settings_scroll_region)
        options_canvas.bind("<Configure>", update_settings_scroll_region)

        for label, variable in [
            ("Speak a greeting when Mini Sean starts", self.startup_var),
            ("Mute Mini Sean's voice", self.muted_var),
            ("Make a comment after I am idle", self.idle_chatter_var),
            ("React when the control window is minimized/restored", self.window_reactions_var),
        ]:
            tk.Checkbutton(
                options, text=label, variable=variable, bg=parchment, fg=ink,
                activebackground=parchment, selectcolor=paper,
                font=("Georgia", 10), wraplength=390, justify="left"
            ).pack(anchor="w", pady=5)

        tk.Label(options, text="Idle time before a comment (minutes)", bg=parchment,
                 fg=burgundy, font=("Georgia", 10, "bold")).pack(anchor="w", pady=(12, 0))
        tk.Scale(options, from_=1, to=30, orient="horizontal", variable=self.idle_minutes_var,
                 bg=parchment, fg=ink, highlightthickness=0, troughcolor=paper,
                 activebackground=burgundy, length=360).pack(anchor="w", fill="x")

        tk.Label(options, text="Recorded-letter voice speed (100% = original)", bg=parchment,
                 fg=burgundy, font=("Georgia", 10, "bold")).pack(anchor="w", pady=(8, 0))
        tk.Scale(options, from_=75, to=175, orient="horizontal", variable=self.voice_speed_var,
                 bg=parchment, fg=ink, highlightthickness=0, troughcolor=paper,
                 activebackground=burgundy, length=360).pack(anchor="w", fill="x")

        tk.Label(options, text="Pause between letters (milliseconds)", bg=parchment,
                 fg=burgundy, font=("Georgia", 10, "bold")).pack(anchor="w", pady=(8, 0))
        tk.Scale(options, from_=0, to=100, orient="horizontal", variable=self.letter_pause_var,
                 bg=parchment, fg=ink, highlightthickness=0, troughcolor=paper,
                 activebackground=burgundy, length=360).pack(anchor="w", fill="x")

        tk.Label(options, text="Pause at spaces between words (milliseconds)", bg=parchment,
                 fg=burgundy, font=("Georgia", 10, "bold")).pack(anchor="w", pady=(8, 0))
        tk.Scale(options, from_=0, to=500, orient="horizontal", variable=self.word_pause_var,
                 bg=parchment, fg=ink, highlightthickness=0, troughcolor=paper,
                 activebackground=burgundy, length=360).pack(anchor="w", fill="x")

        buttons = tk.Frame(window, bg=parchment)
        buttons.pack(fill="x", padx=16, pady=(8, 14))
        self.settings_status = tk.Label(
            buttons, text="Auto-save is on.",
            bg=parchment, fg="#6c5947", font=("Georgia", 8),
            wraplength=140, justify="left"
        )
        self.settings_status.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Button(
            buttons, text="Save & Close", command=self.close_settings_window,
            bg=burgundy, fg="white", activebackground="#542929",
            font=("Georgia", 10, "bold"), padx=10, pady=7
        ).pack(side="right")
        tk.Button(
            buttons, text="Save now", command=self.apply_settings,
            bg=paper, fg=ink, font=("Georgia", 10), padx=10, pady=7
        ).pack(side="right", padx=(0, 8))

        # Save instantly when a checkbox or slider changes, without needing
        # the user to find a button. Closing the window also saves once more.
        for variable in (
            self.startup_var, self.muted_var, self.idle_chatter_var,
            self.window_reactions_var, self.idle_minutes_var,
            self.voice_speed_var, self.letter_pause_var, self.word_pause_var,
        ):
            variable.trace_add("write", self.auto_save_settings)

    def close_settings_window(self):
        """Save any changes automatically when the settings window is closed."""
        try:
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.apply_settings()
                self.settings_window.withdraw()
        except (tk.TclError, AttributeError):
            pass

    def auto_save_settings(self, *args):
        """Persist settings whenever a checkbox or slider is changed."""
        try:
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.apply_settings(show_feedback=False)
        except tk.TclError:
            pass

    def apply_settings(self, show_feedback=True):
        self.settings.update({
            "startup_greeting": bool(self.startup_var.get()),
            "muted": bool(self.muted_var.get()),
            "idle_chatter": bool(self.idle_chatter_var.get()),
            "window_reactions": bool(self.window_reactions_var.get()),
            "idle_minutes": int(self.idle_minutes_var.get()),
            "voice_speed_percent": int(self.voice_speed_var.get()),
            "letter_pause_ms": int(self.letter_pause_var.get()),
            "word_pause_ms": int(self.word_pause_var.get()),
        })
        self.save_settings()
        try:
            if hasattr(self, "settings_status") and self.settings_status.winfo_exists():
                self.settings_status.configure(
                    text="Settings saved!" if show_feedback else "Auto-saved."
                )
        except tk.TclError:
            pass
        self.last_activity = time.monotonic()
        self.schedule_idle_reaction()
        if show_feedback:
            try:
                self.settings_window.bell()
            except (tk.TclError, AttributeError):
                pass

    def note_user_activity(self, event=None):
        self.last_activity = time.monotonic()
        self.schedule_idle_reaction()

    def schedule_idle_reaction(self):
        if self.idle_reaction_after_id is not None:
            try:
                self.root.after_cancel(self.idle_reaction_after_id)
            except tk.TclError:
                pass
            self.idle_reaction_after_id = None
        if self.settings.get("idle_chatter", False):
            delay = int(self.settings.get("idle_minutes", 5)) * 60 * 1000
            self.idle_reaction_after_id = self.root.after(delay, self.check_idle_reaction)

    def check_idle_reaction(self):
        self.idle_reaction_after_id = None
        if not self.root.winfo_exists() or not self.settings.get("idle_chatter", False):
            return
        idle_seconds = time.monotonic() - self.last_activity
        required_seconds = int(self.settings.get("idle_minutes", 5)) * 60
        if idle_seconds >= required_seconds and not self.speaking.is_set():
            # Record this line as voice/idle_talk.wav for a dedicated idle voice.
            self.speak_event("Just checking in. I'm still here.", "idle_talk.wav")
        self.schedule_idle_reaction()

    def on_control_window_unmap(self, event=None):
        try:
            minimized = self.control_window.state() == "iconic"
        except tk.TclError:
            minimized = False
        if minimized and not self.control_was_minimized:
            self.control_was_minimized = True
            if self.settings.get("window_reactions", True):
                self.react_to_window_event(
                    "I'll be here when you need me.", "closing_window_talk.wav"
                )

    def on_control_window_map(self, event=None):
        if self.control_was_minimized:
            self.control_was_minimized = False
            if self.settings.get("window_reactions", True):
                self.react_to_window_event(
                    "Welcome back to my control panel.", "welcome_back.wav"
                )

    def react_to_window_event(self, comment, filename=None):
        if self.speaking.is_set():
            return
        if filename:
            self.speak_event(comment, filename)
        else:
            self.speak_text_from_letters(comment)

    def show_control_window(self):
        try:
            if not self.control_window.winfo_exists():
                self.build_control_window()
            self.control_window.deiconify()
            self.control_window.lift()
            self.control_window.focus_force()
        except tk.TclError:
            pass

    def hide_control_window(self):
        try:
            self.control_window.withdraw()
            if self.settings.get("window_reactions", True):
                self.react_to_window_event(
                    "I'll be here when you need me.", "closing_window_talk.wav"
                )
        except tk.TclError:
            pass

    def show_character(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def tell_joke(self):
        jokes = [
            "Why did the computer go to the doctor? It had a virus. Don't worry, I'm not one!",
            "Why was the computer cold? It left its Windows open.",
            "I tried to make a belt out of watches. It was a waist of time.",
            "Why did the keyboard need a break? It was working too many shifts.",
        ]
        joke = random.choice(jokes)
        joke_recordings = {
            jokes[0]: "joke_1.wav",
            jokes[1]: "joke_2.wav",
            jokes[2]: "joke_3.wav",
            jokes[3]: "joke_4.wav",
        }
        self.speak_sequence([
            ("Here's a joke for you.", "joke_intro.wav"),
            (joke, joke_recordings[joke]),
        ])

    def tell_fact(self):
        facts = [
            "Octopuses have three hearts.",
            "A day on Venus is longer than its year.",
            "Honey can remain edible for a very long time when sealed and stored properly.",
            "Wombat droppings are cube-shaped.",
            "The Eiffel Tower can become a little taller in hot weather because metal expands.",
        ]
        fact = random.choice(facts)
        fact_recordings = {
            facts[0]: "fact_1.wav",
            facts[1]: "fact_2.wav",
            facts[2]: "fact_3.wav",
            facts[3]: "fact_4.wav",
            facts[4]: "fact_5.wav",
        }
        self.speak_sequence([
            ("Here's a fun fact.", "fact_intro.wav"),
            (fact, fact_recordings[fact]),
        ])

    def tell_story(self):
        story = (
            "Once upon a time, a tiny desktop companion named Mini Sean decided to explore the screen. "
            "He walked past the clock, waved at the taskbar, and discovered a forgotten folder full of old projects. "
            "Instead of opening everything at once, he asked first. The folder contained a drawing, a silly joke, "
            "and a note that said: the best adventures are the ones you choose yourself. The end."
        )
        self.speak_sequence([
            ("Let me tell you a short story.", "story_intro.wav"),
            (story, "story.wav"),
        ])

    def speak_sequence(self, parts):
        """Play a sequence of prerecorded lines, showing each line in the bubble.

        Expected intro recordings in the voice folder:
        joke_intro.wav, fact_intro.wav, and story_intro.wav.
        If an intro recording is missing, that intro is skipped and the main
        recording still plays.
        """
        if self.speaking.is_set():
            return

        self.speaking.set()

        def speech_worker():
            try:
                for line, filename in parts:
                    audio_file = VOICE_DIR / filename

                    # Windows may hide extensions, and files copied from other
                    # systems can have different capitalization or stray spaces.
                    # Try a case-insensitive filename match before skipping a clip.
                    if not audio_file.is_file() and VOICE_DIR.is_dir():
                        wanted = filename.strip().casefold()
                        try:
                            match = next(
                                (candidate for candidate in VOICE_DIR.iterdir()
                                 if candidate.is_file() and candidate.name.strip().casefold() == wanted),
                                None
                            )
                            if match is not None:
                                audio_file = match
                        except OSError as error:
                            print(f"Could not inspect voice folder {VOICE_DIR}: {error}")

                    if not audio_file.is_file():
                        print(f"Recording not found: {audio_file}")
                        print(f"Mini Sean looked in: {VOICE_DIR.resolve()}")
                        # Continue to the joke/fact/story even if an intro is missing.
                        continue

                    self.current_text = line
                    print(f"Playing recording: {audio_file.name}")
                    winsound.PlaySound(str(audio_file), winsound.SND_FILENAME)
            except Exception as error:
                print("Audio playback error:", error)
            finally:
                self.speaking.clear()

        threading.Thread(target=speech_worker, daemon=True).start()

    def sing_song(self):
        # Original jingle, spoken by the installed text-to-speech voice.
        self.speak("Mini Sean's little song! Hello hello, I'm here today. A tiny friend to brighten your day. I'll take a stroll, then stop and say: have a great and happy day!")

    def web_search(self):
        query = simpledialog.askstring("Web search", "What would you like to search for?", parent=self.control_window)
        if query and query.strip():
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query.strip()))

    def open_news(self):
        webbrowser.open("https://news.google.com/")

    def compare_prices(self):
        query = simpledialog.askstring("Compare prices", "What product would you like to compare prices for?", parent=self.control_window)
        if query and query.strip():
            search = query.strip() + " price comparison"
            webbrowser.open("https://www.google.com/search?tbm=shop&q=" + urllib.parse.quote_plus(search))

    def add_reminder(self):
        description = simpledialog.askstring("New reminder", "What should I remind you about?", parent=self.control_window)
        if not description or not description.strip():
            return
        when_text = simpledialog.askstring(
            "Reminder time",
            "When? Enter a number of minutes from now (for example, 15).",
            parent=self.control_window
        )
        if not when_text:
            return
        try:
            minutes = int(when_text.strip())
            if minutes < 1 or minutes > 10080:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid time", "Please enter a whole number from 1 to 10080 minutes.", parent=self.control_window)
            return
        self.root.after(minutes * 60 * 1000, lambda msg=description.strip(): self.reminder_alert(msg))
        due = datetime.now() + timedelta(minutes=minutes)
        self.speak(f"Okay, I'll remind you about {description.strip()} in {minutes} minutes.")
        messagebox.showinfo("Reminder set", f"{description.strip()}\n\nReminder time: {due.strftime('%I:%M %p')}", parent=self.control_window)

    def reminder_alert(self, description):
        try:
            messagebox.showinfo("Mini Sean reminder", description, parent=self.control_window)
            self.speak("Reminder! " + description)
        except tk.TclError:
            pass

    def open_downloads(self):
        import os
        import subprocess
        import sys
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(downloads))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(downloads)])
            else:
                subprocess.Popen(["xdg-open", str(downloads)])
        except Exception as error:
            messagebox.showerror("Could not open Downloads", str(error), parent=self.control_window)

    def email_shortcut(self):
        recipient = simpledialog.askstring("Email shortcut", "Recipient email address (optional):", parent=self.control_window)
        subject = simpledialog.askstring("Email shortcut", "Email subject (optional):", parent=self.control_window)
        mailto = "mailto:" + urllib.parse.quote(recipient.strip() if recipient else "")
        if subject and subject.strip():
            mailto += "?subject=" + urllib.parse.quote(subject.strip())
        webbrowser.open(mailto)

    # -------------------------
    # WINDOW POSITION
    # -------------------------

    def update_position(self):
        self.root.geometry(
            f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}"
            f"+{int(self.x)}+{int(self.y)}"
        )

    def start_drag(self, event):
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.window_start_x = self.x
        self.window_start_y = self.y

    def drag(self, event):
        self.x = (
            self.window_start_x
            + event.x_root - self.drag_start_x
        )
        self.y = (
            self.window_start_y
            + event.y_root - self.drag_start_y
        )

        self.x = max(
            0, min(self.x, self.screen_width - WINDOW_WIDTH)
        )
        self.y = max(
            0, min(self.y, self.screen_height - WINDOW_HEIGHT)
        )

        self.update_position()

    # -------------------------
    # IDLE PERSONALITY
    # -------------------------

    def cancel_behavior_timer(self):
        if self.behavior_after_id is not None:
            try:
                self.root.after_cancel(self.behavior_after_id)
            except tk.TclError:
                pass

            self.behavior_after_id = None

    def cancel_idle_pose_timer(self):
        if self.idle_pose_after_id is not None:
            try:
                self.root.after_cancel(self.idle_pose_after_id)
            except tk.TclError:
                pass

            self.idle_pose_after_id = None

    def schedule_next_behavior(self):
        if not self.auto_wander:
            return

        self.cancel_behavior_timer()

        wait_time = random.randint(
            MIN_IDLE_BEHAVIOR_WAIT,
            MAX_IDLE_BEHAVIOR_WAIT
        )

        self.behavior_after_id = self.root.after(
            wait_time,
            self.choose_behavior
        )

    def choose_behavior(self):
        self.behavior_after_id = None

        if not self.auto_wander or not self.root.winfo_exists():
            return

        if self.speaking.is_set():
            self.schedule_next_behavior()
            return

        # Weighted choices: standing is common, walking less so.
        behavior = random.choices(
            ["stand", "crouch", "look", "walk"],
            weights=[40, 25, 15, 20],
            k=1
        )[0]

        if behavior == "stand":
            self.mode = "idle_stand"
            self.schedule_next_behavior()

        elif behavior == "crouch":
            self.mode = "idle_crouch"

            # Stay crouched for a while, then stand back up.
            duration = random.randint(2500, 5000)
            self.behavior_after_id = self.root.after(
                duration,
                self.finish_idle_behavior
            )

        elif behavior == "look":
            # Briefly face a direction without moving.
            self.direction = random.choice([-1, 1])
            self.mode = (
                "walk_right" if self.direction == 1
                else "walk_left"
            )

            duration = random.randint(600, 1300)
            self.behavior_after_id = self.root.after(
                duration,
                self.finish_idle_behavior
            )

        elif behavior == "walk":
            # Sometimes hesitate before starting to walk.
            if random.random() < 0.30:
                self.direction = random.choice([-1, 1])
                self.mode = "idle_stand"

                self.behavior_after_id = self.root.after(
                    random.randint(500, 1400),
                    self.start_random_walk
                )
            else:
                self.start_random_walk()

    def finish_idle_behavior(self):
        self.behavior_after_id = None

        if not self.auto_wander:
            return

        self.mode = "idle_stand"
        self.schedule_next_behavior()

    def schedule_idle_pose_change(self):
        if not self.root.winfo_exists():
            return

        duration = random.randint(
            IDLE_POSE_MIN,
            IDLE_POSE_MAX
        )

        self.idle_pose_after_id = self.root.after(
            duration,
            self.change_idle_pose
        )

    def change_idle_pose(self):
        self.idle_pose_after_id = None

        if not self.root.winfo_exists():
            return

        # Alternate standing and crouching every 0.5 seconds
        if (
                not self.walking
                and not self.speaking.is_set()
                and self.mode in ("idle_stand", "idle_crouch")
        ):
            if self.mode == "idle_stand":
                self.mode = "idle_crouch"
            else:
                self.mode = "idle_stand"

        self.schedule_idle_pose_change()

    # -------------------------
    # RANDOM WALKING
    # -------------------------

    def start_random_walk(self):
        self.behavior_after_id = None

        if not self.auto_wander or not self.root.winfo_exists():
            return

        if self.speaking.is_set():
            self.schedule_next_behavior()
            return

        self.direction = random.choice([-1, 1])
        self.walking = True

        duration = random.randint(MIN_WALK, MAX_WALK)
        self.walk_end_time = time.monotonic() + duration / 1000

    # -------------------------
    # ANIMATION
    # -------------------------

    def animate(self):
        if not self.root.winfo_exists():
            return

        # Talking takes priority; otherwise the dance temporarily takes priority
        # over wandering and idle poses.
        if self.speaking.is_set() and not self.dance_active:
            self.mode = "talk"
        elif self.dance_active:
            if time.monotonic() >= self.dance_end_time:
                self.finish_dance()
            else:
                # Alternate walk frames and shuffle a few pixels left/right.
                dance_phase = (self.frame_index // 3) % 4
                dance_offsets = (0, -10, 0, 10)
                self.x = max(0, min(
                    self.dance_origin_x + dance_offsets[dance_phase],
                    self.screen_width - WINDOW_WIDTH
                ))
                self.direction = 1 if dance_phase in (0, 1) else -1
                self.mode = "dance"
                self.update_position()
        else:
            # Return to a normal pose after speech finishes.
            if self.mode == "talk":
                self.mode = "idle_stand"

            # Move only while automatic wandering is enabled.
            if self.walking and self.auto_wander:
                if time.monotonic() >= self.walk_end_time:
                    self.walking = False
                    self.mode = "idle_stand"
                    self.schedule_next_behavior()
                else:
                    self.mode = (
                        "walk_right" if self.direction == 1
                        else "walk_left"
                    )

                    self.x += WALK_SPEED * self.direction

                    # Turn around at the desktop edges.
                    if self.x >= self.screen_width - WINDOW_WIDTH:
                        self.x = self.screen_width - WINDOW_WIDTH
                        self.direction = -1
                    elif self.x <= 0:
                        self.x = 0
                        self.direction = 1

                    self.update_position()

        # Show the current animation frame.
        frames = self.animations.get(self.mode, [])
        if frames:
            frame = frames[self.frame_index % len(frames)]
            self.canvas.itemconfigure(self.character, image=frame)

            if self.mode in ("idle_stand", "idle_crouch"):
                frame_delay = 100
            else:
                frame_delay = ANIMATION_DELAY

            self.frame_index += 1
        else:
            frame_delay = ANIMATION_DELAY

        # Display the speech bubble only while Mini Sean is speaking.
        # Measure the wrapped text and resize the bubble so long stories stay
        # inside it instead of spilling into the transparent/purple area.
        if self.speaking.is_set():
            self.canvas.itemconfigure(
                self.bubble, state="normal", text=self.current_text
            )
            text_bounds = self.canvas.bbox(self.bubble)
            if text_bounds:
                bubble_bottom = max(65, text_bounds[3] + 10)
            else:
                bubble_bottom = 65
            # Leave space for Mini Sean below the bubble.
            bubble_bottom = min(bubble_bottom, WINDOW_HEIGHT - 105)

            x1, y1, x2 = 15, 8, WINDOW_WIDTH - 15
            radius = 15
            points = [
                x1 + radius, y1, x2 - radius, y1,
                x2, y1, x2, y1 + radius,
                x2, bubble_bottom - radius, x2, bubble_bottom,
                x2 - radius, bubble_bottom, x1 + radius, bubble_bottom,
                x1, bubble_bottom, x1, bubble_bottom - radius,
                x1, y1 + radius, x1, y1
            ]
            self.canvas.coords(self.bubble_bg, *points)
            self.canvas.coords(
                self.bubble_tail,
                WINDOW_WIDTH // 2 - 8, bubble_bottom,
                WINDOW_WIDTH // 2 + 8, bubble_bottom,
                WINDOW_WIDTH // 2, bubble_bottom + 13
            )
            self.canvas.itemconfigure(self.bubble_bg, state="normal")
            self.canvas.itemconfigure(self.bubble_tail, state="normal")
        else:
            self.canvas.itemconfigure(self.bubble_bg, state="hidden")
            self.canvas.itemconfigure(self.bubble_tail, state="hidden")
            self.canvas.itemconfigure(self.bubble, state="hidden", text="")

        # Schedule the next animation frame. Do not call animate() directly.
        self.root.after(frame_delay, self.animate)

    # -------------------------
    # TEXT TO SPEECH
    # -------------------------

    def ask_to_speak(self, event=None):
        text = simpledialog.askstring(
            "Talk to Mini Sean",
            "What should Mini Sean say? He will spell it using your recorded letters.",
            parent=self.root
        )

        if text and text.strip():
            self.speak_text_from_letters(text.strip())

    def speak_text_from_letters(self, text):
        """Spell typed text using the user's own recorded letter clips.

        Put recordings in voice/letters/a.wav through z.wav. Optional number
        recordings can be named 0.wav through 9.wav in the same folder.
        A clip may also be placed directly in voice/ as a fallback.
        Spaces and punctuation create pauses instead of being spoken aloud.
        """
        if self.speaking.is_set() or self.settings.get("muted", False):
            return

        self.current_text = text
        self.speaking.set()
        letters_dir = VOICE_DIR / "letters"

        def find_clip(character):
            filename = f"{character.lower()}.wav"
            # Prefer the organized letters subfolder.
            for folder in (letters_dir, VOICE_DIR):
                direct = folder / filename
                if direct.is_file():
                    return direct
                # Also tolerate uppercase filenames or extra spaces.
                if folder.is_dir():
                    try:
                        wanted = filename.casefold()
                        for candidate in folder.iterdir():
                            if candidate.is_file() and candidate.name.strip().casefold() == wanted:
                                return candidate
                    except OSError as error:
                        print(f"Could not inspect {folder}: {error}")
            return None

        def make_faster_clip(audio_file, speed=None):
            """Cache a WAV adjusted to the selected playback speed."""
            if speed is None:
                speed = self.settings.get("voice_speed_percent", 100) / 100.0
            cache_dir = letters_dir / f".speed_cache_{int(round(speed * 100))}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_file = cache_dir / audio_file.name
            try:
                if cached_file.is_file() and cached_file.stat().st_mtime >= audio_file.stat().st_mtime:
                    return cached_file
                with wave.open(str(audio_file), "rb") as source:
                    params = source.getparams()
                    frames = source.readframes(source.getnframes())
                with wave.open(str(cached_file), "wb") as target:
                    target.setnchannels(params.nchannels)
                    target.setsampwidth(params.sampwidth)
                    target.setframerate(max(1, int(params.framerate * speed)))
                    target.setcomptype(params.comptype, params.compname)
                    target.writeframes(frames)
                return cached_file
            except (wave.Error, OSError, ValueError) as error:
                print(f"Could not speed up {audio_file.name}; playing original: {error}")
                return audio_file

        def speech_worker():
            try:
                for character in text:
                    if character.isspace():
                        time.sleep(self.settings.get("word_pause_ms", 80) / 1000.0)
                        continue

                    if character.isalnum():
                        audio_file = find_clip(character)
                        if audio_file is None:
                            print(f"Missing recording for {character!r}. Expected: {letters_dir / (character.lower() + '.wav')}")
                            continue
                        faster_clip = make_faster_clip(audio_file)
                        print(f"Playing character recording at about {self.settings.get('voice_speed_percent', 100)}% speed: {audio_file.name}")
                        winsound.PlaySound(str(faster_clip), winsound.SND_FILENAME)
                        time.sleep(self.settings.get("letter_pause_ms", 5) / 1000.0)
                    elif character in ",;:":
                        time.sleep(0.12)
                    elif character in ".!?":
                        time.sleep(0.20)
                    else:
                        # Other punctuation (quotes, apostrophes, hyphens, etc.)
                        # is not spoken, but a tiny pause keeps words separated.
                        time.sleep(0.04)
            except Exception as error:
                print("Custom letter playback error:", error)
            finally:
                self.speaking.clear()

        threading.Thread(target=speech_worker, daemon=True).start()

    def speak_event(self, text, filename):
        """Play a dedicated voice recording for a special Mini Sean event.

        Place the WAV file directly in the voice folder. If it is missing,
        fall back to the recorded-letter voice so the event still has audio.
        """
        if self.speaking.is_set() or self.settings.get("muted", False):
            return
        audio_file = VOICE_DIR / filename
        if not audio_file.is_file():
            print(f"Special-event recording not found: {audio_file}")
            print(f"Add {filename} to the voice folder; using letter recordings for now.")
            self.speak_text_from_letters(text)
            return

        self.current_text = text
        self.speaking.set()

        def speech_worker():
            try:
                winsound.PlaySound(str(audio_file), winsound.SND_FILENAME)
            except Exception as error:
                print(f"Audio playback error for {filename}: {error}")
            finally:
                self.speaking.clear()

        threading.Thread(target=speech_worker, daemon=True).start()


    def speak(self, text):
        """Play a prerecorded WAV clip that matches this line of dialogue.

        Add recordings to the 'voice' folder beside this Python file. If a
        line has no dedicated recording, Mini Sean plays unknown.wav instead.
        """
        if self.speaking.is_set() or self.settings.get("muted", False):
            return

        self.current_text = text
        self.speaking.set()

        voice_clips = {
            "Hey, I'm Mini Sean nice to see you.": "greeting.wav",
            "Alright, I'll see you later!": "goodbye.wav",
            "Why did the computer go to the doctor? It had a virus. Don't worry, I'm not one!": "joke_1.wav",
            "Why was the computer cold? It left its Windows open.": "joke_2.wav",
            "I tried to make a belt out of watches. It was a waist of time.": "joke_3.wav",
            "Why did the keyboard need a break? It was working too many shifts.": "joke_4.wav",
            "Octopuses have three hearts.": "fact_1.wav",
            "A day on Venus is longer than its year.": "fact_2.wav",
            "Honey can remain edible for a very long time when sealed and stored properly.": "fact_3.wav",
            "Wombat droppings are cube-shaped.": "fact_4.wav",
            "The Eiffel Tower can become a little taller in hot weather because metal expands.": "fact_5.wav",
            "Once upon a time, a tiny desktop companion named Mini Sean decided to explore the screen. He walked past the clock, waved at the taskbar, and discovered a forgotten folder full of old projects. Instead of opening everything at once, he asked first. The folder contained a drawing, a silly joke, and a note that said: the best adventures are the ones you choose yourself. The end.": "story.wav",
            "Mini Sean's little song! Hello hello, I'm here today. A tiny friend to brighten your day. I'll take a stroll, then stop and say: have a great and happy day!": "jingle.wav",
        }

        filename = voice_clips.get(text, "unknown.wav")
        audio_file = VOICE_DIR / filename

        def speech_worker():
            try:
                if audio_file.is_file():
                    # Play synchronously inside this worker thread so the
                    # speaking animation remains active until playback ends.
                    winsound.PlaySound(str(audio_file), winsound.SND_FILENAME)
                else:
                    print(f"Recording not found: {audio_file}")
                    print("Create that WAV file in the voice folder to use this line.")
            except Exception as error:
                print("Audio playback error:", error)
            finally:
                self.speaking.clear()

        threading.Thread(target=speech_worker, daemon=True).start()

    # -------------------------
    # CONTROLS
    # -------------------------

    def start_dance(self):
        """Make Mini Sean do a brief side-to-side dance using available walk frames."""
        self.cancel_behavior_timer()
        self.walking = False
        self.dance_active = True
        self.dance_origin_x = self.x
        self.dance_end_time = time.monotonic() + 4.0
        if self.dance_after_id is not None:
            try:
                self.root.after_cancel(self.dance_after_id)
            except tk.TclError:
                pass
        self.dance_after_id = self.root.after(4000, self.finish_dance)
        if not self.speaking.is_set():
            self.speak_event("Dance break!", "dance_break.wav")

    def finish_dance(self):
        self.dance_after_id = None
        self.dance_active = False
        self.x = max(0, min(self.dance_origin_x, self.screen_width - WINDOW_WIDTH))
        self.update_position()
        if not self.speaking.is_set():
            self.mode = "idle_stand"
        if self.auto_wander:
            self.schedule_next_behavior()

    def toggle_walking(self, event=None):
        self.dance_active = False
        if self.dance_after_id is not None:
            try:
                self.root.after_cancel(self.dance_after_id)
            except tk.TclError:
                pass
            self.dance_after_id = None
        self.auto_wander = not self.auto_wander
        self.walking = False
        self.cancel_behavior_timer()

        if self.auto_wander:
            self.mode = "idle_stand"
            self.schedule_next_behavior()
        else:
            self.mode = "idle_stand"

    def quit(self, event=None):
        # Persist the most recently applied settings when quitting.
        try:
            self.save_settings()
        except Exception:
            pass
        self.cancel_behavior_timer()
        if self.dance_after_id is not None:
            try:
                self.root.after_cancel(self.dance_after_id)
            except tk.TclError:
                pass
            self.dance_after_id = None
        self.cancel_idle_pose_timer()
        if self.idle_reaction_after_id is not None:
            try:
                self.root.after_cancel(self.idle_reaction_after_id)
            except tk.TclError:
                pass
            self.idle_reaction_after_id = None
        try:
            if self.control_window.winfo_exists():
                self.control_window.destroy()
        except (tk.TclError, AttributeError):
            pass
        self.root.destroy()


# -----------------------------
# START PROGRAM
# -----------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = MiniMe(root)
    root.mainloop()
