"""Prince DAT Explorer — viewer, comparison workspace, and composite editor."""

# SPDX-License-Identifier: GPL-2.0-or-later
# Python reimplementation created in 2026; see THIRD_PARTY_NOTICES.md.

from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from editor_windows import CompositeEditorWindow, ComparisonWindow
from room_sets import ArchiveContext, RoomSetError

from prince_dat import (
    VERSION,
    DatArchive,
    DatFormatError,
    DecodedImage,
    PrincePalette,
    RenderedRaster,
    ResourceAnalysis,
    auto_display_mode,
    composite_pattern_at,
    display_colors,
    display_horizontal_factors,
    extract_all,
    hardware_palette_for_resource,
    hex_dump,
    mode6_bit_at,
    normalized_display_width,
    render_display_mode,
    translated_index,
    write_display_png,
)


APP_NAME = "Prince DAT Explorer"

VIEW_CHOICES = (
    "Auto — archive video family",
    "VGA — embedded RGB",
    "EGA — embedded translation",
    "CGA — embedded translation",
    "640×200 — translated digital bits",
    "Composite — DOSBox-X New CGA cells",
)
VIEW_TO_MODE = {
    VIEW_CHOICES[1]: "vga",
    VIEW_CHOICES[2]: "ega",
    VIEW_CHOICES[3]: "cga",
    VIEW_CHOICES[4]: "mode6",
    VIEW_CHOICES[5]: "composite",
}


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class PrinceDatExplorer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1320x840")
        self.minsize(980, 640)

        self.archive: DatArchive | None = None
        self.archive_context: ArchiveContext | None = None
        self.current: ResourceAnalysis | None = None
        self.current_render_archive: DatArchive | None = None
        self.current_render_analysis: ResourceAnalysis | None = None
        self.current_mode: str | None = None
        self.current_hardware_palette: PrincePalette | None = None
        self.preview_raster: RenderedRaster | None = None
        self.preview_photo: tk.PhotoImage | None = None
        self.preview_origin = (0, 0)
        self.preview_scale = 1
        self.preview_x_zoom = 1
        self.preview_x_subsample = 1
        self._fit_after: str | None = None
        self._base_status = "Open a Prince of Persia .DAT file to begin."
        self.comparison_windows: list[ComparisonWindow] = []
        self.composite_editor: CompositeEditorWindow | None = None

        self.filter_var = tk.StringVar(value="All resources")
        self.search_var = tk.StringVar()
        self.palette_var = tk.StringVar(value=VIEW_CHOICES[0])
        self.zoom_var = tk.StringVar(value="Fit")
        self.transparent_var = tk.BooleanVar(value=False)
        self.grid_var = tk.BooleanVar(value=False)
        self.path_var = tk.StringVar(value="No DAT open")
        self.status_var = tk.StringVar(value=self._base_status)

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        themes = style.theme_names()
        if sys.platform == "win32" and "vista" in themes:
            style.theme_use("vista")
        elif "clam" in themes:
            style.theme_use("clam")
        list_font = tkfont.nametofont("TkDefaultFont")
        resource_row_height = max(36, list_font.metrics("linespace") + 16)
        style.configure("Resource.Treeview", rowheight=resource_row_height)
        style.configure("Resource.Treeview.Heading", padding=(6, 7))
        style.configure("Status.TLabel", padding=(8, 5))
        style.configure("Path.TLabel", foreground="#44515f")
        style.configure("ReadOnly.TLabel", foreground="#28684a")

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open DAT…", accelerator="Ctrl+O", command=self.open_dialog)
        file_menu.add_separator()
        file_menu.add_command(
            label="Export selected image…",
            accelerator="Ctrl+E",
            command=self.export_selected_image,
        )
        file_menu.add_command(label="Export selected raw resource…", command=self.export_selected_raw)
        file_menu.add_command(label="Extract all resources…", command=self.extract_all_resources)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)
        menu.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(
            label="Treat index 0 as transparent",
            variable=self.transparent_var,
            command=self.render_current,
        )
        view_menu.add_checkbutton(
            label="Pixel grid",
            variable=self.grid_var,
            command=self.render_current,
        )
        view_menu.add_separator()
        view_menu.add_command(
            label="Compare two display modes…",
            accelerator="Ctrl+M",
            command=self.open_comparison,
        )
        view_menu.add_command(
            label="Open composite editor…",
            accelerator="Ctrl+Shift+E",
            command=self.open_composite_editor,
        )
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        action_bar = ttk.Frame(self, padding=(10, 9, 10, 7))
        action_bar.pack(fill=tk.X)

        ttk.Button(action_bar, text="Open DAT…", command=self.open_dialog).pack(side=tk.LEFT)
        ttk.Button(action_bar, text="Export image…", command=self.export_selected_image).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(action_bar, text="Export raw…", command=self.export_selected_raw).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(action_bar, text="Extract all…", command=self.extract_all_resources).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Separator(action_bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=12
        )
        ttk.Button(action_bar, text="Compare modes…", command=self.open_comparison).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(action_bar, text="Composite editor…", command=self.open_composite_editor).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(action_bar, text="Source protected", style="ReadOnly.TLabel").pack(
            side=tk.LEFT, padx=(10, 0)
        )
        ttk.Label(
            action_bar,
            textvariable=self.path_var,
            style="Path.TLabel",
            anchor=tk.E,
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(16, 0))

        search_bar = ttk.Frame(self, padding=(10, 0, 10, 8))
        search_bar.pack(fill=tk.X)
        ttk.Label(search_bar, text="Show:").pack(side=tk.LEFT)
        filter_box = ttk.Combobox(
            search_bar,
            textvariable=self.filter_var,
            state="readonly",
            width=18,
            values=("All resources", "Images only", "Palettes only", "Other data"),
        )
        filter_box.pack(side=tk.LEFT, padx=(6, 18))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tree())

        ttk.Label(search_bar, text="Find ID or type:").pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_bar, textvariable=self.search_var, width=24)
        search_entry.pack(side=tk.LEFT, padx=(6, 0))
        self.search_var.trace_add("write", lambda *_args: self.refresh_tree())

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(right, weight=5)

        tree_frame = ttk.LabelFrame(left, text="Indexed resources", padding=(8, 7))
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("id", "kind", "dimensions", "compression", "size", "checksum")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Resource.Treeview",
        )
        headings = {
            "id": "ID",
            "kind": "Type",
            "dimensions": "Size",
            "compression": "Codec",
            "size": "Bytes",
            "checksum": "Sum",
        }
        widths = {
            "id": 70,
            "kind": 105,
            "dimensions": 85,
            "compression": 95,
            "size": 70,
            "checksum": 52,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column], command=lambda c=column: self._sort_tree(c))
            anchor = tk.E if column in ("id", "size") else tk.W
            self.tree.column(column, width=widths[column], minwidth=45, anchor=anchor)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        tree_x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.tree.tag_configure("bad", foreground="#a32424")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_selection)

        controls = ttk.LabelFrame(right, text="Preview controls", padding=(9, 7))
        controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(controls, text="Display mode:").grid(row=0, column=0, sticky="w")
        self.palette_box = ttk.Combobox(
            controls,
            textvariable=self.palette_var,
            state="readonly",
            width=39,
            values=VIEW_CHOICES,
        )
        self.palette_box.grid(row=0, column=1, sticky="ew", padx=(6, 18))
        self.palette_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_preview_details())

        ttk.Label(controls, text="Zoom:").grid(row=0, column=2, sticky="w")
        zoom_box = ttk.Combobox(
            controls,
            textvariable=self.zoom_var,
            state="readonly",
            width=7,
            values=("Fit", "1x", "2x", "3x", "4x", "6x", "8x", "12x", "16x", "24x", "32x"),
        )
        zoom_box.grid(row=0, column=3, sticky="w", padx=(6, 18))
        zoom_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_preview_details())

        ttk.Checkbutton(
            controls,
            text="Index 0 transparent",
            variable=self.transparent_var,
            command=self.render_current,
        ).grid(row=0, column=4, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            controls,
            text="Pixel grid",
            variable=self.grid_var,
            command=self.render_current,
        ).grid(row=0, column=5, sticky="w")
        controls.columnconfigure(1, weight=1)

        right_pane = ttk.Panedwindow(right, orient=tk.VERTICAL)
        right_pane.pack(fill=tk.BOTH, expand=True)

        preview_frame = ttk.LabelFrame(right_pane, text="Resource preview", padding=(7, 7))
        details_frame = ttk.Frame(right_pane)
        right_pane.add(preview_frame, weight=5)
        right_pane.add(details_frame, weight=2)

        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            preview_frame,
            background="#20252b",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        canvas_y = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        canvas_y.grid(row=0, column=1, sticky="ns")
        canvas_x = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        canvas_x.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=canvas_y.set, xscrollcommand=canvas_x.set)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", lambda _event: self.status_var.set(self._base_status))

        notebook = ttk.Notebook(details_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        details_tab = ttk.Frame(notebook, padding=6)
        hex_tab = ttk.Frame(notebook, padding=6)
        notebook.add(details_tab, text="Details")
        notebook.add(hex_tab, text="Hex data")

        self.details_text = self._make_text_panel(details_tab, wrap=tk.WORD)
        self.hex_text = self._make_text_panel(hex_tab, wrap=tk.NONE)

        status = ttk.Label(
            self,
            textvariable=self.status_var,
            style="Status.TLabel",
            relief=tk.SUNKEN,
            anchor=tk.W,
        )
        status.pack(fill=tk.X, side=tk.BOTTOM)

        self._show_canvas_message("Open a .DAT file to inspect its resources.")

    def _make_text_panel(self, parent: ttk.Frame, *, wrap: str) -> tk.Text:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        text = tk.Text(
            parent,
            wrap=wrap,
            height=8,
            font=("Consolas", 10),
            background="#fbfbfb",
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        text.grid(row=0, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=text.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll_y.set, state=tk.DISABLED)
        if wrap == tk.NONE:
            scroll_x = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=text.xview)
            scroll_x.grid(row=1, column=0, sticky="ew")
            text.configure(xscrollcommand=scroll_x.set)
        return text

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-o>", lambda _event: self.open_dialog())
        self.bind_all("<Control-e>", lambda _event: self.export_selected_image())
        self.bind_all("<Control-m>", lambda _event: self.open_comparison())
        self.bind_all("<Control-Shift-E>", lambda _event: self.open_composite_editor())
        self.bind_all("<F5>", lambda _event: self.refresh_preview_details())

    def open_dialog(self) -> None:
        initial = str(self.archive.path.parent) if self.archive else os.getcwd()
        filename = filedialog.askopenfilename(
            parent=self,
            title="Open Prince of Persia DAT",
            initialdir=initial,
            filetypes=(("Prince DAT files", "*.dat *.DAT"), ("All files", "*.*")),
        )
        if filename:
            self.open_archive(filename)

    def open_archive(self, filename: str | Path) -> None:
        if self.composite_editor is not None and self.composite_editor.winfo_exists():
            if not self.composite_editor._confirm_discard():
                return
            self.composite_editor.on_close_callback = None
            self.composite_editor.destroy()
            self.composite_editor = None
        for window in list(self.comparison_windows):
            if window.winfo_exists():
                window.on_close_callback = None
                window.destroy()
        self.comparison_windows.clear()
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            archive = DatArchive.open(filename)
        except DatFormatError as exc:
            messagebox.showerror("Cannot open DAT", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")

        self.archive = archive
        self.archive_context = ArchiveContext.discover(archive)
        self.current = None
        self.path_var.set(str(archive.path))
        self.title(f"{APP_NAME} {VERSION} — {archive.path.name}")
        self._install_palette_choices()
        self.refresh_tree()

        self._refresh_base_status()
        self.status_var.set(self._base_status)

        first_image = next(
            (analysis.resource.index for analysis in archive.analyses if analysis.image is not None),
            0,
        )
        iid = str(first_image)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self.on_tree_selection()
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.on_tree_selection()

    def _refresh_base_status(self) -> None:
        if self.archive is None or self.archive_context is None:
            self._base_status = "Open a Prince of Persia .DAT file to begin."
            return
        archive = self.archive
        images = sum(analysis.image is not None for analysis in archive.analyses)
        palettes = len(archive.embedded_palettes)
        bad = sum(not resource.checksum_ok for resource in archive.resources)
        checksum_text = "all checksums valid" if not bad else f"{bad} bad checksum(s)"
        self._base_status = (
            f"{archive.path.name}: {len(archive.resources)} resources, "
            f"{images} decoded images, {palettes} embedded palette(s), {checksum_text}."
        )
        if not self.archive_context.is_room_set:
            return
        loaded = [
            item.path.name
            for item in self.archive_context.archives.values()
            if item is not None
        ]
        missing = [
            self.archive_context.expected_filename(adapter)
            for adapter in ("cga", "ega", "vga")
            if self.archive_context.archives.get(adapter) is None
        ]
        self._base_status += " Linked room set: " + ", ".join(loaded) + "."
        if missing:
            self._base_status += " Missing: " + ", ".join(missing) + "."

    def _install_palette_choices(self) -> None:
        self.palette_box.configure(values=VIEW_CHOICES)
        self.palette_var.set(VIEW_CHOICES[0])

    def refresh_tree(self) -> None:
        selected = self.tree.selection()
        selected_iid = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        if self.archive is None:
            return

        filter_name = self.filter_var.get()
        needle = self.search_var.get().strip().lower()
        for analysis in self.archive.analyses:
            image = analysis.image
            if filter_name == "Images only" and image is None:
                continue
            if filter_name == "Palettes only" and analysis.palette is None:
                continue
            if filter_name == "Other data" and (image is not None or analysis.palette is not None):
                continue

            dimensions = f"{image.width}×{image.height}" if image else ""
            compression = image.compression_name.split()[0] if image else ""
            searchable = " ".join(
                (
                    str(analysis.resource.resource_id),
                    f"{analysis.resource.resource_id:05d}",
                    analysis.kind,
                    dimensions,
                    compression,
                )
            ).lower()
            if needle and needle not in searchable:
                continue

            resource = analysis.resource
            tags = () if resource.checksum_ok else ("bad",)
            self.tree.insert(
                "",
                tk.END,
                iid=str(resource.index),
                values=(
                    resource.resource_id,
                    analysis.kind,
                    dimensions,
                    compression,
                    f"{resource.size:,}",
                    "OK" if resource.checksum_ok else "BAD",
                ),
                tags=tags,
            )

        if selected_iid and self.tree.exists(selected_iid):
            self.tree.selection_set(selected_iid)

    def _sort_tree(self, column: str) -> None:
        children = list(self.tree.get_children())
        if not children:
            return
        numeric = column in ("id", "size")

        def key(item: str):
            value = self.tree.set(item, column).replace(",", "")
            if numeric:
                try:
                    return int(value)
                except ValueError:
                    return -1
            return value.lower()

        descending = bool(getattr(self, "_sort_state", {}).get(column, False))
        children.sort(key=key, reverse=descending)
        for position, item in enumerate(children):
            self.tree.move(item, "", position)
        self._sort_state = {column: not descending}

    def on_tree_selection(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection or self.archive is None:
            return
        resource_index = int(selection[0])
        self.current = self.archive.analysis_for_index(resource_index)
        self.render_current()
        self._update_text_panels()
        for window in list(self.comparison_windows):
            if window.winfo_exists():
                window.set_analysis(self.current)
            else:
                self.comparison_windows.remove(window)
        if self.composite_editor is not None:
            if self.composite_editor.winfo_exists():
                self.composite_editor.set_analysis(self.current)
            else:
                self.composite_editor = None

    def _selected_mode(self) -> str:
        assert self.archive is not None
        label = self.palette_var.get()
        return auto_display_mode(self.archive) if label.startswith("Auto") else VIEW_TO_MODE.get(label, "vga")

    def refresh_preview_details(self) -> None:
        self.render_current()
        self._update_text_panels()

    def render_current(self) -> None:
        self.canvas.delete("all")
        self.preview_photo = None
        self.preview_raster = None
        self.current_mode = None
        self.current_hardware_palette = None
        self.current_render_archive = None
        self.current_render_analysis = None
        if self.current is None:
            self._show_canvas_message("Select a resource to preview it.")
            return

        if self.current.image is not None:
            self._render_image(self.current.image)
        elif self.current.palette is not None:
            self._render_palette(self.current.palette)
        else:
            self._show_canvas_message(
                "This resource is not a recognized image.\n\n"
                "Use the Hex data tab or Export raw to inspect it."
            )

    def _render_image(self, image: DecodedImage) -> None:
        assert (
            self.archive is not None
            and self.archive_context is not None
            and self.current is not None
        )
        mode = self._selected_mode()
        self.current_mode = mode
        resolved = self.archive_context.analysis_for_display_mode(
            mode, self.current.resource.resource_id
        )
        if resolved is None:
            source = self.archive_context.source_description(mode)
            self._show_canvas_message(
                f"Resource {self.current.resource.resource_id} is unavailable in\n{source}.\n\n"
                "For DUNGEON/PALACE, use the Composite editor to choose missing E/V references."
            )
            return
        render_archive, render_analysis = resolved
        if render_analysis.image is None:
            self._show_canvas_message(
                f"Resource {self.current.resource.resource_id} is not an image in\n"
                f"{render_archive.path.name}."
            )
            return
        image = render_analysis.image
        hardware = hardware_palette_for_resource(
            render_archive, render_analysis.resource
        )
        self.current_render_archive = render_archive
        self.current_render_analysis = render_analysis
        self.current_hardware_palette = hardware
        rendered = render_display_mode(
            image,
            mode,
            hardware,
            transparent_zero=self.transparent_var.get(),
            checkerboard=True,
        )
        self.preview_raster = rendered
        ppm = (
            f"P6\n{rendered.width} {rendered.height}\n255\n".encode("ascii")
            + rendered.pixels
        )
        base_photo = tk.PhotoImage(data=ppm, format="PPM")
        x_zoom, x_subsample = display_horizontal_factors(mode, image.bits)
        display_width = normalized_display_width(rendered.width, mode, image.bits)
        scale = self._calculate_scale(display_width, rendered.height)
        max_pixels = 24_000_000
        while display_width * rendered.height * scale * scale > max_pixels and scale > 1:
            scale -= 1
        self.preview_scale = max(1, scale)
        self.preview_x_zoom = x_zoom
        self.preview_x_subsample = x_subsample
        zoom_x = self.preview_scale * x_zoom
        zoom_y = self.preview_scale
        photo = base_photo
        if zoom_x > 1 or zoom_y > 1:
            photo = photo.zoom(zoom_x, zoom_y)
        if x_subsample > 1:
            # Apply the half-width mode-6 pixel shape after zooming.  At even
            # zoom levels this retains every underlying bit instead of dropping
            # every second bit before enlargement.
            photo = photo.subsample(x_subsample, 1)
        self.preview_photo = photo

        rendered_width = photo.width()
        rendered_height = photo.height()
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        x = max(20, (canvas_width - rendered_width) // 2)
        y = max(20, (canvas_height - rendered_height) // 2)
        self.preview_origin = (x, y)
        self.canvas.create_image(x, y, image=self.preview_photo, anchor=tk.NW, tags=("preview",))

        pixel_width = self.preview_scale * x_zoom / x_subsample
        if self.grid_var.get() and self.preview_scale >= 6 and pixel_width >= 2:
            grid_color = "#47515c"
            for column in range(rendered.width + 1):
                gx = x + column * pixel_width
                self.canvas.create_line(gx, y, gx, y + rendered_height, fill=grid_color, tags=("grid",))
            for row in range(rendered.height + 1):
                gy = y + row * self.preview_scale
                self.canvas.create_line(x, gy, x + rendered_width, gy, fill=grid_color, tags=("grid",))

        scroll_width = max(canvas_width, x + rendered_width + 20)
        scroll_height = max(canvas_height, y + rendered_height + 20)
        self.canvas.configure(scrollregion=(0, 0, scroll_width, scroll_height))

    def _calculate_scale(self, display_width: int, height: int) -> int:
        value = self.zoom_var.get()
        if value != "Fit":
            try:
                return max(1, int(value.rstrip("x")))
            except ValueError:
                return 1

        available_width = max(1, self.canvas.winfo_width() - 44)
        available_height = max(1, self.canvas.winfo_height() - 44)
        return max(1, min(16, available_width // display_width, available_height // height))

    def _render_palette(self, palette: PrincePalette) -> None:
        cell_width = 112
        cell_height = 70
        margin = 24
        columns = 4
        rows = (len(palette.colors) + columns - 1) // columns
        for index, color in enumerate(palette.colors):
            row, column = divmod(index, columns)
            x0 = margin + column * cell_width
            y0 = margin + row * cell_height
            x1 = x0 + cell_width - 10
            y1 = y0 + cell_height - 10
            fill = "#%02x%02x%02x" % color
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="#9299a1")
            luminance = color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114
            text_color = "#111111" if luminance > 150 else "#ffffff"
            label = f"{index:X}   {color[0]:3},{color[1]:3},{color[2]:3}"
            self.canvas.create_text(
                x0 + 8,
                y0 + 8,
                text=label,
                fill=text_color,
                anchor=tk.NW,
                font=("Consolas", 9),
            )
        width = margin * 2 + columns * cell_width
        height = margin * 2 + rows * cell_height
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _show_canvas_message(self, text: str) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 600)
        height = max(self.canvas.winfo_height(), 320)
        self.canvas.create_text(
            width // 2,
            height // 2,
            text=text,
            fill="#d7dde4",
            justify=tk.CENTER,
            width=max(300, width - 120),
            font=("Segoe UI", 12),
        )
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _update_text_panels(self) -> None:
        if self.current is None or self.archive is None:
            self._set_text(self.details_text, "")
            self._set_text(self.hex_text, "")
            return

        analysis = self.current
        resource = analysis.resource
        lines = [
            f"Archive:              {self.archive.path.name}",
            f"Resource ID:          {resource.resource_id} (0x{resource.resource_id:04X})",
            f"Index position:       {resource.index}",
            f"DAT offset:           0x{resource.offset:08X} ({resource.offset:,})",
            f"Content bytes:        {resource.size:,}",
            f"Stored checksum:      0x{resource.stored_checksum:02X}",
            f"Calculated checksum:  0x{resource.calculated_checksum:02X}",
            f"Checksum status:      {'OK' if resource.checksum_ok else 'BAD'}",
            f"Detected type:        {analysis.kind}",
        ]
        if analysis.image is not None:
            render_analysis = self.current_render_analysis or analysis
            render_archive = self.current_render_archive or self.archive
            image = render_analysis.image or analysis.image
            mode = self.current_mode or self._selected_mode()
            hardware = self.current_hardware_palette or hardware_palette_for_resource(
                render_archive, render_analysis.resource
            )
            preview_dimensions = (
                f"{self.preview_raster.width} × {self.preview_raster.height} pixels"
                if self.preview_raster is not None
                else "Pending render"
            )
            normalized_width = (
                normalized_display_width(self.preview_raster.width, mode, image.bits)
                if self.preview_raster is not None
                else None
            )
            lines.extend(
                (
                    "",
                    f"Preview source:       {render_archive.path.name}",
                    f"Preview resource idx: {render_analysis.resource.index}",
                    f"Source dimensions:    {image.width} × {image.height} pixels",
                    f"Raster dimensions:    {preview_dimensions}",
                    f"Normalized display:   {normalized_width} × {image.height} logical pixels"
                    if normalized_width is not None
                    else "Normalized display:   Pending render",
                    f"Pixel depth:          {image.bits} bit",
                    f"Type byte:            0x{image.type_byte:02X}",
                    f"Compression:          {image.compression_name}",
                    f"Decoded packed bytes: {len(image.packed_pixels):,}",
                    f"Display mode:         {mode.upper() if mode != 'composite' else 'Composite'}",
                    f"Hardware table:       {hardware.name if hardware else 'Fallback identity mapping'}",
                    f"Preview zoom:         {self.preview_scale}x",
                )
            )
            if mode == "mode6":
                lines.append(
                    "640 mapping:           CGA-translated value becomes two 1-bit pixels"
                )
            elif mode == "composite":
                lines.extend(
                    (
                        "Composite mapping:    four translated mode-6 bits become one color cell",
                        "Composite model:      DOSBox-X cga_composite2 (New CGA)",
                    )
                )
        elif analysis.palette is not None:
            lines.extend(
                (
                    "",
                    f"Palette colors:       {len(analysis.palette.colors)}",
                    f"Usable as RGB:        {'Yes' if analysis.palette.usable else 'No'}",
                    f"CGA translations:     {len(analysis.palette.cga_translation)} entries (4 phases × 16)",
                    f"EGA translations:     {len(analysis.palette.ega_translation)} entries (4 phases × 16)",
                )
            )
            if analysis.palette.note:
                lines.append(f"Note:                  {analysis.palette.note}")
        elif analysis.decode_error:
            lines.extend(("", f"Image probe:          {analysis.decode_error}"))

        self._set_text(self.details_text, "\n".join(lines))
        self._set_text(
            self.hex_text,
            "Resource content (DAT checksum byte excluded)\n\n" + hex_dump(resource.data),
        )

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def on_canvas_configure(self, _event=None) -> None:
        if self.zoom_var.get() != "Fit" or self.current is None or self.current.image is None:
            return
        if self._fit_after is not None:
            self.after_cancel(self._fit_after)
        self._fit_after = self.after(100, self._render_fitted_image)

    def _render_fitted_image(self) -> None:
        self._fit_after = None
        self.render_current()

    def on_canvas_motion(self, event: tk.Event) -> None:
        if (
            self.current_render_analysis is None
            or self.current_render_analysis.image is None
            or self.current_mode is None
            or self.preview_raster is None
        ):
            return
        image = self.current_render_analysis.image
        rendered = self.preview_raster
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        pixel_width = self.preview_scale * self.preview_x_zoom / self.preview_x_subsample
        x = int((canvas_x - self.preview_origin[0]) // pixel_width)
        y = int((canvas_y - self.preview_origin[1]) // self.preview_scale)
        if not (0 <= x < rendered.width and 0 <= y < rendered.height):
            self.status_var.set(self._base_status)
            return

        if rendered.mode == "mode6":
            bit, source_x, source_index = mode6_bit_at(
                image, x, y, self.current_hardware_palette
            )
            color = display_colors("mode6")[bit]
            self.status_var.set(
                f"640×200 bit x={x}, y={y}   source x={source_x}, index={source_index}   "
                f"bit={bit}   RGB={color[0]}, {color[1]}, {color[2]}"
            )
            return

        if rendered.mode == "composite":
            pattern, source_start, source_end = composite_pattern_at(
                image, x, y, self.current_hardware_palette
            )
            color = display_colors("composite")[pattern]
            source_label = (
                str(source_start)
                if source_start == source_end
                else f"{source_start}–{source_end}"
            )
            self.status_var.set(
                f"Composite cell x={x}, y={y}   source x={source_label}   "
                f"pattern={pattern:04b} (0x{pattern:X})   "
                f"RGB={color[0]}, {color[1]}, {color[2]}"
            )
            return

        source_index = image.pixels[y * image.width + x]
        index = translated_index(
            image, x, y, self.current_mode, self.current_hardware_palette
        )
        colors = (
            tuple((value, value, value) for value in range(256))
            if self.current_mode == "vga" and image.bits == 8
            else display_colors(self.current_mode, self.current_hardware_palette)
        )
        color = colors[index] if index < len(colors) else (255, 0, 255)
        self.status_var.set(
            f"Pixel x={x}, y={y}   source index={source_index:X} → {self.current_mode.upper()} index={index:X}   "
            f"RGB={color[0]}, {color[1]}, {color[2]}"
        )

    def export_selected_image(self) -> None:
        if (
            self.current is None
            or self.archive is None
            or self.archive_context is None
        ):
            messagebox.showinfo("Export image", "Select a decoded image resource first.", parent=self)
            return
        mode = self._selected_mode()
        resolved = self.archive_context.analysis_for_display_mode(
            mode, self.current.resource.resource_id
        )
        if resolved is None or resolved[1].image is None:
            messagebox.showinfo(
                "Export image",
                f"Resource {self.current.resource.resource_id} has no image in "
                f"{self.archive_context.source_description(mode)}.",
                parent=self,
            )
            return
        render_archive, render_analysis = resolved
        resource = render_analysis.resource
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export decoded image",
            initialdir=str(render_archive.path.parent),
            initialfile=f"{render_archive.path.stem}_res{resource.resource_id:05d}.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not filename:
            return
        hardware = hardware_palette_for_resource(render_archive, resource)
        try:
            write_display_png(
                filename,
                render_analysis.image,
                mode,
                hardware,
                transparent_zero=self.transparent_var.get(),
            )
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.status_var.set(f"Exported image to {filename}")

    def export_selected_raw(self) -> None:
        if self.current is None or self.archive is None:
            messagebox.showinfo("Export raw", "Select a resource first.", parent=self)
            return
        resource = self.current.resource
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export raw resource content",
            initialdir=str(self.archive.path.parent),
            initialfile=f"{self.archive.path.stem}_res{resource.resource_id:05d}.bin",
            defaultextension=".bin",
            filetypes=(("Binary file", "*.bin"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            Path(filename).write_bytes(resource.data)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.status_var.set(f"Exported raw resource content to {filename}")

    def extract_all_resources(self) -> None:
        if self.archive is None or self.archive_context is None:
            messagebox.showinfo("Extract all", "Open a DAT archive first.", parent=self)
            return
        label = self.palette_var.get()
        display_mode = "auto" if label.startswith("Auto") else VIEW_TO_MODE.get(label, "vga")
        source_archive = self.archive
        if display_mode != "auto":
            source_archive = self.archive_context.archive_for_display_mode(display_mode)
            if source_archive is None:
                messagebox.showinfo(
                    "Extract all",
                    f"{self.archive_context.source_description(display_mode)} is not loaded.",
                    parent=self,
                )
                return
        parent = filedialog.askdirectory(
            parent=self,
            title="Choose a parent folder for the extracted resources",
            initialdir=str(source_archive.path.parent),
            mustexist=True,
        )
        if not parent:
            return
        destination = Path(parent) / f"{source_archive.path.stem}_extracted"
        if destination.exists() and not messagebox.askyesno(
            "Folder exists",
            f"{destination}\n\nalready exists. Replace files with matching names?",
            parent=self,
        ):
            return

        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            images, other = extract_all(
                source_archive,
                destination,
                selected_display_mode=display_mode,
                transparent_zero=self.transparent_var.get(),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Extraction failed", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")
        messagebox.showinfo(
            "Extraction complete",
            f"Extracted {images} image(s) and {other} other resource(s).\n\n{destination}",
            parent=self,
        )
        self.status_var.set(f"Extraction complete: {destination}")

    def open_comparison(self) -> None:
        if self.archive is None or self.archive_context is None:
            messagebox.showinfo("Compare modes", "Open a DAT archive first.", parent=self)
            return
        window = ComparisonWindow(
            self,
            self.archive_context,
            self.current,
            on_close=self._comparison_closed,
        )
        self.comparison_windows.append(window)
        window.transient(self)

    def _comparison_closed(self, window: ComparisonWindow) -> None:
        if window in self.comparison_windows:
            self.comparison_windows.remove(window)

    def open_composite_editor(self) -> None:
        if self.archive is None or self.archive_context is None:
            messagebox.showinfo("Composite editor", "Open a DAT archive first.", parent=self)
            return
        if self.composite_editor is not None and self.composite_editor.winfo_exists():
            self.composite_editor.deiconify()
            self.composite_editor.lift()
            self.composite_editor.focus_force()
            self.composite_editor.set_analysis(self.current)
            return
        if self.archive_context.is_room_set and self.archive_context.composite_target is None:
            expected = self.archive_context.expected_filename("cga")
            filename = filedialog.askopenfilename(
                parent=self,
                title=f"Choose {expected} composite target",
                initialdir=str(self.archive.path.parent),
                initialfile=expected,
                filetypes=(("Prince DAT files", "*.DAT *.dat"), ("All files", "*.*")),
            )
            if not filename:
                return
            try:
                target = DatArchive.open(filename)
                self.archive_context.attach("cga", target)
                self._refresh_base_status()
            except (DatFormatError, RoomSetError) as exc:
                messagebox.showerror("Cannot load CGA target", str(exc), parent=self)
                return
        try:
            self.composite_editor = CompositeEditorWindow(
                self,
                self.archive_context,
                self.current,
                on_close=self._composite_editor_closed,
                on_sources_changed=self._room_sources_changed,
            )
        except RoomSetError as exc:
            messagebox.showerror("Cannot open composite editor", str(exc), parent=self)

    def _room_sources_changed(self) -> None:
        self._refresh_base_status()
        self.render_current()
        self._update_text_panels()
        for window in list(self.comparison_windows):
            if window.winfo_exists():
                window.render()

    def _composite_editor_closed(self, _window: CompositeEditorWindow) -> None:
        self.composite_editor = None

    def close_app(self) -> None:
        if self.composite_editor is not None and self.composite_editor.winfo_exists():
            if not self.composite_editor._confirm_discard():
                return
        self.destroy()

    def show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {VERSION}\n\n"
            "POP1 DAT archive viewer and protected-source composite editor.\n"
            "Decodes RAW, RLE, transposed RLE, LZG, and transposed LZG resources.\n\n"
            "CGA/EGA previews use the archive's embedded phase translations.\n"
            "DUNGEON/PALACE comparisons link independent C/E/V archives by resource ID.\n"
            "Composite editing supports direct Mode-6 bits plus rough cells, with a\n"
            "neighbor-aware New-CGA-default artifact preview plus beam and exact "
            "selected/all-phase 640-column conversion.\n"
            "Work saves to a sidecar and a new patched DAT.\n\n"
            "Format research by the Princed Development Team.\n"
            "Licensed under GPL-2.0-or-later.",
            parent=self,
        )


def main() -> None:
    enable_windows_dpi_awareness()
    app = PrinceDatExplorer()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        app.after(120, lambda: app.open_archive(candidate))
    app.mainloop()


if __name__ == "__main__":
    main()
