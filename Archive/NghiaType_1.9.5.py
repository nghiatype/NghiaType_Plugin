# -*- coding: utf-8 -*-
#FLM: NghiaType 1.9.5 - Kerning Studio (2026-11-20)
"""NghiaType Tools V3: consolidated Native and OpenType kerning workflow.

PythonQt / FontLab 8 (FL9 support remains experimental).
The Native tab calls the existing V2 scanner/planner; OpenType and Native
use separate guarded FL8 COPY-only writers.

Keep source ASCII-only for FontLab's Macro panel compatibility.
"""

from __future__ import print_function

import importlib.util
import json
import ntpath
import os
import re
import sys
import time
import traceback
import unicodedata


PUBLIC_VERSION = "1.9.5"
RELEASE_DATE = "20.11.2026"
SHELL_VERSION = PUBLIC_VERSION
NATIVE_GUI_FILENAME = "NghiaType_Native_Kerning_V2_GUI_Alpha1.py"
OT_V1_CORE_FILENAME = "FontLab_Vietnamese_Kerning_Assistant_v1.py"
CROSSCHECK_FILENAME = "NghiaType_Kerning_Crosscheck_V3_Alpha0_11.py"
OT_SYNC_FILENAME = "NghiaType_OT_Sync_Preview_V3_Alpha0_12.py"
OT_PREFLIGHT_FILENAME = "NghiaType_OT_Guarded_Preflight_V3_Alpha0_14.py"
OT_WRITER_FILENAME = "NghiaType_OT_Guarded_Writer_V3_Alpha0_16.py"
WINDOW_CACHE_KEY = "_nghiatype_tools_v3_shell"

# Light scheme from the user's Material Theme Builder export (2026-11-18).
# Keep the GUI self-contained: FontLab's Macro panel must not need the JSON.
# Dark/contrast schemes in the export are reserved for a later theme switch.
M3_LIGHT = {
    "primary": "#784F82",
    "surfaceTint": "#784F82",
    "onPrimary": "#FFFFFF",
    "primaryContainer": "#FBD7FF",
    "onPrimaryContainer": "#5F3869",
    "secondary": "#6A596C",
    "onSecondary": "#FFFFFF",
    "secondaryContainer": "#F2DBF3",
    "onSecondaryContainer": "#514154",
    "tertiary": "#82524D",
    "onTertiary": "#FFFFFF",
    "tertiaryContainer": "#FFDAD6",
    "onTertiaryContainer": "#673B37",
    "error": "#BA1A1A",
    "onError": "#FFFFFF",
    "errorContainer": "#FFDAD6",
    "onErrorContainer": "#93000A",
    "background": "#FFF7FB",
    "onBackground": "#1F1A1F",
    "surface": "#FFF7FB",
    "onSurface": "#1F1A1F",
    "surfaceVariant": "#ECDFE9",
    "onSurfaceVariant": "#4C444C",
    "outline": "#7E747D",
    "outlineVariant": "#CFC3CD",
    "primaryFixedDim": "#E7B6F0",
    "secondaryFixedDim": "#D6C0D6",
    "tertiaryFixedDim": "#F5B7B1",
    "surfaceContainerLowest": "#FFFFFF",
    "surfaceContainerLow": "#FBF1F8",
    "surfaceContainer": "#F5EBF2",
    "surfaceContainerHigh": "#F0E5EC",
    "surfaceContainerHighest": "#EAE0E7",
}

# The supplied Material Theme Builder JSON defines the theme tokens above.
# Success is a single supplemental semantic accent from the UX HTML demos;
# it is intentionally not a replacement for the Material primary/tertiary.
SUCCESS_COLOR = "#2E7D32"
# Windows' installed Fluent/MDL2 icon glyph for Lock; not an emoji.
# Monochrome Windows glyphs, shared by Segoe Fluent Icons and Segoe MDL2.
# Qt's own checkbox indicators stay native so checked/unchecked behavior is
# still handled by QTreeWidgetItem and FontLab's existing PythonQt signals.
WINDOWS_LOCK_GLYPH = "\uE72E"
WINDOWS_CHECK_GLYPH = "\uE73E"
WINDOWS_INFO_GLYPH = "\uE946"
WINDOWS_FORWARD_GLYPH = "\uE72A"
WINDOWS_WARNING_GLYPH = "\uE7BA"
WINDOWS_ERROR_GLYPH = "\uE783"

UI_FONT_FAMILIES = (
    "Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI",
    "Arial", "Helvetica", "Sans Serif",
)

COMBINING_MARK_LABELS = {
    0x0300: "grave", 0x0301: "acute", 0x0302: "circumflex",
    0x0303: "tilde", 0x0306: "breve", 0x0309: "hook above",
    0x031B: "horn", 0x0323: "dot below",
}


def crosscheck_summary_html(report):
    """Plain-language summary; technical linking stays in the optional log."""
    in_sync = report.get("statuses", {}).get("MATCH", 0)
    needs_review = len(report.get("rows", ())) - in_sync
    return (
        "Native: <b>%d</b> &nbsp;&#8226;&nbsp; OpenType: <b>%d</b> "
        "&nbsp;&#8226;&nbsp; <span style='color:%s'><b>In sync: %d</b></span> "
        "&nbsp;&#8226;&nbsp; <span style='color:%s'><b>Need review: %d</b></span>" % (
            report["native_classes"], report["ot_classes"],
            SUCCESS_COLOR, in_sync, M3_LIGHT["tertiary"], needs_review,
        )
    )


def read_glyph_codepoints(font, names):
    """Read each FontLab glyph's actual Unicode values, without mutations."""
    result = {}
    for name in set(names):
        try:
            points = read_qt_value(font[name], "unicodes", ()) or ()
            result[name] = tuple(sorted({
                cp for cp in points
                if isinstance(cp, int) and not isinstance(cp, bool)
                and 0 <= cp <= 0x10FFFF
            }))
        except Exception:
            result[name] = ()
    return result


def format_unicode_values(codepoints):
    """Show exact encoded values; never infer a codepoint from glyph names."""
    return (
        ", ".join("U+%04X" % cp for cp in codepoints)
        if codepoints else "\u2014"
    )


def describe_unicode_components(codepoints):
    """Describe canonical accents only when there is a unique encoded glyph."""
    if len(codepoints) != 1:
        return "\u2014"
    pieces = unicodedata.normalize("NFD", chr(codepoints[0]))
    if len(pieces) < 2:
        return "\u2014"
    marks = []
    for mark in pieces[1:]:
        cp = ord(mark)
        if not unicodedata.combining(mark):
            return "\u2014"
        marks.append(COMBINING_MARK_LABELS.get(
            cp, unicodedata.name(mark, "mark").replace("COMBINING ", "").lower()
        ))
    return pieces[0] + " + " + " + ".join(marks)


def choose_ui_font_family(qtgui, platform=None):
    """Use macOS's native system font; prefer Segoe UI Variable elsewhere."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        # Qt resolves the actual San Francisco system family on macOS.
        # Avoid hardcoding SF Pro, whose public family name may vary.
        try:
            database = qtgui.QFontDatabase
            system_font = database.systemFont(database.GeneralFont)
            family = str(read_qt_value(system_font, "family", "") or "")
            if family:
                return family
        except Exception:
            pass
        try:
            family = str(read_qt_value(qtgui.QFont(), "family", "") or "")
            if family:
                return family
        except Exception:
            pass
        return "Helvetica Neue"
    try:
        database = qtgui.QFontDatabase()
        available = read_qt_value(database, "families", [])
        families = {str(name).casefold(): str(name) for name in available}
        for preferred in UI_FONT_FAMILIES:
            if preferred.casefold() in families:
                return families[preferred.casefold()]
    except Exception:
        pass
    # If font enumeration is unavailable in PythonQt, Qt substitutes a font.
    return "Segoe UI Variable"


def choose_system_icon_font_family(qtgui):
    """Prefer the native Windows icon fonts for a monochrome Lock symbol."""
    try:
        available = read_qt_value(qtgui.QFontDatabase(), "families", [])
        names = {str(name).casefold(): str(name) for name in available}
        for preferred in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
            if preferred.casefold() in names:
                return names[preferred.casefold()]
    except Exception:
        pass
    return ""


def read_qt_value(obj, name, default=None):
    """Handle Qt/PythonQt getters exported as either methods or properties."""
    try:
        value = getattr(obj, name, default)
        return value() if callable(value) else value
    except Exception:
        return default


def detect_fontlab_major(fontlab, qtcore=None):
    """Display-only detection. Actual writer authorization stays in V2."""
    paths = [str(read_qt_value(fontlab, "ApplicationPath", "") or "")]
    if qtcore is not None:
        application = getattr(qtcore, "QCoreApplication", None)
        paths.append(str(read_qt_value(application, "applicationFilePath", "") or ""))
    found = set()
    for path in paths:
        found.update(int(n) for n in re.findall(
            r"(?i)fontlab[ _-]*([89])(?=\W|$)", path
        ))
    return next(iter(found)) if len(found) == 1 else None


def current_font_context(fontlab):
    """Read active font context only. No class/feature writes."""
    try:
        font = fontlab.CurrentFont()
    except Exception:
        font = None
    if font is None:
        return {"font": "No font open", "master": "--", "masters": "--"}
    font_name = ntpath.basename(str(getattr(font, "path", "") or ""))
    if not font_name:
        font_name = "<UNSAVED FONT>"
    master, masters = "--", "--"
    try:
        workspace = fontlab.flWorkspace.instance()
        package = read_qt_value(workspace, "currentPackage")
        if package is not None:
            master = str(read_qt_value(package, "getLayerName", "--") or "--")
            masters = str(read_qt_value(package, "mastersCount", "--") or "--")
    except Exception:
        pass
    return {"font": font_name, "master": master, "masters": masters}


def native_gui_hint():
    """Find the existing V2 script only when placed beside this shell."""
    return companion_script_hint(NATIVE_GUI_FILENAME)


def companion_script_hint(filename):
    """Find an exact named companion; FontLab's Macro panel may omit __file__."""
    folder = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""
    target = os.path.join(folder, filename) if folder else ""
    return target if target and os.path.isfile(target) else ""


