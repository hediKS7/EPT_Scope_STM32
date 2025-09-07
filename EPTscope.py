import sys
import os
import csv
import serial.tools.list_ports
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QComboBox, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QRadioButton, QSlider, QFileDialog, QMessageBox, QSplitter, QCheckBox,
    QSizeGrip
)
from PyQt5.QtGui import QIcon, QPalette, QColor
from PyQt5.QtCore import Qt, QTimer, QEasingCurve, QPropertyAnimation

import pyqtgraph as pg
from scipy.signal import butter, filtfilt
from pyqtgraph.exporters import ImageExporter

# Dark palette & stylesheet helper
def apply_dark_theme(widget):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(35, 35, 35))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.Highlight, QColor(85, 170, 255))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    widget.setPalette(palette)
    widget.setStyleSheet("""
        QWidget { background: #1e1e1e; color: #ddd; }
        QWidget#TitleBar { background: #222; }
        QLabel#TitleLabel { color: #ddd; }
        QPushButton#TitleButton { background: transparent; color: #ddd; border: none; padding:5px; }
        QPushButton#TitleButton:hover { background: #555; }
        QPushButton#Hamburger { font-size:18px; background: transparent; color: #ddd; border: none; padding:5px; }
        QPushButton#Hamburger:hover { background: #555; }
        QMenuBar { background-color: #333; color: #ddd; }
        QMenuBar::item:selected { background: #555; }
        QGroupBox { border: 1px solid #555; border-radius: 5px; margin-top: 10px; font-weight: bold; }
        QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; color: #aad; }
        QPushButton { background-color: #555; border: none; padding: 6px; border-radius: 4px; }
        QPushButton:hover { background-color: #667; }
        QPushButton:pressed { background-color: #446; }
        QSlider::groove:horizontal { height: 8px; background: #444; border-radius:4px; }
        QSlider::handle:horizontal { width: 14px; background: #88f; margin:-3px 0; border-radius:7px; }
        QLabel, QLineEdit, QComboBox, QMenu, QMenuBar { color: #ddd; }
        QComboBox { background: #333; border: 1px solid #555; padding: 4px; }
        QLineEdit { background: #222; border: 1px solid #555; padding: 4px; }
    """)

# Directory for icons
dir_path = os.path.dirname(os.path.realpath(__file__))

class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.parent = parent
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 5, 0)

        # Hamburger toggle
        self.btnHam = QPushButton("☰", self)
        self.btnHam.setObjectName("Hamburger")
        self.btnHam.clicked.connect(parent.toggle_sidebar)
        layout.addWidget(self.btnHam)

        # Window icon and title
        icon = QLabel(self)
        icon.setPixmap(parent.windowIcon().pixmap(16,16))
        layout.addWidget(icon)
        title = QLabel(parent.windowTitle(), self)
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        layout.addStretch()

        # Minimize, maximize, close
        self.btnMin = QPushButton("–", self)
        self.btnMin.setObjectName("TitleButton")
        self.btnMin.clicked.connect(parent.showMinimized)
        layout.addWidget(self.btnMin)

        self.btnMax = QPushButton("□", self)
        self.btnMax.setObjectName("TitleButton")
        self.btnMax.clicked.connect(self.toggle_max)
        layout.addWidget(self.btnMax)

        self.btnClose = QPushButton("×", self)
        self.btnClose.setObjectName("TitleButton")
        self.btnClose.clicked.connect(parent.close)
        layout.addWidget(self.btnClose)

        self.startPos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.startPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.startPos:
            delta = event.globalPos() - self.startPos
            self.parent.move(self.parent.pos() + delta)
            self.startPos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.startPos = None

    def toggle_max(self):
        if self.parent.isMaximized():
            self.parent.showNormal()
        else:
            self.parent.showMaximized()

