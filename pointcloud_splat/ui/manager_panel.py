# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Side tray panel and dialog for Point Cloud & Gaussian Splatting."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union

import numpy as np

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette, QVector3D
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from views.fold_section import FoldSection, wrapping_form
from core.i18n import tr

from ..data_models import PointCloudDataset, GaussianSplatDataset
from ..parsers import (
    read_ply,
    read_splat,
    read_xyz,
    read_las,
    generate_demo_pointcloud,
    generate_demo_splats,
)
from ..cad_tools import (
    create_plane_surface_group,
    create_bounding_box_group,
    convert_to_guide_points,
)
from ..scene_proxy import (
    create_pointcloud_proxy,
    remove_pointcloud_proxy,
    sync_proxy_from_dataset,
)
from .icons import clear_cache, make_icon

log = logging.getLogger("ingetrazo.plugins.pointcloud_splat")


# ---- Static UI tables ---------------------------------------------------------

# (color_mode, colormap, label)
COLOR_MODES = [
    ("rgb", "turbo", "True Color (RGB / SH)"),
    ("elevation", "turbo", "Elevation · Turbo"),
    ("elevation", "viridis", "Elevation · Viridis"),
    ("elevation", "jet", "Elevation · Jet"),
    ("elevation", "terrain", "Elevation · Terrain"),
    ("intensity", "turbo", "Intensity"),
    ("normals", "turbo", "Surface Normals"),
    ("solid", "turbo", "Solid Color"),
]

# (budget, label)
POINT_BUDGETS = [
    (500_000, "0.5 M points"),
    (1_000_000, "1 M points"),
    (3_000_000, "3 M points"),
    (6_000_000, "6 M points"),
    (12_000_000, "12 M points"),
    (99_999_999, "Unlimited"),
]
DEFAULT_BUDGET_INDEX = 3

# (label, factor)
SCALE_PRESETS = [
    ("Millimetres → metres", 0.001),
    ("Centimetres → metres", 0.01),
    ("Inches → metres", 0.0254),
    ("Feet → metres", 0.3048),
    ("Metres (1 : 1)", 1.0),
]

CLOUD_EXTS = (".ply", ".xyz", ".pts", ".las", ".laz", ".txt", ".csv")
SPLAT_EXTS = (".ply", ".splat")
SUPPORTED_EXTS = frozenset(CLOUD_EXTS + SPLAT_EXTS)

_COORD_LIMIT = 1.0e7  # metres — large enough for georeferenced (UTM) scans


def _is_splat(ds) -> bool:
    return bool(getattr(ds, "is_gaussian_splat", False)) or isinstance(ds, GaussianSplatDataset)


def _rgba(c: QColor, alpha: float) -> str:
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(max(0.0, min(1.0, alpha)) * 255)})"


