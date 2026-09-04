"""Focused Tk workspace for V22 right/P0 and left/P0 actor artwork."""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from editor_windows import RasterPane
from animation_contact_sheet import render_v22_runtime_contact_sheet
from orientation_workspace import Direction, OrientationPair, V22OrientationWorkspace
from composite_project import CompositeProjectError
from prince_dat import DatFormatError, png_bytes


class V22OrientationEditorWindow(tk.Toplevel):
    """A phase-free linked editor matching the V22 runtime contract."""

    def __init__(
        self,
        parent: tk.Misc,
        source_path: str | Path,
        orient_path: str | Path,
        *,
        initial_resource_id: int | None = None,
        on_close=None,
    ) -> None:
        super().__init__(parent)
        self.workspace = V22OrientationWorkspace.open(source_path, orient_path)
        self.on_close = on_close
        self.title("V22 Runtime Workspace — linked ORIENT.DAT")
        self.geometry("1460x820")
        self.minsize(1050, 650)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.pair_var = tk.StringVar()
        self.context_var = tk.StringVar()
        self.zoom_var = tk.StringVar(value="6x")
        self.grid_var = tk.BooleanVar(value=True)
        self.transparent_var = tk.BooleanVar(value=True)
        self.brush_var = tk.IntVar(value=1)
        self.status_var = tk.StringVar(value="V22 inputs validated; source DAT is read-only.")
        self._drag_value: dict[Direction, int | None] = {"right": None, "left": None}
        self._sync_pending = False
        self._pairs_by_label: dict[str, OrientationPair] = {}

        self._build_ui()
        self._populate_pairs(initial_resource_id)
        self.bind("<Control-s>", lambda _event: self.export_orient())

    @property
    def dirty(self) -> bool:
        return self.workspace.project.dirty

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=9)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Frame:").pack(side=tk.LEFT)
        self.pair_box = ttk.Combobox(
            top, textvariable=self.pair_var, state="readonly", width=43
        )
        self.pair_box.pack(side=tk.LEFT, padx=(6, 10))
        self.pair_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        ttk.Label(top, text="Guard context:").pack(side=tk.LEFT)
        self.context_box = ttk.Combobox(
            top,
            textvariable=self.context_var,
            state="readonly",
            width=10,
            values=("Dungeon", "Palace"),
        )
        self.context_box.pack(side=tk.LEFT, padx=(6, 14))
        self.context_box.bind("<<ComboboxSelected>>", lambda _event: self._context_changed())
        if self.workspace.family != "GUARD":
            self.context_box.configure(state="disabled")

        ttk.Label(top, text="Zoom:").pack(side=tk.LEFT)
        zoom = ttk.Combobox(
            top,
            textvariable=self.zoom_var,
            state="readonly",
            width=5,
            values=("1x", "2x", "3x", "4x", "6x", "8x", "12x", "16x"),
        )
        zoom.pack(side=tk.LEFT, padx=(6, 10))
        zoom.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Checkbutton(top, text="Grid", variable=self.grid_var, command=self.refresh).pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(
            top,
            text="Show transparency",
            variable=self.transparent_var,
            command=self.refresh,
        ).pack(side=tk.LEFT, padx=(10, 0))

        action = ttk.Frame(self, padding=(9, 0, 9, 8))
        action.pack(fill=tk.X)
        ttk.Label(action, text="Pencil:").pack(side=tk.LEFT)
        ttk.Radiobutton(action, text="Black / 0", variable=self.brush_var, value=0).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Radiobutton(action, text="White / 1", variable=self.brush_var, value=1).pack(
            side=tk.LEFT, padx=(6, 14)
        )
        ttk.Button(
            action, text="Generate Right (exhaustive)", command=lambda: self.generate("right")
        ).pack(side=tk.LEFT)
        ttk.Button(
            action, text="Generate Left (exhaustive)", command=lambda: self.generate("left")
        ).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Button(action, text="Generate Both", command=self.generate_both).pack(
            side=tk.LEFT, padx=(7, 0)
        )
        ttk.Button(action, text="Runtime contact sheet…", command=self.export_contact_sheet).pack(
            side=tk.LEFT, padx=(7, 0)
        )
        ttk.Button(action, text="Export complete ORIENT.DAT…", command=self.export_orient).pack(
            side=tk.RIGHT
        )

        note = ttk.Label(
            self,
            padding=(10, 0, 10, 7),
            foreground="#34566f",
            text=(
                "Actual runtime views only: both are P0. Click/drag either output to edit that "
                "orientation. Right includes Prince's runtime source-pixel reversal; Left is native."
            ),
        )
        note.pack(fill=tk.X)

        panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=9, pady=(0, 8))
        self.source_pane = RasterPane(panes, "Original VGA reference (read-only)")
        self.right_pane = RasterPane(panes, "Actual in-game Right / P0 (editable)")
        self.left_pane = RasterPane(panes, "Actual in-game Left / P0 (editable)")
        panes.add(self.source_pane, weight=1)
        panes.add(self.right_pane, weight=1)
        panes.add(self.left_pane, weight=1)

        for pane, direction in ((self.right_pane, "right"), (self.left_pane, "left")):
            pane.canvas.bind(
                "<Button-1>", lambda event, d=direction: self._paint(event, d, start=True)
            )
            pane.canvas.bind(
                "<B1-Motion>", lambda event, d=direction: self._paint(event, d, start=False)
            )
            pane.canvas.bind(
                "<ButtonRelease-1>", lambda _event, d=direction: self._end_paint(d)
            )
        for pane in (self.source_pane, self.right_pane, self.left_pane):
            pane.canvas.bind("<MouseWheel>", self._schedule_sync, add="+")
            pane.canvas.bind("<ButtonRelease-1>", self._schedule_sync, add="+")

        status = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _populate_pairs(self, initial_resource_id: int | None) -> None:
        pairs = list(self.workspace.pairs)
        if self.workspace.family == "GUARD":
            self.context_var.set("Dungeon")
            pairs = [pair for pair in pairs if pair.table.context == "Dungeon"]
        self._set_pair_values(pairs, initial_resource_id)

    def _set_pair_values(
        self, pairs: list[OrientationPair], initial_resource_id: int | None = None
    ) -> None:
        self._pairs_by_label = {pair.label: pair for pair in pairs}
        values = tuple(self._pairs_by_label)
        self.pair_box.configure(values=values)
        selected = next(
            (pair.label for pair in pairs if pair.source_resource_id == initial_resource_id),
            values[0] if values else "",
        )
        self.pair_var.set(selected)
        self.refresh()

    def _context_changed(self) -> None:
        current = self.current_pair()
        resource_id = current.source_resource_id if current else None
        pairs = [
            pair for pair in self.workspace.pairs
            if pair.table.context == self.context_var.get()
        ]
        self._set_pair_values(pairs, resource_id)

    def current_pair(self) -> OrientationPair | None:
        return self._pairs_by_label.get(self.pair_var.get())

    def _scale(self) -> int:
        try:
            return max(1, int(self.zoom_var.get().rstrip("x")))
        except ValueError:
            return 1

    def refresh(self) -> None:
        pair = self.current_pair()
        if pair is None:
            return
        try:
            source = self.workspace.source_raster(
                pair, transparent=self.transparent_var.get()
            )
            right = self.workspace.runtime_raster(
                pair, "right", transparent=self.transparent_var.get()
            )
            left = self.workspace.runtime_raster(
                pair, "left", transparent=self.transparent_var.get()
            )
        except (CompositeProjectError, ValueError) as exc:
            messagebox.showerror("Cannot render V22 frame", str(exc), parent=self)
            return
        scale = self._scale()
        grid = self.grid_var.get()
        # VGA source pixels are twice as wide as the Mode-6 samples. The extra
        # horizontal zoom keeps all three panes spatially comparable.
        self.source_pane.show(source, scale=scale, x_zoom=2, cell_grid=grid)
        self.right_pane.show(right, scale=scale, cell_grid=grid)
        self.left_pane.show(left, scale=scale, cell_grid=grid)
        self.status_var.set(
            f"{pair.label}  |  ORIENT R{pair.right_resource_id} / R{pair.left_resource_id}"
        )

    def _paint(self, event: tk.Event, direction: Direction, *, start: bool) -> None:
        pair = self.current_pair()
        pane = self.right_pane if direction == "right" else self.left_pane
        coords = pane.raster_coordinates(event)
        if pair is None or coords is None:
            return
        x, y = coords
        value = self.brush_var.get()
        if start:
            self._drag_value[direction] = value
        else:
            value = self._drag_value[direction]
            if value is None:
                return
        try:
            if self.workspace.set_display_bit(pair, direction, x, y, int(value)):
                self.refresh()
        except CompositeProjectError as exc:
            self.status_var.set(str(exc))

    def _end_paint(self, direction: Direction) -> None:
        self._drag_value[direction] = None

    def _schedule_sync(self, event=None) -> None:
        if self._sync_pending:
            return
        self._sync_pending = True
        source_canvas = event.widget if event is not None else self.right_pane.canvas
        self.after_idle(lambda: self._sync_from(source_canvas))

    def _sync_from(self, source_canvas: tk.Canvas) -> None:
        self._sync_pending = False
        x = source_canvas.xview()[0]
        y = source_canvas.yview()[0]
        for pane in (self.source_pane, self.right_pane, self.left_pane):
            if pane.canvas is not source_canvas:
                pane.canvas.xview_moveto(x)
                pane.canvas.yview_moveto(y)

    def generate(self, direction: Direction) -> None:
        pair = self.current_pair()
        if pair is None:
            return
        self.configure(cursor="watch")
        self.status_var.set(f"Exhaustively optimizing {pair.label} {direction}/P0…")
        self.update_idletasks()
        try:
            result = self.workspace.generate_exhaustive(pair, direction)
        except (CompositeProjectError, ValueError) as exc:
            messagebox.showerror("Conversion failed", str(exc), parent=self)
        else:
            self.status_var.set(
                f"Generated {direction}/P0 for {pair.label}; signal RMSE {result.source_rmse:.2f}."
            )
            self.refresh()
        finally:
            self.configure(cursor="")

    def generate_both(self) -> None:
        self.generate("right")
        self.generate("left")

    def export_orient(self) -> None:
        initial = self.workspace.orient.path.with_name("ORIENT-EDITED.DAT")
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export complete V22 ORIENT.DAT",
            initialdir=str(initial.parent),
            initialfile=initial.name,
            defaultextension=".DAT",
            filetypes=(("Prince DAT files", "*.DAT"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            target, changed, digest = self.workspace.export(filename)
        except (CompositeProjectError, DatFormatError, OSError, ValueError) as exc:
            messagebox.showerror("V22 export failed", str(exc), parent=self)
        else:
            self.status_var.set(f"Exported complete {target.name}: {changed} changed resource(s).")
            messagebox.showinfo(
                "V22 export verified",
                f"Complete 889-resource ORIENT.DAT written to:\n{target}\n\n"
                f"Changed images: {changed}\nSHA-256: {digest}",
                parent=self,
            )
        finally:
            self.configure(cursor="")

    def export_contact_sheet(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export V22 right/left runtime contact sheet",
            initialdir=str(self.workspace.orient.path.parent),
            initialfile=f"{self.workspace.family}-V22-RIGHT-LEFT-P0.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            sheet = render_v22_runtime_contact_sheet(self.workspace)
            Path(filename).write_bytes(png_bytes(sheet))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Contact-sheet export failed", str(exc), parent=self)
        else:
            self.status_var.set(f"Exported actual-runtime contact sheet: {filename}")
        finally:
            self.configure(cursor="")

    def close(self) -> None:
        if self.dirty and not messagebox.askyesno(
            "Discard V22 edits?",
            "There are unexported ORIENT.DAT changes. Close and discard them?",
            parent=self,
        ):
            return
        callback = self.on_close
        self.destroy()
        if callback is not None:
            callback(self)
