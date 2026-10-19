#!/usr/bin/env python3
"""Native Windows desktop app for nvidia-fix.

Pick a corrupted NVIDIA ShadowPlay recording, choose where the recovered files
should go, and click Recover. The recovery engine is the same one used by the
CLI and the tests: it scans H.264 samples, cuts from the first clean IDR, and
verifies the result.
"""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import nvidia_fix

BG = "#090b0e"
PANEL = "#11151b"
PANEL_2 = "#171d25"
ENTRY_BG = "#0b0e12"
LINE = "#242c37"
LINE_STRONG = "#323b49"
TEXT = "#f2f5f8"
MUTED = "#8d98a9"
MUTED_DIM = "#66707f"
ACCENT = "#f0b44a"
ACCENT_HOVER = "#ffc96b"
ACCENT_INK = "#1a1204"
ACCENT_DIM = "#6e5424"
GOOD = "#5bd39a"
BAD = "#e86a6a"

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_HINT = ("Segoe UI", 8)
FONT_MICRO = ("Cascadia Mono", 7)
FONT_TINY = ("Cascadia Mono", 8)
FONT_LABEL = ("Cascadia Mono", 8, "bold")
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_BTN = ("Bahnschrift SemiBold", 9)
FONT_CTA = ("Bahnschrift SemiBold", 12)
FONT_BRAND = ("Bahnschrift SemiBold", 11)
FONT_TITLE = ("Bahnschrift SemiBold", 28)
FONT_INTRO_TITLE = ("Bahnschrift SemiBold", 9)
FONT_PATH = ("Cascadia Mono", 9)
FONT_STAT = ("Cascadia Mono", 16)


def _timecode(value) -> str:
    if value is None:
        return "—"
    minutes, seconds = divmod(float(value), 60)
    return f"{int(minutes)}:{seconds:05.2f}"


def _resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