def load_existing_native_gui(path):
    """Load exactly the known V2 GUI; never alter its writer or checks."""
    path = os.path.abspath(str(path or ""))
    if ntpath.basename(path) != NATIVE_GUI_FILENAME or not os.path.isfile(path):
        raise RuntimeError("Select the existing NghiaType Native Kerning V2 GUI .py file.")
    spec = importlib.util.spec_from_file_location("_nghiatype_v2_gui_from_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the existing V2 GUI.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "main", None)):
        raise RuntimeError("The chosen V2 GUI has no main() function.")
    return module


def load_exact_readonly_module(path, expected_filename, module_key, functions):
    """Load only a named V1 reader/cross-check engine, never call its main()."""
    path = os.path.abspath(str(path or ""))
    if ntpath.basename(path) != expected_filename or not os.path.isfile(path):
        raise RuntimeError("Select the exact reader file: " + expected_filename)
    spec = importlib.util.spec_from_file_location(module_key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load read-only module: " + expected_filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in functions:
        if not callable(getattr(module, name, None)):
            raise RuntimeError("Missing read-only function: " + name)
    return module


def load_exact_ot_writer_module(path):
    """Load only the known FL8 test-COPY writer; never execute a write on import."""
    return load_exact_readonly_module(
        path, OT_WRITER_FILENAME, "_nghiatype_v3_ot_guarded_writer",
        ("guarded_write_to_copy", "render_writer_result")
    )


def start_gui(fontlab, QtCore, QtGui):
    class ToolsShell(QtGui.QDialog):
        def __init__(self, parent=None):
            QtGui.QDialog.__init__(self, parent)
            self.setWindowTitle("NghiaType | " + SHELL_VERSION)
            self.setMinimumSize(1180, 650)
            window_width, window_height = 1420, 820
            try:
                desktop = read_qt_value(QtGui.QApplication, "desktop")
                geometry = read_qt_value(desktop, "availableGeometry")
                screen_width = int(read_qt_value(geometry, "width", 0))
                screen_height = int(read_qt_value(geometry, "height", 0))
                if screen_width > 0:
                    window_width = max(1180, min(window_width, screen_width - 36))
                if screen_height > 0:
                    window_height = max(650, min(window_height, screen_height - 36))
            except Exception:
                pass
            self.resize(window_width, window_height)
            try:
                self.setWindowFlags(
                    self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
                )
            except Exception:
                pass
            self.native_backend = None
            self.native_core = None
            self.native_snapshot = None
            self.native_preview = None
            self.native_rows = {}
            self.native_selected = set()
            self.native_entries = []
            self.native_unicode_map = {}
            self.native_active_class = None
            self.native_updating = False
            self.native_checked_token = None
            self.native_write_result = None
            self.native_write_attempted = False
            self.native_write_failed = False
            self.native_applied = False
            # Cumulative successful Native writes are tracked by native_applied.
            # Only the CURRENT selection cycle needs a fresh Scan before it
            # can be written again. Do not confuse these two states.
            self.native_cycle_applied = False
            self.native_selection_locked = False
            # A failed or unverified OT write also makes this COPY unsafe.
            self.ot_write_failed = False
            self.ot_v1_core = None
            self.ot_crosscheck_core = None
            self.ot_crosscheck_report = None
            self.ot_crosscheck_error = False
            self.ot_crosscheck_rows = {}
            self.ot_sync_core = None
            self.ot_preflight_core = None
            self.ot_writer_core = None
            self.ot_last_preflight = None
            self.ot_last_preflight_selection = frozenset()
            self.ot_sync_preview = None
            self.ot_sync_rows = {}
            self.ot_sync_selected = set()
            self.ot_sync_updating = False
            self.ot_sync_source_kern = None
            self.ot_sync_expected_native = None
            self.ot_sync_expected_pairs = None
            self.ot_sync_original_issues = None
            self.ot_sync_original_master_count = None
            self.ot_sync_expected_glyphs = None
            self.ot_sync_original_prefix = None
            self.ot_sync_original_font_path = None
            self.ot_sync_original_master = None
            self.ot_crosscheck_source_kern = None
            self.ot_crosscheck_native_snapshot = None
            self.ot_crosscheck_original_prefix = None
            self.ot_sync_applied = False
            self.ot_last_applied_count = 0
            self.ot_sync_verified_by_class = {}
            self.ot_ui_issue = None
            self.connections = []
            self.ui_font_family = choose_ui_font_family(QtGui)
            self.system_icon_font_family = choose_system_icon_font_family(QtGui)
            self.setFont(QtGui.QFont(self.ui_font_family, 11))
            palette = dict(M3_LIGHT)
            palette["uiFont"] = self.ui_font_family
            self.setStyleSheet("""
                QDialog { background:%(background)s; color:%(onBackground)s;
                    font-family:'%(uiFont)s'; font-size:12px; }
                QLabel { color:%(onSurface)s; }
                QTabWidget::pane { border:1px solid %(outlineVariant)s;
                    border-radius:10px; background:%(surfaceContainerLowest)s; }
                QFrame#kerningWorkflowBand {
                    background:%(surfaceContainerLowest)s;
                    border:0; border-bottom:1px solid %(outlineVariant)s; }
                QFrame#kerningGuidanceBand {
                    background:%(surfaceContainerLowest)s;
                    border:1px solid %(outlineVariant)s; border-radius:9px; }
                QPushButton#kerningGuidanceNext {
                    background:%(primary)s; color:%(onPrimary)s;
                    border-radius:8px; padding:7px 12px; }
                QPushButton#kerningGuidanceOther {
                    background:%(surfaceContainerLowest)s;
                    color:%(primary)s; border:1px solid %(primary)s;
                    border-radius:8px; padding:7px 12px; }
                QPushButton#nativeReport {
                    background:%(surfaceContainerLowest)s;
                    color:%(primary)s;
                    border:1px solid %(outlineVariant)s;
                    border-radius:8px; padding:5px 10px;
                    font-weight:normal; }
                QPushButton#nativeReport:hover {
                    background:%(surfaceContainerLow)s; }
                QFrame#otAuditSummaryBand {
                    background:%(surfaceContainerLowest)s;
                    border:1px solid %(outlineVariant)s; border-radius:9px; }
                QFrame#otAuditPanelHead, QFrame#otAuditInspectorHead {
                    background:%(surfaceContainerLow)s;
                    border:0; border-bottom:1px solid %(outlineVariant)s;
                    border-top-left-radius:9px; border-top-right-radius:9px; }
                QFrame#otAuditNotice {
                    background:%(primaryContainer)s; border:0; border-radius:8px; }
                QFrame#otAuditInspectorFooter {
                    background:%(surfaceContainerLow)s; border:0;
                    border-top:1px solid %(outlineVariant)s; }
                QPushButton#otAuditSync { background:%(primary)s;
                    color:%(onPrimary)s; border-radius:8px; padding:9px 13px; }
                QPushButton#kerningStep {
                    background:transparent; color:%(onSurfaceVariant)s;
                    border:0; border-radius:7px; padding:9px 14px;
                    min-width:155px; font-weight:bold; }
                QPushButton#kerningStep:checked {
                    background:%(primary)s; color:%(onPrimary)s; }
                QPushButton#kerningStep:hover:!checked {
                    background:%(primaryContainer)s;
                    color:%(onPrimaryContainer)s; }
                QTabBar::tab { background:%(surfaceContainer)s;
                    color:%(onSurfaceVariant)s;
                    border:0; border-radius:8px; margin-right:8px;
                    padding:10px 17px; font-weight:bold; min-width:118px; }
                QTabBar::tab:selected { background:%(primary)s;
                    color:%(onPrimary)s; }
                QTabBar::tab:hover:!selected { background:%(primaryContainer)s; }
                QTreeWidget, QPlainTextEdit, QLineEdit {
                    background:%(surfaceContainerLowest)s;
                    color:%(onSurface)s;border:1px solid %(outlineVariant)s;
                    border-radius:11px;
                    selection-background-color:%(primaryContainer)s; }
                QTreeWidget { outline:none;
                    alternate-background-color:%(surfaceContainerLow)s; }
                QTreeWidget::item { padding:7px 5px; }
                QTreeWidget::item:selected {
                    background:%(primaryContainer)s;
                    color:%(onPrimaryContainer)s; }
                QHeaderView::section { background:%(surfaceContainerHigh)s;
                    color:%(onSurfaceVariant)s;
                    border:0;border-bottom:1px solid %(outlineVariant)s;
                    padding:9px 6px;font-weight:bold; }
                QHeaderView::section:first { border-top-left-radius:9px; }
                QHeaderView::section:last { border-top-right-radius:9px; }
                QPlainTextEdit { padding:10px;
                    font-family:Consolas,'Courier New',monospace;font-size:11px; }
                QLineEdit { padding:9px 12px; }
                QPushButton { border:0; border-radius:11px;
                    background:%(secondaryContainer)s;
                    color:%(onSecondaryContainer)s;
                    padding:10px 16px; font-weight:bold; }
                QPushButton:hover { background:%(primaryContainer)s;
                    color:%(onPrimaryContainer)s; }
                QPushButton#nativeScan { background:%(primary)s;
                    color:%(onPrimary)s; font-size:13px; border-radius:15px; }
                QPushButton#nativeScan:hover { background:%(onPrimaryContainer)s; }
                QFrame#sideRail { background:%(surfaceContainerLow)s;
                    border:0; border-right:1px solid %(outlineVariant)s; }
                QFrame#sidebarBrand { background:%(surfaceContainerLowest)s;
                    border:0; border-bottom:1px solid %(outlineVariant)s; }
                QFrame#sidebarContext { background:%(surfaceContainerLow)s;
                    border:0; border-bottom:1px solid %(outlineVariant)s; }
                QFrame#sidebarRuntime { background:%(surfaceContainerLowest)s;
                    border:0; border-top:1px solid %(outlineVariant)s; }
                QFrame#sidebarNav { background:transparent; border:0; }
                QFrame#nativeTopBand {
                    background:%(surfaceContainerLowest)s; border:0;
                    border-bottom:1px solid %(outlineVariant)s; }
                QFrame#footerBand {
                    background:%(surfaceContainerLowest)s; border:0;
                    border-top:1px solid %(outlineVariant)s; }
                QFrame#nativeMetricBand {
                    background:%(surfaceContainerLow)s; border:0;
                    border-bottom:1px solid %(outlineVariant)s; }
                QWidget#nativeWorkArea { background:%(background)s; }
                QFrame#nativeClassHead, QFrame#nativeGlyphHead,
                QFrame#nativePreviewHead, QFrame#nativeApplyHead {
                    background:%(surfaceContainerLow)s; border:0;
                    border-bottom:1px solid %(outlineVariant)s;
                    border-top-left-radius:14px; border-top-right-radius:14px; }
                QPushButton#sideNav { padding:0; border-radius:11px;
                    color:%(onSurfaceVariant)s;
                    border:1px solid transparent;
                    background:transparent; font-weight:normal; }
                QPushButton#sideNav:checked {
                    background:%(surfaceContainerLowest)s;
                    color:%(primary)s;
                    border:1px solid %(outlineVariant)s; }
                QPushButton#sideNav:hover:!checked {
                    background:%(surfaceContainerHigh)s; }
                QPushButton#refreshFontInfo { background:%(surfaceContainerLowest)s;
                    border:1px solid %(outlineVariant)s; border-radius:8px;
                    color:%(onSurface)s; padding:7px 9px; }
                QPushButton:disabled, QPushButton#nativeApply:disabled {
                    background:%(surfaceContainerHighest)s;
                    color:%(outline)s; }
            """ % palette)
            # The sidebar is fixed-width; only the desktop workspace grows.
            outer = QtGui.QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            sidebar = QtGui.QFrame()
            sidebar.setObjectName("sideRail")
            sidebar.setFixedWidth(236)
            rail = QtGui.QVBoxLayout(sidebar)
            rail.setContentsMargins(0, 0, 0, 0)
            rail.setSpacing(0)

            brand = QtGui.QFrame()
            brand.setObjectName("sidebarBrand")
            brand_col = QtGui.QVBoxLayout(brand)
            brand_col.setContentsMargins(15, 12, 15, 11)
            brand_col.setSpacing(3)
            brand_col.addWidget(self.heading("NghiaType", 15))
            brand_col.addWidget(self.paragraph("FontLab 8 Plugin  /  " + PUBLIC_VERSION))
            rail.addWidget(brand)
            self.sidebar_brand = brand

            context = QtGui.QFrame()
            context.setObjectName("sidebarContext")
            context_col = QtGui.QVBoxLayout(context)
            context_col.setContentsMargins(15, 11, 15, 12)
            context_col.setSpacing(4)
            context_col.addWidget(self.paragraph("ACTIVE FONT FILE"))
            self.context_label = QtGui.QLabel("No font open")
            self.context_label.setWordWrap(True)
            self.context_label.setStyleSheet(
                "color:%s;background:transparent;border:0;font-weight:bold;" %
                M3_LIGHT["onSurface"]
            )
            context_col.addWidget(self.context_label)
            self.context_detail = self.paragraph("Master: --  /  Masters: --")
            context_col.addWidget(self.context_detail)
            rail.addWidget(context)
            self.sidebar_context = context

            nav = QtGui.QFrame()
            nav.setObjectName("sidebarNav")
            nav_col = QtGui.QVBoxLayout(nav)
            nav_col.setContentsMargins(9, 12, 9, 10)
            nav_col.setSpacing(5)
            nav_caption = self.paragraph("WORKFLOW MODULES")
            nav_caption.setContentsMargins(6, 0, 0, 5)
            nav_col.addWidget(nav_caption)
            self.nav_buttons = []
            self.nav_badges = []
            self.nav_titles = []
            for index, (name, subtitle) in enumerate((
                ("Kerning Studio", "Native + OpenType kern"),
                ("OpenType Studio", "Features & lookups"),
                ("Glyph Matrix", "Unicode & languages"),
                ("Reports & Logs", "Checks & exports"),
            )):
                button = QtGui.QPushButton("")
                button.setObjectName("sideNav")
                button.setCheckable(True)
                button.setFixedHeight(54)
                button.setToolTip(name + " - " + subtitle)
                nav_row = QtGui.QHBoxLayout(button)
                nav_row.setContentsMargins(9, 5, 8, 5)
                nav_row.setSpacing(9)

                number = QtGui.QLabel("%02d" % (index + 1))
                number.setAlignment(QtCore.Qt.AlignCenter)
                number.setFixedSize(27, 27)
                nav_row.addWidget(number)

                words = QtGui.QVBoxLayout()
                words.setContentsMargins(0, 0, 0, 0)
                words.setSpacing(1)
                title = QtGui.QLabel(name)
                title.setFont(QtGui.QFont(self.ui_font_family, 10,
                                         QtGui.QFont.Bold))
                description = QtGui.QLabel(subtitle)
                description.setStyleSheet(
                    "color:%s;background:transparent;border:0;font-size:10px;" %
                    M3_LIGHT["onSurfaceVariant"]
                )
                words.addWidget(title)
                words.addWidget(description)
                nav_row.addLayout(words, 1)

                # Labels are visual only; clicks anywhere on a nav card must
                # reach its checkable button, including the number chip.
                for label in (number, title, description):
                    label.setAttribute(
                        QtCore.Qt.WA_TransparentForMouseEvents, True
                    )
                callback = lambda *args, target=index: self.navigate_to(target)
                button.clicked.connect(callback)
                self.connections.append((button.clicked, callback))
                self.nav_buttons.append(button)
                self.nav_badges.append(number)
                self.nav_titles.append(title)
                nav_col.addWidget(button)
            rail.addWidget(nav)
            rail.addStretch(1)

            runtime = QtGui.QFrame()
            runtime.setObjectName("sidebarRuntime")
            runtime_col = QtGui.QVBoxLayout(runtime)
            runtime_col.setContentsMargins(14, 11, 14, 13)
            runtime_col.setSpacing(5)
            for heading_text, value_text in (
                ("Engine:", "Python %d.%d.%d" % sys.version_info[:3]),
                ("FL Host:", "FontLab %s" %
                 (detect_fontlab_major(fontlab, QtCore) or "unknown")),
            ):
                info_row = QtGui.QHBoxLayout()
                info_row.addWidget(self.paragraph(heading_text))
                info_row.addStretch(1)
                info_row.addWidget(self.paragraph(value_text))
                runtime_col.addLayout(info_row)
            refresh = QtGui.QPushButton("Refresh font info")
            refresh.setObjectName("refreshFontInfo")
            refresh.setToolTip("Refresh the active filename and master only.")
            refresh.clicked.connect(self.refresh_context)
            runtime_col.addWidget(refresh)
            rail.addWidget(runtime)
            outer.addWidget(sidebar)

            right = QtGui.QWidget()
            right_layout = QtGui.QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(0)

            self.pages = QtGui.QStackedWidget()
            self.pages.addWidget(self.kerning_studio_page())
            self.pages.addWidget(self.opentype_page())
            self.pages.addWidget(self.glyph_matrix_page())
            self.pages.addWidget(self.reports_page())
            right_layout.addWidget(self.pages, 1)

            footer_band = QtGui.QFrame()
            footer_band.setObjectName("footerBand")
            footer = QtGui.QHBoxLayout(footer_band)
            footer.setContentsMargins(16, 6, 16, 6)
            self.status_label = QtGui.QLabel(
                "Font unchanged until you confirm an action. No automatic Save."
            )
            self.status_label.setStyleSheet(
                "color:%s;font-size:10px;" % M3_LIGHT["primary"]
            )
            # Technical status remains available to workflow handlers, but
            # the user already sees status in the contextual guidance card.
            # Avoid a second, sometimes stale sentence beside Close.
            self.status_label.setVisible(False)
            footer.addWidget(self.status_label)
            footer.addStretch(1)
            close = QtGui.QPushButton("Close")
            # PythonQt QPushButton.clicked supplies checked=False; QDialog.close
            # accepts no arguments and rejects that boolean if connected raw.
            close_clicked = lambda *args: self.close()
            close.clicked.connect(close_clicked)
            self.connections.append((close.clicked, close_clicked))
            footer.addWidget(close)
            right_layout.addWidget(footer_band)
            outer.addWidget(right, 1)
            self.navigate_to(0)
            self.refresh_context()

        def navigate_to(self, index):
            """Sidebar navigation only; never starts a scan or applies data."""
            if index < 0 or index >= len(self.nav_buttons):
                return
            self.pages.setCurrentIndex(index)
            for current, button in enumerate(self.nav_buttons):
                active = current == index
                button.setChecked(active)
                self.nav_badges[current].setStyleSheet(
                    "background:%s;color:%s;border:0;border-radius:7px;"
                    "font-weight:bold;font-size:10px;" % (
                        M3_LIGHT["primaryContainer"] if active else
                        M3_LIGHT["surfaceContainer"],
                        M3_LIGHT["onPrimaryContainer"] if active else
                        M3_LIGHT["onSurfaceVariant"]
                    )
                )
                self.nav_titles[current].setStyleSheet(
                    "background:transparent;border:0;color:%s;" % (
                        M3_LIGHT["primary"] if active else
                        M3_LIGHT["onSurfaceVariant"]
                    )
                )

        def align_native_bands(self):
            """Match the two sidebar separators to their Native page bands."""
            for side, main, minimum in (
                (self.sidebar_brand, self.native_top_band, 70),
                (self.sidebar_context, self.native_metrics_band, 91),
            ):
                heights = [minimum]
                for frame in (side, main):
                    layout = read_qt_value(frame, "layout")
                    hint = read_qt_value(layout, "sizeHint")
                    heights.append(int(read_qt_value(hint, "height", 0)))
                # A little breathing room prevents text clipping when the
                # system font or FontLab display scaling differs.
                height = max(heights) + 7
                side.setFixedHeight(height)
                main.setFixedHeight(height)

        def toggle_native_workspace(self):
            """Give class/glyph tables more height without changing font state."""
            expanded = not getattr(self, "native_workspace_expanded", False)
            self.native_workspace_expanded = expanded
            self.native_lower_container.setVisible(not expanded)
            self.native_expand_button.setText(
                "Show Preview / Apply" if expanded else "Expand workspace"
            )

        def prepare_report_title_bar(self, dialog):
            """Keep the native close X, without Qt's unused Windows ? hint."""
            try:
                flags = read_qt_value(dialog, "windowFlags")
                dialog.setWindowFlags(
                    flags & ~QtCore.Qt.WindowContextHelpButtonHint
                )
            except Exception:
                try:
                    dialog.setWindowFlags(
                        QtCore.Qt.Dialog | QtCore.Qt.WindowTitleHint |
                        QtCore.Qt.WindowSystemMenuHint |
                        QtCore.Qt.WindowCloseButtonHint
                    )
                except Exception:
                    # Cosmetic titlebar flags must never block the report.
                    pass

        def toggle_native_report(self):
            """Open secondary technical details without a bottom workspace bar."""
            dialog = QtGui.QDialog(self)
            dialog.setWindowTitle("Native Classes / Report")
            self.prepare_report_title_bar(dialog)
            dialog.resize(740, 470)
            column = QtGui.QVBoxLayout(dialog)
            column.setContentsMargins(18, 16, 18, 16)
            column.setSpacing(11)
            column.addWidget(self.heading("Native scan report", 13))
            column.addWidget(self.paragraph(
                "Read-only details for this scan. Export JSON if you "
                "need the full technical record."
            ))
            report = QtGui.QPlainTextEdit()
            report.setReadOnly(True)
            report.setPlainText(str(read_qt_value(
                self.native_diagnostics, "toPlainText", ""
            ) or ""))
            column.addWidget(report, 1)
            actions = QtGui.QHBoxLayout()
            actions.addStretch(1)
            export = QtGui.QPushButton("Export JSON")
            export.setEnabled(self.native_snapshot is not None)
            export.clicked.connect(
                lambda *args: self.safe_native(self.export_native_report)
            )
            actions.addWidget(export)
            close = QtGui.QPushButton("Close")
            # QPushButton.clicked(bool) must not be passed to QDialog.accept().
            close.clicked.connect(lambda *args: dialog.accept())
            actions.addWidget(close)
            column.addLayout(actions)
            execute = getattr(dialog, "exec_", None)
            if not callable(execute):
                execute = getattr(dialog, "exec", None)
            if callable(execute):
                execute()
            else:
                # Some FontLab builds expose only modeless QDialog.show().
                self.native_report_dialog = dialog
                dialog.show()

        def show_readonly_details_dialog(self, title, description, details):
            """Secondary report dialog shared by Cross-check and OT Sync."""
            dialog = QtGui.QDialog(self)
            dialog.setWindowTitle(title)
            self.prepare_report_title_bar(dialog)
            dialog.resize(740, 470)
            column = QtGui.QVBoxLayout(dialog)
            column.setContentsMargins(18, 16, 18, 16)
            column.setSpacing(11)
            column.addWidget(self.heading(title, 13))
            column.addWidget(self.paragraph(description))
            report = QtGui.QPlainTextEdit()
            report.setReadOnly(True)
            report.setPlainText(str(details or ""))
            column.addWidget(report, 1)
            close_row = QtGui.QHBoxLayout()
            close_row.addStretch(1)
            close = QtGui.QPushButton("Close")
            close.clicked.connect(lambda *args: dialog.accept())
            close_row.addWidget(close)
            column.addLayout(close_row)
            execute = getattr(dialog, "exec_", None)
            if not callable(execute):
                execute = getattr(dialog, "exec", None)
            if callable(execute):
                execute()
            else:
                self.secondary_report_dialog = dialog
                dialog.show()

        def set_native_latest(self, message):
            """Always display the latest preview event, even when collapsed."""
            self.native_latest_line.setText("Latest: " + message)
            self.native_latest_line.setToolTip(message)
            self.refresh_kerning_guidance()

        def make_card(self, name, background, border, radius):
            frame = QtGui.QFrame()
            frame.setObjectName(name)
            frame.setStyleSheet(
                "QFrame#%s{background:%s;border:1px solid %s;"
                "border-radius:%dpx;}" % (name, background, border,
                                          min(radius, 10))
            )
            return frame

        def confirm_glyph_additions(self, title, details, count,
                                    acknowledgement):
            """One explicit confirmation with a required tick, like the UX demo.

            This is UI consent only. Native/OT writers MUST still run their
            live COPY guards, fresh preflight and exact post-write readback.
            Dialog rejection (including window close) never authorizes a write.
            """
            dialog = QtGui.QDialog(self)
            dialog.setWindowTitle("NghiaType | Confirm changes")
            # The test FontLab window has no use for the standard Windows '?'
            # context-help button. Leave its normal close X intact.
            title_bar = getattr(self, "prepare_report_title_bar", None)
            if callable(title_bar):
                title_bar(dialog)
            dialog.setMinimumWidth(550)
            dialog.setModal(True)
            container = QtGui.QVBoxLayout(dialog)
            container.setContentsMargins(22, 23, 22, 20)
            container.setSpacing(14)

            heading = self.heading(title, 13)
            heading.setWordWrap(True)
            container.addWidget(heading)

            # Do not flatten risk, destination and action into one long block.
            # Each operation has a short summary and an unmistakable backup
            # or changed-memberships callout, matching the HTML UX prototype.
            is_opentype = "OpenType" in title
            context = self.paragraph(details[0] if details else "")
            container.addWidget(context)
            if is_opentype:
                introduction = self.paragraph(
                    "First, NghiaType will save a separate .fea backup of "
                    "your current OpenType kern feature."
                )
                container.addWidget(introduction)
                backup_destination = self.paragraph(
                    "NEXT: Choose where to save the .fea backup.\n"
                    "This is a copy of the kern feature, NOT the font file."
                )
                backup_destination.setWordWrap(True)
                backup_destination.setStyleSheet(
                    "background:%s;color:%s;border:1px solid %s;"
                    "border-radius:9px;padding:15px;font-family:Consolas,"
                    "'Courier New',monospace;font-size:11px;" % (
                        M3_LIGHT["surfaceContainerLow"],
                        M3_LIGHT["onSurface"], M3_LIGHT["outlineVariant"]
                    )
                )
                container.addWidget(backup_destination)
                result_text = details[3] if len(details) > 3 else ""
                container.addWidget(self.paragraph(result_text))
            else:
                summary_text = "\n".join(details[1:3])
                summary = self.paragraph(summary_text)
                summary.setWordWrap(True)
                summary.setStyleSheet(
                    "background:%s;color:%s;border:1px solid %s;"
                    "border-radius:9px;padding:17px;font-size:12px;" % (
                        M3_LIGHT["surfaceContainerLow"],
                        M3_LIGHT["onSurface"], M3_LIGHT["outlineVariant"]
                    )
                )
                container.addWidget(summary)

            consent = QtGui.QCheckBox(acknowledgement)
            consent.setChecked(False)
            consent.setStyleSheet(
                "QCheckBox{background:%s;color:%s;padding:15px;"
                "border:1px solid %s;border-radius:9px;"
                "font-weight:bold;}" % (
                    M3_LIGHT.get("surfaceContainerLowest", "#FFFFFF"),
                    M3_LIGHT["onSurface"], M3_LIGHT["outlineVariant"]
                )
            )
            container.addWidget(consent)
            helper = self.paragraph(
                "Tick the box to continue. If verification fails, close "
                "this test COPY without saving."
            )
            container.addWidget(helper)

            actions = QtGui.QHBoxLayout()
            actions.addStretch(1)
            cancel = QtGui.QPushButton("Cancel")
            confirm = QtGui.QPushButton(
                "Choose backup location..." if is_opentype else
                "Add %d glyph%s" % (count, "" if count == 1 else "s")
            )
            confirm.setObjectName("nativeApply")
            confirm.setEnabled(False)
            cancel.setDefault(True)
            actions.addWidget(cancel)
            actions.addWidget(confirm)
            container.addLayout(actions)

            approved = [False]

            def on_tick(*args):
                confirm.setEnabled(bool(read_qt_value(
                    consent, "isChecked", False
                )))

            def on_confirm(*args):
                if bool(read_qt_value(consent, "isChecked", False)):
                    approved[0] = True
                    dialog.accept()

            def on_cancel(*args):
                dialog.reject()

            consent.toggled.connect(on_tick)
            confirm.clicked.connect(on_confirm)
            cancel.clicked.connect(on_cancel)
            # Keep PythonQt signal callbacks alive throughout the modal loop.
            callbacks = (on_tick, on_confirm, on_cancel)
            execute = getattr(dialog, "exec_", None)
            if not callable(execute):
                execute = getattr(dialog, "exec", None)
            if not callable(execute):
                raise RuntimeError(
                    "FontLab cannot open the confirmation dialog; no changes made."
                )
            execute()
            return approved[0] and bool(read_qt_value(
                consent, "isChecked", False
            ))

        def heading(self, text, size=16, color=None):
            label = QtGui.QLabel(text)
            label.setFont(QtGui.QFont(self.ui_font_family, size, QtGui.QFont.Bold))
            label.setStyleSheet(
                "color:%s;background:transparent;border:0;" %
                (color or M3_LIGHT["primary"])
            )
            return label

        def paragraph(self, text):
            label = QtGui.QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet(
                "color:%s;background:transparent;border:0;" %
                M3_LIGHT["onSurfaceVariant"]
            )
            return label

        def configure_tree_columns(self, table, fixed_widths, stretch_columns):
            """Share spare panel width without hiding glyph data offscreen.

            FontLab 8/9 ship different Qt header bindings; a missing resize
            method falls back to readable default column widths.
            """
            for index, width in enumerate(fixed_widths):
                table.setColumnWidth(index, width)
            header = read_qt_value(table, "header")
            if header is None:
                return
            try:
                header.setStretchLastSection(False)
                resize = getattr(header, "setSectionResizeMode", None)
                if resize is None:
                    resize = getattr(header, "setResizeMode", None)
                stretch = getattr(QtGui.QHeaderView, "Stretch", None)
                fixed = getattr(QtGui.QHeaderView, "Fixed", None)
                if not callable(resize) or stretch is None or fixed is None:
                    return
                for index in range(len(fixed_widths)):
                    resize(index, stretch if index in stretch_columns else fixed)
            except Exception:
                # Column resizing is visual only; never block Scan/Preview.
                pass

        def kerning_studio_page(self):
            """One shared desktop workspace for three manual kerning steps.

            Move the already-built Native header and metrics above the tabs.
            No scanning or writing happens merely by switching tabs.
            """
            native = self.native_page()
            # The title carries the stable one-line product purpose. Step
            # instructions live separately in the contextual guidance card.
            self.kerning_description.setVisible(True)
            native_layout = read_qt_value(native, "layout")
            for band in (self.native_top_band, self.native_metrics_band):
                native_layout.removeWidget(band)

            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(self.native_top_band)
            layout.addWidget(self.native_metrics_band)

            # A separate workflow band mirrors the HTML reference: the tab
            # group has its own outlined surface and breathing room. It does
            # not share the metric strip's separator or the workbench cards.
            self.kerning_tabs = QtGui.QStackedWidget()
            self.kerning_tabs.setObjectName("kerningWorkflowPages")
            self.kerning_tabs.addWidget(native)
            self.kerning_tabs.addWidget(self.opentype_kern_audit_page())
            self.kerning_tabs.addWidget(self.opentype_sync_page())

            workflow_band = QtGui.QFrame()
            workflow_band.setObjectName("kerningWorkflowBand")
            workflow_row = QtGui.QHBoxLayout(workflow_band)
            workflow_row.setContentsMargins(18, 10, 18, 10)
            workflow_row.setSpacing(12)
            segment = self.make_card(
                "kerningWorkflowSegment", M3_LIGHT["surfaceContainerLow"],
                M3_LIGHT["outlineVariant"], 10
            )
            segment_row = QtGui.QHBoxLayout(segment)
            segment_row.setContentsMargins(5, 5, 5, 5)
            segment_row.setSpacing(6)
            self.kerning_step_buttons = []
            for index, caption in enumerate((
                "01  Native classes", "02  Cross-check", "03  OpenType sync"
            )):
                step = QtGui.QPushButton(caption)
                step.setObjectName("kerningStep")
                step.setCheckable(True)
                step.setMinimumHeight(36)
                step_clicked = lambda *args, target=index: (
                    self.kerning_tabs.setCurrentIndex(target)
                )
                step.clicked.connect(step_clicked)
                self.connections.append((step.clicked, step_clicked))
                self.kerning_step_buttons.append(step)
                segment_row.addWidget(step)
            workflow_row.addWidget(segment)
            workflow_row.addStretch(1)
            layout.addWidget(workflow_band)

            # A small contextual message mirrors the user's UX prototype.
            # It explains the next action without duplicating an entire
            # Select -> Confirm -> Add progress indicator.
            guidance_wrap = QtGui.QWidget()
            guidance_wrap_layout = QtGui.QHBoxLayout(guidance_wrap)
            guidance_wrap_layout.setContentsMargins(18, 8, 18, 5)
            guidance_wrap_layout.setSpacing(0)
            self.kerning_guidance_band = QtGui.QFrame()
            self.kerning_guidance_band.setObjectName("kerningGuidanceBand")
            guidance_row = QtGui.QHBoxLayout(self.kerning_guidance_band)
            guidance_row.setContentsMargins(13, 9, 13, 9)
            guidance_row.setSpacing(12)
            # Semantic context sits in one small icon. The card itself stays
            # white so its warning/success state never competes with the CTA.
            self.kerning_guidance_icon = QtGui.QLabel("i")
            self.kerning_guidance_icon.setObjectName("kerningGuidanceIcon")
            self.kerning_guidance_icon.setFixedSize(34, 34)
            self.kerning_guidance_icon.setAlignment(QtCore.Qt.AlignCenter)
            self.kerning_guidance_regular_font = QtGui.QFont(
                self.ui_font_family, 16, QtGui.QFont.Bold
            )
            self.kerning_guidance_icon.setFont(
                self.kerning_guidance_regular_font
            )
            guidance_row.addWidget(self.kerning_guidance_icon)
            guidance_copy = QtGui.QVBoxLayout()
            guidance_copy.setContentsMargins(0, 0, 0, 0)
            guidance_copy.setSpacing(3)
            self.kerning_guidance_title = self.heading("Start here", 11)
            guidance_copy.addWidget(self.kerning_guidance_title)
            self.kerning_guidance_text = self.paragraph(
                "Scan Native classes to find glyphs you can add."
            )
            self.kerning_guidance_text.setWordWrap(True)
            guidance_copy.addWidget(self.kerning_guidance_text)
            guidance_row.addLayout(guidance_copy, 1)
            self.kerning_guidance_other = QtGui.QPushButton("Scan again")
            self.kerning_guidance_other.setObjectName("kerningGuidanceOther")
            self.kerning_guidance_other.setVisible(False)
            self.kerning_guidance_other_action = None
            other_clicked = lambda *args: self.run_kerning_guidance_action(
                self.kerning_guidance_other_action
            )
            self.kerning_guidance_other.clicked.connect(other_clicked)
            self.connections.append(
                (self.kerning_guidance_other.clicked, other_clicked)
            )
            guidance_row.addWidget(self.kerning_guidance_other)
            self.kerning_guidance_next = QtGui.QPushButton(
                "Scan Native classes"
            )
            self.kerning_guidance_next.setObjectName("kerningGuidanceNext")
            self.kerning_guidance_next.setVisible(False)
            self.kerning_guidance_action = None
            continue_clicked = lambda *args: self.run_kerning_guidance_action(
                self.kerning_guidance_action
            )
            self.kerning_guidance_next.clicked.connect(continue_clicked)
            self.connections.append(
                (self.kerning_guidance_next.clicked, continue_clicked)
            )
            guidance_row.addWidget(self.kerning_guidance_next)
            guidance_wrap_layout.addWidget(self.kerning_guidance_band, 1)
            layout.addWidget(guidance_wrap)
            layout.addWidget(self.kerning_tabs, 1)

            # Scan / Compare / Find are surfaced through the guidance card.
            # Keep the old header action signal wired, but never display its
            # duplicate button: a fresh Native scan used to make it jump into
            # the top-right corner after a completed OpenType sync round.
            self.ot_audit_scan_button.setVisible(False)
            self.ot_sync_build_button.setVisible(False)
            action_clicked = lambda *args: self.run_kerning_tab_action()
            tab_changed = lambda index: self.update_kerning_tab_header(index)
            self.native_scan_button.clicked.connect(action_clicked)
            self.kerning_tabs.currentChanged.connect(tab_changed)
            self.connections.extend([
                (self.native_scan_button.clicked, action_clicked),
                (self.kerning_tabs.currentChanged, tab_changed),
            ])
            self.update_kerning_tab_header(0)
            return page

        def hide_workflow_table_headers(self):
            """Hide redundant column-label strips in all three work steps.

            Columns and native QTreeWidgetItem checkboxes remain unchanged:
            this is presentation-only and cannot change selected memberships.
            Reapply after scans because FontLab/PythonQt may refresh headers
            while changing labels for a readback-only result.
            """
            for table in (
                self.native_class_table, self.native_glyph_table,
                self.ot_audit_table, self.ot_audit_glyph_table,
                self.ot_sync_class_table, self.ot_sync_glyph_table,
            ):
                try:
                    table.setHeaderHidden(True)
                except Exception:
                    pass
                try:
                    header = read_qt_value(table, "header")
                    if header is not None:
                        header.hide()
                except Exception:
                    pass
                self.style_workflow_table(
                    table,
                    table in (self.native_class_table, self.native_glyph_table)
                    and bool(self.native_selection_locked or
                             self.native_cycle_applied or
                             self.native_write_failed or self.ot_write_failed)
                )
            # With no column-heading strip, every row should read like a
            # compact HTML list. Keep hidden diagnostic fields in the items.
            for table, columns in (
                (self.native_glyph_table, (2, 3)),
                (self.ot_audit_table, (1,)),
                (self.ot_audit_glyph_table, (1,)),
                (self.ot_sync_class_table, (1,)),
            ):
                for column in columns:
                    try:
                        table.setColumnHidden(column, True)
                    except Exception:
                        pass

        def style_workflow_table(self, table, dimmed=False):
            """Flat, separated list rows inside the existing rounded cards.

            The cards carry the corner radius; the inner QTreeWidgets must
            not draw a second rounded outline after their headers are hidden.
            Qt still paints its own native checkbox indicators.
            """
            # A locked list must not turn its entire rectangular viewport
            # pink inside a rounded white card. Lock is communicated by
            # disabled controls, muted text and the separate lock banner.
            surface = M3_LIGHT["surfaceContainerLowest"]
            ink = (M3_LIGHT["outline"] if dimmed else
                   M3_LIGHT["onSurface"])
            selected_surface = (M3_LIGHT["surfaceContainer"] if dimmed else
                                M3_LIGHT["primaryContainer"])
            selected_ink = (M3_LIGHT["outline"] if dimmed else
                            M3_LIGHT["onPrimaryContainer"])
            table.setAlternatingRowColors(False)
            table.setStyleSheet(
                "QTreeWidget{background:%s;color:%s;border:0;"
                "border-radius:0;outline:none;"
                "alternate-background-color:%s;"
                "selection-background-color:%s;}"
                "QTreeWidget::item{background:transparent;color:%s;"
                "padding:5px 5px;border-bottom:1px solid %s;}"
                "QTreeWidget::item:selected{background:%s;color:%s;"
                "border-bottom:1px solid %s;}" % (
                    surface, ink, surface, selected_surface, ink,
                    M3_LIGHT["surfaceContainerHigh"], selected_surface,
                    selected_ink, M3_LIGHT["outlineVariant"]
                )
            )
        def update_kerning_tab_header(self, index):
            self.hide_workflow_table_headers()
            labels = (
                ("Scan again", "Find glyphs to add to existing "
                 "Native kerning groups. Select only what you need."),
                ("Compare again", "See which Native and OpenType "
                 "classes have different glyphs. This only checks."),
                ("Find again", "Choose missing OpenType glyphs, "
                 "check your changes, then confirm on a test COPY."),
            )
            if 0 <= index < len(labels):
                button, description = labels[index]
                if index == 0:
                    if self.native_write_failed or self.ot_write_failed:
                        button = "Scan unavailable"
                        description = (
                            "The previous write could not be verified. "
                            "DO NOT SAVE this test COPY."
                        )
                    elif self.ot_sync_applied:
                        button = "Scan Native again"
                        description = (
                            "This round is complete. Start a new Native "
                            "scan to add more glyphs. Earlier edits are "
                            "not saved yet."
                        )
                    elif self.native_cycle_applied:
                        button = "Scan again"
                        description = (
                            "Native changes verified, not saved. Compare with "
                            "OpenType, or scan again to add more classes."
                        )
                for position, step in enumerate(self.kerning_step_buttons):
                    step.setChecked(position == index)
                self.native_scan_button.setText(button)
                # Keep the stable header tagline across all workflow tabs.
                # `description` is contextual and belongs in the action card.
                self.native_scan_button.setToolTip(
                    "Run this step manually. Never saves or compiles the font."
                )
                self.native_scan_button.setEnabled(
                    index != 0 or not (self.native_write_failed or
                                       self.ot_write_failed)
                )
                # One clear CTA in the guidance banner; no floating/repeated
                # Scan again at the top after a newly completed Native scan.
                self.native_scan_button.setVisible(False)
                if index == 0 and self.ot_write_failed:
                    # An unverified OT write may have changed this font.
                    # Never offer another Native write in that session.
                    for widget in (
                        self.native_class_table, self.native_glyph_table,
                        self.native_filter, self.native_all_button,
                        self.native_clear_button, self.native_check_button,
                        self.native_apply_button,
                    ):
                        widget.setEnabled(False)
                    self.native_apply_badge.setText("DO NOT SAVE")
                    self.native_apply_note.setText(
                        "The previous OpenType write could not be verified. "
                        "Close the test COPY without saving."
                    )
                self.refresh_kerning_guidance()

        def run_kerning_guidance_action(self, action):
            """Mirror existing manual buttons; the writer still checks consent."""
            if action == "scan_native":
                self.safe_native(self.scan_native_tab)
            elif action == "check_native":
                self.safe_native(self.check_native_write_plan)
            elif action == "edit_native":
                self.safe_native(self.unlock_native_selection)
            elif action == "add_native":
                self.safe_native_writer()
            elif action == "compare":
                self.safe_ot_crosscheck(self.run_ot_crosscheck)
            elif action == "find_ot":
                self.safe_ot_sync(self.build_ot_sync_from_audit)
            elif action == "check_ot":
                self.safe_ot_preflight()
            elif action == "add_ot":
                self.safe_ot_writer()
            elif action in ("native", "cross", "ot"):
                self.kerning_tabs.setCurrentIndex(
                    {"native": 0, "cross": 1, "ot": 2}[action]
                )

        def refresh_kerning_guidance(self):
            """Explain the current manual step in one compact status banner."""
            if not hasattr(self, "kerning_guidance_band"):
                return
            index = int(read_qt_value(
                self.kerning_tabs, "currentIndex", 0
            ) or 0)
            kind, title, detail = "info", "Start here", ""
            action, next_label = None, ""
            other_action, other_label = None, ""
            if self.native_write_failed or self.ot_write_failed:
                kind = "error"
                title = "DO NOT SAVE"
                detail = (
                    "A previous write could not be verified. Close the "
                    "test COPY without saving."
                )
            elif index == 0:
                if self.ot_sync_applied:
                    kind, title = "success", "Kerning round complete"
                    detail = (
                        "Native and OpenType changes were verified, but not "
                        "saved. Press Scan again to start a new round."
                    )
                    action, next_label = "scan_native", "Scan again"
                elif self.native_cycle_applied:
                    added_count = (
                        self.native_preview.get("count", 0)
                        if self.native_preview else 0
                    )
                    added_classes = len(
                        (self.native_write_result or {}).get(
                            "steps_passed", ()
                        )
                    )
                    kind, title = "success", (
                        "%d glyph%s added to %d class%s" % (
                            added_count,
                            "" if added_count == 1 else "s",
                            added_classes,
                            "" if added_classes == 1 else "es",
                        )
                        if added_count and added_classes else
                        "Glyphs added to kerning classes"
                    )
                    detail = (
                        "Verified in FontLab. You haven't saved yet. "
                        "You can scan again or compare with OpenType."
                    )
                    action, next_label = "cross", "Compare with OpenType"
                    other_action, other_label = (
                        "scan_native", "Scan Native again"
                    )
                elif self.native_snapshot is None:
                    title = "Start here"
                    detail = (
                        "Scan to find glyphs missing from your Native "
                        "kerning classes. Nothing is changed."
                    )
                    action, next_label = "scan_native", "Scan Native classes"
                elif not self.native_entries:
                    kind, title = "success", "All Native classes are complete"
                    detail = (
                        "Nothing left to add in this scan. "
                        "You can compare with OpenType."
                    )
                    action, next_label = "cross", "Compare with OpenType"
                elif not self.native_selected:
                    title = "Nothing selected"
                    detail = "Tick a class or glyph to continue."
                elif (self.native_preview is not None and
                      self.native_checked_token ==
                      self.native_preview.get("token")):
                    n = len(self.native_selected)
                    kind, title = "action", "Checked %d glyph%s" % (
                        n, "" if n == 1 else "s"
                    )
                    detail = (
                        "Selection locked after safety checks. Confirm "
                        "to add, or edit your selection and check again."
                    )
                    action, next_label = "add_native", "Add %d glyph%s..." % (
                        n, "" if n == 1 else "s"
                    )
                    other_action, other_label = (
                        "edit_native", "Edit selection"
                    )
                else:
                    count = len(self.native_selected)
                    kind = "action"
                    title = "%d glyph%s selected" % (
                        count, "" if count == 1 else "s"
                    )
                    detail = (
                        "Check this selection before adding anything "
                        "to the font."
                    )
                    action, next_label = "check_native", "Check selection"
            elif index == 1:
                if self.ot_crosscheck_error:
                    kind, title = "warning", "Comparison could not finish"
                    detail = (
                        "Open technical details for the reason. "
                        "You can try comparing again."
                    )
                    action, next_label = "compare", "Compare again"
                elif self.ot_crosscheck_report is None:
                    title = "Ready to compare"
                    detail = (
                        "Compare Native with OpenType. This only checks; "
                        "nothing changes."
                    )
                    action, next_label = "compare", "Compare both sides"
                else:
                    statuses = self.ot_crosscheck_report.get("statuses", {})
                    different = (
                        len(self.ot_crosscheck_report.get("rows", ())) -
                        statuses.get("MATCH", 0)
                    )
                    if different:
                        kind, title = "warning", "%d of %d classes differ" % (
                            different,
                            self.ot_crosscheck_report.get("native_classes", 0)
                        )
                        detail = (
                            "The rest are in sync. Select a class to see "
                            "what's missing. This comparison only reads data."
                        )
                    else:
                        kind, title = "success", "Classes are in sync"
                        detail = "Native and OpenType have the same glyphs."
                    if self.native_applied:
                        detail += " Your earlier Native edits are not saved yet."
                    action, next_label = "ot", "Go to OpenType sync"
            elif index == 2:
                if self.ot_sync_applied:
                    kind, title = "success", (
                        "%d glyphs added to OpenType" %
                        self.ot_last_applied_count
                        if self.ot_last_applied_count else
                        "Glyphs added to OpenType"
                    )
                    detail = (
                        "Verified. Your kern feature was backed up first. "
                        "You haven't saved the font yet. To add more glyphs, "
                        "open 01 Native Classes and press Scan again."
                    )
                    # End of the round: no navigation/action buttons in stage 3.
                    # The user returns to Native voluntarily, where a single
                    # Scan again CTA starts a fresh, read-only discovery cycle.
                elif (self.ot_sync_preview is not None and
                      self.ot_sync_preview.get("source_mode") ==
                      "EXTERNAL_FEA_SNAPSHOT"):
                    kind, title = "warning", "Historical FEA preview"
                    detail = (
                        "This older FEA file is for comparison only. "
                        "You cannot add glyphs from this preview."
                    )
                elif self.ot_ui_issue is not None:
                    kind, title = "warning", self.ot_ui_issue[0]
                    detail = self.ot_ui_issue[1]
                    action = self.ot_ui_issue[2]
                    if action == "find_ot":
                        next_label = "Find again"
                    elif action == "check_ot":
                        next_label = "Check again"
                elif self.ot_crosscheck_report is None:
                    title = "Compare first"
                    detail = "OpenType sync uses the Cross-check result."
                    action, next_label = "cross", "Go to Cross-check"
                elif self.ot_sync_preview is None:
                    title = "Find what's missing in OpenType"
                    detail = (
                        "Check which glyphs need adding to OpenType. "
                        "Nothing changes until you confirm."
                    )
                    action, next_label = "find_ot", "Find missing glyphs"
                elif (not self.ot_sync_selected and
                      self.ot_sync_preview.get("blocked_memberships", 0)):
                    kind, title = "warning", "Suggestions need review"
                    detail = (
                        "Some classes need a closer look before any "
                        "glyphs can be added. Select a class for details."
                    )
                elif not self.ot_sync_selected:
                    title = "Nothing selected"
                    detail = (
                        "Choose the OpenType glyphs you want to add, "
                        "or review any blocked suggestions."
                    )
                elif (self.ot_last_preflight is not None and
                      self.ot_last_preflight.get(
                          "ready_for_writer_integration_test", False)):
                    n = len(self.ot_sync_selected)
                    kind, title = "action", "Ready to add %d glyph%s" % (
                        n, "" if n == 1 else "s"
                    )
                    detail = (
                        "Safety checks passed. Confirm the OpenType "
                        "change and its FEA backup."
                    )
                    action, next_label = "add_ot", "Add %d glyph%s..." % (
                        n, "" if n == 1 else "s"
                    )
                else:
                    count = len(self.ot_sync_selected)
                    kind = "action"
                    title = "%d glyph%s selected" % (
                        count, "" if count == 1 else "s"
                    )
                    detail = (
                        "Check these OpenType additions before changing "
                        "the font."
                    )
                    action, next_label = "check_ot", "Check changes"
            # Match the light theme's calm, white guidance cards. Only the
            # icon and border signal attention; no off-palette blue/yellow
            # backgrounds or competing full-width success/error fills.
            accents = {
                "info": (M3_LIGHT["primaryContainer"],
                         M3_LIGHT["onPrimaryContainer"],
                         M3_LIGHT["outlineVariant"], "i"),
                "action": (M3_LIGHT["primaryContainer"],
                           M3_LIGHT["onPrimaryContainer"],
                           M3_LIGHT["primary"], "\u2192"),
                "success": (M3_LIGHT["surfaceContainer"],
                            SUCCESS_COLOR, M3_LIGHT["outlineVariant"],
                            "\u2713"),
                "warning": (M3_LIGHT["tertiaryContainer"],
                            M3_LIGHT["onTertiaryContainer"],
                            M3_LIGHT["tertiary"], "!"),
                "error": (M3_LIGHT["errorContainer"],
                          M3_LIGHT["onErrorContainer"],
                          M3_LIGHT["error"], "!"),
            }
            icon_background, icon_ink, border, symbol = accents[kind]
            icon_family = getattr(self, "system_icon_font_family", "")
            if icon_family:
                symbol = {
                    "info": WINDOWS_INFO_GLYPH,
                    "action": WINDOWS_FORWARD_GLYPH,
                    "success": WINDOWS_CHECK_GLYPH,
                    "warning": WINDOWS_WARNING_GLYPH,
                    "error": WINDOWS_ERROR_GLYPH,
                }[kind]
            native_locked = (index == 0 and (
                bool(getattr(self, "native_selection_locked", False)) or
                self.native_cycle_applied or self.ot_sync_applied
            ))
            if native_locked and icon_family:
                symbol = WINDOWS_LOCK_GLYPH
            self.kerning_guidance_band.setStyleSheet(
                "QFrame#kerningGuidanceBand{background:%s;"
                "border:1px solid %s;border-radius:9px;}" %
                (M3_LIGHT["surfaceContainerLowest"], border)
            )
            self.kerning_guidance_icon.setText(symbol)
            self.kerning_guidance_icon.setStyleSheet(
                "QLabel#kerningGuidanceIcon{background:%s;color:%s;"
                "border:0;border-radius:8px;font-size:17px;"
                "font-weight:bold;}" % (icon_background, icon_ink)
            )
            if hasattr(self.kerning_guidance_icon, "setFont"):
                if icon_family:
                    self.kerning_guidance_icon.setFont(
                        QtGui.QFont(icon_family, 17)
                    )
                elif hasattr(self, "kerning_guidance_regular_font"):
                    self.kerning_guidance_icon.setFont(
                        self.kerning_guidance_regular_font
                    )
            self.kerning_guidance_title.setStyleSheet(
                "color:%s;background:transparent;border:0;" %
                (M3_LIGHT["error"] if kind == "error" else
                 M3_LIGHT["onSurface"])
            )
            self.kerning_guidance_text.setStyleSheet(
                "color:%s;background:transparent;border:0;" %
                M3_LIGHT["onSurfaceVariant"]
            )
            self.kerning_guidance_title.setText(title)
            self.kerning_guidance_text.setText(detail)
            self.kerning_guidance_action = action
            self.kerning_guidance_other_action = other_action
            if action is not None:
                self.kerning_guidance_next.setText(next_label)
            self.kerning_guidance_next.setVisible(action is not None)
            if other_action is not None:
                self.kerning_guidance_other.setText(other_label)
            self.kerning_guidance_other.setVisible(other_action is not None)
            self.refresh_kerning_metrics(index)

        def refresh_kerning_metrics(self, index):
            """Show values for the current step, as in the approved HTML UX."""
            if not hasattr(self, "native_metric_titles"):
                return
            snapshot = self.native_snapshot or self.ot_crosscheck_native_snapshot
            report = self.ot_crosscheck_report
            preview = self.ot_sync_preview
            if index == 0:
                labels = ("GLYPHS", "NATIVE CLASSES", "CAN ADD", "SELECTED")
                values = (
                    len(snapshot["available"]) if snapshot else "--",
                    len(snapshot["groups"]) if snapshot else "--",
                    len(self.native_entries) if self.native_snapshot else "--",
                    len(self.native_selected) if self.native_snapshot else "--",
                )
                if self.native_cycle_applied and self.native_preview is not None:
                    labels = (
                        "GLYPHS", "NATIVE CLASSES", "ADDED THIS ROUND",
                        "OPENTYPE CHECK"
                    )
                    values = (values[0], values[1],
                              self.native_preview["count"],
                              "Synced" if self.ot_sync_applied else "Not yet")
            elif index == 1:
                labels = (
                    "NATIVE CLASSES", "OPENTYPE CLASSES", "IN SYNC",
                    "NEED REVIEW"
                )
                values = (
                    report["native_classes"] if report else "--",
                    report["ot_classes"] if report else "--",
                    report["statuses"].get("MATCH", 0) if report else "--",
                    len(report["rows"]) - report["statuses"].get("MATCH", 0)
                    if report else "--",
                )
            else:
                labels = (
                    "OPENTYPE CLASSES", "GLYPHS TO ADD", "NEED REVIEW",
                    "SELECTED"
                )
                values = (
                    len(self.ot_sync_rows) if preview else "--",
                    preview["candidate_unique_memberships"] if preview else "--",
                    preview["blocked_memberships"] if preview else "--",
                    len(self.ot_sync_selected) if preview else "--",
                )
                if self.ot_sync_applied:
                    labels = (
                        "OT CLASSES UPDATED", "GLYPHS ADDED", "READBACK",
                        "FONT FILE"
                    )
                    values = (
                        len(self.ot_sync_verified_by_class),
                        self.ot_last_applied_count, "Passed", "Not saved"
                    )
            for key, label, value in zip(
                    ("glyphs", "classes", "ot_classes", "differences"),
                    labels, values):
                self.native_metric_titles[key].setText(label)
                self.native_metrics[key].setText(str(value))
            # One visual focal point per tab. The same four reused cards
            # change meaning with the workflow: selected (primary), differs
            # (tertiary), in-sync (success on white). No competing fills.
            cards = getattr(self, "native_metric_cards", None)
            if cards:
                emphasis = {}
                if index == 0:
                    emphasis["differences"] = (
                        M3_LIGHT["primaryContainer"],
                        M3_LIGHT["primaryFixedDim"],
                        M3_LIGHT["onPrimaryContainer"]
                    )
                    if self.native_cycle_applied:
                        emphasis["ot_classes"] = (
                            M3_LIGHT["surfaceContainerLowest"],
                            M3_LIGHT["outlineVariant"], SUCCESS_COLOR
                        )
                elif index == 1:
                    emphasis["ot_classes"] = (
                        M3_LIGHT["surfaceContainerLowest"],
                        M3_LIGHT["outlineVariant"], SUCCESS_COLOR
                    )
                    if report and (len(report["rows"]) -
                                   report["statuses"].get("MATCH", 0)):
                        emphasis["differences"] = (
                            M3_LIGHT["tertiaryContainer"],
                            M3_LIGHT["tertiaryFixedDim"],
                            M3_LIGHT["onTertiaryContainer"]
                        )
                else:
                    emphasis["classes"] = (
                        M3_LIGHT["surfaceContainerLowest"],
                        M3_LIGHT["outlineVariant"], SUCCESS_COLOR
                    )
                    if self.ot_sync_applied:
                        emphasis["ot_classes"] = (
                            M3_LIGHT["surfaceContainerLowest"],
                            M3_LIGHT["outlineVariant"], SUCCESS_COLOR
                        )
                    elif preview and preview["blocked_memberships"]:
                        emphasis["ot_classes"] = (
                            M3_LIGHT["tertiaryContainer"],
                            M3_LIGHT["tertiaryFixedDim"],
                            M3_LIGHT["onTertiaryContainer"]
                        )
                    emphasis["differences"] = (
                        M3_LIGHT["primaryContainer"],
                        M3_LIGHT["primaryFixedDim"],
                        M3_LIGHT["onPrimaryContainer"]
                    )
                for key in ("glyphs", "classes", "ot_classes", "differences"):
                    bg, border, ink = emphasis.get(key, (
                        M3_LIGHT["surfaceContainerLowest"],
                        M3_LIGHT["outlineVariant"], M3_LIGHT["onSurface"]
                    ))
                    cards[key].setStyleSheet(
                        "QFrame#nativeMetric_%s{background:%s;"
                        "border:1px solid %s;border-radius:10px;}" %
                        (key, bg, border)
                    )
                    self.native_metric_titles[key].setStyleSheet(
                        "color:%s;background:transparent;border:0;"
                        "font-size:9px;font-weight:bold;" %
                        (ink if key in emphasis else M3_LIGHT["onSurfaceVariant"])
                    )
                    self.native_metrics[key].setStyleSheet(
                        "color:%s;background:transparent;border:0;" % ink
                    )

        def run_kerning_tab_action(self):
            # FontLab PythonQt may expose Qt property getters as values,
            # not callables (e.g. currentIndex is already an int).
            index = int(read_qt_value(self.kerning_tabs, "currentIndex", 0))
            if index == 0:
                self.safe_native(self.scan_native_tab)
            elif index == 1:
                self.safe_ot_crosscheck(self.run_ot_crosscheck)
            elif index == 2:
                self.safe_ot_sync(self.build_ot_sync_from_audit)

        def native_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            header_band = QtGui.QFrame()
            header_band.setObjectName("nativeTopBand")
            self.native_top_band = header_band
            header_layout = QtGui.QVBoxLayout(header_band)
            header_layout.setContentsMargins(18, 11, 18, 11)

            title_row = QtGui.QHBoxLayout()
            header_text = QtGui.QVBoxLayout()
            header_text.setSpacing(3)
            title_line = QtGui.QHBoxLayout()
            title_line.addWidget(self.heading("Kerning Studio", 15))
            title_line.addStretch(1)
            header_text.addLayout(title_line)
            self.kerning_description = self.paragraph(
                "Keep your Native and OpenType kerning classes in sync"
            )
            header_text.addWidget(self.kerning_description)
            title_row.addLayout(header_text, 1)
            self.native_scan_button = QtGui.QPushButton("Scan Native Classes")
            self.native_scan_button.setObjectName("nativeScan")
            self.native_scan_button.setMinimumHeight(43)
            # The guidance card owns Scan / Scan again. Never let the older
            # top-right action appear during construction or after a re-scan.
            self.native_scan_button.setVisible(False)
            title_row.addWidget(self.native_scan_button)
            header_layout.addLayout(title_row)
            layout.addWidget(header_band)

            metrics_band = QtGui.QFrame()
            metrics_band.setObjectName("nativeMetricBand")
            self.native_metrics_band = metrics_band
            metrics = QtGui.QHBoxLayout(metrics_band)
            metrics.setContentsMargins(18, 10, 18, 10)
            metrics.setSpacing(9)
            self.native_metrics = {}
            self.native_metric_titles = {}
            self.native_metric_cards = {}
            for key, label, color, border, ink in (
                ("glyphs", "GLYPHS", M3_LIGHT["surfaceContainerLowest"],
                 M3_LIGHT["outlineVariant"], M3_LIGHT["onSurface"]),
                ("classes", "NATIVE CLASSES", M3_LIGHT["surfaceContainerLowest"],
                 M3_LIGHT["outlineVariant"], M3_LIGHT["primary"]),
                ("ot_classes", "OT KERN CLASSES", M3_LIGHT["surfaceContainerLowest"],
                 M3_LIGHT["outlineVariant"], M3_LIGHT["tertiary"]),
                ("differences", "NEEDS REVIEW", M3_LIGHT["primaryContainer"],
                 M3_LIGHT["primaryFixedDim"], M3_LIGHT["onPrimaryContainer"]),
            ):
                card = self.make_card("nativeMetric_" + key, color, border, 12)
                column = QtGui.QVBoxLayout(card)
                column.setContentsMargins(12, 5, 10, 5)
                column.setSpacing(1)
                caption = QtGui.QLabel(label)
                caption.setStyleSheet(
                    "color:%s;background:transparent;border:0;"
                    "font-size:9px;font-weight:bold;" % ink
                )
                number = QtGui.QLabel("\u2014")
                number.setFont(
                    QtGui.QFont(self.ui_font_family, 19, QtGui.QFont.Bold)
                )
                number.setStyleSheet(
                    "color:%s;background:transparent;border:0;" % ink
                )
                column.addWidget(caption)
                column.addWidget(number)
                self.native_metrics[key] = number
                self.native_metric_titles[key] = caption
                self.native_metric_cards[key] = card
                metrics.addWidget(card, 1)
            layout.addWidget(metrics_band)

            work_area = QtGui.QWidget()
            work_area.setObjectName("nativeWorkArea")
            work_layout = QtGui.QVBoxLayout(work_area)
            work_layout.setContentsMargins(18, 15, 18, 12)
            work_layout.setSpacing(13)

            self.native_all_button = QtGui.QPushButton("Select all")
            self.native_all_button.setText("All")
            self.native_all_button.setToolTip("Select all proposed glyphs")
            self.native_clear_button = QtGui.QPushButton("Clear")
            self.native_selection_label = QtGui.QLabel("0 glyphs selected")
            self.native_selection_label.setStyleSheet(
                "background:%s;color:%s;border-radius:8px;"
                "padding:8px;font-weight:bold;" %
                (M3_LIGHT["primaryContainer"], M3_LIGHT["onPrimaryContainer"])
            )
            self.native_filter = QtGui.QLineEdit()
            self.native_filter.setPlaceholderText("Search classes or glyphs...")
            self.native_filter.setMinimumWidth(145)
            self.native_report_button = QtGui.QPushButton("Report")
            self.native_report_button.setObjectName("nativeReport")
            self.native_report_button.setToolTip(
                "Open scan details and export a JSON report if needed."
            )
            self.native_expand_button = QtGui.QPushButton("Expand workspace")
            # The two panes already have enough room. Keep the old signal and
            # layout code untouched for compatibility, but hide this control.
            self.native_expand_button.setVisible(False)

            tables = QtGui.QHBoxLayout()
            tables.setSpacing(11)
            class_panel = self.make_card(
                "nativeClassPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 15
            )
            class_col = QtGui.QVBoxLayout(class_panel)
            class_col.setContentsMargins(1, 1, 1, 1)
            class_col.setSpacing(0)
            class_head = QtGui.QFrame()
            class_head.setObjectName("nativeClassHead")
            class_head_layout = QtGui.QVBoxLayout(class_head)
            class_head_layout.setContentsMargins(13, 10, 13, 10)
            class_head_layout.setSpacing(5)
            class_actions = QtGui.QHBoxLayout()
            class_actions.addWidget(self.heading("Browse classes", 11))
            class_actions.addStretch(1)
            class_actions.addWidget(self.native_all_button)
            class_actions.addWidget(self.native_clear_button)
            class_actions.addWidget(self.native_selection_label)
            class_head_layout.addLayout(class_actions)
            self.native_class_hint = self.paragraph(
                "Click a row to preview. Tick it to select all its glyphs."
            )
            class_head_layout.addWidget(self.native_class_hint)
            class_head_layout.addWidget(self.native_filter)
            class_col.addWidget(class_head)
            class_body = QtGui.QWidget()
            class_body_layout = QtGui.QVBoxLayout(class_body)
            class_body_layout.setContentsMargins(8, 7, 8, 8)
            class_body_layout.setSpacing(0)
            self.native_class_table = QtGui.QTreeWidget()
            self.native_class_table.setColumnCount(4)
            self.native_class_table.setHeaderLabels(
                ["Select", "Class", "Side", "Can add"]
            )
            self.native_class_table.setRootIsDecorated(False)
            self.native_class_table.setIndentation(0)
            self.native_class_table.setItemsExpandable(False)
            # The left workspace already has a descriptive card title.
            # Keep Side and +Adds in each row, but omit the redundant
            # Select / Class / Side / Can add header strip (HTML reference).
            try:
                read_qt_value(self.native_class_table, "header").hide()
            except Exception:
                pass
            self.native_class_table.setAlternatingRowColors(True)
            self.native_class_table.setSelectionMode(
                QtGui.QAbstractItemView.SingleSelection
            )
            self.native_class_table.setMinimumHeight(170)
            self.native_class_table.setStyleSheet(
                "QTreeWidget{background:#FFFFFF;border:0;border-radius:0;}"
            )
            self.configure_tree_columns(
                self.native_class_table, (48, 105, 85, 80), (3,)
            )
            class_body_layout.addWidget(self.native_class_table, 1)
            class_col.addWidget(class_body, 1)
            tables.addWidget(class_panel, 1)

            glyph_panel = self.make_card(
                "nativeGlyphPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 15
            )
            glyph_col = QtGui.QVBoxLayout(glyph_panel)
            glyph_col.setContentsMargins(1, 1, 1, 1)
            glyph_col.setSpacing(0)
            glyph_head = QtGui.QFrame()
            glyph_head.setObjectName("nativeGlyphHead")
            glyph_head_layout = QtGui.QVBoxLayout(glyph_head)
            glyph_head_layout.setContentsMargins(13, 10, 13, 10)
            glyph_head_layout.setSpacing(5)
            self.native_glyph_title = self.heading(
                "Glyphs to add  /  Select a class", 11
            )
            glyph_header = QtGui.QHBoxLayout()
            glyph_header.addWidget(self.native_glyph_title)
            glyph_header.addStretch(1)
            glyph_header.addWidget(self.native_report_button)
            glyph_header.addWidget(self.native_expand_button)
            glyph_head_layout.addLayout(glyph_header)
            self.native_glyph_hint = self.paragraph(
                "Tick individual glyphs; switching classes preserves selections."
            )
            glyph_head_layout.addWidget(self.native_glyph_hint)
            glyph_col.addWidget(glyph_head)
            glyph_body = QtGui.QWidget()
            glyph_body_layout = QtGui.QVBoxLayout(glyph_body)
            glyph_body_layout.setContentsMargins(8, 7, 8, 8)
            glyph_body_layout.setSpacing(0)
            self.native_glyph_table = QtGui.QTreeWidget()
            self.native_glyph_table.setColumnCount(4)
            self.native_glyph_table.setHeaderLabels([
                "Select", "Glyph to add", "Base & accents", "Unicode"
            ])
            self.native_glyph_table.setRootIsDecorated(False)
            self.native_glyph_table.setIndentation(0)
            self.native_glyph_table.setItemsExpandable(False)
            self.native_glyph_table.setAlternatingRowColors(True)
            self.native_glyph_table.setSelectionMode(
                QtGui.QAbstractItemView.NoSelection
            )
            self.native_glyph_table.setMinimumHeight(170)
            self.native_glyph_table.setStyleSheet(
                "QTreeWidget{background:#FFFFFF;border:0;border-radius:0;}"
            )
            self.configure_tree_columns(
                self.native_glyph_table, (42, 220, 0, 0), (1,)
            )
            glyph_body_layout.addWidget(self.native_glyph_table, 1)
            glyph_col.addWidget(glyph_body, 1)
            tables.addWidget(glyph_panel, 1)
            work_layout.addLayout(tables, 1)

            self.native_lower_container = QtGui.QWidget()
            lower = QtGui.QHBoxLayout(self.native_lower_container)
            lower.setContentsMargins(0, 0, 0, 0)
            lower.setSpacing(11)
            preview_panel = self.make_card(
                "nativePreviewPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 15
            )
            preview_col = QtGui.QVBoxLayout(preview_panel)
            preview_col.setContentsMargins(1, 1, 1, 1)
            preview_col.setSpacing(0)
            preview_head_frame = QtGui.QFrame()
            preview_head_frame.setObjectName("nativePreviewHead")
            preview_head = QtGui.QHBoxLayout(preview_head_frame)
            preview_head.setContentsMargins(11, 8, 11, 8)
            preview_head.addWidget(self.heading("What will change?", 11))
            preview_head.addStretch()
            self.native_live_badge = QtGui.QLabel("NOT SCANNED")
            self.native_live_badge.setStyleSheet(
                "background:%s;color:%s;border-radius:9px;"
                "padding:6px 9px;font-weight:bold;font-size:9px;" %
                (M3_LIGHT["primaryContainer"], M3_LIGHT["onPrimaryContainer"])
            )
            preview_head.addWidget(self.native_live_badge)
            self.native_export_button = QtGui.QPushButton("Export JSON")
            self.native_export_button.setEnabled(False)
            preview_head.addWidget(self.native_export_button)
            preview_col.addWidget(preview_head_frame)
            preview_body = QtGui.QWidget()
            self.native_preview_body = preview_body
            preview_body_layout = QtGui.QVBoxLayout(preview_body)
            preview_body_layout.setContentsMargins(12, 9, 12, 9)
            preview_body_layout.setSpacing(5)
            self.native_latest_line = self.paragraph(
                "Latest: Waiting for native class scan. Font unchanged."
            )
            preview_body_layout.addWidget(self.native_latest_line)
            self.native_diagnostics = QtGui.QPlainTextEdit()
            self.native_diagnostics.setReadOnly(True)
            self.native_diagnostics.setMinimumHeight(105)
            self.native_diagnostics.setMaximumHeight(175)
            self.native_diagnostics.setPlainText(
                "Scan native classes to inspect proposals. Font unchanged."
            )
            self.native_report_expanded = False
            self.native_diagnostics.setVisible(False)
            preview_body_layout.addWidget(self.native_diagnostics)
            preview_body.setVisible(False)
            preview_col.addWidget(preview_body, 1)
            lower.addWidget(preview_panel, 7)

            apply_panel = self.make_card(
                "nativeApplyPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 15
            )
            apply_col = QtGui.QVBoxLayout(apply_panel)
            apply_col.setContentsMargins(1, 1, 1, 1)
            apply_col.setSpacing(0)
            apply_head_frame = QtGui.QFrame()
            apply_head_frame.setObjectName("nativeApplyHead")
            apply_head = QtGui.QHBoxLayout(apply_head_frame)
            apply_head.setContentsMargins(11, 8, 11, 8)
            apply_head.addWidget(self.heading("Confirm changes", 11))
            apply_head.addStretch(1)
            self.native_apply_badge = QtGui.QLabel("CHECK FIRST")
            self.native_apply_badge.setStyleSheet(
                "background:%s;color:%s;border-radius:9px;"
                "padding:6px 9px;font-weight:bold;" %
                (M3_LIGHT["errorContainer"], M3_LIGHT["onErrorContainer"])
            )
            apply_head.addWidget(self.native_apply_badge)
            apply_col.addWidget(apply_head_frame)
            apply_body = QtGui.QWidget()
            apply_body_layout = QtGui.QVBoxLayout(apply_body)
            apply_body_layout.setContentsMargins(12, 9, 12, 9)
            apply_body_layout.setSpacing(5)
            self.native_apply_note = self.paragraph(
                "Select glyphs, check your selection, then confirm. "
                "You will save the test COPY yourself."
            )
            apply_body_layout.addWidget(self.native_apply_note)
            native_actions = QtGui.QHBoxLayout()
            native_actions.setSpacing(7)
            self.native_check_button = QtGui.QPushButton("Check selection")
            self.native_check_button.setEnabled(False)
            self.native_check_button.setToolTip(
                "Check the live Native classes, kerning pairs, font COPY "
                "and selected glyphs. This does not write or save."
            )
            native_actions.addWidget(self.native_check_button, 1)
            self.native_apply_button = QtGui.QPushButton("Add selected glyphs...")
            self.native_apply_button.setObjectName("nativeApply")
            self.native_apply_button.setToolTip(
                "Add the selected glyphs to existing Native kerning classes "
                "in your saved test COPY. Confirmation is required."
            )
            self.native_apply_button.setEnabled(False)
            self.native_apply_button.setMinimumHeight(32)
            native_actions.addWidget(self.native_apply_button, 1)
            apply_body_layout.addLayout(native_actions)
            apply_col.addWidget(apply_body, 1)
            lower.addWidget(apply_panel, 5)
            # The guidance banner owns Check selection and Add glyphs.
            # Keep the original guarded buttons alive, but not duplicated
            # in a second visible confirmation card.
            apply_panel.setVisible(False)
            work_layout.addWidget(self.native_lower_container, 0)
            # Keep internal diagnostics as state, not an entire bottom toolbar.
            # The compact Report button in the right pane opens them on demand.
            self.native_lower_container.setVisible(False)
            layout.addWidget(work_area, 1)

            self.native_all_button.setEnabled(False)
            self.native_clear_button.setEnabled(False)
            self.native_all_button.clicked.connect(
                lambda *args: self.safe_native(lambda: self.select_all_native(True))
            )
            self.native_clear_button.clicked.connect(
                lambda *args: self.safe_native(lambda: self.select_all_native(False))
            )
            self.native_expand_button.clicked.connect(
                lambda *args: self.toggle_native_workspace()
            )
            self.native_export_button.clicked.connect(
                lambda *args: self.safe_native(self.export_native_report)
            )
            self.native_report_button.clicked.connect(
                lambda *args: self.toggle_native_report()
            )
            self.native_check_button.clicked.connect(
                lambda *args: self.safe_native(self.check_native_write_plan)
            )
            self.native_apply_button.clicked.connect(
                lambda *args: self.safe_native_writer()
            )
            self.native_filter.textChanged.connect(
                lambda *args: self.safe_native(self.filter_native_classes)
            )
            class_toggled = lambda item, col: self.safe_native(
                lambda: self.on_native_class_toggled(item, col)
            )
            glyph_toggled = lambda item, col: self.safe_native(
                lambda: self.on_native_glyph_toggled(item, col)
            )
            class_focus = lambda item, old: self.safe_native(
                lambda: self.show_native_class(item)
            )
            self.native_class_table.itemChanged.connect(class_toggled)
            self.native_glyph_table.itemChanged.connect(glyph_toggled)
            self.native_class_table.currentItemChanged.connect(class_focus)
            self.connections.extend([
                (self.native_class_table.itemChanged, class_toggled),
                (self.native_glyph_table.itemChanged, glyph_toggled),
                (self.native_class_table.currentItemChanged, class_focus),
            ])
            return page

        def empty_ot_table(self, labels, widths):
            table = QtGui.QTreeWidget()
            table.setColumnCount(len(labels))
            table.setHeaderLabels(labels)
            table.setRootIsDecorated(False)
            table.setAlternatingRowColors(True)
            for i, width in enumerate(widths):
                table.setColumnWidth(i, width)
            table.setEnabled(False)
            return table

        def opentype_kern_audit_page(self):
            """Native V2 vs. V1 text 'kern' audit; NO write controls."""
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(20, 16, 20, 14)
            layout.setSpacing(14)

            self.ot_audit_scan_button = QtGui.QPushButton("Compare both sides", page)
            self.ot_audit_scan_button.setObjectName("nativeScan")
            self.ot_audit_scan_button.setToolTip(
                "Read the current Native groups and text kern feature; never apply."
            )
            self.ot_audit_scan_button.setVisible(False)
            summary_band = QtGui.QFrame()
            summary_band.setObjectName("otAuditSummaryBand")
            summary_row = QtGui.QHBoxLayout(summary_band)
            summary_row.setContentsMargins(13, 12, 13, 12)
            summary_row.setSpacing(13)
            summary_row.addWidget(self.heading("READ ONLY", 9))
            self.ot_audit_summary = self.paragraph(
                "Waiting for comparison. Scan Native and OpenType classes "
                "to see which glyphs are in sync."
            )
            self.ot_audit_summary.setFont(QtGui.QFont("Consolas", 9))
            summary_row.addWidget(self.ot_audit_summary, 1)
            layout.addWidget(summary_band)
            # The contextual card above this tab already explains read-only
            # comparison; this second summary repeats the same information.
            summary_band.setVisible(False)

            tables = QtGui.QHBoxLayout()
            tables.setSpacing(16)
            native_panel = self.make_card(
                "otAuditNativePanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 10
            )
            native_col = QtGui.QVBoxLayout(native_panel)
            native_col.setContentsMargins(1, 1, 1, 1)
            native_col.setSpacing(0)
            native_head = QtGui.QFrame()
            native_head.setObjectName("otAuditPanelHead")
            native_head_row = QtGui.QHBoxLayout(native_head)
            native_head_row.setContentsMargins(13, 12, 13, 12)
            native_head_row.addWidget(self.heading(
                "Class cross-check", 11, M3_LIGHT["onSurface"]
            ))
            native_head_row.addStretch(1)
            self.ot_audit_count_label = self.paragraph("Not scanned")
            self.ot_audit_count_label.setFont(QtGui.QFont("Consolas", 9))
            native_head_row.addWidget(self.ot_audit_count_label)
            self.ot_audit_details_button = QtGui.QPushButton("Details")
            self.ot_audit_details_button.setObjectName("nativeReport")
            self.ot_audit_details_button.setToolTip(
                "Open how Native and OpenType classes were compared."
            )
            native_head_row.addWidget(self.ot_audit_details_button)
            native_col.addWidget(native_head)
            # No column-header strip: rows can sit directly beneath the
            # divider as in the compact HTML cross-check prototype.
            self.ot_audit_table = QtGui.QTreeWidget()
            self.ot_audit_table.setColumnCount(4)
            self.ot_audit_table.setHeaderLabels(
                ["Native class", "OpenType class", "Result", "N / OT"]
            )
            self.ot_audit_table.setRootIsDecorated(False)
            self.ot_audit_table.setIndentation(0)
            self.ot_audit_table.setAlternatingRowColors(True)
            self.configure_tree_columns(
                self.ot_audit_table, (174, 0, 160, 75), (0, 2)
            )
            native_col.addWidget(self.ot_audit_table, 1)
            tables.addWidget(native_panel, 7)

            difference_panel = self.make_card(
                "otAuditGlyphPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 10
            )
            difference_col = QtGui.QVBoxLayout(difference_panel)
            difference_col.setContentsMargins(1, 1, 1, 1)
            difference_col.setSpacing(0)
            inspector_head = QtGui.QFrame()
            inspector_head.setObjectName("otAuditInspectorHead")
            inspector_head_col = QtGui.QVBoxLayout(inspector_head)
            inspector_head_col.setContentsMargins(13, 12, 13, 12)
            inspector_head_col.setSpacing(5)
            inspector_status_row = QtGui.QHBoxLayout()
            self.ot_audit_detail = self.heading("Select a class", 10)
            self.ot_audit_detail.setWordWrap(True)
            # Let the title use the available width; otherwise the MATCH
            # badge sits beside a squeezed label and breaks (LEFT) onto an
            # unnecessary second line in FontLab's PythonQt layout.
            inspector_status_row.addWidget(self.ot_audit_detail, 1)
            self.ot_audit_status_badge = QtGui.QLabel("--")
            self.ot_audit_status_badge.setAlignment(QtCore.Qt.AlignCenter)
            self.ot_audit_status_badge.setFixedHeight(24)
            self.ot_audit_status_badge.setStyleSheet(
                "background:%s;color:%s;padding:3px 9px;"
                "border-radius:12px;font-weight:bold;font-size:9px;" % (
                    M3_LIGHT["surfaceContainerHigh"],
                    M3_LIGHT["onSurfaceVariant"]
                )
            )
            inspector_status_row.addWidget(self.ot_audit_status_badge)
            inspector_head_col.addLayout(inspector_status_row)
            self.ot_audit_reason = self.paragraph(
                "Click a class to compare its glyph members."
            )
            inspector_head_col.addWidget(self.ot_audit_reason)
            difference_col.addWidget(inspector_head)

            inspector_body = QtGui.QWidget()
            inspector_body_col = QtGui.QVBoxLayout(inspector_body)
            inspector_body_col.setContentsMargins(12, 13, 12, 13)
            inspector_body_col.setSpacing(10)
            comparison_label = self.paragraph("GLYPHS THAT DIFFER")
            comparison_label.setFont(QtGui.QFont(
                self.ui_font_family, 9, QtGui.QFont.Bold
            ))
            # The inspector title already identifies what these glyphs are.
            # A second all-caps heading adds noise above a headerless list.
            comparison_label.setVisible(False)
            inspector_body_col.addWidget(comparison_label)
            # Important states get their own notice, never an extra sentence
            # buried at the end of the numeric comparison summary.
            self.ot_audit_notice = QtGui.QFrame()
            self.ot_audit_notice.setObjectName("otAuditReviewCard")
            notice_layout = QtGui.QVBoxLayout(self.ot_audit_notice)
            notice_layout.setContentsMargins(13, 12, 13, 12)
            notice_layout.setSpacing(5)
            self.ot_audit_notice_title = self.heading("", 10)
            notice_layout.addWidget(self.ot_audit_notice_title)
            self.ot_audit_notice_description = self.paragraph("")
            notice_layout.addWidget(self.ot_audit_notice_description)
            inspector_body_col.addWidget(self.ot_audit_notice)
            self.ot_audit_notice.setVisible(False)
            self.ot_audit_glyph_table = QtGui.QTreeWidget()
            self.ot_audit_glyph_table.setColumnCount(3)
            self.ot_audit_glyph_table.setHeaderLabels(
                ["Glyph", "Native", "OpenType"]
            )
            self.ot_audit_glyph_table.setRootIsDecorated(False)
            self.ot_audit_glyph_table.setAlternatingRowColors(True)
            self.ot_audit_glyph_table.setSelectionMode(
                QtGui.QAbstractItemView.NoSelection
            )
            self.configure_tree_columns(
                self.ot_audit_glyph_table, (200, 0, 110), (0,)
            )
            self.ot_audit_glyph_table.setFixedHeight(118)
            inspector_body_col.addWidget(self.ot_audit_glyph_table)

            # The context banner already states that Cross-check is read only.
            # Do not obscure the glyph table with a second warning callout.
            inspector_body_col.addStretch(1)
            difference_col.addWidget(inspector_body, 1)

            inspector_footer = QtGui.QFrame()
            inspector_footer.setObjectName("otAuditInspectorFooter")
            inspector_footer_row = QtGui.QHBoxLayout(inspector_footer)
            inspector_footer_row.setContentsMargins(12, 9, 12, 9)
            inspector_footer_row.setSpacing(8)
            self.ot_audit_footer_note = self.paragraph(
                "Comparison only"
            )
            inspector_footer_row.addWidget(self.ot_audit_footer_note, 1)
            self.ot_audit_to_sync = QtGui.QPushButton("Go to OpenType sync  >")
            self.ot_audit_to_sync.setObjectName("otAuditSync")
            self.ot_audit_to_sync.setEnabled(False)
            to_sync = lambda *args: self.kerning_tabs.setCurrentIndex(2)
            self.ot_audit_to_sync.clicked.connect(to_sync)
            self.connections.append((self.ot_audit_to_sync.clicked, to_sync))
            inspector_footer_row.addWidget(self.ot_audit_to_sync)
            difference_col.addWidget(inspector_footer)
            # The banner above the tables is the one place to proceed.
            # A second CTA at the bottom of this inspector was redundant.
            inspector_footer.setVisible(False)
            tables.addWidget(difference_panel, 5)
            layout.addLayout(tables, 1)

            self.ot_audit_notes = QtGui.QPlainTextEdit()
            self.ot_audit_notes.setReadOnly(True)
            self.ot_audit_notes.setMinimumHeight(90)
            self.ot_audit_notes.setMaximumHeight(150)
            self.ot_audit_notes.setPlainText(
                "No scan yet. One OT class may be used in both kerning "
                "positions; each Native side is verified separately. "
                "Nothing will be modified."
            )
            self.ot_audit_notes.setVisible(False)
            self.ot_audit_details_button.clicked.connect(
                self.toggle_ot_audit_details
            )
            layout.addWidget(self.ot_audit_notes)
            self.ot_audit_scan_button.clicked.connect(
                lambda *args: self.safe_ot_crosscheck(self.run_ot_crosscheck)
            )
            class_focus = lambda item, old: self.show_ot_audit_class(item)
            self.ot_audit_table.currentItemChanged.connect(class_focus)
            self.connections.append(
                (self.ot_audit_table.currentItemChanged, class_focus)
            )
            return page

        def toggle_ot_audit_details(self):
            self.show_readonly_details_dialog(
                "Cross-check details",
                "Read-only notes on class matching and the OpenType reader.",
                read_qt_value(self.ot_audit_notes, "toPlainText", "")
            )

        def set_ot_audit_status_badge(self, status):
            colors = {
                "MATCH": (M3_LIGHT.get("onPrimary", "#FFFFFF"), SUCCESS_COLOR),
                "DIFFERENT": (M3_LIGHT["onTertiaryContainer"],
                              M3_LIGHT["tertiaryContainer"]),
            }
            foreground, background = colors.get(status, (
                M3_LIGHT["onSurfaceVariant"], M3_LIGHT["surfaceContainerHigh"]
            ))
            self.ot_audit_status_badge.setText({
                "MATCH": "IN SYNC",
                "DIFFERENT": "DIFFERS",
                "AMBIGUOUS": "REVIEW",
                "UNMAPPED": "REVIEW",
            }.get(status, status))
            self.ot_audit_status_badge.setStyleSheet(
                "background:%s;color:%s;padding:3px 9px;"
                "border-radius:12px;font-weight:bold;font-size:9px;" % (
                    background, foreground
                )
            )

        def install_ot_audit_result_capsule(self, item, status, label):
            """Compact status capsule; left/right rows remain neutral.

            QTreeWidgetItem cannot draw rounded backgrounds itself. A tiny
            QLabel in the Result column does, while mouse events pass through
            to the row selection. If PythonQt disallows item widgets, the
            already-set colored plain text remains an accessible fallback.
            Never draw a capsule on top of that same plain text.
            """
            if not hasattr(self.ot_audit_table, "setItemWidget"):
                return
            colors = {
                "MATCH": (M3_LIGHT.get("onPrimary", "#FFFFFF"), SUCCESS_COLOR),
                "DIFFERENT": (M3_LIGHT["onTertiaryContainer"],
                              M3_LIGHT["tertiaryContainer"]),
            }
            ink, surface = colors.get(status, (
                M3_LIGHT["onTertiaryContainer"],
                M3_LIGHT["tertiaryContainer"]
            ))
            try:
                host = QtGui.QWidget(self.ot_audit_table)
                host.setStyleSheet("background:transparent;border:0;")
                badge_row = QtGui.QHBoxLayout(host)
                badge_row.setContentsMargins(5, 0, 0, 0)
                badge_row.setSpacing(0)
                badge = QtGui.QLabel(label)
                badge.setFixedHeight(22)
                badge.setAlignment(QtCore.Qt.AlignCenter)
                badge.setStyleSheet(
                    "background:%s;color:%s;border:0;border-radius:11px;"
                    "padding:0px 8px;font-size:9px;font-weight:bold;" %
                    (surface, ink)
                )
                badge_row.addWidget(badge)
                badge_row.addStretch(1)
                # Qt needs row height to include the embedded label; otherwise
                # PythonQt can position a 22px capsule below a shallow row.
                try:
                    item.setSizeHint(2, QtCore.QSize(155, 35))
                except Exception:
                    # A FontLab build may expose item widgets but not QSize.
                    pass
                try:
                    host.setAttribute(
                        QtCore.Qt.WA_TransparentForMouseEvents, True
                    )
                except Exception:
                    pass
                self.ot_audit_table.setItemWidget(item, 2, host)
                # setItemWidget does NOT replace QTreeWidgetItem's own text.
                # Leaving it intact caused the visible double/shifted labels.
                item.setText(2, "")
            except Exception:
                # A styling-only failure must not stop a read-only comparison.
                pass

        def install_row_pill(self, table, item, column, label, tone="neutral"):
            """Draw only small non-interactive badges, never Qt checkboxes.

            The QTreeWidgetItem plain text is a fallback if PythonQt rejects
            embedded labels. Its contents are cleared ONLY after a successful
            setItemWidget, preventing the duplicate text seen in earlier tests.
            """
            if not hasattr(table, "setItemWidget"):
                return
            colors = {
                "neutral": (M3_LIGHT["onPrimaryContainer"],
                            M3_LIGHT["surfaceContainer"]),
                "accent": (M3_LIGHT["onPrimaryContainer"],
                           M3_LIGHT["primaryContainer"]),
                "ready": (M3_LIGHT["onPrimaryContainer"],
                          M3_LIGHT["primaryContainer"]),
                "match": (M3_LIGHT.get("onPrimary", "#FFFFFF"), SUCCESS_COLOR),
                "warning": (M3_LIGHT["onTertiaryContainer"],
                            M3_LIGHT["tertiaryContainer"]),
            }
            ink, surface = colors.get(tone, colors["neutral"])
            try:
                host = QtGui.QWidget(table)
                host.setStyleSheet("background:transparent;border:0;")
                line = QtGui.QHBoxLayout(host)
                line.setContentsMargins(3, 0, 2, 0)
                line.setSpacing(0)
                pill = QtGui.QLabel(label)
                pill.setFixedHeight(21)
                pill.setAlignment(QtCore.Qt.AlignCenter)
                pill.setStyleSheet(
                    "background:%s;color:%s;border:0;border-radius:10px;"
                    "padding:0px 7px;font-size:9px;font-weight:bold;" %
                    (surface, ink)
                )
                if tone in ("accent", "ready", "warning", "match"):
                    line.addStretch(1)
                    line.addWidget(pill)
                else:
                    line.addWidget(pill)
                    line.addStretch(1)
                try:
                    item.setSizeHint(column, QtCore.QSize(135, 35))
                except Exception:
                    pass
                try:
                    host.setAttribute(
                        QtCore.Qt.WA_TransparentForMouseEvents, True
                    )
                except Exception:
                    pass
                table.setItemWidget(item, column, host)
                item.setText(column, "")
            except Exception:
                # Decorative badges must not interfere with class scanning.
                pass

        def install_audit_class_cell(self, item, class_name, side):
            """Native class and Left/Right side share one clean list cell."""
            table = self.ot_audit_table
            if not hasattr(table, "setItemWidget"):
                return
            try:
                # Keep selection and lookup stable after hiding cell text.
                item.setData(0, QtCore.Qt.UserRole, class_name)
                item.setToolTip(0, class_name)
                host = QtGui.QWidget(table)
                host.setStyleSheet("background:transparent;border:0;")
                line = QtGui.QHBoxLayout(host)
                line.setContentsMargins(8, 0, 0, 0)
                line.setSpacing(6)
                name = QtGui.QLabel(class_name)
                name.setStyleSheet("background:transparent;border:0;")
                line.addWidget(name)
                side_pill = QtGui.QLabel(side)
                side_pill.setAlignment(QtCore.Qt.AlignCenter)
                side_pill.setFixedHeight(19)
                side_pill.setStyleSheet(
                    "background:%s;color:%s;border:0;border-radius:9px;"
                    "padding:0px 6px;font-size:9px;" % (
                        M3_LIGHT["surfaceContainer"],
                        M3_LIGHT["onPrimaryContainer"]
                    )
                )
                line.addWidget(side_pill)
                line.addStretch(1)
                try:
                    item.setSizeHint(0, QtCore.QSize(170, 35))
                except Exception:
                    pass
                try:
                    host.setAttribute(
                        QtCore.Qt.WA_TransparentForMouseEvents, True
                    )
                except Exception:
                    pass
                table.setItemWidget(item, 0, host)
                item.setText(0, "")
            except Exception:
                # In the fallback, the existing 'A (left)' text remains.
                pass

        def set_verified_mark(self, item):
            """One aligned, monochrome system tick for readback-only rows."""
            family = getattr(self, "system_icon_font_family", "")
            item.setText(0, WINDOWS_CHECK_GLYPH if family else "OK")
            if family:
                item.setFont(0, QtGui.QFont(family, 12))
            try:
                item.setTextAlignment(
                    0, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter
                )
            except Exception:
                pass

        def opentype_sync_page(self):
            """Preview selection with a separately confirmed FL8 COPY writer."""
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(12, 11, 12, 11)
            layout.setSpacing(8)

            head = QtGui.QHBoxLayout()
            head.addWidget(self.heading("OpenType glyphs to add", 12))
            head.addStretch(1)
            self.ot_sync_build_button = QtGui.QPushButton("Find missing glyphs")
            self.ot_sync_build_button.setObjectName("nativeScan")
            self.ot_sync_build_button.setToolTip(
                "Use the last Cross-check snapshot to plan OT additions. No writes."
            )
            head.addWidget(self.ot_sync_build_button)
            self.ot_sync_fea_button = QtGui.QPushButton("Compare an older .fea")
            self.ot_sync_fea_button.setToolTip(
                "Test against an older .fea export while leaving the active font unchanged."
            )
            head.addWidget(self.ot_sync_fea_button)
            self.ot_sync_report_button = QtGui.QPushButton("FEA details")
            self.ot_sync_report_button.setObjectName("nativeReport")
            self.ot_sync_report_button.setToolTip(
                "Open the proposed feature text, safety checks and readback."
            )
            head.addWidget(self.ot_sync_report_button)
            layout.addLayout(head)
            self.ot_sync_summary = self.paragraph(
                "First compare both sides. Then choose which missing glyphs "
                "to add to OpenType. Nothing changes until you confirm."
            )
            self.ot_sync_summary.setVisible(False)
            layout.addWidget(self.ot_sync_summary)
            self.ot_sync_source_label = self.paragraph(
                "No comparison loaded yet. Saved .fea files are for review only."
            )
            self.ot_sync_source_label.setVisible(False)
            layout.addWidget(self.ot_sync_source_label)

            grids = QtGui.QHBoxLayout()
            grids.setSpacing(10)
            left_panel = self.make_card(
                "otSyncClassesPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 14
            )
            left_layout = QtGui.QVBoxLayout(left_panel)
            left_layout.setContentsMargins(10, 10, 10, 10)
            left_layout.setSpacing(7)
            left_header = QtGui.QHBoxLayout()
            self.ot_sync_classes_title = self.heading(
                "OpenType classes to update", 10
            )
            left_header.addWidget(self.ot_sync_classes_title)
            left_header.addStretch(1)
            self.ot_sync_select_all_button = QtGui.QPushButton("Select all")
            self.ot_sync_select_all_button.setEnabled(False)
            left_header.addWidget(self.ot_sync_select_all_button)
            self.ot_sync_clear_button = QtGui.QPushButton("Clear")
            self.ot_sync_clear_button.setEnabled(False)
            left_header.addWidget(self.ot_sync_clear_button)
            left_layout.addLayout(left_header)
            self.ot_sync_class_table = QtGui.QTreeWidget()
            self.ot_sync_class_table.setColumnCount(3)
            self.ot_sync_class_table.setHeaderLabels(
                ["OpenType class", "Glyphs to add", "Result"]
            )
            self.ot_sync_class_table.setRootIsDecorated(False)
            self.ot_sync_class_table.setAlternatingRowColors(True)
            self.configure_tree_columns(
                self.ot_sync_class_table, (165, 0, 170), (0, 2)
            )
            left_layout.addWidget(self.ot_sync_class_table, 1)
            grids.addWidget(left_panel, 6)

            right_panel = self.make_card(
                "otSyncGlyphsPanel", M3_LIGHT["surfaceContainerLowest"],
                M3_LIGHT["outlineVariant"], 14
            )
            right_layout = QtGui.QVBoxLayout(right_panel)
            right_layout.setContentsMargins(10, 10, 10, 10)
            right_layout.setSpacing(7)
            self.ot_sync_glyph_heading = self.heading("Glyphs you can add", 10)
            right_layout.addWidget(self.ot_sync_glyph_heading)
            # Blocked/shared classes need an explanation that survives even
            # if the user does not notice the tiny class-list status pill.
            self.ot_sync_warning_card = QtGui.QFrame()
            self.ot_sync_warning_card.setObjectName("otSyncReviewCard")
            self.ot_sync_warning_card.setStyleSheet(
                "QFrame#otSyncReviewCard{background:%s;border:1px solid %s;"
                "border-radius:9px;}" % (
                    M3_LIGHT["tertiaryContainer"],
                    M3_LIGHT["tertiaryFixedDim"]
                )
            )
            warning_layout = QtGui.QVBoxLayout(self.ot_sync_warning_card)
            warning_layout.setContentsMargins(14, 13, 14, 13)
            warning_layout.setSpacing(5)
            self.ot_sync_warning_title = self.heading(
                "", 10, M3_LIGHT["onTertiaryContainer"]
            )
            warning_layout.addWidget(self.ot_sync_warning_title)
            self.ot_sync_warning_message = self.paragraph("")
            self.ot_sync_warning_message.setStyleSheet(
                "background:transparent;border:0;color:%s;" %
                M3_LIGHT["onTertiaryContainer"]
            )
            warning_layout.addWidget(self.ot_sync_warning_message)
            right_layout.addWidget(self.ot_sync_warning_card)
            self.ot_sync_warning_card.setVisible(False)
            self.ot_sync_glyph_table = QtGui.QTreeWidget()
            self.ot_sync_glyph_table.setColumnCount(3)
            self.ot_sync_glyph_table.setHeaderLabels(
                ["Select", "Glyph", "Status"]
            )
            self.ot_sync_glyph_table.setRootIsDecorated(False)
            self.ot_sync_glyph_table.setAlternatingRowColors(True)
            self.configure_tree_columns(
                self.ot_sync_glyph_table, (46, 200, 122), (1,)
            )
            right_layout.addWidget(self.ot_sync_glyph_table, 1)
            grids.addWidget(right_panel, 6)
            layout.addLayout(grids, 1)

            preview_head = QtGui.QHBoxLayout()
            review_heading = self.heading("Review OpenType changes", 10)
            review_heading.setVisible(False)
            preview_head.addWidget(review_heading)
            preview_head.addStretch(1)
            self.ot_sync_selected_badge = self.paragraph("0 selected")
            self.ot_sync_selected_badge.setVisible(False)
            preview_head.addWidget(self.ot_sync_selected_badge)
            self.ot_preflight_button = QtGui.QPushButton("Check changes")
            self.ot_preflight_button.setToolTip(
                "Run a fresh FL8/FEA/Native safety check and show an exact "
                "diff. READ ONLY: this button never writes or saves."
            )
            self.ot_preflight_button.setEnabled(False)
            self.ot_preflight_button.setVisible(False)
            preview_head.addWidget(self.ot_preflight_button)
            self.ot_writer_button = QtGui.QPushButton("Add selected glyphs...")
            self.ot_writer_button.setToolTip(
                "FL8 saved COPY only. After PASS, choose a separate .fea "
                "backup and confirm. Exact readback; no automatic Compile or Save."
            )
            self.ot_writer_button.setEnabled(False)
            self.ot_writer_button.setVisible(False)
            preview_head.addWidget(self.ot_writer_button)
            layout.addLayout(preview_head)
            self.ot_sync_latest_line = self.paragraph(
                "Latest: Nothing selected. Your font has not changed."
            )
            # The contextual banner and summary already explain the next step.
            # Retain the internal status text, but avoid a duplicate UX line.
            self.ot_sync_latest_line.setVisible(False)
            layout.addWidget(self.ot_sync_latest_line)
            self.ot_sync_output = QtGui.QPlainTextEdit()
            self.ot_sync_output.setReadOnly(True)
            self.ot_sync_output.setMinimumHeight(132)
            self.ot_sync_output.setMaximumHeight(175)
            self.ot_sync_output.setPlainText(
                "READ ONLY / Run Cross-check, then build a preview. "
                "No automatic Apply or Save."
            )
            self.ot_sync_output.setVisible(False)
            self.ot_sync_report_button.clicked.connect(self.toggle_ot_sync_report)
            layout.addWidget(self.ot_sync_output)

            self.ot_sync_build_button.clicked.connect(
                lambda *args: self.safe_ot_sync(self.build_ot_sync_from_audit)
            )
            self.ot_sync_fea_button.clicked.connect(
                lambda *args: self.safe_ot_sync(self.build_ot_sync_from_fea)
            )
            self.ot_preflight_button.clicked.connect(
                lambda *args: self.safe_ot_preflight()
            )
            self.ot_writer_button.clicked.connect(
                lambda *args: self.safe_ot_writer()
            )
            self.ot_sync_select_all_button.clicked.connect(
                lambda *args: self.safe_ot_sync(
                    lambda: self.set_ot_sync_all(True)
                )
            )
            self.ot_sync_clear_button.clicked.connect(
                lambda *args: self.safe_ot_sync(
                    lambda: self.set_ot_sync_all(False)
                )
            )
            class_changed = lambda item, old: self.safe_ot_sync(
                lambda: self.show_ot_sync_class(item)
            )
            glyph_changed = lambda item, col: self.safe_ot_sync(
                lambda: self.on_ot_sync_glyph_changed(item, col)
            )
            self.ot_sync_class_table.currentItemChanged.connect(class_changed)
            self.ot_sync_glyph_table.itemChanged.connect(glyph_changed)
            self.connections.extend([
                (self.ot_sync_class_table.currentItemChanged, class_changed),
                (self.ot_sync_glyph_table.itemChanged, glyph_changed),
            ])
            return page

        def toggle_ot_sync_report(self):
            self.show_readonly_details_dialog(
                "OpenType FEA details",
                "Read-only FEA preview, safety checks and last writer result.",
                read_qt_value(self.ot_sync_output, "toPlainText", "")
            )

        def opentype_classes_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(14, 13, 14, 13)
            layout.setSpacing(9)
            heading_row = QtGui.QHBoxLayout()
            heading_row.addWidget(self.heading("OpenType Classes", 12))
            heading_row.addStretch()
            search = QtGui.QLineEdit()
            search.setPlaceholderText("Search OT classes or glyphs...")
            search.setEnabled(False)
            heading_row.addWidget(search)
            scan = QtGui.QPushButton("Scan OT classes")
            scan.setEnabled(False)
            scan.setToolTip("Enabled after verifying the OpenType reader API.")
            heading_row.addWidget(scan)
            layout.addLayout(heading_row)

            tables = QtGui.QHBoxLayout()
            tables.setSpacing(10)
            left = self.make_card(
                "otClassList", M3_LIGHT["surfaceContainerLow"],
                M3_LIGHT["outlineVariant"], 16
            )
            left_layout = QtGui.QVBoxLayout(left)
            left_layout.setContentsMargins(10, 10, 10, 10)
            left_layout.addWidget(self.heading("CLASS DIRECTORY", 10))
            left_layout.addWidget(self.paragraph(
                "Name, side, membership count, and linked features."
            ))
            left_layout.addWidget(self.empty_ot_table(
                ["Class", "Type / Side", "Members", "Features"],
                [150, 110, 75, 120]
            ), 1)
            tables.addWidget(left, 7)
            right = self.make_card(
                "otClassInspect", M3_LIGHT["surfaceContainerLow"],
                M3_LIGHT["outlineVariant"], 16
            )
            right_layout = QtGui.QVBoxLayout(right)
            right_layout.setContentsMargins(10, 10, 10, 10)
            right_layout.addWidget(self.heading("CLASS MEMBERS", 10))
            right_layout.addWidget(self.paragraph(
                "Choose a class to inspect its glyphs and references."
            ))
            right_layout.addWidget(self.empty_ot_table(
                ["Glyph name", "Unicode / Source"], [210, 130]
            ), 1)
            tables.addWidget(right, 5)
            layout.addLayout(tables, 1)
            layout.addWidget(self.paragraph(
                "READER NOT CONNECTED / No OpenType class data shown yet."
            ))
            return page

        def opentype_features_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(14, 13, 14, 13)
            layout.setSpacing(9)
            layout.addWidget(self.heading("Feature Explorer", 12))
            layout.addWidget(self.paragraph(
                "Planned coverage: kern, liga, locl, smcp, c2sc, aalt, "
                "ss01-ss20, and additional OpenType features."
            ))
            columns = QtGui.QHBoxLayout()
            columns.setSpacing(10)
            feature_list = self.make_card(
                "otFeatureList", M3_LIGHT["surfaceContainerLow"],
                M3_LIGHT["outlineVariant"], 16
            )
            list_layout = QtGui.QVBoxLayout(feature_list)
            list_layout.addWidget(self.heading("FEATURES", 10))
            list_layout.addWidget(self.empty_ot_table(
                ["Tag", "Status", "Lookups"], [110, 120, 100]
            ), 1)
            columns.addWidget(feature_list, 5)
            feature_detail = self.make_card(
                "otFeatureDetail", M3_LIGHT["surfaceContainerLow"],
                M3_LIGHT["outlineVariant"], 16
            )
            detail_layout = QtGui.QVBoxLayout(feature_detail)
            detail_layout.addWidget(self.heading("FEATURE DETAILS", 10))
            details = QtGui.QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText(
                "OpenType feature code and class references will appear here "
                "after the read-only feature scanner is verified."
            )
            detail_layout.addWidget(details, 1)
            columns.addWidget(feature_detail, 7)
            layout.addLayout(columns, 1)
            return page

        def opentype_validation_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(14, 13, 14, 13)
            layout.addWidget(self.heading("OpenType Validation", 12))
            layout.addWidget(self.paragraph(
                "Future checks: missing glyphs, duplicate memberships, "
                "broken class references, unsupported lookups, and feature dependencies."
            ))
            results = QtGui.QPlainTextEdit()
            results.setReadOnly(True)
            results.setPlainText(
                "No checks available in this section yet.\n\n"
                "To compare kerning groups or add glyphs to OpenType kern, "
                "open Kerning Studio. Other OpenType features are planned."
            )
            layout.addWidget(results, 1)
            return page

        def opentype_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(11)
            layout.addWidget(self.heading("OpenType Studio"))
            layout.addWidget(self.paragraph(
                "Explore OpenType classes, features and their checks. "
                "For kerning, use the three steps in Kerning Studio."
            ))
            sections = QtGui.QTabWidget()
            sections.addTab(self.opentype_classes_page(), "Classes")
            sections.addTab(self.opentype_features_page(), "Features")
            sections.addTab(self.opentype_validation_page(), "Validation")
            layout.addWidget(sections, 1)
            return page

        def glyph_matrix_page(self):
            """Show the future module honestly, without querying or editing font data."""
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(9)
            layout.addWidget(self.heading("Glyph Matrix / Planned"))
            layout.addWidget(self.paragraph(
                "A future read-only workspace for Unicode coverage, glyph sets "
                "and consistency checks across Native and OpenType modules."
            ))
            placeholder = QtGui.QPlainTextEdit()
            placeholder.setReadOnly(True)
            placeholder.setPlainText(
                "NOT CONNECTED / no glyph scans are running here yet.\n\n"
                "The active Native Kerning scanner remains available in module 01."
            )
            layout.addWidget(placeholder, 1)
            return page

        def reports_page(self):
            page = QtGui.QWidget()
            layout = QtGui.QVBoxLayout(page)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(self.heading("Reports & Readback"))
            layout.addWidget(self.paragraph(
                "A future shared home for Native and OpenType scan results, "
                "conflicts, and JSON exports. Native V2's existing Export JSON "
                "button remains functional in its own verified GUI."
            ))
            layout.addStretch(1)
            return page

        def refresh_context(self):
            snap = current_font_context(fontlab)
            self.context_label.setText(snap["font"])
            self.context_label.setToolTip(snap["font"])
            self.context_detail.setText(
                "Master: %s   /   Masters: %s" %
                (snap["master"], snap["masters"])
            )
            self.align_native_bands()

        def safe_native(self, callback):
            try:
                callback()
            except Exception as exc:
                print("NGHIATYPE V3 NATIVE PREVIEW ERROR:\n" + traceback.format_exc())
                self.native_diagnostics.setPlainText(traceback.format_exc()[-4000:])
                self.native_live_badge.setText("SCAN NEEDS ATTENTION")
                self.native_report_expanded = True
                self.native_preview_body.setVisible(True)
                self.native_diagnostics.setVisible(True)
                self.native_report_button.setText("Report")
                self.status_label.setText(
                    "Native scan stopped. See the detailed report; font unchanged."
                )
                self.set_native_latest(
                    "Scan stopped. See report for details. Font unchanged."
                )

        def get_native_backend(self):
            """Load the V2 reader/planner and companion Core, but NOT its GUI."""
            if self.native_backend is not None and self.native_core is not None:
                return self.native_backend, self.native_core
            path = native_gui_hint()
            if not path:
                selected = QtGui.QFileDialog.getOpenFileName(
                    self, "Select the verified Native Kerning V2 GUI",
                    "", "Python scripts (*.py)"
                )
                if isinstance(selected, (tuple, list)):
                    selected = selected[0]
                path = str(selected or "").strip()
            if not path:
                return None, None
            backend = load_existing_native_gui(path)
            core_path = backend.native_core_path_hint()
            if not core_path:
                selected = QtGui.QFileDialog.getOpenFileName(
                    self, "Select the Native Core V2 Alpha.1.4.1",
                    "", "Python scripts (*.py)"
                )
                if isinstance(selected, (tuple, list)):
                    selected = selected[0]
                core_path = str(selected or "").strip()
            if not core_path:
                return None, None
            core = backend.load_native_core(core_path)
            self.native_backend = backend
            self.native_core = core
            return backend, core

        def safe_ot_crosscheck(self, callback):
            """Show scanner failures without ever offering a write action."""
            try:
                callback()
            except Exception as exc:
                trace = traceback.format_exc()
                print("NGHIATYPE V3 KERN CROSS-CHECK ERROR:\n" + trace)
                self.ot_crosscheck_report = None
                self.ot_crosscheck_error = True
                self.ot_crosscheck_rows = {}
                self.reset_ot_sync_preview()
                self.ot_audit_table.clear()
                self.ot_audit_glyph_table.clear()
                self.ot_audit_detail.setText("No comparison available")
                self.ot_audit_reason.setText("No valid read-only comparison available.")
                self.set_ot_audit_status_badge("--")
                self.ot_audit_count_label.setText("Not compared")
                self.ot_audit_to_sync.setEnabled(False)
                self.ot_audit_summary.setText(
                    "Could not compare the classes. Open technical details "
                    "for the reason. Cross-check did not change the font."
                )
                self.ot_audit_notes.setPlainText(trace[-5000:])
                self.status_label.setText(
                    "Cross-check failed; font unchanged. " + type(exc).__name__
                )
                self.update_kerning_tab_header(1)
                self.refresh_kerning_guidance()

        def get_ot_crosscheck_cores(self):
            """Reuse V1's FEA parser and V2's reader without calling main()."""
            backend, native_core = self.get_native_backend()
            if backend is None or native_core is None:
                return None

            def choose_exact(filename, title):
                path = companion_script_hint(filename)
                if not path:
                    chosen = QtGui.QFileDialog.getOpenFileName(
                        self, title, "", "Python scripts (*.py)"
                    )
                    if isinstance(chosen, (tuple, list)):
                        chosen = chosen[0]
                    path = str(chosen or "").strip()
                return path

            if self.ot_v1_core is None:
                path = choose_exact(
                    OT_V1_CORE_FILENAME, "Select the verified V1 OpenType kern reader"
                )
                if not path:
                    return None
                self.ot_v1_core = load_exact_readonly_module(
                    path, OT_V1_CORE_FILENAME, "_nghiatype_v1_kern_reader",
                    ("read_kern", "parse_classes", "pair_roles")
                )

            if self.ot_crosscheck_core is None:
                path = choose_exact(
                    CROSSCHECK_FILENAME, "Select the V3 read-only cross-check engine"
                )
                if not path:
                    return None
                self.ot_crosscheck_core = load_exact_readonly_module(
                    path, CROSSCHECK_FILENAME, "_nghiatype_v3_kern_audit",
                    ("compare_kerning",)
                )
            return backend, native_core, self.ot_v1_core, self.ot_crosscheck_core

        def reset_ot_sync_preview(self):
            """Invalidate stale preview data after a new read-only audit."""
            self.ot_sync_applied = False
            self.ot_last_applied_count = 0
            self.ot_sync_verified_by_class = {}
            self.ot_ui_issue = None
            self.ot_last_preflight = None
            self.ot_last_preflight_selection = frozenset()
            self.ot_sync_preview = None
            self.ot_sync_rows = {}
            self.ot_sync_selected = set()
            self.ot_sync_source_kern = None
            self.ot_sync_expected_native = None
            self.ot_sync_expected_pairs = None
            self.ot_sync_original_issues = None
            self.ot_sync_original_master_count = None
            self.ot_sync_expected_glyphs = None
            self.ot_sync_original_prefix = None
            self.ot_sync_original_font_path = None
            self.ot_sync_original_master = None
            self.ot_sync_updating = True
            try:
                self.ot_sync_class_table.clear()
                self.ot_sync_glyph_table.clear()
            finally:
                self.ot_sync_updating = False
            self.ot_sync_glyph_heading.setText("Glyphs you can add")
            self.ot_sync_classes_title.setText("OpenType classes to update")
            self.ot_sync_class_table.setHeaderLabels(
                ["OpenType class", "Glyphs to add", "Result"]
            )
            self.ot_sync_glyph_table.setHeaderLabels(
                ["Select", "Glyph", "Status"]
            )
            self.ot_sync_select_all_button.setEnabled(False)
            self.ot_sync_clear_button.setEnabled(False)
            self.ot_sync_select_all_button.setVisible(True)
            self.ot_sync_clear_button.setVisible(True)
            self.ot_sync_build_button.setEnabled(True)
            self.ot_sync_fea_button.setEnabled(True)
            self.ot_sync_fea_button.setVisible(True)
            self.ot_preflight_button.setEnabled(False)
            self.ot_writer_button.setEnabled(False)
            self.ot_sync_selected_badge.setText("0 selected")
            self.ot_sync_source_label.setText(
                "No comparison loaded yet. An older .fea file is only for review."
            )
            self.ot_sync_source_label.setVisible(False)
            self.ot_sync_summary.setText(
                "First compare both sides, then find the missing OpenType glyphs."
            )
            self.ot_sync_output.setPlainText(
                "READ ONLY / No proposal loaded. Font unchanged."
            )
            self.ot_sync_latest_line.setText(
                "Latest: Waiting for a comparison. Your font has not changed."
            )

        def safe_ot_sync(self, callback):
            try:
                callback()
            except Exception as exc:
                print("NGHIATYPE V3 SELECTIVE OT PREVIEW ERROR:\n" +
                      traceback.format_exc())
                if self.ot_sync_applied:
                    # This callback can be just a read-only click in the
                    # verified results table. A display problem must never
                    # erase the already confirmed writer/readback state.
                    self.ot_sync_output.setPlainText(
                        "Verified OpenType edits are unchanged. "
                        "Could not display the selected result row.\n\n" +
                        traceback.format_exc()[-3000:]
                    )
                    self.status_label.setText(
                        "Verified edits kept; result display needs attention."
                    )
                    return
                self.reset_ot_sync_preview()
                self.ot_sync_summary.setText(
                    "Could not prepare the OpenType list. See details for help. "
                    "Your font has not changed."
                )
                self.ot_ui_issue = (
                    "Could not prepare the list",
                    "Open FEA details for the reason, then try again.",
                    "find_ot",
                )
                self.ot_sync_output.setPlainText(traceback.format_exc()[-3500:])
                self.ot_sync_latest_line.setText(
                    "Latest: Something went wrong while checking the list. "
                    "No changes were made."
                )
                self.status_label.setText(
                    "Selective OT Preview failed; font unchanged."
                )
                self.refresh_kerning_guidance()

        def get_ot_sync_core(self):
            if self.ot_sync_core is not None:
                return self.ot_sync_core
            path = companion_script_hint(OT_SYNC_FILENAME)
            if not path:
                chosen = QtGui.QFileDialog.getOpenFileName(
                    self, "Select the V3 Selective OT Sync Preview engine",
                    "", "Python scripts (*.py)"
                )
                if isinstance(chosen, (tuple, list)):
                    chosen = chosen[0]
                path = str(chosen or "").strip()
            if not path:
                return None
            self.ot_sync_core = load_exact_readonly_module(
                path, OT_SYNC_FILENAME, "_nghiatype_v3_ot_sync_preview",
                ("build_ot_sync_preview", "render_selected_fea_preview",
                 "extract_kern_feature_text")
            )
            return self.ot_sync_core

        def get_ot_preflight_core(self):
            if self.ot_preflight_core is not None:
                return self.ot_preflight_core
            path = companion_script_hint(OT_PREFLIGHT_FILENAME)
            if not path:
                chosen = QtGui.QFileDialog.getOpenFileName(
                    self, "Select the V3 Guarded OT Preflight engine",
                    "", "Python scripts (*.py)"
                )
                if isinstance(chosen, (tuple, list)):
                    chosen = chosen[0]
                path = str(chosen or "").strip()
            if not path:
                return None
            self.ot_preflight_core = load_exact_readonly_module(
                path, OT_PREFLIGHT_FILENAME, "_nghiatype_v3_ot_preflight",
                ("prepare_ot_preflight", "render_preflight_report")
            )
            return self.ot_preflight_core

        def get_ot_writer_core(self):
            if self.ot_writer_core is not None:
                return self.ot_writer_core
            path = companion_script_hint(OT_WRITER_FILENAME)
            if not path:
                chosen = QtGui.QFileDialog.getOpenFileName(
                    self, "Select the V3 FL8 COPY writer engine",
                    "", "Python scripts (*.py)"
                )
                if isinstance(chosen, (tuple, list)):
                    chosen = chosen[0]
                path = str(chosen or "").strip()
            if not path:
                return None
            self.ot_writer_core = load_exact_ot_writer_module(path)
            return self.ot_writer_core

        def build_ot_sync_from_audit(self):
            """Create a selectable report from the last READ-ONLY snapshot."""
            if self.ot_crosscheck_report is None:
                self.ot_sync_summary.setText(
                    "Start with step 02: Compare both sides. Then come back "
                    "here to find the missing glyphs."
                )
                self.ot_sync_latest_line.setText(
                    "Latest: Waiting for step 02. No OpenType edits were made."
                )
                return
            core = self.get_ot_sync_core()
            if core is None:
                self.status_label.setText("OT preview cancelled; font unchanged.")
                return
            preview = core.build_ot_sync_preview(self.ot_crosscheck_report)
            preview["source_mode"] = "LIVE_CROSSCHECK_SNAPSHOT"
            self.populate_ot_sync_preview(preview)
            self.remember_ot_sync_source(
                self.ot_crosscheck_source_kern,
                self.ot_crosscheck_native_snapshot,
                self.ot_crosscheck_original_prefix
            )

        def build_ot_sync_from_fea(self):
            """Compare an exported FEA with current Native READ-ONLY groups.

            This is a test harness only: the external FEA is NOT the active
            feature, and its proposal must NEVER be applied to the live font.
            """
            chosen = QtGui.QFileDialog.getOpenFileName(
                self, "Choose an older exported .fea for READ-ONLY comparison",
                "", "OpenType FEA (*.fea);;Text files (*.txt)"
            )
            if isinstance(chosen, (tuple, list)):
                chosen = chosen[0]
            path = os.path.abspath(str(chosen or "").strip()) if chosen else ""
            if not path:
                return
            if not os.path.isfile(path):
                raise RuntimeError("Cannot read the selected .fea snapshot.")
            if os.path.getsize(path) > 5 * 1024 * 1024:
                raise RuntimeError("FEA snapshot exceeds the 5 MiB read-only limit.")

            components = self.get_ot_crosscheck_cores()
            if components is None:
                self.status_label.setText("FEA comparison cancelled; font unchanged.")
                return
            backend, native_core, ot_core, audit_core = components
            sync_core = self.get_ot_sync_core()
            if sync_core is None:
                self.status_label.setText("FEA comparison cancelled; font unchanged.")
                return

            with open(path, "r", encoding="utf-8-sig") as stream:
                exported = stream.read()
            kern_text = sync_core.extract_kern_feature_text(exported)
            ot_classes, issues = ot_core.parse_classes(kern_text)
            ot_roles = ot_core.pair_roles(kern_text)
            native_snapshot = backend.scan_native(fontlab, native_core)
            report = audit_core.compare_kerning(
                native_snapshot["groups"], ot_classes, ot_roles, issues
            )
            preview = sync_core.build_ot_sync_preview(report)
            preview["source_mode"] = "EXTERNAL_FEA_SNAPSHOT"
            preview["source_label"] = ntpath.basename(path)
            self.populate_ot_sync_preview(preview)
            self.remember_ot_sync_source(kern_text, native_snapshot)
            self.status_label.setText(
                "Compared external FEA / test preview only / active font unchanged."
            )

        def remember_ot_sync_source(self, kern_text, native_snapshot,
                                    source_prefix=None):
            """Freeze the exact source context; all values re-read on preflight."""
            self.ot_sync_source_kern = kern_text
            if native_snapshot is None:
                return
            self.ot_sync_expected_native = native_snapshot["groups"]
            self.ot_sync_expected_pairs = native_snapshot["pairs"]
            self.ot_sync_original_issues = native_snapshot["issues"]
            self.ot_sync_original_master_count = native_snapshot["master_count"]
            self.ot_sync_expected_glyphs = frozenset(native_snapshot["available"])
            self.ot_sync_original_font_path = native_snapshot["font_path"]
            self.ot_sync_original_master = native_snapshot["master"]
            font = fontlab.CurrentFont()
            layout = read_qt_value(font, "features") if font else None
            self.ot_sync_original_prefix = (
                source_prefix if source_prefix is not None else
                read_qt_value(layout, "get_prefix", "")
            )

        def populate_ot_sync_preview(self, preview):
            """Display checked glyph suggestions from either read-only source."""
            self.reset_ot_sync_preview()
            self.ot_sync_preview = preview
            external = preview.get("source_mode") == "EXTERNAL_FEA_SNAPSHOT"
            if external:
                self.ot_sync_source_label.setText(
                    "Older .fea for comparison: %s. This is NOT your current "
                    "font's OpenType feature; you cannot apply from this file." %
                    preview.get("source_label", "exported .fea")
                )
            else:
                self.ot_sync_source_label.setText(
                    "Based on your latest comparison of the open font. "
                    "Compare again if you edit the font."
                )
            self.ot_sync_source_label.setVisible(external)
            self.ot_sync_rows = {
                group["ot_class"]: group for group in preview["groups"]
            }
            # Proposed FEA remains read-only, so every safe candidate may be
            # checked initially. Apply is deliberately NOT implemented.
            self.ot_sync_selected = {
                (group["ot_class"], name)
                for group in preview["groups"] for name in group["proposed"]
            }
            self.ot_sync_updating = True
            try:
                for group in preview["groups"]:
                    item = QtGui.QTreeWidgetItem(self.ot_sync_class_table)
                    item.setText(0, "@" + group["ot_class"])
                    item.setText(1, "+%d" % len(group["proposed"]))
                    item.setText(2, {
                        "READY": "Ready to add", "BLOCKED": "Needs review"
                    }.get(group["status"], "See details"))
                    self.install_row_pill(
                        self.ot_sync_class_table, item, 2,
                        "%d glyphs ready" % len(group["proposed"])
                        if group["status"] == "READY" else "Needs review",
                        "ready" if group["status"] == "READY" else "warning"
                    )
                    item.setToolTip(
                        0, "Linked Native classes: " +
                        ", ".join(group["native_sources"])
                    )
            finally:
                self.ot_sync_updating = False
            can_select = bool(preview["candidate_unique_memberships"])
            self.ot_sync_select_all_button.setEnabled(can_select)
            self.ot_sync_clear_button.setEnabled(can_select)
            self.ot_preflight_button.setEnabled(can_select)
            first = self.ot_sync_class_table.topLevelItem(0)
            if first is not None:
                self.ot_sync_class_table.setCurrentItem(first)
                self.show_ot_sync_class(first)
            self.refresh_ot_sync_output()
            self.update_kerning_tab_header(2)
            self.status_label.setText(
                ("Older .fea compared" if external
                 else "Missing OpenType glyphs listed") +
                (". Native edits are not saved yet."
                 if self.native_applied else ". No changes were made.")
            )

        def show_ot_applied_summary(self):
            """Display the verified OT additions, with no stale Add checkboxes.

            The guarded writer has already performed exact readback. This
            method only presents the confirmed selection and closes editing
            until a fresh Scan / Cross-check establishes new source data.
            """
            groups = {}
            for key, name in self.ot_sync_selected:
                groups.setdefault(key, []).append(name)
            self.ot_sync_verified_by_class = {
                key: tuple(sorted(names, key=lambda name: (
                    name.casefold(), name
                ))) for key, names in groups.items()
            }
            self.ot_sync_updating = True
            try:
                self.ot_sync_class_table.clear()
                self.ot_sync_glyph_table.clear()
                self.ot_sync_class_table.setHeaderLabels(
                    ["OpenType class", "Glyphs added", "Result"]
                )
                self.ot_sync_glyph_table.setHeaderLabels(
                    ["", "Added glyph", "Result"]
                )
                for key in sorted(groups, key=lambda value: (
                        value.casefold(), value)):
                    item = QtGui.QTreeWidgetItem(self.ot_sync_class_table)
                    item.setText(0, "@" + key)
                    item.setText(1, "+%d" % len(groups[key]))
                    item.setText(2, "Verified")
                    item.setForeground(2, QtGui.QBrush(
                        QtGui.QColor(SUCCESS_COLOR)
                    ))
                    self.install_row_pill(
                        self.ot_sync_class_table, item, 2, "Verified", "match"
                    )
                first = self.ot_sync_class_table.topLevelItem(0)
                if first is not None:
                    # Signals may fire here. Keep the updater guard active so
                    # a nested class-change signal cannot rebuild old rows.
                    self.ot_sync_class_table.setCurrentItem(first)
            finally:
                self.ot_sync_updating = False
            self.ot_sync_classes_title.setText("Updated OpenType classes")
            self.ot_sync_glyph_heading.setText("Added glyphs - verified")
            self.ot_sync_select_all_button.setEnabled(False)
            self.ot_sync_clear_button.setEnabled(False)
            self.ot_sync_select_all_button.setVisible(False)
            self.ot_sync_clear_button.setVisible(False)
            self.ot_preflight_button.setEnabled(False)
            self.ot_writer_button.setEnabled(False)
            self.ot_sync_build_button.setEnabled(False)
            self.ot_sync_fea_button.setEnabled(False)
            self.ot_sync_fea_button.setVisible(False)
            self.ot_sync_selected_badge.setText(
                "%d added and verified" % self.ot_last_applied_count
            )
            if first is not None:
                self.show_ot_sync_class(first)

        def show_ot_sync_class(self, item):
            if self.ot_sync_updating:
                return
            key = str(item.text(0)).lstrip("@") if item is not None else ""
            warning_card = getattr(self, "ot_sync_warning_card", None)
            if warning_card is not None:
                warning_card.setVisible(False)
            if self.ot_sync_applied:
                # Verified readback stays browsable, but cannot be edited.
                # Do not resurrect old "Ready" checkboxes after Apply.
                self.ot_sync_updating = True
                try:
                    self.ot_sync_glyph_table.clear()
                    names = self.ot_sync_verified_by_class.get(key, ())
                    self.ot_sync_glyph_heading.setText(
                        "@%s / %d added and verified" % (key, len(names))
                        if key else "OpenType changes verified"
                    )
                    for name in names:
                        glyph = QtGui.QTreeWidgetItem(self.ot_sync_glyph_table)
                        self.set_verified_mark(glyph)
                        glyph.setText(1, name)
                        glyph.setText(2, "Added")
                finally:
                    self.ot_sync_updating = False
                return
            group = self.ot_sync_rows.get(key)
            self.ot_sync_updating = True
            try:
                self.ot_sync_glyph_table.clear()
                self.ot_sync_glyph_heading.setText(
                    "@%s / Missing glyphs" % key
                    if group else "Glyphs you can add"
                )
                if group is not None:
                    if group.get("status") == "BLOCKED" and warning_card is not None:
                        linked = list(group.get("native_sources") or ())
                        shared = len(linked) > 1
                        self.ot_sync_warning_title.setText(
                            "Why @%s is locked" % key if shared else
                            "Why @%s needs review" % key
                        )
                        if shared:
                            explanation = (
                                "This OpenType class is linked to %s. "
                                "Updating it could affect more than one "
                                "Native kerning group. Review these links "
                                "in OpenType Studio before making changes."
                            ) % ", ".join(linked[:4])
                        else:
                            explanation = (
                                "NghiaType cannot confirm a safe automatic "
                                "update for this class. Review it manually "
                                "in OpenType Studio."
                            )
                        self.ot_sync_warning_message.setText(explanation)
                        self.ot_sync_warning_card.setVisible(True)
                    for name in group["proposed"]:
                        glyph = QtGui.QTreeWidgetItem(self.ot_sync_glyph_table)
                        glyph.setFlags(glyph.flags() | QtCore.Qt.ItemIsUserCheckable)
                        glyph.setCheckState(
                            0, QtCore.Qt.Checked
                            if (key, name) in self.ot_sync_selected
                            else QtCore.Qt.Unchecked
                        )
                        glyph.setText(1, name)
                        glyph.setText(2, "Will add to @%s" % key)
                    for name in group["blocked"]:
                        glyph = QtGui.QTreeWidgetItem(self.ot_sync_glyph_table)
                        glyph.setText(0, "--")
                        glyph.setText(1, name)
                        glyph.setText(2, "Needs review")
                        glyph.setToolTip(
                            1, "Needs review: " + ", ".join(group["warnings"])
                        )
            finally:
                self.ot_sync_updating = False

        def on_ot_sync_glyph_changed(self, item, column):
            if self.ot_sync_updating or self.ot_sync_applied or column != 0:
                return
            active = self.ot_sync_class_table.currentItem()
            if active is None:
                return
            key = str(active.text(0)).lstrip("@")
            name = str(item.text(1))
            group = self.ot_sync_rows.get(key)
            if group is None or name not in group["proposed"]:
                return
            choice = (key, name)
            if item.checkState(0) == QtCore.Qt.Checked:
                self.ot_sync_selected.add(choice)
            else:
                self.ot_sync_selected.discard(choice)
            self.refresh_ot_sync_output()

        def set_ot_sync_all(self, checked):
            if self.ot_sync_preview is None or self.ot_sync_applied:
                return
            self.ot_sync_selected = (
                {(group["ot_class"], name)
                 for group in self.ot_sync_preview["groups"]
                 for name in group["proposed"]}
                if checked else set()
            )
            self.show_ot_sync_class(self.ot_sync_class_table.currentItem())
            self.refresh_ot_sync_output()

        def refresh_ot_sync_output(self):
            preview = self.ot_sync_preview
            if preview is None or self.ot_sync_core is None:
                return
            # Any checkbox change invalidates consent for the previous plan.
            self.ot_ui_issue = None
            self.ot_last_preflight = None
            self.ot_last_preflight_selection = frozenset()
            self.ot_writer_button.setEnabled(False)
            self.ot_preflight_button.setEnabled(bool(self.ot_sync_selected))
            self.ot_sync_selected_badge.setText(
                "%d glyphs selected" % len(self.ot_sync_selected)
            )
            ready_count = preview["candidate_unique_memberships"]
            review_count = preview["blocked_memberships"]
            self.ot_sync_summary.setText(
                "%d glyphs ready in %d OpenType classes. %s" % (
                    ready_count, preview["candidate_ot_classes"],
                    ("%d glyphs need a closer look." % review_count)
                    if review_count else "Choose which glyphs to add."
                )
            )
            self.ot_writer_button.setText("Add selected glyphs...")
            self.ot_sync_latest_line.setText(
                "%d selected. Nothing changed yet." % len(self.ot_sync_selected)
            )
            rendered = self.ot_sync_core.render_selected_fea_preview(
                preview, self.ot_sync_selected
            )
            if preview.get("source_mode") == "EXTERNAL_FEA_SNAPSHOT":
                rendered = (
                    "# EXTERNAL FEA SNAPSHOT / TEST DISPLAY ONLY\n"
                    "# THIS IS NOT YOUR CURRENT FONT'S OPENTYPE FEATURE.\n"
                    "# NO APPLY IS AVAILABLE FOR HISTORICAL SNAPSHOTS.\n\n"
                    + rendered
                )
            for group in preview["groups"]:
                if group["warnings"]:
                    rendered += "\n# REVIEW @%s: %s / blocked glyphs: %s" % (
                        group["ot_class"], ", ".join(group["warnings"]),
                        ", ".join(group["blocked"])
                    )
            self.ot_sync_output.setPlainText(rendered)
            self.refresh_kerning_guidance()

        def safe_ot_preflight(self):
            """Keep the selected plan visible even if preflight itself fails."""
            try:
                self.run_ot_preflight()
            except Exception as exc:
                self.ot_last_preflight = None
                self.ot_writer_button.setEnabled(False)
                trace = traceback.format_exc()
                print("NGHIATYPE V3 OT PREFLIGHT ERROR:\n" + trace)
                self.ot_sync_output.setPlainText(
                    "PREFLIGHT FAILED / FONT UNCHANGED / NO APPLY\n\n" + trace[-3500:]
                )
                self.ot_sync_summary.setText(
                    "Could not check these changes. Nothing was added. "
                    "Open FEA details for the reason."
                )
                self.ot_ui_issue = (
                    "Could not check these changes",
                    "Nothing was added. Open FEA details, then check again.",
                    "check_ot",
                )
                self.ot_sync_latest_line.setText(
                    "Latest: Check failed. No OpenType edits were made."
                )
                self.status_label.setText(
                    "OT preflight failed / " + type(exc).__name__ + ": " + str(exc)
                )
                self.refresh_kerning_guidance()

        def run_ot_preflight(self):
            """Re-read Native and live kern; compute a dry-run diff only."""
            if self.native_write_failed:
                raise RuntimeError(
                    "The previous Native write could not be verified. "
                    "DO NOT SAVE this test COPY or proceed to OpenType."
                )
            # A verified Native in-memory write may feed a fresh live
            # Cross-check and OT preflight in this FontLab session.
            # Preflight still re-reads Native groups/pairs and live FEA.
            if self.ot_sync_preview is None or not self.ot_sync_selected:
                raise RuntimeError("Select proposed glyphs before preflight.")
            engine = self.get_ot_preflight_core()
            if engine is None:
                self.status_label.setText("OT preflight cancelled. No changes.")
                return
            components = self.get_ot_crosscheck_cores()
            if components is None:
                self.status_label.setText("OT preflight cancelled. No changes.")
                return
            backend, native_core, v1_core, unused_audit_core = components
            font = fontlab.CurrentFont()
            if font is None:
                raise RuntimeError("No active font for OT safety preflight.")
            layout = read_qt_value(font, "features")
            if layout is None or "kern" not in list(layout.keys()):
                raise RuntimeError("Active font has no text kern feature.")
            live_kern = v1_core.read_kern(layout)
            if not isinstance(live_kern, str):
                raise RuntimeError("Cannot read active kern feature as text.")
            fresh = backend.scan_native(fontlab, native_core)
            report = engine.prepare_ot_preflight(
                self.ot_sync_preview, self.ot_sync_selected,
                self.ot_sync_source_kern, live_kern, v1_core,
                self.ot_sync_expected_native, fresh["groups"],
                self.ot_sync_expected_glyphs, set(font.keys()),
                self.ot_sync_original_prefix,
                read_qt_value(layout, "get_prefix", ""),
                self.ot_sync_original_font_path, fresh["font_path"],
                self.ot_sync_original_master, fresh["master"],
                detect_fontlab_major(fontlab, QtCore),
                original_native_pairs=self.ot_sync_expected_pairs,
                live_native_pairs=fresh["pairs"],
                original_native_issues=self.ot_sync_original_issues,
                live_native_issues=fresh["issues"],
                original_master_count=self.ot_sync_original_master_count,
                live_master_count=fresh["master_count"],
                saved_copy_exists=os.path.isfile(fresh["font_path"])
            )
            self.ot_last_preflight = report
            self.ot_last_preflight_selection = frozenset(self.ot_sync_selected)
            self.ot_writer_button.setEnabled(
                bool(report["ready_for_writer_integration_test"])
            )
            self.ot_sync_output.setPlainText(engine.render_preflight_report(report))
            allowed = bool(report["ready_for_writer_integration_test"])
            if allowed:
                self.ot_ui_issue = None
                message = (
                    "%d glyph%s ready. Safety checks passed. "
                    "Confirm the OpenType change and its FEA backup. "
                    "Nothing has been saved." % (
                        report["selected_memberships"],
                        "" if report["selected_memberships"] == 1 else "s"
                    )
                )
                self.ot_writer_button.setText(
                    "Add %d glyph%s..." % (
                        report["selected_memberships"],
                        "" if report["selected_memberships"] == 1 else "s"
                    )
                )
            else:
                self.ot_ui_issue = (
                    "These changes need review",
                    "The safety check found %d issue(s). See FEA details "
                    "and adjust your selection." % len(report["blockers"]),
                    None,
                )
                message = (
                    "Needs attention: %d issue(s) found. The Add button "
                    "will stay disabled. Open FEA details to see why. "
                    "No OpenType edits were made." % len(report["blockers"])
                )
            self.ot_sync_summary.setText(message)
            self.ot_sync_latest_line.setText("Latest: " + message)
            self.status_label.setText(
                "" if allowed else "Some issues need your review."
            )
            self.refresh_kerning_guidance()
            return report

        def safe_ot_writer(self):
            """Treat uncertain runtime failures as DO NOT SAVE, never as success."""
            try:
                self.run_ot_writer()
            except Exception as exc:
                # Fail closed even when it is unclear whether the writer ran.
                self.ot_write_failed = True
                trace = traceback.format_exc()
                print("NGHIATYPE V3 GUARDED OT WRITER ERROR:\n" + trace)
                self.ot_writer_button.setEnabled(False)
                self.ot_last_preflight = None
                self.ot_sync_output.setPlainText(
                    "WRITER STOPPED / DO NOT SAVE UNTIL REVIEWED\n\n" + trace[-3500:]
                )
                self.ot_sync_summary.setText(
                    "Could not confirm that the changes were added correctly. "
                    "DO NOT SAVE this font. Check the details or close the "
                    "test COPY without saving."
                )
                self.ot_sync_latest_line.setText(
                    "Latest: Add stopped. DO NOT SAVE the test font."
                )
                self.status_label.setText(
                    "Guarded OT writer stopped: " + type(exc).__name__
                )
                self.refresh_kerning_guidance()

        def run_ot_writer(self):
            """Explicitly confirmed FL8 COPY-only in-memory kern write."""
            approved = self.ot_last_preflight
            if (approved is None or
                    not approved["ready_for_writer_integration_test"] or
                    frozenset(self.ot_sync_selected) !=
                    self.ot_last_preflight_selection):
                raise RuntimeError("Run a PASS Safety Preflight for this selection first.")
            approved_choices = frozenset(self.ot_sync_selected)
            writer = self.get_ot_writer_core()
            if writer is None:
                self.status_label.setText("OT writer cancelled. No font changes.")
                return

            def matching_pass():
                current = self.run_ot_preflight()
                if (current is None or
                        not current["ready_for_writer_integration_test"] or
                        any(current[field] != approved[field] for field in (
                            "original_sha256", "proposed_sha256",
                            "original_prefix_sha256", "selected_memberships",
                            "changed_classes", "source_mode"
                        )) or frozenset(self.ot_sync_selected) !=
                        approved_choices):
                    raise RuntimeError(
                        "Preflight changed since review; re-scan and review. NO WRITE."
                    )
                return current

            matching_pass()
            copy_path = self.ot_sync_original_font_path
            count = approved["selected_memberships"]
            accepted = self.confirm_glyph_additions(
                "Add %d glyph%s to OpenType?" % (
                    count, "" if count == 1 else "s"
                ),
                [
                    "Font: %s  |  Master: %s" % (
                        ntpath.basename(copy_path), self.ot_sync_original_master
                    ),
                    "NghiaType will ask where to save a NEW .fea backup.",
                    "The backup stores the original OpenType kern feature, "
                    "not a copy of the font file.",
                    "After the backup, %d glyph%s will be added to %d "
                    "OpenType class%s. The font will not be saved or "
                    "compiled automatically." % (
                        count, "" if count == 1 else "s",
                        approved["changed_classes"],
                        "" if approved["changed_classes"] == 1 else "es"
                    ),
                ],
                count,
                "This is a test COPY; I backed up the original and will save manually."
            )
            if not accepted:
                self.status_label.setText("Add cancelled. Nothing changed.")
                return

            # The destination dialog must come AFTER the explanation above.
            # Otherwise Windows shows 'Save As' before users know this is a
            # separate .fea safety backup, NOT a Save Font operation.
            matching_pass()  # Re-check the active FontLab font after consent.
            suggested = os.path.join(
                os.path.dirname(copy_path),
                "NghiaType_OT_kern_original_%s.fea" % time.strftime("%Y%m%d_%H%M%S")
            )
            selected_path = QtGui.QFileDialog.getSaveFileName(
                self, "Save an OpenType kern BACKUP (.fea), not the font",
                suggested, "OpenType kern backup (*.fea)"
            )
            if isinstance(selected_path, (tuple, list)):
                selected_path = selected_path[0]
            backup_path = str(selected_path or "").strip()
            if not backup_path:
                self.status_label.setText("Backup cancelled. No glyphs added.")
                return
            if not backup_path.lower().endswith(".fea"):
                backup_path += ".fea"
            if os.path.lexists(backup_path):
                raise RuntimeError("Backup file already exists. Choose a NEW filename.")

            verified = matching_pass()  # Fresh safety gate AFTER both dialogs.
            components = self.get_ot_crosscheck_cores()
            if components is None:
                raise RuntimeError("Native and OT readers unavailable; NO WRITE.")
            backend, native_core, v1_core, unused = components
            font = fontlab.CurrentFont()
            if font is None:
                raise RuntimeError("No active FontLab font; NO WRITE.")
            layout = read_qt_value(font, "features")
            if layout is None:
                raise RuntimeError("Live FEA layout missing; NO WRITE.")
            current_native = backend.scan_native(fontlab, native_core)

            def other_fea_snapshot():
                reader = getattr(layout, "get_feature", None)
                return {
                    str(tag): reader(tag) if callable(reader) else layout[tag]
                    for tag in list(layout.keys()) if str(tag) != "kern"
                }

            other_fea_before = other_fea_snapshot()

            def verify_after_write():
                fresh = backend.scan_native(fontlab, native_core)
                problems = []
                if fresh["font_path"] != self.ot_sync_original_font_path:
                    problems.append("ACTIVE_FONT_CHANGED")
                if fresh["master"] != self.ot_sync_original_master:
                    problems.append("MASTER_CHANGED")
                if fresh["master_count"] != 1:
                    problems.append("MASTER_COUNT_CHANGED")
                if fresh["groups"] != self.ot_sync_expected_native:
                    problems.append("NATIVE_GROUPS_CHANGED")
                if fresh["pairs"] != self.ot_sync_expected_pairs:
                    problems.append("NATIVE_PAIRS_CHANGED")
                if set(fresh["available"]) != self.ot_sync_expected_glyphs:
                    problems.append("GLYPH_SET_CHANGED")
                if fresh["issues"] != self.ot_sync_original_issues:
                    problems.append("NATIVE_SCAN_ISSUES_CHANGED")
                if other_fea_snapshot() != other_fea_before:
                    problems.append("OTHER_OPENTYPE_FEATURES_CHANGED")
                return problems

            result = writer.guarded_write_to_copy(
                layout=layout, v1=v1_core, preflight=verified,
                backup_path=backup_path,
                fontlab_major=detect_fontlab_major(fontlab, QtCore),
                active_font_path=str(getattr(font, "path", "") or ""),
                expected_font_path=copy_path,
                active_master=current_native["master"],
                expected_master=self.ot_sync_original_master,
                master_count=current_native["master_count"],
                live_glyph_names=set(font.keys()),
                get_prefix=lambda: layout.get_prefix(),
                verify_after=verify_after_write,
                confirmed_by_user=True
            )
            self.ot_sync_output.setPlainText(writer.render_writer_result(result))
            if result["status"] == "READBACK_PASS_NOT_SAVED_OR_COMPILED":
                self.ot_sync_applied = True
                self.ot_last_applied_count = result["memberships"]
                self.show_ot_applied_summary()
                # A verified round is locked. Do not show an editable Native
                # proposal from before OT Apply as though it were a new plan.
                # The next Native Scan explicitly unlocks these controls.
                for widget in (
                    self.native_class_table, self.native_glyph_table,
                    self.native_filter, self.native_all_button,
                    self.native_clear_button, self.native_check_button,
                    self.native_apply_button,
                ):
                    widget.setEnabled(False)
                # An older read-only comparison is also stale after writing.
                self.ot_crosscheck_rows = {}
                self.ot_audit_table.clear()
                self.ot_audit_glyph_table.clear()
                self.ot_audit_count_label.setText("Compare again to refresh")
                self.ot_audit_summary.setText(
                    "OpenType changes verified. Run a new Cross-check "
                    "to see the current class differences."
                )
                self.ot_audit_to_sync.setEnabled(False)
                message = (
                    "Added %d glyphs to %d OpenType classes. Verified. "
                    "A kern backup was saved. The font itself is not saved yet. "
                    "Return to Native Classes and scan again to add more." % (
                        result["memberships"], len(result["classes"])
                ))
            else:
                self.ot_write_failed = True
                message = (
                    "The result could not be confirmed. DO NOT SAVE your "
                    "test COPY. Open FEA details to find out what happened."
                )
            self.ot_sync_summary.setText(message)
            self.ot_sync_latest_line.setText("Latest: " + message)
            self.ot_writer_button.setEnabled(False)
            self.ot_preflight_button.setEnabled(False)
            self.ot_last_preflight = None
            self.ot_crosscheck_report = None  # No stale plan may be reused.
            self.status_label.setText("" if self.ot_sync_applied else message)
            self.update_kerning_tab_header(2)
            self.refresh_kerning_guidance()

        def run_ot_crosscheck(self):
            """Read live Native and OT 'kern' text, then compare in memory."""
            self.ot_crosscheck_report = None
            self.ot_crosscheck_error = False
            self.ot_crosscheck_rows = {}
            self.ot_crosscheck_source_kern = None
            self.ot_crosscheck_native_snapshot = None
            self.ot_crosscheck_original_prefix = None
            self.reset_ot_sync_preview()
            font = fontlab.CurrentFont()
            if font is None:
                raise RuntimeError("Open a font before running Cross-check.")
            components = self.get_ot_crosscheck_cores()
            if components is None:
                self.status_label.setText(
                    "Cross-check cancelled; font unchanged."
                )
                return
            backend, native_core, ot_core, audit_core = components

            layout = read_qt_value(font, "features")
            if layout is None or "kern" not in list(layout.keys()):
                raise RuntimeError(
                    "No text OpenType 'kern' feature found in the active font."
                )
            original = ot_core.read_kern(layout)
            if not isinstance(original, str):
                raise RuntimeError("The OpenType kern reader did not return text.")
            ot_classes, parse_issues = ot_core.parse_classes(original)
            ot_roles = ot_core.pair_roles(original)
            native_snapshot = backend.scan_native(fontlab, native_core)

            result = audit_core.compare_kerning(
                native_snapshot["groups"], ot_classes, ot_roles, parse_issues
            )
            self.ot_crosscheck_source_kern = original
            self.ot_crosscheck_native_snapshot = native_snapshot
            self.ot_crosscheck_original_prefix = read_qt_value(
                layout, "get_prefix", ""
            )
            self.ot_crosscheck_report = result
            self.ot_crosscheck_rows = {
                row["native_class"]: row for row in result["rows"]
            }
            statuses = result["statuses"]
            needs_review = len(result["rows"]) - statuses.get("MATCH", 0)
            self.native_metrics["glyphs"].setText(
                str(len(native_snapshot["available"]))
            )
            self.native_metrics["classes"].setText(
                str(result["native_classes"])
            )
            self.native_metrics["ot_classes"].setText(
                str(result["ot_classes"])
            )
            self.native_metrics["differences"].setText(str(needs_review))
            self.ot_audit_summary.setText(crosscheck_summary_html(result))
            self.ot_audit_count_label.setText(
                "%d classes compared" % result["native_classes"]
            )
            self.ot_audit_to_sync.setEnabled(True)
            self.ot_audit_footer_note.setText(
                "Native edits not saved yet" if self.native_applied
                else "Comparison only"
            )

            self.ot_audit_table.clear()
            self.ot_audit_glyph_table.clear()
            priority = {
                "DIFFERENT": 0, "AMBIGUOUS": 1, "UNMAPPED": 2,
                "UNKNOWN_NATIVE_MODE": 3, "EMPTY_NATIVE_CLASS": 4,
                "MATCH": 5,
            }
            displayed = sorted(
                result["rows"],
                key=lambda row: (
                    priority.get(row["status"], 9),
                    row["native_class"].casefold(), row["native_class"]
                )
            )
            for row in displayed:
                item = QtGui.QTreeWidgetItem(self.ot_audit_table)
                side = (
                    "left" if row["mode"] == "KernLeft" else
                    "right" if row["mode"] == "KernRight" else "unknown"
                )
                item.setText(0, "%s (%s)" % (row["native_class"], side))
                item.setText(
                    1, "@" + row["ot_class"] if row["ot_class"] else "--"
                )
                self.install_audit_class_cell(
                    item, row["native_class"], side
                )
                if row["status"] == "MATCH":
                    result_text = "In sync"
                elif row["status"] == "DIFFERENT":
                    missing = len(row["native_only"])
                    result_text = (
                        "Differs - %d missing" % missing if missing
                        else "Differs"
                    )
                else:
                    result_text = "Needs review"
                item.setText(2, result_text)
                status_colors = {
                    "MATCH": SUCCESS_COLOR,
                    "DIFFERENT": M3_LIGHT["onTertiaryContainer"],
                }
                foreground = status_colors.get(
                    row["status"], M3_LIGHT["onSurfaceVariant"]
                )
                item.setForeground(2, QtGui.QBrush(QtGui.QColor(foreground)))
                item.setFont(2, QtGui.QFont(
                    self.ui_font_family, 9, QtGui.QFont.Bold
                ))
                self.install_ot_audit_result_capsule(
                    item, row["status"], result_text
                )
                # Left/right are readable in the label. Their old lavender/
                # coral cell fills obscured the important In sync / Differs.
                # Neutral zebra stripes and one selected row carry hierarchy.
                ot_count = (str(row["ot_count"])
                            if row["ot_count"] is not None else "--")
                item.setText(3, "%d / %s" % (row["native_count"], ot_count))

            lines = [
                "READ ONLY / font unchanged / no Apply or Save.",
                "Scope: V1 parses simple @class = [...] declarations and "
                "two-position pos statements INSIDE the text 'kern' feature.",
                "OT class may serve BOTH sides; compare separate Native Left "
                "and Right groups against the same OT class, per side.",
                "Links require the first Native glyph, the corresponding "
                "OT pair role, and NO competing Native group on that side.",
                "Class names alone and compiled GPOS lookups are NOT checked.",
                "Different/unmapped does not authorize modifying either side.",
                "Confirmed dual-side OT classes: %d / Native side links: %d" % (
                    result["dual_side_ot_classes"],
                    result["dual_side_native_links"]
                ),
                "Native master: %s / path: %s" % (
                    native_snapshot.get("master", "--"),
                    native_snapshot.get("font_path", "")
                ),
            ]
            if native_snapshot.get("issues"):
                issues = native_snapshot["issues"]
                lines.append("Native scan warnings (%d):" % len(issues))
                lines.extend(str(issue) for issue in issues[:12])
            if result["parse_issues"]:
                lines.append("OpenType V1 parser warnings (%d):" %
                             len(result["parse_issues"]))
                lines.extend(str(issue) for issue in result["parse_issues"][:12])
            if result["unmatched_ot_classes"]:
                lines.append("Unlinked OT classes (%d): %s" % (
                    len(result["unmatched_ot_classes"]),
                    ", ".join("@" + name for name in
                              result["unmatched_ot_classes"][:16])
                ))
            if result["uncovered_ot_sides"]:
                lines.append("Uncovered OT sides (%d): %s" % (
                    len(result["uncovered_ot_sides"]),
                    ", ".join(
                        "@%s:%s" % (entry["ot_class"],
                                    "+".join(entry["missing_roles"]))
                        for entry in result["uncovered_ot_sides"][:16]
                    )
                ))
            self.ot_audit_notes.setPlainText("\n".join(lines))
            first = self.ot_audit_table.topLevelItem(0)
            if first is not None:
                self.ot_audit_table.setCurrentItem(first)
                self.show_ot_audit_class(first)
            else:
                self.ot_audit_detail.setText("NO NATIVE CLASSES")
                self.ot_audit_reason.setText("There are no Native groups to audit.")
            self.status_label.setText("")
            self.update_kerning_tab_header(1)
            self.refresh_kerning_guidance()
            self.refresh_context()

        def show_ot_audit_class(self, item):
            """Inspect evidence or differences; never link/write from UI hints."""
            self.ot_audit_glyph_table.clear()
            self.ot_audit_notice.setVisible(False)
            self.ot_audit_glyph_table.setVisible(True)
            # A successful badge replaces display text in column zero; the
            # stable key is stored in Qt.UserRole for the selection handler.
            visual_key = str(item.text(0)) if item is not None else ""
            key = visual_key.rsplit(" (", 1)[0]
            if item is not None:
                try:
                    stored = item.data(0, QtCore.Qt.UserRole)
                    if stored and str(stored) in self.ot_crosscheck_rows:
                        key = str(stored)
                except Exception:
                    pass
                if key not in self.ot_crosscheck_rows:
                    try:
                        hint_key = str(item.toolTip(0))
                        if hint_key in self.ot_crosscheck_rows:
                            key = hint_key
                    except Exception:
                        pass
            row = self.ot_crosscheck_rows.get(key)
            if row is None:
                self.ot_audit_detail.setText("Select a class")
                self.ot_audit_reason.setText("Select a Native class to inspect.")
                self.ot_audit_reason.setVisible(True)
                self.ot_audit_glyph_table.setFixedHeight(118)
                self.ot_audit_glyph_table.setVisible(False)
                self.set_ot_audit_status_badge("--")
                return
            reason_text = getattr(
                self.ot_crosscheck_core, "REASON_TEXT", {}
            ).get(row["reason"], row["reason"])
            self.ot_audit_reason.setToolTip(reason_text)
            self.set_ot_audit_status_badge(row["status"])
            if row["ot_class"] is None:
                self.ot_audit_glyph_table.setHeaderLabels(
                    ["OT class hint", "Rep glyph", "Detected OT roles"]
                )
                candidates = row["inspected_candidates"]
                self.ot_audit_detail.setText(
                    "%s (%s) / No clear OT link" % (
                        key, row["mode"]
                    )
                )
                self.ot_audit_reason.setText(
                    "NghiaType could not match this Native class to one "
                    "OpenType class. Review the suggested classes before syncing."
                )
                self.ot_audit_reason.setVisible(True)
                self.set_ot_audit_notice(
                    "No safe OpenType match",
                    "This Native class cannot be synced automatically. "
                    "Check its suggested OpenType links first.",
                    warning=True
                )
                for candidate in candidates:
                    glyph = QtGui.QTreeWidgetItem(self.ot_audit_glyph_table)
                    glyph.setText(0, "@" + candidate["ot_class"])
                    glyph.setText(1, (
                        "YES" if candidate["representative_present"] else "NO"
                    ))
                    glyph.setText(2, "+".join(candidate["ot_roles"]) or "NOT FOUND")
                    glyph.setToolTip(
                        0, "Name hint only" if candidate["name_hint"]
                        and not candidate["representative_present"]
                        else "Contains the Native representative"
                    )
                self.size_ot_audit_glyph_table()
                return
            self.ot_audit_glyph_table.setHeaderLabels(
                ["Glyph", "Native", "OpenType"]
            )
            self.ot_audit_detail.setText(
                "%s (%s) vs @%s" % (
                    key,
                    "left" if row["mode"] == "KernLeft" else "right",
                    row["ot_class"]
                )
            )
            if row["status"] == "MATCH":
                explanation = (
                    "In sync. Both classes contain the same glyphs."
                )
            elif row["status"] == "DIFFERENT":
                explanation = (
                    "Native has %d glyphs; OpenType @%s has %d. " % (
                        row["native_count"], row["ot_class"],
                        row["ot_count"]
                    )
                )
                missing = len(row["native_only"])
                extra = len(row["ot_only"])
                if missing:
                    explanation += "%d missing from OpenType. " % missing
                if extra:
                    explanation += "%d only in OpenType. " % extra
            else:
                explanation = (
                    "This class needs review. NghiaType could not confirm "
                    "that its OpenType match is safe to update."
                )
            self.ot_audit_reason.setText(explanation)
            # The matching notice below already explains success. Avoid
            # repeating the same sentence in the panel header.
            self.ot_audit_reason.setVisible(row["status"] != "MATCH")
            if (row["mapping"] == "SHARED_BOTH_SIDES" and
                    row["status"] != "MATCH"):
                self.set_ot_audit_notice(
                    "Shared OpenType class - review both sides",
                    "@%s is used by the left and right kerning groups. "
                    "Updating it can affect both. Check both linked Native "
                    "classes before making changes." % row["ot_class"],
                    warning=True
                )
            elif row["status"] == "MATCH":
                self.set_ot_audit_notice(
                    "Native and OpenType match",
                    "All %d glyphs are present in @%s." % (
                        row["native_count"], row["ot_class"]
                    ),
                    warning=False
                )
                self.ot_audit_glyph_table.setVisible(False)
            native_members = set(row["native_members"])
            ot_members = set(row["ot_members"])
            for name in sorted(native_members ^ ot_members,
                               key=lambda value: (value.casefold(), value)):
                glyph = QtGui.QTreeWidgetItem(self.ot_audit_glyph_table)
                glyph.setText(0, name)
                glyph.setText(1, "YES" if name in native_members else "--")
                glyph.setText(
                    2, "Missing in OT" if name in native_members else
                    "Only in OT"
                )
                if name in native_members:
                    glyph.setForeground(1, QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))
                glyph.setForeground(2, QtGui.QBrush(QtGui.QColor(
                    M3_LIGHT["onTertiaryContainer"]
                )))
            self.size_ot_audit_glyph_table()

        def set_ot_audit_notice(self, title, description, warning=False):
            """Show a separate comparison result or manual-review warning."""
            surface = (M3_LIGHT["tertiaryContainer"] if warning else
                       M3_LIGHT["surfaceContainerLowest"])
            border = (M3_LIGHT["tertiaryFixedDim"] if warning else
                      SUCCESS_COLOR)
            ink = (M3_LIGHT["onTertiaryContainer"] if warning else
                   SUCCESS_COLOR)
            self.ot_audit_notice.setStyleSheet(
                "QFrame#otAuditReviewCard{background:%s;border:1px solid %s;"
                "border-radius:9px;}" % (surface, border)
            )
            self.ot_audit_notice_title.setStyleSheet(
                "background:transparent;border:0;color:%s;" % ink
            )
            self.ot_audit_notice_title.setText(title)
            self.ot_audit_notice_description.setText(description)
            self.ot_audit_notice.setVisible(True)

        def size_ot_audit_glyph_table(self):
            """Allow a few rows to fit; scroll longer lists in the inspector."""
            # FontLab's PythonQt exposes this getter as an int property,
            # whereas regular PyQt exposes a callable method.
            count = int(read_qt_value(
                self.ot_audit_glyph_table, "topLevelItemCount", 0
            ) or 0)
            self.ot_audit_glyph_table.setFixedHeight(
                min(340, max(118, 44 + 37 * count))
            )

        def scan_native_tab(self):
            """Start a NEW read-only cycle after any verified Native Apply."""
            if self.native_write_failed or self.ot_write_failed:
                raise RuntimeError(
                    "A previous write could not be verified. DO NOT SAVE this "
                    "test COPY; close it without saving before retrying."
                )
            backend, core = self.get_native_backend()
            if backend is None or core is None:
                self.status_label.setText("Native scan cancelled; font unchanged.")
                self.set_native_latest("Scan cancelled; no font changes.")
                return
            # A new Native scan makes earlier OT comparison/selection stale.
            # Never leave an old proposal apparently ready after fresh data.
            self.ot_crosscheck_report = None
            self.ot_crosscheck_error = False
            self.ot_crosscheck_rows = {}
            self.ot_crosscheck_source_kern = None
            self.ot_crosscheck_native_snapshot = None
            self.reset_ot_sync_preview()
            self.ot_audit_to_sync.setEnabled(False)
            self.ot_audit_table.clear()
            self.ot_audit_glyph_table.clear()
            self.ot_audit_summary.setText(
                "Native data refreshed. Run 'Compare both sides' again "
                "to check OpenType."
            )
            self.native_metrics["ot_classes"].setText("--")
            self.native_metrics["differences"].setText("--")
            self.native_snapshot = None
            self.native_preview = None
            self.native_checked_token = None
            self.native_check_button.setEnabled(False)
            self.native_apply_button.setEnabled(False)
            self.native_apply_badge.setText("CHECK FIRST")
            self.native_apply_note.setText(
                "Select glyphs, check your selection, then confirm. "
                "You will save the test COPY yourself."
            )
            self.native_selected = set()
            self.native_entries = []
            self.native_rows = {}
            self.native_unicode_map = {}
            self.native_active_class = None
            self.native_updating = True
            try:
                self.native_class_table.clear()
                self.native_glyph_table.clear()
                # A previous Apply may have displayed a locked readback view.
                # Fresh Scan restores editable candidate columns and flags.
                self.native_class_table.setHeaderLabels(
                    ["Select", "Class", "Side", "Can add"]
                )
                self.native_glyph_table.setHeaderLabels(
                    ["Select", "Glyph to add", "Base & accents", "Unicode"]
                )
            finally:
                self.native_updating = False
            self.native_all_button.setEnabled(False)
            self.native_clear_button.setEnabled(False)
            self.native_export_button.setEnabled(False)
            self.native_live_badge.setText("SCANNING CLASSES")
            self.set_native_latest("Looking through the Native classes...")
            snap = backend.scan_native(fontlab, core)
            self.native_snapshot = snap
            try:
                scanned_font = fontlab.CurrentFont()
            except Exception:
                scanned_font = None
            self.native_unicode_map = read_glyph_codepoints(
                scanned_font,
                (name for names in snap["safe_all"].values() for name in names)
            )
            self.native_metrics["glyphs"].setText(str(len(snap["available"])))
            self.native_metrics["classes"].setText(str(len(snap["groups"])))
            self.native_updating = True
            try:
                for key in sorted(snap["safe_all"],
                                  key=lambda text: (text.casefold(), text)):
                    names = snap["safe_all"][key]
                    members, mode = snap["groups"][key]
                    row = QtGui.QTreeWidgetItem(self.native_class_table)
                    row.setFlags(row.flags() | QtCore.Qt.ItemIsUserCheckable)
                    row.setCheckState(0, QtCore.Qt.Unchecked)
                    row.setText(1, key)
                    row.setText(2, (
                        "Left" if mode == "KernLeft" else
                        "Right" if mode == "KernRight" else mode
                    ))
                    row.setText(3, "+" + str(len(names)))
                    self.install_row_pill(
                        self.native_class_table, row, 2,
                        "Left" if mode == "KernLeft" else
                        "Right" if mode == "KernRight" else mode,
                        "neutral"
                    )
                    self.install_row_pill(
                        self.native_class_table, row, 3,
                        "+" + str(len(names)), "accent"
                    )
                    row.setToolTip(1, "%d glyphs already in this class" % (
                        len(members)
                    ))
                    self.native_rows[key] = row
                    self.native_entries.extend((key, glyph) for glyph in names)
                first = next(iter(self.native_rows.values()), None)
                if first is not None:
                    self.native_class_table.setCurrentItem(first)
            finally:
                self.native_updating = False
            self.show_native_class(first)
            # A completed fresh Scan invalidates the previous selection and
            # unlocks only the new cycle. Keep cumulative native_applied=True
            # to accurately mark earlier in-memory changes as unsaved.
            self.native_cycle_applied = False
            self.native_write_result = None
            self.native_selection_locked = False
            self.native_class_table.setEnabled(True)
            self.native_glyph_table.setEnabled(True)
            self.native_filter.setEnabled(True)
            self.native_all_button.setEnabled(bool(self.native_entries))
            self.native_clear_button.setEnabled(bool(self.native_entries))
            self.native_export_button.setEnabled(True)
            self.set_native_selection_locked(False)
            self.native_diagnostics.setPlainText(
                "READ ONLY / %d available classes / %d memberships\n"
                "%d conflicts, %d scan issues.\n"
                "Select a class or glyph. Preview updates automatically.\n"
                "Run Check selection before adding. Font unchanged."
                % (len(snap["safe_all"]), len(self.native_entries),
                   len(snap["blocked"]), len(snap["issues"]))
            )
            self.native_live_badge.setText("READY TO CHOOSE")
            self.status_label.setText("Native scan complete; font unchanged.")
            self.set_native_latest(
                "Found %d classes with %d glyphs you can add. %s" % (
                    len(snap["safe_all"]), len(self.native_entries),
                    "Earlier changes are still not saved."
                    if self.native_applied else "Nothing was changed."
                )
            )
            self.update_kerning_tab_header(0)
            self.refresh_native_selection_count()
            self.filter_native_classes()
            self.refresh_context()

        def show_native_class(self, item):
            if self.native_updating or self.native_snapshot is None:
                return
            key = str(item.text(1)) if item is not None else ""
            if key not in self.native_snapshot["safe_all"]:
                key = None
            self.native_active_class = key
            self.render_native_glyphs()

        def render_native_glyphs(self):
            self.native_updating = True
            try:
                self.native_glyph_table.clear()
                key = self.native_active_class
                if key is None or self.native_snapshot is None:
                    self.native_glyph_title.setText(
                        "Glyphs to add  /  Choose a class"
                    )
                    return
                names = self.native_snapshot["safe_all"][key]
                checked = sum((key, name) in self.native_selected for name in names)
                self.native_glyph_title.setText(
                    "Class %s / %d glyphs to add / %d selected" %
                    (key, len(names), checked)
                )
                for glyph in names:
                    row = QtGui.QTreeWidgetItem(self.native_glyph_table)
                    row.setFlags(row.flags() | QtCore.Qt.ItemIsUserCheckable)
                    row.setCheckState(
                        0, QtCore.Qt.Checked if (key, glyph) in self.native_selected
                        else QtCore.Qt.Unchecked
                    )
                    row.setText(1, glyph)
                    codepoints = self.native_unicode_map.get(glyph, ())
                    row.setText(2, describe_unicode_components(codepoints))
                    row.setText(3, format_unicode_values(codepoints))
                    origin = self.native_snapshot["origin"].get(
                        glyph.split(".", 1)[0], (None, "name")
                    )[1]
                    try:
                        row.setToolTip(
                            1, (
                                "Unicode: %s\nComponents: %s\n%s" % (
                                    format_unicode_values(codepoints),
                                    describe_unicode_components(codepoints),
                                    "Unicode-backed proposal" if origin == "unicode"
                                    else "Name-only proposal / not authorized for Apply"
                                )
                            )
                        )
                    except Exception:
                        pass
            finally:
                self.native_updating = False

        def show_native_applied_summary(self, result):
            """Replace old checked proposals with non-editable verified results."""
            steps = result.get("steps_passed", ())
            count = sum(len(step["added"]) for step in steps)
            self.native_updating = True
            try:
                self.native_class_table.clear()
                self.native_glyph_table.clear()
                self.native_class_table.setHeaderLabels(
                    ["", "Class", "Side", "Added"]
                )
                self.native_glyph_table.setHeaderLabels(
                    ["", "Added glyph", "Class", "Unicode"]
                )
                for step in steps:
                    key = step["class"]
                    mode = self.native_snapshot["groups"][key][1]
                    item = QtGui.QTreeWidgetItem(self.native_class_table)
                    self.set_verified_mark(item)
                    item.setText(1, key)
                    item.setText(2, (
                        "Left" if mode == "KernLeft" else
                        "Right" if mode == "KernRight" else mode
                    ))
                    item.setText(3, "+%d" % len(step["added"]))
                    self.install_row_pill(
                        self.native_class_table, item, 2,
                        "Left" if mode == "KernLeft" else
                        "Right" if mode == "KernRight" else mode,
                        "neutral"
                    )
                    self.install_row_pill(
                        self.native_class_table, item, 3,
                        "+%d" % len(step["added"]), "accent"
                    )
                    for name in step["added"]:
                        glyph = QtGui.QTreeWidgetItem(self.native_glyph_table)
                        self.set_verified_mark(glyph)
                        glyph.setText(1, name)
                        glyph.setText(2, key)
                        glyph.setText(3, format_unicode_values(
                            self.native_unicode_map.get(name, ())
                        ))
                self.native_glyph_title.setText(
                    "Added %d glyph%s to %d class%s - verified" % (
                        count, "" if count == 1 else "s", len(steps),
                        "" if len(steps) == 1 else "es"
                    )
                )
            finally:
                self.native_updating = False

            self.native_class_hint.setText(
                "Verified additions. Start a fresh Scan to add more classes."
            )
            self.native_glyph_hint.setText(
                "Read-only result. These glyphs were verified in FontLab."
            )
            self.refresh_native_selection_count()

        def sync_native_class_checks(self):
            if self.native_snapshot is None:
                return
            self.native_updating = True
            try:
                for key, row in self.native_rows.items():
                    names = self.native_snapshot["safe_all"][key]
                    chosen = sum((key, name) in self.native_selected for name in names)
                    state = (QtCore.Qt.Checked if chosen == len(names)
                             else QtCore.Qt.Unchecked if not chosen
                             else QtCore.Qt.PartiallyChecked)
                    row.setCheckState(0, state)
            finally:
                self.native_updating = False

        def on_native_class_toggled(self, item, column):
            if (self.native_updating or self.native_selection_locked or
                    column != 0 or self.native_snapshot is None):
                return
            key = str(item.text(1))
            if key not in self.native_snapshot["safe_all"]:
                return
            state = item.checkState(0)
            if state == QtCore.Qt.PartiallyChecked:
                return
            pairs = {(key, glyph) for glyph in self.native_snapshot["safe_all"][key]}
            if state == QtCore.Qt.Checked:
                self.native_selected.update(pairs)
            else:
                self.native_selected.difference_update(pairs)
            self.sync_native_class_checks()
            self.render_native_glyphs()
            self.refresh_native_preview()
            self.set_native_latest(
                "Class %s / %s %d proposed glyphs. Font unchanged." %
                (key, "selected" if state == QtCore.Qt.Checked else "cleared",
                 len(pairs))
            )

        def on_native_glyph_toggled(self, item, column):
            if (self.native_updating or self.native_selection_locked or
                    column != 0 or
                    self.native_active_class is None or self.native_snapshot is None):
                return
            key = self.native_active_class
            glyph = str(item.text(1))
            if glyph not in self.native_snapshot["safe_all"][key]:
                return
            if item.checkState(0) == QtCore.Qt.Checked:
                self.native_selected.add((key, glyph))
            else:
                self.native_selected.discard((key, glyph))
            self.sync_native_class_checks()
            # This is called from QTreeWidget.itemChanged. Re-rendering here
            # clears/deletes the emitting item while Qt is still dispatching
            # its checkbox change and can terminate the FontLab host process.
            # Keep the tree intact; only its selection count needs refreshing.
            names = self.native_snapshot["safe_all"][key]
            checked = sum((key, name) in self.native_selected for name in names)
            self.native_glyph_title.setText(
                "Class %s / %d glyphs to add / %d selected" %
                (key, len(names), checked)
            )
            self.refresh_native_preview()
            self.set_native_latest(
                "%s / %s / class %s. Font unchanged." %
                (glyph, "selected" if (key, glyph) in self.native_selected
                 else "deselected", key)
            )

        def select_all_native(self, select):
            if self.native_snapshot is None or self.native_selection_locked:
                return
            self.native_selected = set(self.native_entries) if select else set()
            self.sync_native_class_checks()
            self.render_native_glyphs()
            self.refresh_native_preview()
            self.set_native_latest(
                "%s / %d memberships selected. Font unchanged." %
                ("Select all" if select else "Clear all", len(self.native_selected))
            )

        def filter_native_classes(self):
            if self.native_snapshot is None:
                return
            query = str(read_qt_value(self.native_filter, "text", "")).strip().casefold()
            first = None
            for key, row in self.native_rows.items():
                visible = (not query or query in key.casefold()
                           or any(query in glyph.casefold()
                                  for glyph in self.native_snapshot["safe_all"][key]))
                row.setHidden(not visible)
                if visible and first is None:
                    first = row
            current = self.native_rows.get(self.native_active_class)
            if current is None or bool(read_qt_value(
                    current, "isHidden", False)):
                if first is not None:
                    self.native_class_table.setCurrentItem(first)
                else:
                    self.show_native_class(None)

        def refresh_native_selection_count(self):
            count = len(self.native_selected)
            if self.native_cycle_applied:
                label = "%d added - locked" % count
            elif self.native_selection_locked:
                label = "%d checked - locked" % count
            else:
                label = "%d glyphs selected" % count
            self.native_selection_label.setText(label)

        def dim_native_selection_workspace(self, dimmed):
            """Keep white list surfaces; mute disabled rows without compositing.

            A QGraphicsOpacityEffect on FontLab's embedded QTreeWidget caused
            old table contents to be painted over the next stacked tab.
            Disabled state stays enforced by setEnabled(False); theme colors
            provide the visual lock without an offscreen graphics effect.
            Native QTreeWidgetItem checkboxes remain untouched.
            """
            for table in (self.native_class_table, self.native_glyph_table):
                self.style_workflow_table(table, bool(dimmed))

        def set_native_selection_locked(self, locked):
            """Freeze checkbox selections after Check without changing font."""
            self.native_selection_locked = bool(locked)
            editable = bool(self.native_snapshot is not None and not locked and
                            not self.native_cycle_applied and
                            not self.native_write_failed and
                            not self.ot_write_failed)
            for widget in (self.native_class_table, self.native_glyph_table,
                           self.native_filter):
                widget.setEnabled(editable)
            self.dim_native_selection_workspace(
                bool(locked or self.native_cycle_applied or
                     self.native_write_failed or self.ot_write_failed)
            )
            self.native_all_button.setEnabled(editable and bool(self.native_entries))
            self.native_clear_button.setEnabled(editable and bool(self.native_entries))
            self.native_class_hint.setText(
                "Selection locked. Use Edit selection above to change it."
                if locked else
                "Click a row to preview. Tick it to select all its glyphs."
            )
            self.native_glyph_hint.setText(
                "Checked glyphs are locked until you choose Edit selection."
                if locked else
                "Tick individual glyphs; switching classes preserves selections."
            )
            self.refresh_native_selection_count()

        def unlock_native_selection(self):
            """Explicitly discard Check approval before allowing edits again."""
            if (not self.native_selection_locked or self.native_cycle_applied or
                    self.native_write_failed or self.ot_write_failed):
                return
            self.native_checked_token = None
            self.native_apply_button.setEnabled(False)
            self.native_apply_badge.setText("CHECK FIRST")
            self.set_native_selection_locked(False)
            self.refresh_native_preview()
            self.set_native_latest(
                "Selection unlocked. Review your glyphs and run Check again."
            )

        def refresh_native_preview(self):
            self.native_preview = None
            self.native_checked_token = None
            self.native_apply_button.setEnabled(False)
            self.native_check_button.setEnabled(False)
            self.native_apply_button.setText("Add selected glyphs...")
            self.native_apply_badge.setText("CHECK FIRST")
            self.refresh_native_selection_count()
            snap = self.native_snapshot
            if snap is None:
                return
            if not self.native_selected:
                self.native_live_badge.setText("NOTHING SELECTED")
                self.native_apply_note.setText(
                    "Select one or more glyphs, then click Check selection."
                )
                self.native_diagnostics.setPlainText(
                    "READ ONLY / no proposed glyphs selected.\n"
                    "Tick a class or individual glyph. V3 font unchanged."
                )
                self.set_native_latest("No glyphs selected. Font unchanged.")
                return
            preview = self.native_backend.selected_preview(
                self.native_core, snap, frozenset(self.native_selected)
            )
            self.native_preview = preview
            self.native_check_button.setEnabled(
                not (self.native_cycle_applied or self.native_write_failed or
                     self.ot_write_failed)
            )
            self.native_apply_note.setText(
                "%d glyphs selected. Check this selection before adding "
                "anything to the font." % preview["count"]
            )
            lines = [
                "PROPOSED CHANGES / NOT YET APPLIED",
                "Selected: %d classes / %d memberships" %
                (len(preview["selected"]), preview["count"]), "",
            ]
            for key, names in sorted(preview["selected"].items()):
                lines.append("%s  |  +%d  |  %s" %
                             (key, len(names), ", ".join(names)))
            if snap["blocked"] or preview["issues"] or preview["name_only"]:
                lines.append("")
                lines.append("REVIEW: conflicts / scan issues / name-only proposals")
                if snap["blocked"]:
                    lines.append("Conflicts: %d" % len(snap["blocked"]))
                if preview["issues"]:
                    lines.extend(preview["issues"][:8])
                if preview["name_only"]:
                    lines.append("Name-only: " + ", ".join(preview["name_only"]))
            lines.extend(["", "Run Check selection before adding.",
                          "Font unchanged. No automatic writes or saves."])
            self.native_diagnostics.setPlainText("\n".join(lines))
            self.native_live_badge.setText(
                "%d GLYPHS SELECTED" % preview["count"]
            )
            self.status_label.setText(
                "Selection ready. Check it before adding."
            )
            self.set_native_latest(
                "%d glyphs selected across %d classes. Nothing changed yet." %
                (preview["count"], len(preview["selected"]))
            )

        def native_live_safety_check(self):
            """Reuse the verified V2 fail-closed preflight; never write here."""
            if (self.native_snapshot is None or self.native_preview is None or
                    self.native_cycle_applied or self.native_write_failed or
                    self.ot_write_failed):
                return None, ["Scan Native classes and select glyphs first."]
            snap = self.native_snapshot
            major, unused_paths = self.native_backend.detect_major(fontlab, QtCore)
            font_name = ntpath.basename(snap["font_path"])
            if not snap["font_path"] or not os.path.isfile(snap["font_path"]):
                return None, [
                    "Save a disposable font COPY on disk before adding glyphs."
                ]
            return self.native_backend.fresh_preflight(
                fontlab, self.native_core, snap, self.native_preview,
                major, font_name, snap["master"], True
            )

        def check_native_write_plan(self):
            """Manual check only; enable the action for THIS exact plan."""
            self.native_checked_token = None
            self.native_apply_button.setEnabled(False)
            live, blockers = self.native_live_safety_check()
            if blockers:
                self.set_native_selection_locked(False)
                reason = "; ".join(str(issue) for issue in blockers[:3])
                self.native_apply_badge.setText("NEEDS ATTENTION")
                self.native_apply_note.setText(
                    "Cannot add yet: " + reason
                )
                self.native_diagnostics.setPlainText(
                    "NATIVE CHECK / NO FONT CHANGES\n\n" +
                    "\n".join(str(issue) for issue in blockers)
                )
                self.set_native_latest(
                    "Checks need attention. No font changes. " + reason
                )
                self.status_label.setText(
                    "Native check found an issue. Nothing was added."
                )
                return False
            if live is None:
                raise RuntimeError("Native check returned no live font snapshot.")
            self.native_checked_token = self.native_preview["token"]
            self.native_apply_button.setEnabled(True)
            self.set_native_selection_locked(True)
            self.native_apply_button.setText(
                "Add %d glyph%s..." % (
                    self.native_preview["count"],
                    "" if self.native_preview["count"] == 1 else "s"
                )
            )
            self.native_apply_badge.setText("READY TO CONFIRM")
            self.native_live_badge.setText("SELECTION LOCKED / CHECK PASSED")
            self.native_apply_note.setText(
                "%d glyphs ready. You can now confirm the changes "
                "to your test COPY." % self.native_preview["count"]
            )
            self.set_native_latest(
                "Checks passed. You can confirm adding to your test COPY."
            )
            self.status_label.setText(
                "Native check passed. The font has not changed yet."
            )
            return True

        def safe_native_writer(self):
            """Treat an unexpected exception after a write as DO NOT SAVE."""
            self.native_write_attempted = False
            try:
                self.run_native_guarded_apply()
            except Exception as exc:
                trace = traceback.format_exc()
                print("NGHIATYPE V3 NATIVE GUARDED APPLY ERROR:\n" + trace)
                self.native_checked_token = None
                self.native_apply_button.setEnabled(False)
                if self.native_write_attempted:
                    self.native_applied = True
                    self.native_cycle_applied = True
                    self.native_write_failed = True
                    self.native_apply_badge.setText("DO NOT SAVE")
                    self.native_check_button.setEnabled(False)
                    self.native_class_table.setEnabled(False)
                    self.native_glyph_table.setEnabled(False)
                    self.native_all_button.setEnabled(False)
                    self.native_clear_button.setEnabled(False)
                    self.native_filter.setEnabled(False)
                    self.native_scan_button.setEnabled(False)
                    self.ot_crosscheck_report = None
                    self.reset_ot_sync_preview()
                    message = (
                        "Could not verify the Native changes. DO NOT SAVE "
                        "this test COPY; close it without saving."
                    )
                else:
                    self.set_native_selection_locked(False)
                    self.native_apply_badge.setText("NEEDS ATTENTION")
                    message = (
                        "Native Apply stopped before writing. Review the "
                        "error and check the selection again."
                    )
                self.native_apply_note.setText(message)
                self.native_diagnostics.setPlainText(trace[-4000:])
                self.native_report_expanded = True
                self.native_preview_body.setVisible(True)
                self.native_diagnostics.setVisible(True)
                self.native_report_button.setText("Report")
                self.set_native_latest(message)
                self.status_label.setText(message)

        def run_native_guarded_apply(self):
            """Explicit FL8 COPY-only Native write using verified V2 backend."""
            preview = self.native_preview
            snap = self.native_snapshot
            if (preview is None or snap is None or self.native_cycle_applied or
                    self.native_write_failed or self.ot_write_failed or
                    self.native_checked_token != preview["token"] or
                    frozenset(self.native_selected) != preview["pairs"]):
                raise RuntimeError("Check this exact Native selection again first.")
            live, blockers = self.native_live_safety_check()
            if blockers:
                self.native_checked_token = None
                self.native_apply_button.setEnabled(False)
                self.set_native_selection_locked(False)
                self.native_apply_note.setText(
                    "Something changed since the last check. Check again. " +
                    "; ".join(str(issue) for issue in blockers[:2])
                )
                return

            font_name = ntpath.basename(snap["font_path"])
            classes = sorted(preview["selected"], key=str.casefold)
            shown = ", ".join(classes[:6])
            if len(classes) > 6:
                shown += " (+%d more)" % (len(classes) - 6)
            accepted = self.confirm_glyph_additions(
                "Add %d glyph%s to Native classes?" % (
                    preview["count"],
                    "" if preview["count"] == 1 else "s"
                ),
                [
                    "Font: %s  |  Master: %s" % (font_name, snap["master"]),
                    "%d glyph%s will be added to %d existing class%s: %s." % (
                        preview["count"],
                        "" if preview["count"] == 1 else "s",
                        len(classes), "" if len(classes) == 1 else "es",
                        shown
                    ),
                    "Only these class members will change in the open font. "
                    "Nothing will be saved or compiled automatically."
                ],
                preview["count"],
                "This is a test COPY, and I have a backup of the original."
            )
            if not accepted:
                self.status_label.setText("Add cancelled. Nothing changed.")
                return
            # The active font can change while a modal dialog is open.
            live, blockers = self.native_live_safety_check()
            if blockers:
                self.native_checked_token = None
                self.native_apply_button.setEnabled(False)
                self.set_native_selection_locked(False)
                self.native_apply_note.setText(
                    "Font data changed before adding. Check again."
                )
                return
            if (self.native_preview is not preview or
                    self.native_checked_token != preview["token"] or
                    frozenset(self.native_selected) != preview["pairs"]):
                self.native_checked_token = None
                self.native_apply_button.setEnabled(False)
                self.set_native_selection_locked(False)
                self.native_apply_note.setText(
                    "The selection changed during confirmation. Check again."
                )
                return

            self.native_apply_button.setEnabled(False)
            self.native_check_button.setEnabled(False)
            self.native_write_attempted = True
            record = {"write_attempted": False}
            result = self.native_backend.stepwise_native_apply(
                fontlab, self.native_core, live, preview, record
            )
            self.native_write_result = result
            self.native_checked_token = None
            self.native_applied = True
            self.native_cycle_applied = True
            self.native_write_failed = not bool(result["ok"])
            self.native_class_table.setEnabled(False)
            self.native_glyph_table.setEnabled(False)
            self.native_all_button.setEnabled(False)
            self.native_clear_button.setEnabled(False)
            self.native_filter.setEnabled(False)
            # Keep the just-verified readback visible until a deliberate Scan.
            # A successful write must not permanently disable future cycles.
            self.update_kerning_tab_header(0)
            self.ot_crosscheck_report = None
            self.ot_crosscheck_rows = {}
            self.ot_audit_table.clear()
            self.ot_audit_glyph_table.clear()
            self.native_metrics["ot_classes"].setText("--")
            self.native_metrics["differences"].setText("--")
            self.ot_audit_summary.setText(
                "Native classes updated and verified in memory. Go to "
                "Cross-check to compare with OpenType. Save manually later."
            )
            self.reset_ot_sync_preview()

            if result["ok"]:
                self.show_native_applied_summary(result)
                lines = [
                    "NATIVE WRITE / RESULT VERIFIED / NOT SAVED",
                    "%d glyphs added to %d Native classes" % (
                        preview["count"], len(result["steps_passed"])), "",
                ]
                for step in result["steps_passed"]:
                    lines.append("%s  +%d  %s" % (
                        step["class"], len(step["added"]),
                        ", ".join(step["added"])
                    ))
                lines.extend(["", "Other Native classes and pair values: unchanged.",
                              "Continue to Cross-check. Save TEST COPY manually."])
                self.native_diagnostics.setPlainText("\n".join(lines))
                self.native_live_badge.setText(
                    "%d GLYPHS ADDED" % preview["count"]
                )
                self.native_apply_badge.setText("ADDED - NOT SAVED")
                label = (
                    "Added %d glyph%s to %d class%s. "
                    "Verified in FontLab, not saved yet." % (
                        preview["count"],
                        "" if preview["count"] == 1 else "s",
                        len(result["steps_passed"]),
                        "" if len(result["steps_passed"]) == 1 else "es"
                    )
                )
            else:
                self.native_apply_badge.setText("DO NOT SAVE")
                self.native_diagnostics.setPlainText(
                    "NATIVE WRITE / COULD NOT VERIFY / POSSIBLE PARTIAL CHANGES\n"
                    "DO NOT SAVE. CLOSE TEST COPY WITHOUT SAVING.\n\n" +
                    result.get("error", "Unknown readback error")
                )
                label = (
                    "Native change could not be verified. DO NOT SAVE; "
                    "close this test COPY without saving."
                )
            self.native_apply_note.setText(label)
            # Leave the diagnostics available, without forcing a verbose
            # technical report into the workspace after a successful write.
            self.native_report_expanded = not bool(result["ok"])
            self.native_preview_body.setVisible(self.native_report_expanded)
            self.native_diagnostics.setVisible(self.native_report_expanded)
            self.native_report_button.setText("Report")
            self.set_native_latest(label)
            self.status_label.setText("" if result["ok"] else label)

        def export_native_report(self):
            if self.native_snapshot is None or self.native_backend is None:
                raise RuntimeError("Scan native classes first.")
            data = self.native_backend.report_data(
                self.native_snapshot, self.native_preview,
                detect_fontlab_major(fontlab, QtCore), self.native_write_result
            )
            selected = QtGui.QFileDialog.getSaveFileName(
                self, "Export V3 native preview JSON",
                "NghiaType_V3_Native_Preview.json", "JSON (*.json)"
            )
            if isinstance(selected, (tuple, list)):
                selected = selected[0]
            path = str(selected or "").strip()
            if not path:
                return
            if not path.lower().endswith(".json"):
                path += ".json"
            with open(path, "x", encoding="utf-8") as output:
                json.dump(data, output, indent=2, sort_keys=True, ensure_ascii=True)
                output.write("\n")
            self.status_label.setText("Preview JSON exported; font unchanged.")
            self.set_native_latest("Preview JSON exported. Font unchanged.")

        def closeEvent(self, event):
            cache = sys.__dict__.setdefault(WINDOW_CACHE_KEY, {})
            if cache.get("window") is self:
                cache.pop("window", None)
            QtGui.QDialog.closeEvent(self, event)

    cache = sys.__dict__.setdefault(WINDOW_CACHE_KEY, {})
    previous = cache.pop("window", None)
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass
    try:
        parent = fontlab.MainWindow()
    except Exception:
        parent = None
    window = ToolsShell(parent)
    cache["window"] = window
    window.show()
    window.raise_()
    return window


def main():
    try:
        import fontlab
        from PythonQt import QtCore, QtGui
        return start_gui(fontlab, QtCore, QtGui)
    except Exception:
        print("NghiaType Tools V3 shell startup failure:")
        print(traceback.format_exc())
        return None


if __name__ == "__main__":
    main()