class EPTScope(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.buffer_t = []
        self.buffer_y = []
        self.trigger_line = None
        self.record_fh = None
        self.is_running = False

        self._init_ui()
        self.init_timers()
        self._add_hover()
        self._animate_startup()

    def _init_ui(self):
        self.setWindowTitle("EPTScope")
        self.setWindowIcon(QIcon(os.path.join(dir_path, "icon/app_icon.png")))
        apply_dark_theme(self)

        # Main container & layout
        central = QWidget()
        main_v = QVBoxLayout(central)
        main_v.setContentsMargins(0,0,0,0)
        main_v.setSpacing(0)

        # Custom title bar
        self.titleBar = TitleBar(self)
        main_v.addWidget(self.titleBar)

        # Content area with horizontal splitter
        content = QWidget()
        content_h = QHBoxLayout(content)
        content_h.setContentsMargins(5,5,5,5)

        # Plot widget
        self.plot = pg.PlotWidget(title="Live Signal")
        self.plot.setLabel('bottom','Time',units='ms')
        self.plot.setLabel('left','Voltage',units='mV')
        self.plot.showGrid(x=True,y=True,alpha=0.3)
        self.curve = self.plot.plot(pen=pg.mkPen('b',width=2))

        # Sidebar on left
        self.sidebar = QWidget()
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setMaximumWidth(380)
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setSpacing(15)
        self._build_sidebar(sb_layout)

        # Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.plot)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        content_h.addWidget(self.splitter)
        main_v.addWidget(content)
        self.setCentralWidget(central)

        # Resize grip
        grip = QSizeGrip(self)
        main_v.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)

        # Menus & ports
        self._build_menu()
        self.refresh_ports()

    def _build_menu(self):
        mb = self.menuBar()
        mb.setNativeMenuBar(False)
        fm = mb.addMenu("File")
        fm.addAction("Open", self.open_signal)
        fm.addAction("Save", self.take_snapshot)
        fm.addSeparator()
        fm.addAction("Exit", self.close)
        hm = mb.addMenu("Help")
        hm.addAction("About", self.show_about)

    def _build_sidebar(self, layout):
        # Channel controls
        gb = QGroupBox("Channel A")
        f = QFormLayout(gb)
        self.ch_enable = QCheckBox("Enable")
        self.ch_enable.setChecked(True)
        self.ch_enable.toggled.connect(lambda on: self.plot.setVisible(on))
        f.addRow(self.ch_enable)
        self.ch_scale = QComboBox()
        self.ch_scale.addItems(["±5 V","±2 V","±1 V","±500 mV","±200 mV","±100 mV"])
        f.addRow("Scale:", self.ch_scale)
        self.ch_coupling = QComboBox()
        self.ch_coupling.addItems(["DC","AC","GND"])
        f.addRow("Coupling:", self.ch_coupling)
        layout.addWidget(gb)

        # Trigger settings
        gb2 = QGroupBox("Trigger")
        f2 = QFormLayout(gb2)
        self.trig_mode = QComboBox()
        self.trig_mode.addItems(["Auto","Normal","Single"])
        f2.addRow("Mode:", self.trig_mode)
        edge_l = QHBoxLayout()
        self.rb_rise = QRadioButton("Rising"); self.rb_rise.setChecked(True)
        self.rb_fall = QRadioButton("Falling")
        edge_l.addWidget(self.rb_rise); edge_l.addWidget(self.rb_fall)
        f2.addRow("Edge:", edge_l)
        th_l = QHBoxLayout()
        self.th_spin = QLineEdit("0.0"); self.th_spin.setFixedWidth(60)
        self.th_spin.editingFinished.connect(self.change_threshold)
        th_l.addWidget(self.th_spin); th_l.addWidget(QLabel("mV"))
        f2.addRow("Threshold:", th_l)
        self.pre_slider = QSlider(Qt.Horizontal)
        self.pre_slider.setRange(0,100)
        f2.addRow("Pre-trigger %:", self.pre_slider)
        layout.addWidget(gb2)

        # Control buttons
        gb3 = QGroupBox("Controls")
        vb = QVBoxLayout(gb3)
        self.start_btn = QPushButton("▶ Start"); self.start_btn.clicked.connect(self.start_acq)
        self.pause_btn = QPushButton("⏸ Pause"); self.pause_btn.clicked.connect(self.pause_acq)
        self.pause_btn.setEnabled(False)
        vb.addWidget(self.start_btn); vb.addWidget(self.pause_btn)
        for txt,slot in [("🧹 Clear",self.clear_screen),("↔ Auto-Scale",self.auto_scale),
                         ("📊 Measure",self.measure_stats),("📷 Snapshot",self.take_snapshot)]:
            b=QPushButton(txt); b.clicked.connect(slot); vb.addWidget(b)
        self.rec_btn=QPushButton("⏺ Record"); self.rec_btn.setCheckable(True)
        self.rec_btn.toggled.connect(self.toggle_recording)
        vb.addWidget(self.rec_btn)
        layout.addWidget(gb3)

        # I/O & extras
        gb4 = QGroupBox("I/O & Extras")
        f4 = QFormLayout(gb4)
        self.com = QComboBox(); f4.addRow("COM:", self.com)
        refresh_btn = QPushButton("⟳"); refresh_btn.clicked.connect(self.refresh_ports)
        f4.addRow(refresh_btn)
        self.baud = QLineEdit("115200"); f4.addRow("Baud:", self.baud)
        bot=QHBoxLayout()
        for txt,slot in [("⧋ FFT",self.perform_fft),("⚙ Filter",self.perform_filter),("📂 Open",self.open_signal)]:
            b=QPushButton(txt); b.clicked.connect(slot); bot.addWidget(b)
        f4.addRow(bot)
        layout.addWidget(gb4)

        layout.addStretch()

    def init_timers(self):
        self.tmr = QTimer()
        self.tmr.timeout.connect(self.update_plot)
        self.tmr.start(30)

    def _add_hover(self):
        proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_hover)
        self.hover_label = QLabel("", self)
        self.hover_label.setStyleSheet("background: rgba(255,255,255,0.8); padding:2px;")
        self.hover_label.hide()

    def _on_hover(self, ev):
        pos = ev[0]
        if not self.plot.sceneBoundingRect().contains(pos):
            self.hover_label.hide()
            return
        mp = self.plot.getViewBox().mapSceneToView(pos)
        if not self.buffer_t:
            return
        idx = min(range(len(self.buffer_t)), key=lambda i: abs(self.buffer_t[i] - mp.x()))
        x, y = self.buffer_t[idx], self.buffer_y[idx]
        self.hover_label.setText(f"{x:.1f} ms\n{y:.1f} mV")
        self.hover_label.adjustSize()
        self.hover_label.move(int(pos.x()) + 15, int(pos.y()) + 15)
        self.hover_label.show()

    def _animate_startup(self):
        self.setWindowOpacity(0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(600)
        anim.setStartValue(0)
        anim.setEndValue(1)
        anim.start()

    def toggle_sidebar(self):
        start = self.sidebar.width()
        end = 0 if start > 0 else 380
        anim = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        anim.setDuration(300)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.finished.connect(self._adjust_splitter)
        anim.start()

    def _adjust_splitter(self):
        if self.sidebar.width() == 0:
            self.splitter.setSizes([0, self.width()])
        else:
            self.splitter.setSizes([380, 0])

    def refresh_ports(self):
        self.com.clear()
        for p in serial.tools.list_ports.comports():
            self.com.addItem(p.device)

    def start_acq(self):
        self.is_running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)

    def pause_acq(self):
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)

    def update_plot(self):
        # Only redraw existing buffer; no synthetic signal
        if not self.is_running or not self.buffer_t or not self.buffer_y:
            return
        self.curve.setData(self.buffer_t, self.buffer_y)
        if self.rec_btn.isChecked() and self.record_fh:
            self.record_fh.writerow([datetime.now().isoformat(), self.buffer_y[-1]])

    def clear_screen(self):
        self.buffer_t.clear()
        self.buffer_y.clear()
        self.curve.clear()

    def auto_scale(self):
        self.plot.enableAutoRange('x')
        self.plot.enableAutoRange('y')

    def measure_stats(self):
        if not self.buffer_y:
            QMessageBox.warning(self, "Measure", "No data.")
            return
        mn, mx, av = min(self.buffer_y), max(self.buffer_y), sum(self.buffer_y)/len(self.buffer_y)
        QMessageBox.information(self, "Stats", f"Min: {mn:.2f}\nMax: {mx:.2f}\nMean: {av:.2f}")

    def change_threshold(self):
        try:
            val = float(self.th_spin.text())
        except ValueError:
            return
        if self.trigger_line:
            self.plot.removeItem(self.trigger_line)
        self.trigger_line = pg.InfiniteLine(val, angle=0, pen=pg.mkPen('r', style=Qt.DashLine))
        self.plot.addItem(self.trigger_line)

    def toggle_recording(self, rec):
        if rec:
            fn, _ = QFileDialog.getSaveFileName(self, "Record to CSV", "", "*.csv")
            if not fn:
                self.rec_btn.setChecked(False)
                return
            f = open(fn, 'w', newline='')
            self.record_fh = csv.writer(f)
            self.record_fh.writerow(["timestamp","voltage"])
            self.rec_btn.setText("⏹ Stop")
        else:
            self.rec_btn.setText("⏺ Record")
            QMessageBox.information(self, "Record", "Saved.")
            self.record_fh = None

    def take_snapshot(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Snapshot", "", "*.png")
        if not fn:
            return
        if not fn.lower().endswith('.png'):
            fn += '.png'
        exporter = ImageExporter(self.plot.getPlotItem())
        exporter.export(fn)
        QMessageBox.information(self, "Snapshot", f"Saved: {fn}")

    def perform_fft(self):
        if len(self.buffer_y) < 2:
            QMessageBox.warning(self, "FFT", "Not enough data")
            return
        Y = abs(pg.np.fft.rfft(self.buffer_y))
        X = pg.np.fft.rfftfreq(len(self.buffer_y), d=(self.buffer_t[1]-self.buffer_t[0])/1000)
        win = pg.plot(X, Y, title="FFT Spectrum")
        win.setLabel('bottom','Freq',units='Hz')
        win.setLabel('left','Amp')

    def perform_filter(self):
        if len(self.buffer_y) < 10:
            QMessageBox.warning(self, "Filter", "Not enough data")
            return
        b, a = butter(4, [1/50, 50/500], btype='band')
        y2 = filtfilt(b, a, self.buffer_y)
        self.curve.setData(self.buffer_t, y2)

    def open_signal(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open CSV", "", "*.csv")
        if not fn:
            return
        t, y = [], []
        with open(fn) as f:
            r = csv.reader(f)
            next(r)
            for row in r:
                t.append(float(row[0]))
                y.append(float(row[1]))
        self.buffer_t, self.buffer_y = t, y
        self.curve.setData(t, y)

    def show_about(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("About")
        dlg.setText("EPTScope v2.0\nÉcole Polytechnique de Tunisie")
        apply_dark_theme(dlg)
        dlg.exec_()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = EPTScope()
    win.show()
    sys.exit(app.exec_())