class DesktopApp:
    def __init__(
        self,
        root: tk.Tk,
        initial_input: Optional[str] = None,
        initial_output: Optional[str] = None,
        test_mode: bool = False,
        auto_start: bool = False,
    ) -> None:
        self.root = root
        self.busy = False
        self.result = None
        self.timeline_data = None
        self.exit_code = 0
        self.test_mode = test_mode
        self.auto_start = auto_start
        self._auto_output = True
        self._closed = False
        self.events: queue.Queue = queue.Queue()

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a corrupted recording to begin.")
        self.stage_var = tk.StringVar(value="READY")
        self.stat_clean = tk.StringVar(value="—")
        self.stat_duration = tk.StringVar(value="—")
        self.stat_packets = tk.StringVar(value="—")
        self.stat_errors = tk.StringVar(value="—")
        self.saved_path = tk.StringVar(value="")
        self.caveat_var = tk.StringVar(value="")

        self._configure_window()
        self._build_ui()

        if initial_input:
            self._set_input(initial_input)
        if initial_output:
            self.output_var.set(initial_output)
            self._auto_output = False

        self._check_tools()
        self._refresh_controls()
        self.root.after(80, self._poll_events)

    # ------------------------------------------------------------------ window
    def _configure_window(self) -> None:
        self.root.title("NVIDIA-Fix - ShadowPlay Recovery")
        self.root.configure(bg=BG)
        width, height = 880, 740
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(780, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.root.iconbitmap(default=str(_resource_path("assets/nvidia-fix.ico")))
        except Exception:
            pass

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=BG,
            background=ACCENT,
            bordercolor=BG,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=4,
        )

    def _build_ui(self) -> None:
        tk.Frame(self.root, bg=ACCENT, height=3).pack(side="top", fill="x")

        # Footer stays at the bottom even when the result card appears.
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side="bottom", fill="x", padx=26, pady=(8, 12))
        tk.Label(
            footer,
            text="H.264 MP4/MOV  ·  STREAM COPY  ·  ORIGINAL READ-ONLY",
            bg=BG,
            fg=MUTED_DIM,
            font=FONT_MICRO,
        ).pack(side="left")
        tk.Label(
            footer,
            text=f"v{nvidia_fix.VERSION}",
            bg=BG,
            fg=MUTED_DIM,
            font=FONT_MICRO,
        ).pack(side="right")

        separator = tk.Frame(self.root, bg=LINE, height=1)
        separator.pack(side="bottom", fill="x", padx=26)

        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True, padx=26, pady=(16, 0))

        brand = tk.Frame(content, bg=BG)
        brand.pack(fill="x")
        tk.Label(
            brand,
            text="N",
            bg=ACCENT,
            fg=ACCENT_INK,
            font=("Bahnschrift SemiBold", 13),
            width=2,
            height=1,
        ).pack(side="left")
        tk.Label(
            brand, text="NVIDIA-FIX", bg=BG, fg=TEXT, font=FONT_BRAND
        ).pack(side="left", padx=(9, 0))
        tk.Frame(brand, bg=LINE, width=1, height=13).pack(
            side="left", padx=(12, 12)
        )
        tk.Label(
            brand,
            text="SHADOWPLAY RECOVERY",
            bg=BG,
            fg=MUTED,
            font=FONT_MICRO,
        ).pack(side="left")

        chip = tk.Frame(
            brand, bg=PANEL_2, highlightbackground=LINE, highlightthickness=1
        )
        chip.pack(side="right")
        tk.Label(
            chip, text="●", bg=PANEL_2, fg=GOOD, font=("Segoe UI", 7)
        ).pack(side="left", padx=(8, 5), pady=4)
        tk.Label(
            chip,
            text="LOCAL ONLY  ·  NO UPLOAD",
            bg=PANEL_2,
            fg=MUTED,
            font=FONT_MICRO,
        ).pack(side="left", padx=(0, 8), pady=4)

        tk.Label(
            content,
            text="NVIDIA SHADOWPLAY  /  H.264",
            bg=BG,
            fg=ACCENT,
            font=FONT_TINY,
            anchor="w",
        ).pack(fill="x", pady=(14, 3))
        title_row = tk.Frame(content, bg=BG)
        title_row.pack(fill="x")
        tk.Label(
            title_row,
            text="Recover the ",
            bg=BG,
            fg=TEXT,
            font=FONT_TITLE,
        ).pack(side="left")
        tk.Label(
            title_row,
            text="clean tail.",
            bg=BG,
            fg=ACCENT,
            font=FONT_TITLE,
        ).pack(side="left")
        tk.Label(
            content,
            text=(
                "Scan the damaged file, cut from the first intact keyframe, and "
                "verify every packet. The original is never modified."
            ),
            bg=BG,
            fg=MUTED,
            font=FONT,
            anchor="w",
            justify="left",
            wraplength=800,
        ).pack(fill="x", pady=(5, 0))

        self.tool_notice = tk.Label(
            content,
            text="",
            bg="#3a1b1b",
            fg="#ffc1c1",
            font=FONT_SM,
            anchor="w",
            justify="left",
            padx=12,
            pady=8,
            wraplength=780,
        )

        self.card = tk.Frame(
            content,
            bg=PANEL,
            highlightbackground=LINE,
            highlightthickness=1,
        )
        self.card.pack(fill="x", pady=(16, 0))

        inner = tk.Frame(self.card, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=15)
        inner.columnconfigure(0, weight=1)

        self._field_label(inner, "SOURCE RECORDING", 0)
        self.input_entry = self._entry(inner, self.input_var, readonly=True)
        self.input_entry.grid(row=1, column=0, sticky="ew", ipady=5)
        self.input_btn = self._secondary_button(inner, "Browse…", self._choose_input)
        self.input_btn.grid(row=1, column=1, padx=(10, 0), sticky="e")
        tk.Label(
            inner,
            text="MP4 / MOV / M4V  ·  H.264  ·  opened read-only",
            bg=PANEL,
            fg=MUTED,
            font=FONT_HINT,
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self._field_label(inner, "OUTPUT FOLDER", 3, pady=(13, 4))
        self.output_entry = self._entry(inner, self.output_var, readonly=False)
        self.output_entry.grid(row=4, column=0, sticky="ew", ipady=5)
        self.output_btn = self._secondary_button(inner, "Choose…", self._choose_output)
        self.output_btn.grid(row=4, column=1, padx=(10, 0), sticky="e")
        tk.Label(
            inner,
            text="Defaults to the source folder. Existing files are never overwritten.",
            bg=PANEL,
            fg=MUTED,
            font=FONT_HINT,
            anchor="w",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.start_btn = tk.Button(
            content,
            text="Recover clean tail",
            command=self._start_recovery,
            bg="#2a2418",
            fg="#7c6a45",
            activebackground=ACCENT_HOVER,
            activeforeground=ACCENT_INK,
            font=FONT_CTA,
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            cursor="arrow",
            state="disabled",
        )
        self.start_btn.pack(fill="x", pady=(15, 9))

        self.progress = ttk.Progressbar(
            content,
            mode="determinate",
            maximum=100,
            value=0,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x")

        status_row = tk.Frame(content, bg=BG)
        status_row.pack(fill="x", pady=(7, 0))
        self.stage_label = tk.Label(
            status_row,
            textvariable=self.stage_var,
            bg=BG,
            fg=MUTED_DIM,
            font=FONT_MICRO,
            anchor="e",
        )
        self.stage_label.pack(side="right", padx=(12, 0))
        self.status_label = tk.Label(
            status_row,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            font=FONT_SM,
            anchor="w",
            justify="left",
            wraplength=690,
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self._build_intro(content)
        self._build_result_card(content)

    def _build_intro(self, content) -> None:
        self.intro = tk.Frame(content, bg=BG)
        tk.Frame(self.intro, bg=LINE, height=1).pack(fill="x")
        inner = tk.Frame(self.intro, bg=BG)
        inner.pack(fill="x", pady=(11, 11))
        for col in (0, 2, 4):
            inner.columnconfigure(col, weight=1)

        steps = (
            ("01", "SCAN", "Audits every H.264 sample", "Finds the overwritten region"),
            ("02", "CUT", "Starts at the first clean IDR", "The original stays read-only"),
            ("03", "VERIFY", "Hashes packets, decodes the tail", "Writes a recovery report"),
        )
        for index, (number, title, line_one, line_two) in enumerate(steps):
            column = index * 2
            step = tk.Frame(inner, bg=BG)
            step.grid(row=0, column=column, sticky="nsew")
            head = tk.Frame(step, bg=BG)
            head.pack(fill="x")
            tk.Label(
                head, text=number, bg=BG, fg=ACCENT, font=FONT_TINY
            ).pack(side="left")
            tk.Label(
                head, text=title, bg=BG, fg=TEXT, font=FONT_INTRO_TITLE
            ).pack(side="left", padx=(7, 0))
            tk.Label(
                step,
                text=line_one,
                bg=BG,
                fg=MUTED,
                font=FONT_SM,
                anchor="w",
            ).pack(fill="x", pady=(5, 0))
            tk.Label(
                step,
                text=line_two,
                bg=BG,
                fg=MUTED_DIM,
                font=FONT_HINT,
                anchor="w",
            ).pack(fill="x", pady=(1, 0))
            if index < 2:
                tk.Frame(inner, bg=LINE, width=1).grid(
                    row=0, column=column + 1, sticky="ns", padx=16
                )

        tk.Frame(self.intro, bg=LINE, height=1).pack(fill="x")
        note = tk.Frame(self.intro, bg=BG)
        note.pack(fill="x", pady=(9, 11))
        tk.Label(
            note,
            text="RECOVERY, NOT REPAIR",
            bg=BG,
            fg=MUTED,
            font=FONT_LABEL,
        ).pack(side="left")
        tk.Label(
            note,
            text="Overwritten frames cannot be rebuilt.",
            bg=BG,
            fg=MUTED_DIM,
            font=FONT_HINT,
        ).pack(side="left", padx=(10, 0))

        self.intro.pack(fill="x", pady=(15, 0))

    def _field_label(self, parent, text, row, pady=(0, 4)):
        tk.Label(
            parent,
            text=text,
            bg=PANEL,
            fg=MUTED,
            font=FONT_TINY,
            anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=pady)

    def _entry(self, parent, variable, readonly):
        return tk.Entry(
            parent,
            textvariable=variable,
            state="readonly" if readonly else "normal",
            bg=ENTRY_BG,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=PANEL_2,
            disabledforeground=MUTED,
            readonlybackground=ENTRY_BG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            font=FONT_PATH,
        )

    def _secondary_button(self, parent, text, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL_2,
            fg=TEXT,
            activebackground=LINE,
            activeforeground=TEXT,
            font=FONT_BTN,
            relief="flat",
            bd=0,
            padx=13,
            pady=6,
            cursor="hand2",
        )

    def _build_result_card(self, content) -> None:
        self.result_card = tk.Frame(
            content,
            bg=PANEL,
            highlightbackground=LINE,
            highlightthickness=1,
        )
        inner = tk.Frame(self.result_card, bg=PANEL)
        inner.pack(fill="x", padx=16, pady=12)

        head = tk.Frame(inner, bg=PANEL)
        head.pack(fill="x")
        left = tk.Frame(head, bg=PANEL)
        left.pack(side="left")
        tk.Label(left, text="●", bg=PANEL, fg=GOOD, font=("Segoe UI", 7)).pack(
            side="left"
        )
        tk.Label(
            left,
            text="RECOVERED CLEAN TAIL",
            bg=PANEL,
            fg=GOOD,
            font=FONT_LABEL,
        ).pack(side="left", padx=(6, 0))

        buttons = tk.Frame(head, bg=PANEL)
        buttons.pack(side="right")
        self.open_folder_btn = self._secondary_button(
            buttons, "Open folder", self._open_folder
        )
        self.open_folder_btn.pack(side="left", padx=(0, 8))
        self.play_btn = self._secondary_button(
            buttons, "Play video", self._play_video
        )
        self.play_btn.pack(side="left", padx=(0, 8))
        self.report_btn = self._secondary_button(
            buttons, "Report", self._open_report
        )
        self.report_btn.pack(side="left")

        stats = tk.Frame(inner, bg=PANEL)
        stats.pack(fill="x", pady=(9, 8))
        for col in range(4):
            stats.columnconfigure(col, weight=1)
        self._stat_box(stats, 0, "CLEAN START", self.stat_clean)
        self._stat_box(stats, 1, "RECOVERED VIDEO", self.stat_duration)
        self._stat_box(stats, 2, "VIDEO PACKETS", self.stat_packets)
        self.errors_stat = self._stat_box(
            stats, 3, "DECODE ERRORS", self.stat_errors
        )

        self.timeline_canvas = tk.Canvas(
            inner,
            bg=PANEL,
            height=26,
            highlightthickness=0,
            bd=0,
        )
        self.timeline_canvas.pack(fill="x", pady=(0, 8))
        self.timeline_canvas.bind("<Configure>", self._on_timeline_configure)
        self.timeline_data = None

        caveat = tk.Frame(inner, bg=PANEL)
        caveat.pack(fill="x")
        tk.Frame(caveat, bg=ACCENT_DIM, width=3).pack(side="left", fill="y")
        tk.Label(
            caveat,
            textvariable=self.caveat_var,
            bg=PANEL,
            fg=MUTED,
            font=FONT_HINT,
            anchor="w",
            justify="left",
            wraplength=760,
        ).pack(side="left", fill="x", padx=(10, 0))

    def _stat_box(self, parent, col, label, variable):
        box = tk.Frame(parent, bg=PANEL_2)
        box.grid(
            row=0,
            column=col,
            sticky="nsew",
            padx=(0 if col == 0 else 6, 0),
        )
        tk.Label(
            box, text=label, bg=PANEL_2, fg=MUTED, font=FONT_MICRO, anchor="w"
        ).pack(fill="x", padx=10, pady=(6, 0))
        value = tk.Label(
            box,
            textvariable=variable,
            bg=PANEL_2,
            fg=TEXT,
            font=FONT_STAT,
            anchor="w",
        )
        value.pack(fill="x", padx=10, pady=(0, 6))
        return value

    # ------------------------------------------------------------------ state
    def _poll_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self._set_status(payload)
                elif kind == "success":
                    self._on_success(payload)
                elif kind == "error":
                    self._on_failure(payload)
                if self._closed:
                    return
        except queue.Empty:
            pass
        try:
            self.root.after(80, self._poll_events)
        except tk.TclError:
            self._closed = True

    def _set_input(self, path: str) -> None:
        source = Path(path)
        self.input_var.set(str(source))
        if self._auto_output or not self.output_var.get().strip():
            self.output_var.set(str(source.parent))
            self._auto_output = True
        self.status_label.config(fg=MUTED)
        self.status_var.set("Ready. Click Recover clean tail.")
        self._set_stage("READY", MUTED_DIM)
        self._hide_result()
        self._show_intro()
        self._refresh_controls()

    def _choose_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a corrupted recording",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._set_input(path)

    def _choose_output(self) -> None:
        initial = self.output_var.get().strip() or str(Path.home())
        path = filedialog.askdirectory(
            title="Choose where recovered files should go",
            initialdir=initial,
        )
        if path:
            self.output_var.set(path)
            self._auto_output = False
            self._refresh_controls()

    def _check_tools(self) -> bool:
        missing = [
            name
            for name in (nvidia_fix.FFMPEG, nvidia_fix.FFPROBE)
            if shutil.which(name) is None
        ]
        if missing:
            self.tool_notice.config(
                text=(
                    "ffmpeg / ffprobe were not found on PATH. Install ffmpeg "
                    "(for example: winget install Gyan.FFmpeg), reopen the app, "
                    "and try again."
                )
            )
            self.tool_notice.pack(fill="x", pady=(12, 0), before=self.card)
            return False
        self.tool_notice.pack_forget()
        return True

    def _refresh_controls(self) -> None:
        enabled = not self.busy
        self.input_btn.config(state="normal" if enabled else "disabled")
        self.output_btn.config(state="normal" if enabled else "disabled")
        self.input_entry.config(state="readonly" if enabled else "disabled")
        self.output_entry.config(state="normal" if enabled else "disabled")

        has_input = bool(self.input_var.get().strip())
        if enabled and has_input:
            self.start_btn.config(
                state="normal",
                bg=ACCENT,
                fg=ACCENT_INK,
                cursor="hand2",
            )
        else:
            self.start_btn.config(
                state="disabled",
                bg="#2a2418",
                fg="#7c6a45",
                cursor="arrow",
            )

    def _show_intro(self) -> None:
        if not self.intro.winfo_manager():
            self.intro.pack(fill="x", pady=(15, 0))

    def _hide_intro(self) -> None:
        self.intro.pack_forget()

    def _hide_result(self) -> None:
        self.result_card.pack_forget()
        self.result = None
        self.timeline_data = None
        if hasattr(self, "timeline_canvas"):
            self.timeline_canvas.delete("all")

    def _set_stage(self, text: str, color: str = MUTED_DIM) -> None:
        self.stage_var.set(text)
        self.stage_label.config(fg=color)

    def _set_status(self, message: str) -> None:
        self.status_label.config(fg=MUTED)
        self.status_var.set(message)
        lower = message.lower()
        if any(
            token in lower
            for token in ("scanning", "reading", "damaged samples")
        ):
            self._set_stage("01 / SCAN", ACCENT)
        elif any(
            token in lower
            for token in ("cutting", "verifying", "checking", "exporting")
        ):
            self._set_stage("02 / CUT", ACCENT)
        elif any(token in lower for token in ("decoding", "writing")):
            self._set_stage("03 / VERIFY", ACCENT)

    def _on_timeline_configure(self, _event=None) -> None:
        self._draw_timeline()

    def _draw_timeline(self) -> None:
        canvas = self.timeline_canvas
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        if not self.timeline_data:
            return

        bad_end, clean_start, total = self.timeline_data
        width = canvas.winfo_width()
        if width <= 1 or total <= 0:
            return

        y0, height = 6, 14
        x_bad = max(2.0, min(width - 2.0, width * bad_end / total))
        x_clean = max(x_bad + 2.0, min(float(width), width * clean_start / total))

        canvas.create_rectangle(0, y0, width, y0 + height, fill=LINE, outline="")
        canvas.create_rectangle(0, y0, x_bad, y0 + height, fill="#8f3d3d", outline="")
        canvas.create_rectangle(
            x_clean, y0, width, y0 + height, fill=GOOD, outline=""
        )
        canvas.create_line(
            x_clean, y0 - 3, x_clean, y0 + height + 3, fill=TEXT, width=1
        )

        red_width = x_bad
        if red_width > 125:
            canvas.create_text(
                red_width / 2,
                y0 + height / 2,
                text=f"LOST  {_timecode(0)} – {_timecode(bad_end)}",
                fill="#ffe5e5",
                font=FONT_MICRO,
            )
        elif red_width > 38:
            canvas.create_text(
                red_width / 2,
                y0 + height / 2,
                text="LOST",
                fill="#ffe5e5",
                font=FONT_MICRO,
            )

        green_width = width - x_clean
        if green_width > 175:
            canvas.create_text(
                x_clean + green_width / 2,
                y0 + height / 2,
                text=f"RECOVERED  {_timecode(clean_start)} – {_timecode(total)}",
                fill="#06170f",
                font=FONT_MICRO,
            )
        elif green_width > 58:
            canvas.create_text(
                x_clean + green_width / 2,
                y0 + height / 2,
                text="RECOVERED",
                fill="#06170f",
                font=FONT_MICRO,
            )

    # ---------------------------------------------------------------- recovery
    def _start_recovery(self) -> None:
        if self.busy:
            return
        if not self._check_tools():
            messagebox.showerror(
                "ffmpeg missing",
                "ffmpeg and ffprobe are required. Install ffmpeg and reopen the app.",
            )
            return

        raw_input = self.input_var.get().strip()
        if not raw_input:
            messagebox.showwarning("Choose a recording", "Select a corrupted video first.")
            return
        source = Path(raw_input)
        if not source.is_file():
            messagebox.showerror("File not found", f"Could not find:\n{source}")
            return
        if source.suffix.lower() not in nvidia_fix.SUPPORTED_SUFFIXES:
            messagebox.showerror(
                "Unsupported file type",
                "Choose an MP4, MOV, or M4V file. H.264 is required.",
            )
            return

        raw_output = self.output_var.get().strip()
        output_dir = Path(raw_output) if raw_output else source.parent
        if output_dir.exists() and not output_dir.is_dir():
            messagebox.showerror(
                "Invalid output folder",
                f"This path is a file, not a folder:\n{output_dir}",
            )
            return

        self.busy = True
        self._hide_result()
        self._show_intro()
        self._refresh_controls()
        self.status_label.config(fg=MUTED)
        self.status_var.set("Starting…")
        self._set_stage("01 / SCAN", ACCENT)
        self.progress.config(mode="indeterminate")
        self.progress.start(12)

        thread = threading.Thread(
            target=self._worker,
            args=(source, output_dir),
            daemon=True,
        )
        thread.start()

    def _worker(self, source: Path, output_dir: Path) -> None:
        def progress(message: str) -> None:
            self.events.put(("status", message))

        try:
            result = nvidia_fix.process(
                source,
                out_dir=output_dir,
                full_decode=True,
                progress=progress,
            )
        except Exception as exc:  # surface any failure to the UI
            self.events.put(("error", str(exc) or exc.__class__.__name__))
            return
        self.events.put(("success", result))

    def _finish_busy(self) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self._refresh_controls()

    def _on_success(self, result) -> None:
        self._finish_busy()
        if result.get("status") == "healthy":
            self.status_label.config(fg=GOOD)
            self.status_var.set(
                "No corruption detected. This file is already intact."
            )
            self._set_stage("INTACT", GOOD)
            if not self.test_mode:
                messagebox.showinfo(
                    "No corruption found",
                    result.get("message")
                    or "No corruption detected. This file is already intact.",
                )
            if self.test_mode and self.auto_start:
                self._closed = True
                self.root.after(50, self.root.destroy)
            return

        self.result = result
        corruption = result["corruption"]
        recovery = result["recovery"]
        video = recovery["video"]

        self.stat_clean.set(_timecode(corruption.get("clean_start_seconds")))
        self.stat_duration.set(_timecode(video.get("duration_seconds")))
        self.stat_packets.set(f"{int(video.get('packets') or 0):,}")
        self.stat_errors.set(str(video.get("decode_errors", 0)))
        self.saved_path.set(str(Path(result["paths"]["video"]).parent))
        self.caveat_var.set(
            f"Footage before {_timecode(corruption.get('last_bad_seconds'))} "
            "was overwritten and cannot be rebuilt; the clean tail and early "
            "audio are saved."
        )

        errors = int(video.get("decode_errors") or 0)
        self.errors_stat.config(fg=GOOD if not errors else BAD)
        if errors:
            self.status_label.config(fg=ACCENT)
            self.status_var.set(
                f"Recovered, but the full decode reported {errors} error line(s). "
                "See the report."
            )
            self._set_stage("WARNINGS", ACCENT)
        else:
            self.status_label.config(fg=GOOD)
            self.status_var.set(
                "Recovered and verified. 0 decode errors. "
                f"Clean start {_timecode(corruption.get('clean_start_seconds'))}."
            )
            self._set_stage("COMPLETE", GOOD)

        clean_start = float(corruption.get("clean_start_seconds") or 0)
        duration = float(video.get("duration_seconds") or 0)
        source_total = float((result.get("media") or {}).get("duration_seconds") or 0)
        if source_total <= 0:
            source_total = clean_start + duration
        if source_total > 0:
            self.timeline_data = (
                float(corruption.get("last_bad_seconds") or 0),
                clean_start,
                source_total,
            )

        self._hide_intro()
        self.result_card.pack(fill="x", pady=(12, 0))
        self.root.update_idletasks()
        self.root.after_idle(self._draw_timeline)
        if self.test_mode and self.auto_start:
            self._closed = True
            self.root.after(50, self.root.destroy)

    def _on_failure(self, message: str) -> None:
        self._finish_busy()
        self.status_label.config(fg=BAD)
        self.status_var.set("Recovery failed.")
        self._set_stage("FAILED", BAD)
        if self.test_mode:
            self.exit_code = 1
            self._closed = True
            self.root.after(50, self.root.destroy)
            return
        messagebox.showerror("Recovery failed", message)

    # ------------------------------------------------------------------ openers
    def _open_path(self, path) -> None:
        if not path:
            return
        target = Path(path)
        if not target.exists():
            messagebox.showerror("Not found", f"This path no longer exists:\n{target}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror("Could not open", str(exc))

    def _video_file(self) -> Optional[str]:
        if not self.result:
            return None
        return self.result["paths"].get("video")

    def _open_folder(self) -> None:
        video = self._video_file()
        if video:
            self._open_path(Path(video).parent)

    def _play_video(self) -> None:
        self._open_path(self._video_file())

    def _open_report(self) -> None:
        if self.result:
            self._open_path(self.result["paths"].get("report"))

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                "Recovery running",
                "A recovery is still running. Close the window anyway?",
            ):
                return
        self._closed = True
        self.root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="NVIDIA-Fix",
        description="Recover the clean tail of a corrupted NVIDIA ShadowPlay recording.",
    )
    parser.add_argument("input", nargs="?", help="recording to open")
    parser.add_argument("--output", help="output folder")
    parser.add_argument("--auto-start", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = DesktopApp(
        root,
        initial_input=args.input,
        initial_output=args.output,
        test_mode=args.smoke_test,
        auto_start=args.auto_start,
    )

    if args.smoke_test:
        if args.auto_start and args.input:
            root.after(600, app._start_recovery)
            root.after(180000, root.destroy)
        else:
            root.after(1200, root.destroy)

    root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