class PointCloudManagerPanel(QWidget):
    """Side tray panel for importing, configuring, and analysing point clouds and splats."""

    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pcPanel")
        self.app = app
        self.datasets: List[Union[PointCloudDataset, GaussianSplatDataset]] = []
        self._active_idx: int = -1
        self._icon_targets: list = []        # (widget/action, icon name) for theme refresh
        self._dataset_widgets: list = []     # controls enabled only with an active dataset
        self._styling: bool = False
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        body = QWidget()
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(8, 8, 8, 8)
        self.lay.setSpacing(6)

        self._build_datasets_list()
        self._build_display_section()
        self._build_clipping_section()
        self._build_transform_section()
        self._build_cad_tools_section()
        self.lay.addStretch(1)

        outer.addWidget(self._build_status_footer())

        self._apply_style()
        self._refresh_table()
        self._sync_ui_state()

        # Periodic sync with native viewport selection
        self._sel_timer = QTimer(self)
        self._sel_timer.setInterval(200)
        self._sel_timer.timeout.connect(self._sync_selection_from_scene)
        self._sel_timer.start()

    # ---- Small widget helpers -----------------------------------------------

    def _register_icon(self, target, name: str) -> None:
        self._icon_targets.append((target, name))
        target.setIcon(make_icon(name))

    def _icon_button(self, icon: str, tip: str, slot=None, text: Optional[str] = None,
                     object_name: str = "pcIconBtn") -> QToolButton:
        btn = QToolButton()
        btn.setObjectName(object_name)
        btn.setAutoRaise(True)
        btn.setToolTip(tip)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        if text:
            btn.setText(text)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        else:
            btn.setFixedSize(28, 28)
        self._register_icon(btn, icon)
        if slot is not None:
            btn.clicked.connect(slot)
        return btn

    def _action_button(self, icon: str, text: str, tip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("pcAction")
        btn.setToolTip(tip)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        self._register_icon(btn, icon)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _muted_label(text: str = "", wrap: bool = True) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("pcMuted")
        lbl.setWordWrap(wrap)
        return lbl

    @staticmethod
    def _spin(lo: float, hi: float, decimals: int = 3, step: float = 0.1,
              prefix: str = "", suffix: str = "") -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        sp.setSingleStep(step)
        sp.setKeyboardTracking(False)   # commit on Enter / focus-out, not per keystroke
        sp.setAccelerated(True)
        sp.setMinimumWidth(56)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if prefix:
            sp.setPrefix(prefix)
        if suffix:
            sp.setSuffix(suffix)
        return sp

    @staticmethod
    def _row(*widgets, stretch_first: bool = False) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for i, wid in enumerate(widgets):
            h.addWidget(wid, 1 if (stretch_first and i == 0) else 0)
        return w

    def _ds_widget(self, w):
        """Mark a control as requiring an active dataset."""
        self._dataset_widgets.append(w)
        return w

    # ---- Theme / style --------------------------------------------------------

    def _apply_style(self) -> None:
        if self._styling:
            return
        self._styling = True
        try:
            pal = self.palette()
            txt = pal.color(QPalette.WindowText)
            hl = pal.color(QPalette.Highlight)
            self.setStyleSheet(f"""
                QFrame#pcHeader {{ border-bottom: 1px solid {_rgba(txt, 0.10)}; }}
                QFrame#pcFooter {{ border-top: 1px solid {_rgba(txt, 0.10)}; }}
                QFrame#pcVSep {{ background: {_rgba(txt, 0.16)}; border: none; }}

                QToolButton#pcIconBtn {{
                    background: transparent; border: 1px solid transparent;
                    border-radius: 4px; padding: 4px;
                }}
                QToolButton#pcIconBtn:hover {{ background: {_rgba(txt, 0.08)}; border-color: {_rgba(txt, 0.14)}; }}
                QToolButton#pcIconBtn:pressed {{ background: {_rgba(txt, 0.16)}; }}
                QToolButton#pcIconBtn:disabled {{ background: transparent; border-color: transparent; }}

                QToolButton#pcImportBtn {{
                    background: {_rgba(txt, 0.05)}; border: 1px solid {_rgba(txt, 0.18)};
                    border-radius: 4px; padding: 4px 18px 4px 8px; font-weight: 600;
                }}
                QToolButton#pcImportBtn:hover {{ background: {_rgba(hl, 0.22)}; border-color: {hl.name()}; }}
                QToolButton#pcImportBtn::menu-indicator {{
                    subcontrol-origin: padding; subcontrol-position: center right; right: 5px;
                }}

                QTreeWidget#pcTree {{ border: 1px solid {_rgba(txt, 0.12)}; border-radius: 4px; }}
                QTreeWidget#pcTree::item {{ padding: 3px 0px; }}

                QFrame#pcEmpty {{ border: 1px dashed {_rgba(txt, 0.22)}; border-radius: 6px; }}
                QLabel#pcEmptyTitle {{ font-weight: 600; }}
                QLabel#pcMuted {{ color: {_rgba(txt, 0.62)}; font-size: 10px; }}
                QLabel#pcAxis {{ color: {_rgba(txt, 0.62)}; font-weight: 600; }}

                QPushButton#pcAction {{ text-align: left; padding: 5px 8px; }}
                QPushButton#pcSwatch {{ border: 1px solid {_rgba(txt, 0.30)}; border-radius: 3px; }}
            """)
        finally:
            self._styling = False

    def _refresh_icons(self) -> None:
        clear_cache()
        alive = []
        for target, name in self._icon_targets:
            try:
                target.setIcon(make_icon(name))
                alive.append((target, name))
            except RuntimeError:  # underlying C++ object deleted
                pass
        self._icon_targets = alive
        if hasattr(self, "_empty_icon"):
            self._empty_icon.setPixmap(make_icon("cloud_points", 32).pixmap(32, 32, mode=_disabled_mode()))
        if hasattr(self, "_hint_icon"):
            self._hint_icon.setPixmap(make_icon("info", 14).pixmap(14, 14))
        if hasattr(self, "_snap_icon"):
            self._snap_icon.setPixmap(make_icon("magnet", 16).pixmap(16, 16))
        self._refresh_table()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.type() == QEvent.PaletteChange and not self._styling:
            self._apply_style()
            self._refresh_icons()
        super().changeEvent(event)

    # ---- Header (fixed toolbar) ----------------------------------------------

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("pcHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(2)

        # Single "Import" entry point with a dropdown menu
        self.btn_import = self._icon_button("import", tr("Import point clouds or Gaussian splats"),
                                            text=tr("Import"), object_name="pcImportBtn")
        self.btn_import.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_import)
        act_cloud = menu.addAction(tr("Point Cloud…"))
        act_cloud.setToolTip(tr("PLY, LAS, XYZ, PTS, TXT, CSV"))
        act_cloud.triggered.connect(self._import_cloud_dialog)
        self._register_icon(act_cloud, "cloud_points")
        act_splat = menu.addAction(tr("Gaussian Splat…"))
        act_splat.setToolTip(tr("3DGS PLY, SPLAT"))
        act_splat.triggered.connect(self._import_splat_dialog)
        self._register_icon(act_splat, "splat")
        menu.addSeparator()
        samples = menu.addMenu(tr("Sample Data"))
        self._register_icon(samples.menuAction(), "sample")
        act_demo_pc = samples.addAction(tr("Architectural LiDAR Scan"))
        act_demo_pc.triggered.connect(self._load_demo_pointcloud)
        act_demo_gs = samples.addAction(tr("Gaussian Splat Scene"))
        act_demo_gs.triggered.connect(self._load_demo_splats)
        menu.setToolTipsVisible(True)
        self.btn_import.setMenu(menu)
        row.addWidget(self.btn_import)
        row.addStretch(1)

        self.btn_zoom = self._icon_button("focus", tr("Zoom to fit active dataset  (double-click a row)"),
                                          self.zoom_to_active)
        self.btn_select = self._icon_button("cursor", tr("Select in viewport — then press M to move or Q to rotate"),
                                            self._select_in_viewport)
        row.addWidget(self.btn_zoom)
        row.addWidget(self.btn_select)

        sep = QFrame()
        sep.setObjectName("pcVSep")
        sep.setFixedSize(1, 18)
        row.addSpacing(4)
        row.addWidget(sep)
        row.addSpacing(4)

        self.btn_remove = self._icon_button("trash", tr("Remove active dataset"), self._remove_active_dataset)
        self.btn_clear = self._icon_button("clear_all", tr("Remove all datasets"), self.clear_all)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        return header

    # ---- Dataset list -------------------------------------------------------

    def _build_datasets_list(self) -> None:
        self._list_stack = QStackedWidget()

        # Page 0 — empty state
        empty = QFrame()
        empty.setObjectName("pcEmpty")
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(12, 14, 12, 14)
        ev.setSpacing(6)
        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignCenter)
        self._empty_icon.setPixmap(make_icon("cloud_points", 32).pixmap(32, 32, mode=_disabled_mode()))
        ev.addWidget(self._empty_icon)
        title = QLabel(tr("No datasets loaded"))
        title.setObjectName("pcEmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        ev.addWidget(title)
        sub = self._muted_label(tr("Import a point cloud or Gaussian splat, or drop files onto this panel."))
        sub.setAlignment(Qt.AlignCenter)
        ev.addWidget(sub)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addStretch(1)
        b_pc = self._action_button("cloud_points", tr("Point Cloud"), tr("Import a point cloud"),
                                   self._import_cloud_dialog)
        b_gs = self._action_button("splat", tr("Gaussian Splat"), tr("Import a 3D Gaussian Splat"),
                                   self._import_splat_dialog)
        btns.addWidget(b_pc)
        btns.addWidget(b_gs)
        btns.addStretch(1)
        ev.addLayout(btns)
        self._list_stack.addWidget(empty)

        # Page 1 — dataset tree + info line
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)

        self.tree = QTreeWidget()
        self.tree.setObjectName("pcTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["", tr("Name"), tr("Points")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, 28)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.setMinimumHeight(84)
        self.tree.setMaximumHeight(168)
        self.tree.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(lambda *_: self.zoom_to_active())
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        pv.addWidget(self.tree)

        self.lbl_info = self._muted_label()
        pv.addWidget(self.lbl_info)
        self._list_stack.addWidget(page)

        self.lay.addWidget(self._list_stack)

    # ---- Display section ----------------------------------------------------

    def _build_display_section(self) -> None:
        sec = FoldSection(tr("Display"), "pointcloud_display", parent=self, default_open=True)
        form = wrapping_form(sec.body)
        self._display_form = form

        self.combo_color_mode = self._ds_widget(QComboBox())
        for _mode, _cmap, label in COLOR_MODES:
            self.combo_color_mode.addItem(tr(label))
        self.combo_color_mode.setToolTip(tr("How points are coloured (point clouds only)"))
        self.combo_color_mode.currentIndexChanged.connect(self._on_color_mode_changed)
        form.addRow(tr("Color"), self.combo_color_mode)

        self.btn_solid_color = self._ds_widget(QPushButton())
        self.btn_solid_color.setObjectName("pcSwatch")
        self.btn_solid_color.setFixedHeight(20)
        self.btn_solid_color.setCursor(Qt.PointingHandCursor)
        self.btn_solid_color.setToolTip(tr("Choose solid tint"))
        self._update_color_button((0, 200, 255))
        self.btn_solid_color.clicked.connect(self._pick_solid_color)
        form.addRow(tr("Tint"), self.btn_solid_color)

        self.spin_point_size = self._ds_widget(QSpinBox())
        self.spin_point_size.setRange(1, 14)
        self.spin_point_size.setValue(2)
        self.spin_point_size.setSuffix(" px")
        self.spin_point_size.valueChanged.connect(self._on_display_setting_changed)
        form.addRow(tr("Point size"), self.spin_point_size)

        self.spin_splat_scale = self._ds_widget(QDoubleSpinBox())
        self.spin_splat_scale.setRange(0.1, 4.0)
        self.spin_splat_scale.setSingleStep(0.1)
        self.spin_splat_scale.setValue(1.0)
        self.spin_splat_scale.setSuffix(" ×")
        self.spin_splat_scale.setToolTip(tr("Multiplier for the Gaussian footprint"))
        self.spin_splat_scale.valueChanged.connect(self._on_display_setting_changed)
        form.addRow(tr("Splat scale"), self.spin_splat_scale)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(5, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.valueChanged.connect(self._on_display_setting_changed)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setMinimumWidth(34)
        self.lbl_opacity.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._opacity_row = self._ds_widget(self._row(self.slider_opacity, self.lbl_opacity, stretch_first=True))
        form.addRow(tr("Opacity"), self._opacity_row)

        self.combo_budget = QComboBox()
        for _budget, label in POINT_BUDGETS:
            self.combo_budget.addItem(tr(label))
        self.combo_budget.setCurrentIndex(DEFAULT_BUDGET_INDEX)
        self.combo_budget.setToolTip(tr("Maximum points / splats drawn per frame (applies to all datasets)"))
        self.combo_budget.currentIndexChanged.connect(self._on_budget_changed)
        form.addRow(tr("Budget"), self.combo_budget)

        self.lay.addWidget(sec)

    # ---- Section box --------------------------------------------------------

    def _build_clipping_section(self) -> None:
        sec = FoldSection(tr("Section Box"), "pointcloud_clipping", parent=self, default_open=False)
        vbox = QVBoxLayout(sec.body)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(6)

        self.chk_clipping = QCheckBox(tr("Enable section box"))
        self.chk_clipping.setToolTip(tr("Clip point clouds to an axis-aligned box in world coordinates.\n"
                                        "Gaussian splats are not clipped."))
        self.chk_clipping.toggled.connect(self._on_clipping_toggled)
        vbox.addWidget(self.chk_clipping)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.addWidget(self._muted_label(tr("Min (m)"), wrap=False), 0, 1)
        grid.addWidget(self._muted_label(tr("Max (m)"), wrap=False), 0, 2)

        self.spin_x_min, self.spin_x_max = self._spin(-_COORD_LIMIT, _COORD_LIMIT), self._spin(-_COORD_LIMIT, _COORD_LIMIT)
        self.spin_y_min, self.spin_y_max = self._spin(-_COORD_LIMIT, _COORD_LIMIT), self._spin(-_COORD_LIMIT, _COORD_LIMIT)
        self.spin_z_min, self.spin_z_max = self._spin(-_COORD_LIMIT, _COORD_LIMIT), self._spin(-_COORD_LIMIT, _COORD_LIMIT)
        for r, (axis, lo, hi) in enumerate((
            ("X", self.spin_x_min, self.spin_x_max),
            ("Y", self.spin_y_min, self.spin_y_max),
            ("Z", self.spin_z_min, self.spin_z_max),
        ), start=1):
            lbl = QLabel(axis)
            lbl.setObjectName("pcAxis")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(lo, r, 1)
            grid.addWidget(hi, r, 2)
            lo.valueChanged.connect(self._on_clip_bounds_changed)
            hi.valueChanged.connect(self._on_clip_bounds_changed)
        vbox.addLayout(grid)

        btn_fit_clip = self._ds_widget(self._action_button(
            "focus", tr("Fit to Active Dataset"),
            tr("Set the box to the active dataset's bounds and enable clipping"),
            self._fit_clip_box_to_active))
        vbox.addWidget(btn_fit_clip)

        self.lay.addWidget(sec)

    # ---- Transform ------------------------------------------------------------

    def _build_transform_section(self) -> None:
        sec = FoldSection(tr("Transform"), "pointcloud_transform", parent=self, default_open=False)
        self.sec_transform = sec
        form = wrapping_form(sec.body)

        # Short hint about native interactive tools
        hint = QWidget()
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(0, 0, 0, 2)
        hl.setSpacing(6)
        self._hint_icon = QLabel()
        self._hint_icon.setPixmap(make_icon("info", 14).pixmap(14, 14))
        self._hint_icon.setAlignment(Qt.AlignTop)
        hl.addWidget(self._hint_icon, 0, Qt.AlignTop)
        hl.addWidget(self._muted_label(tr(
            "Select the dataset in the viewport, then use Move (M) or Rotate (Q / R) to place it "
            "interactively. All edits support Undo / Redo.")), 1)
        form.addRow(hint)

        # Position
        self.spin_off_x = self._ds_widget(self._spin(-_COORD_LIMIT, _COORD_LIMIT, step=0.5, prefix="X "))
        self.spin_off_y = self._ds_widget(self._spin(-_COORD_LIMIT, _COORD_LIMIT, step=0.5, prefix="Y "))
        self.spin_off_z = self._ds_widget(self._spin(-_COORD_LIMIT, _COORD_LIMIT, step=0.5, prefix="Z "))
        for sp in (self.spin_off_x, self.spin_off_y, self.spin_off_z):
            sp.valueChanged.connect(self._on_transform_changed)
        btn_reset_off = self._ds_widget(self._icon_button("reset", tr("Reset offset to (0, 0, 0)"), self._reset_offset))
        form.addRow(tr("Offset (m)"), self._row(self.spin_off_x, self.spin_off_y, self.spin_off_z, btn_reset_off))

        # Rotation
        self.spin_rot_z = self._ds_widget(self._spin(-360.0, 360.0, decimals=2, step=1.0, prefix="Z ", suffix="°"))
        self.spin_rot_x = self._ds_widget(self._spin(-360.0, 360.0, decimals=2, step=1.0, prefix="X ", suffix="°"))
        self.spin_rot_y = self._ds_widget(self._spin(-360.0, 360.0, decimals=2, step=1.0, prefix="Y ", suffix="°"))
        for sp in (self.spin_rot_z, self.spin_rot_x, self.spin_rot_y):
            sp.valueChanged.connect(self._on_transform_changed)
        btn_m90 = self._ds_widget(self._icon_button("rotate_ccw", tr("Rotate −90° about Z"), lambda: self._rotate_z_by(-90.0)))
        btn_p90 = self._ds_widget(self._icon_button("rotate_cw", tr("Rotate +90° about Z"), lambda: self._rotate_z_by(90.0)))
        btn_reset_rot = self._ds_widget(self._icon_button("reset", tr("Reset all rotations"), self._reset_rotation))
        form.addRow(tr("Yaw"), self._row(self.spin_rot_z, btn_m90, btn_p90, btn_reset_rot, stretch_first=True))
        form.addRow(tr("Tilt"), self._row(self.spin_rot_x, self.spin_rot_y))

        # Scale with unit presets
        self.spin_scale = self._ds_widget(self._spin(0.0001, 10000.0, decimals=4, step=0.01))
        self.spin_scale.setValue(1.0)
        self.spin_scale.valueChanged.connect(self._on_transform_changed)
        btn_units = self._ds_widget(self._icon_button("ruler", tr("Unit conversion presets")))
        btn_units.setPopupMode(QToolButton.InstantPopup)
        btn_units.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        units_menu = QMenu(btn_units)
        for label, factor in SCALE_PRESETS:
            act = units_menu.addAction(f"{tr(label)}   ({factor:g})")
            act.triggered.connect(lambda _=False, f=factor: self.spin_scale.setValue(f))
        btn_units.setMenu(units_menu)
        btn_reset_s = self._ds_widget(self._icon_button("reset", tr("Reset scale to 1.0"),
                                                        lambda: self.spin_scale.setValue(1.0)))
        form.addRow(tr("Scale"), self._row(self.spin_scale, btn_units, btn_reset_s, stretch_first=True))

        self.lay.addWidget(sec)

    # ---- Scan-to-BIM tools ----------------------------------------------------

    def _build_cad_tools_section(self) -> None:
        sec = FoldSection(tr("Scan-to-BIM"), "pointcloud_cad", parent=self, default_open=True)
        vbox = QVBoxLayout(sec.body)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)

        snap_row = QHBoxLayout()
        snap_row.setContentsMargins(2, 0, 0, 2)
        snap_row.setSpacing(6)
        self._snap_icon = QLabel()
        self._snap_icon.setPixmap(make_icon("magnet", 16).pixmap(16, 16))
        self.chk_snap = QCheckBox(tr("Snap drawing tools to points"))
        self.chk_snap.setToolTip(tr("Line, Tape and Push/Pull lock onto visible point-cloud points"))
        self.chk_snap.setChecked(True)
        self.chk_snap.toggled.connect(self._on_snap_toggled)
        snap_row.addWidget(self._snap_icon)
        snap_row.addWidget(self.chk_snap, 1)
        vbox.addLayout(snap_row)

        vbox.addWidget(self._ds_widget(self._action_button(
            "plane", tr("Fit Dominant Plane"),
            tr("Detect the largest planar surface (floor, wall) with RANSAC and create a face group"),
            self._fit_plane)))
        vbox.addWidget(self._ds_widget(self._action_button(
            "box", tr("Create Bounding Box"),
            tr("Create an axis-aligned bounding volume group around the active dataset"),
            self._create_bbox)))
        vbox.addWidget(self._ds_widget(self._action_button(
            "guide", tr("Add Guide Points"),
            tr("Place up to 120 guide points sampled from the active dataset"),
            self._convert_to_guides)))

        self.lay.addWidget(sec)

    # ---- Status footer --------------------------------------------------------

    def _build_status_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("pcFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(10, 5, 10, 6)
        self.lbl_status = self._muted_label(tr("Ready"))
        fl.addWidget(self.lbl_status, 1)
        return footer

    def _set_status(self, text: str) -> None:
        self.lbl_status.setText(text)
        self.lbl_status.setToolTip(text)

    # ---- Viewport selection sync ------------------------------------------------

    def _select_row(self, i: int) -> None:
        if 0 <= i < self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(i))

    def _sync_selection_from_scene(self) -> None:
        """Keep panel active selection synchronized with native viewport selection."""
        # Ensure all datasets have their proxy group in scene.groups
        for ds in self.datasets:
            grp = getattr(ds, "proxy_group", None)
            if grp is None or grp not in self.app.scene.groups:
                try:
                    create_pointcloud_proxy(ds, self.app.scene)
                except Exception:
                    pass

        sel = getattr(self.app.scene, "selection", ())
        if not sel:
            return
        for i, ds in enumerate(self.datasets):
            grp = getattr(ds, "proxy_group", None)
            if grp is not None and grp in sel:
                if self._active_idx != i:
                    self._active_idx = i
                    self.tree.blockSignals(True)
                    self._select_row(i)
                    self.tree.blockSignals(False)
                    self._sync_ui_state()
                return

    def _select_in_viewport(self) -> None:
        """Select the active point cloud in viewport and activate Select Tool."""
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        grp = getattr(ds, "proxy_group", None)
        if grp is not None:
            self.app.scene.select([grp])
            try:
                from tools.select import SelectTool
                self.app.viewport.set_active_tool(SelectTool(self.app.viewport))
            except Exception:
                pass
            self.app.viewport.update()
            if hasattr(self.app.viewport, "flash_status"):
                self.app.viewport.flash_status(tr("Point cloud selected. Press M to Move, Q or R to Rotate."))

    # ---- Dataset management -------------------------------------------------

    def add_dataset(self, ds: Union[PointCloudDataset, GaussianSplatDataset]) -> None:
        """Add a dataset and update the list."""
        # Default point size to at least 2 or 3 for visibility on high-DPI screens
        if getattr(ds, "point_size", 1) < 2:
            ds.point_size = 3

        # Auto-detect millimetre units if bounding box span exceeds 1,000
        auto_scaled = False
        if ds._raw_bounds is not None:
            span = float(np.max(ds._raw_bounds[1] - ds._raw_bounds[0]))
            if span > 1000.0 and ds.scale == 1.0:
                ds.scale = 0.001
                auto_scaled = True
                log.info(f"Auto-scaled {ds.name} from mm to m (scale 0.001)")

        self._apply_budget()
        self.datasets.append(ds)

        # Create native scene proxy for click selection and Move/Rotate tools
        try:
            create_pointcloud_proxy(ds, self.app.scene)
            if getattr(ds, "proxy_group", None) is not None:
                self.app.scene.select([ds.proxy_group])
        except Exception as e:
            log.warning(f"Failed to create scene proxy: {e}")

        self._active_idx = len(self.datasets) - 1
        self._refresh_table()
        self._select_row(self._active_idx)
        self._sync_ui_state()
        self.zoom_to_active()
        self.app.viewport.update()

        unit = tr("splats") if _is_splat(ds) else tr("points")
        msg = tr("Loaded {name} — {n:,} {unit}", name=ds.name, n=len(ds.coords), unit=unit)
        if auto_scaled:
            msg += " · " + tr("auto-scaled mm → m (see Transform › Scale)")
        self._set_status(msg)

    def clear_all(self) -> None:
        """Remove all loaded datasets (asks for confirmation)."""
        if not self.datasets:
            return
        if QMessageBox.question(
            self, tr("Remove All Datasets"),
            tr("Remove all {n} datasets from the session?", n=len(self.datasets)),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) != QMessageBox.Yes:
            return
        for ds in self.datasets:
            try:
                remove_pointcloud_proxy(ds, self.app.scene)
            except Exception:
                pass
        self.datasets.clear()
        self._active_idx = -1
        self._refresh_table()
        self._sync_ui_state()
        self.app.viewport.update()
        self._set_status(tr("All datasets removed"))

    def _remove_active_dataset(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        idx = self._active_idx
        ds = self.datasets[idx]
        name = ds.name
        try:
            remove_pointcloud_proxy(ds, self.app.scene)
        except Exception:
            pass
        del self.datasets[idx]
        self._active_idx = min(idx, len(self.datasets) - 1)
        self._refresh_table()
        if self._active_idx >= 0:
            self._select_row(self._active_idx)
        self._sync_ui_state()
        self.app.viewport.update()
        self._set_status(tr("Removed {name}", name=name))

    def _refresh_table(self) -> None:
        if not hasattr(self, "tree"):
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        muted = QColor(self.palette().color(QPalette.WindowText))
        muted.setAlphaF(0.45)
        for i, ds in enumerate(self.datasets):
            splat = _is_splat(ds)
            item = QTreeWidgetItem(["", ds.name, f"{len(ds.coords):,}"])
            item.setIcon(0, make_icon("eye" if ds.visible else "eye_off"))
            item.setToolTip(0, tr("Hide") if ds.visible else tr("Show"))
            item.setIcon(1, make_icon("splat" if splat else "cloud_points"))
            item.setToolTip(1, f"{ds.name}\n{tr('Gaussian splat') if splat else tr('Point cloud')}"
                               + (f"\n{ds.filepath}" if getattr(ds, 'filepath', None) else ""))
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            if not ds.visible:
                for col in (1, 2):
                    item.setForeground(col, muted)
            self.tree.addTopLevelItem(item)
            if i == self._active_idx:
                item.setSelected(True)
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

        # Fit list height to its rows (2..6 visible rows, then scroll)
        row_h = self.tree.sizeHintForRow(0) if self.datasets else 24
        row_h = max(row_h, 22)
        visible_rows = max(2, min(len(self.datasets), 6))
        self.tree.setFixedHeight(self.tree.header().sizeHint().height() + visible_rows * row_h + 6)

        has_data = bool(self.datasets)
        self._list_stack.setCurrentIndex(1 if has_data else 0)
        self.btn_clear.setEnabled(has_data)

    def _on_table_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        row = self.tree.indexOfTopLevelItem(items[0])
        if 0 <= row < len(self.datasets):
            self._active_idx = row
            self._sync_ui_state()
            grp = getattr(self.datasets[row], "proxy_group", None)
            if grp is not None:
                try:
                    self.app.scene.select([grp])
                except Exception:
                    pass

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        row = self.tree.indexOfTopLevelItem(item)
        if 0 <= row < len(self.datasets):
            self._toggle_visibility(row)

    def _toggle_visibility(self, row: int) -> None:
        ds = self.datasets[row]
        ds.visible = not ds.visible
        self._refresh_table()
        self.app.viewport.update()

    def _on_tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        row = self.tree.indexOfTopLevelItem(item)
        if not (0 <= row < len(self.datasets)):
            return
        self._select_row(row)
        ds = self.datasets[row]
        menu = QMenu(self)
        a_zoom = menu.addAction(make_icon("focus"), tr("Zoom to Fit"))
        a_sel = menu.addAction(make_icon("cursor"), tr("Select in Viewport"))
        a_vis = menu.addAction(make_icon("eye_off" if ds.visible else "eye"),
                               tr("Hide") if ds.visible else tr("Show"))
        menu.addSeparator()
        a_del = menu.addAction(make_icon("trash"), tr("Remove"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is a_zoom:
            self.zoom_to_active()
        elif chosen is a_sel:
            self._select_in_viewport()
        elif chosen is a_vis:
            self._toggle_visibility(row)
        elif chosen is a_del:
            self._remove_active_dataset()

    # ---- Import -------------------------------------------------------------

    def _import_cloud_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Import Point Cloud"),
            "",
            tr("Point Clouds (*.ply *.xyz *.pts *.las *.laz *.txt *.csv);;All Files (*.*)")
        )
        if path:
            self.load_file(path)

    def _import_splat_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Import 3D Gaussian Splat"),
            "",
            tr("Gaussian Splats (*.ply *.splat);;All Files (*.*)")
        )
        if path:
            self.load_file(path)

    def load_file(self, filepath: Union[str, Path]) -> bool:
        """Load any supported point cloud or splat file into the session."""
        path = Path(filepath)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            QMessageBox.warning(self, tr("Unsupported Format"),
                                tr("“{ext}” files are not supported.", ext=suffix or path.name))
            return False

        self._set_status(tr("Reading {name}…", name=path.name))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            if suffix == ".splat":
                ds = read_splat(path)
            elif suffix == ".ply":
                ds = read_ply(path)
            elif suffix in (".xyz", ".pts", ".txt", ".csv"):
                ds = read_xyz(path)
            else:  # .las / .laz
                ds = read_las(path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            log.exception(f"Failed to import point cloud from {path}: {e}")
            QMessageBox.critical(self, tr("Import Failed"),
                                 tr("Could not open {path}:\n\n{err}", path=path.name, err=str(e)))
            self._set_status(tr("Import failed: {err}", err=str(e)))
            return False

        QApplication.restoreOverrideCursor()
        self.add_dataset(ds)
        return True

    def _load_demo_pointcloud(self) -> None:
        self.add_dataset(generate_demo_pointcloud())

    def _load_demo_splats(self) -> None:
        self.add_dataset(generate_demo_splats())

    # Drag & drop files straight onto the panel
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        md = event.mimeData()
        if md.hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in SUPPORTED_EXTS for u in md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and Path(p).suffix.lower() in SUPPORTED_EXTS:
                self.load_file(p)
        event.acceptProposedAction()

    # ---- Camera fitting -----------------------------------------------------

    def zoom_to_active(self) -> None:
        """Fit the camera view to the active or all datasets."""
        if not self.datasets:
            return
        if 0 <= self._active_idx < len(self.datasets):
            min_pt, max_pt = self.datasets[self._active_idx].bounds
        else:
            all_min = [d.bounds[0] for d in self.datasets if d.visible]
            all_max = [d.bounds[1] for d in self.datasets if d.visible]
            if not all_min:
                return
            min_pt = np.min(np.vstack(all_min), axis=0)
            max_pt = np.max(np.vstack(all_max), axis=0)

        win = getattr(self.app, 'window', None)
        from views.viewport import Viewport
        vps = win.findChildren(Viewport) if win else [getattr(self.app, 'viewport', None)]

        p0 = QVector3D(float(min_pt[0]), float(min_pt[1]), float(min_pt[2]))
        p1 = QVector3D(float(max_pt[0]), float(max_pt[1]), float(max_pt[2]))
        center = (p0 + p1) * 0.5
        diag = (p1 - p0).length()

        for vp in vps:
            cam = getattr(vp, 'camera', None)
            if cam is None:
                continue
            if not getattr(cam, 'perspective', True):
                # Orthographic view: target MUST be centered on the point cloud!
                cam.target = center
                cam.distance = max(diag * 0.85, 10.0)
            elif hasattr(cam, 'fit_box'):
                cam.fit_box(p0, p1, margin=1.15)
            vp.update()

    # ---- Display settings sync ----------------------------------------------

    def _sync_ui_state(self) -> None:
        """Update form controls to reflect the active dataset's values."""
        has_active = 0 <= self._active_idx < len(self.datasets)
        for w in self._dataset_widgets:
            w.setEnabled(has_active)
        self.btn_zoom.setEnabled(bool(self.datasets))
        self.btn_select.setEnabled(has_active)
        self.btn_remove.setEnabled(has_active)

        if not has_active:
            self.lbl_info.setText("")
            self._display_form.setRowVisible(self.btn_solid_color, False)
            self._display_form.setRowVisible(self.spin_splat_scale, False)
            self._display_form.setRowVisible(self.combo_color_mode, True)
            self._display_form.setRowVisible(self.spin_point_size, True)
            return

        ds = self.datasets[self._active_idx]
        splat = _is_splat(ds)

        # Info line
        min_p, max_p = ds.bounds
        dim = max_p - min_p
        kind = tr("Gaussian splat") if splat else tr("Point cloud")
        self.lbl_info.setText(tr("{kind} · {w:.2f} × {d:.2f} × {h:.2f} m",
                                 kind=kind, w=float(dim[0]), d=float(dim[1]), h=float(dim[2])))

        # Show only the rows relevant to the dataset type
        form = self._display_form
        form.setRowVisible(self.combo_color_mode, not splat)
        form.setRowVisible(self.spin_point_size, not splat)
        form.setRowVisible(self.spin_splat_scale, splat)

        def _set(widget, value):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        _set(self.spin_point_size, int(ds.point_size))
        if splat:
            _set(self.spin_splat_scale, float(ds.splat_scale))
        opacity_pct = int(round(getattr(ds, "opacity", 1.0) * 100))
        _set(self.slider_opacity, opacity_pct)
        self.lbl_opacity.setText(f"{opacity_pct}%")

        if not splat:
            key = (ds.color_mode, ds.colormap if ds.color_mode == "elevation" else None)
            idx = 0
            for i, (mode, cmap, _label) in enumerate(COLOR_MODES):
                if mode == key[0] and (key[1] is None or cmap == key[1]):
                    idx = i
                    break
            self.combo_color_mode.blockSignals(True)
            self.combo_color_mode.setCurrentIndex(idx)
            self.combo_color_mode.blockSignals(False)
            self._update_color_button(ds.solid_color)
        form.setRowVisible(self.btn_solid_color, (not splat) and ds.color_mode == "solid")

        # Transform
        _set(self.spin_off_x, float(ds.offset[0]))
        _set(self.spin_off_y, float(ds.offset[1]))
        _set(self.spin_off_z, float(ds.offset[2]))
        _set(self.spin_rot_z, float(getattr(ds, "rotation_z_deg", 0.0)))
        _set(self.spin_rot_x, float(getattr(ds, "rotation_x_deg", 0.0)))
        _set(self.spin_rot_y, float(getattr(ds, "rotation_y_deg", 0.0)))
        _set(self.spin_scale, float(ds.scale))

    def _on_display_setting_changed(self) -> None:
        self.lbl_opacity.setText(f"{self.slider_opacity.value()}%")
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        ds.point_size = self.spin_point_size.value()
        if _is_splat(ds):
            ds.splat_scale = self.spin_splat_scale.value()
        ds.opacity = self.slider_opacity.value() / 100.0
        self.app.viewport.update()

    def _on_color_mode_changed(self, idx: int) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        if _is_splat(ds):
            return
        cmode, cmap, _label = COLOR_MODES[max(0, min(idx, len(COLOR_MODES) - 1))]
        ds.color_mode = cmode
        ds.colormap = cmap
        self._display_form.setRowVisible(self.btn_solid_color, cmode == "solid")
        self.app.viewport.update()

    def _pick_solid_color(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        c = QColorDialog.getColor(QColor(*ds.solid_color), self, tr("Choose Point Cloud Tint"))
        if c.isValid():
            rgb = (c.red(), c.green(), c.blue())
            ds.solid_color = rgb
            self._update_color_button(rgb)
            if ds.color_mode == "solid":
                self.app.viewport.update()

    def _update_color_button(self, rgb: tuple[int, int, int]) -> None:
        self.btn_solid_color.setStyleSheet(f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});")

    def _current_budget(self) -> int:
        idx = max(0, min(self.combo_budget.currentIndex(), len(POINT_BUDGETS) - 1))
        return POINT_BUDGETS[idx][0]

    def _apply_budget(self) -> None:
        budget = self._current_budget()
        renderer = getattr(self.app, "_cloud_renderer", None)
        if renderer is not None:
            renderer.max_point_budget = budget
        for ds in self.datasets:
            if hasattr(ds, "max_splats"):
                ds.max_splats = budget

    def _on_budget_changed(self, _idx: int) -> None:
        self._apply_budget()
        self.app.viewport.update()

    # ---- Section box handlers -------------------------------------------------

    def _on_clipping_toggled(self, enabled: bool) -> None:
        if hasattr(self.app, "_cloud_renderer"):
            self._on_clip_bounds_changed()
            self.app._cloud_renderer.clipping_enabled = enabled
            self.app.viewport.update()

    def _on_clip_bounds_changed(self) -> None:
        if hasattr(self.app, "_cloud_renderer"):
            r = self.app._cloud_renderer
            r.clip_min = np.array([self.spin_x_min.value(), self.spin_y_min.value(), self.spin_z_min.value()], dtype=np.float32)
            r.clip_max = np.array([self.spin_x_max.value(), self.spin_y_max.value(), self.spin_z_max.value()], dtype=np.float32)
            if r.clipping_enabled:
                self.app.viewport.update()

    def _fit_clip_box_to_active(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        min_p, max_p = self.datasets[self._active_idx].bounds
        spins = (self.spin_x_min, self.spin_y_min, self.spin_z_min,
                 self.spin_x_max, self.spin_y_max, self.spin_z_max)
        values = (min_p[0], min_p[1], min_p[2], max_p[0], max_p[1], max_p[2])
        for sp, v in zip(spins, values):
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)
        self._on_clip_bounds_changed()
        if self.chk_clipping.isChecked():
            self.app.viewport.update()
        else:
            self.chk_clipping.setChecked(True)

    # ---- Transform handlers -------------------------------------------------

    def _reset_offset(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        ds.offset = np.zeros(3, dtype=np.float32)
        sync_proxy_from_dataset(ds)
        self._sync_ui_state()
        self.app.viewport.update()

    def _reset_rotation(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        ds.rotation_x_deg = 0.0
        ds.rotation_y_deg = 0.0
        ds.rotation_z_deg = 0.0
        sync_proxy_from_dataset(ds)
        self._sync_ui_state()
        self.app.viewport.update()

    def _rotate_z_by(self, delta: float) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        ds.rotation_z_deg = (ds.rotation_z_deg + delta) % 360.0
        sync_proxy_from_dataset(ds)
        self._sync_ui_state()
        self.app.viewport.update()

    def _on_transform_changed(self) -> None:
        if not (0 <= self._active_idx < len(self.datasets)):
            return
        ds = self.datasets[self._active_idx]
        ds.offset = np.array([
            self.spin_off_x.value(),
            self.spin_off_y.value(),
            self.spin_off_z.value()
        ], dtype=np.float32)
        ds.rotation_z_deg = self.spin_rot_z.value()
        ds.rotation_x_deg = self.spin_rot_x.value()
        ds.rotation_y_deg = self.spin_rot_y.value()
        ds.scale = max(0.00001, self.spin_scale.value())
        sync_proxy_from_dataset(ds)
        self.app.viewport.update()

    # ---- Scan-to-BIM handlers -----------------------------------------------

    def _on_snap_toggled(self, enabled: bool) -> None:
        if hasattr(self.app, "_cloud_snap_engine"):
            self.app._cloud_snap_engine.enabled = enabled

    def _active_or_warn(self, title: str):
        if 0 <= self._active_idx < len(self.datasets):
            return self.datasets[self._active_idx]
        QMessageBox.information(self, title, tr("Select a dataset in the list first."))
        return None

    def _fit_plane(self) -> None:
        ds = self._active_or_warn(tr("Fit Dominant Plane"))
        if ds is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            grp = create_plane_surface_group(ds, self.app.scene)
        finally:
            QApplication.restoreOverrideCursor()
        if grp:
            self._set_status(tr("Created plane: {name}", name=grp.name))
            self.app.viewport.flash_status(tr("Created planar surface group: {name}", name=grp.name))
            self.app.viewport.update()
        else:
            QMessageBox.warning(self, tr("Fit Dominant Plane"),
                                tr("Could not fit a planar surface (not enough co-planar points)."))

    def _create_bbox(self) -> None:
        ds = self._active_or_warn(tr("Create Bounding Box"))
        if ds is None:
            return
        grp = create_bounding_box_group(ds, self.app.scene)
        self._set_status(tr("Created bounding box: {name}", name=grp.name))
        self.app.viewport.flash_status(tr("Created bounding box: {name}", name=grp.name))
        self.app.viewport.update()

    def _convert_to_guides(self) -> None:
        ds = self._active_or_warn(tr("Add Guide Points"))
        if ds is None:
            return
        n = convert_to_guide_points(ds, self.app.scene, max_points=120)
        self._set_status(tr("Added {n} guide points", n=n))
        self.app.viewport.flash_status(tr("Added {n} reference guide points", n=n))
        self.app.viewport.update()


def _disabled_mode():
    return QIcon.Disabled


class PointCloudDialog(QDialog):
    """Modeless floating dialog for Point Cloud & Gaussian Splatting."""

    def __init__(self, panel: PointCloudManagerPanel, parent=None) -> None:
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle(tr("Point Clouds & Gaussian Splats"))
        self.setMinimumSize(340, 560)
        self.resize(380, 680)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
