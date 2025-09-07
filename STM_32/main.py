import sys
from PyQt5.QtWidgets import QInputDialog , QMessageBox, QFileDialog, QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QComboBox
import serial
import threading
import pyqtgraph as pg
import serial.tools.list_ports  # Add this import for port detection
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QTimer, QPointF
import os
from pyqtgraph.exporters import ImageExporter
import numpy as np
from scipy.fftpack import fft
from scipy.signal import butter, filtfilt

from scipy.signal import butter, lfilter
from datetime import datetime
import re
# Get the directory path of the current script
dir_path = os.path.dirname(os.path.realpath(__file__))


class OscilloscopeUI(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

        # Initialize serial connection and data storage
        self.ser = None
        self.data = []
        self.timestamps = []
        self.is_running = False
        self.data_lock = threading.Lock()  # Lock for thread-safe data access
        # Initialize timer for plot updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)

        # Set up port refresh timer
        self.port_timer = QTimer()
        self.port_timer.timeout.connect(self.refresh_ports)
        self.port_timer.start(3000)
    def initUI(self):
        self.setWindowTitle("EPT'Scope")
        self.setGeometry(100, 100, 1200, 600)

        # Set application icon
        self.setWindowIcon(QIcon(os.path.join(dir_path, "icon", "app_icon.png")))
        controls_layout = QVBoxLayout()
        # COM Port and Baud Rate Selection with refresh button
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("COM N°:"))
        self.com_select = QComboBox()
        port_layout.addWidget(self.com_select)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "refresh_icon.png")))
        self.refresh_btn.setFixedWidth(30)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_layout.addWidget(self.refresh_btn)
        controls_layout.addLayout(port_layout)

        # Now populate the ports initially
        self.refresh_ports()
        # Apply styles to the application
        self.setStyleSheet("""
    QWidget {
        background-color: #2B2B2B;  /* Dark background */
        color: #FFFFFF;            /* Light text */
        font-family: "Segoe UI";
        font-size: 14px;
    }
    QPushButton {
        background-color: #3C3F41;  /* Slightly lighter dark */
        color: #FFFFFF;             /* White text */
        border: 1px solid #5C5C5C;  /* Medium gray border */
        border-radius: 5px;
        padding: 8px;
        min-width: 80px;
    }
    QPushButton:hover {
        background-color: #505355;  /* Hover darker gray */
        border: 1px solid #6C6C6C;  /* Darker border on hover */
    }
    QPushButton:pressed {
        background-color: #6C6C6C;  /* Pressed state */
    }
    QComboBox {
        background-color: #3C3F41;  /* Dark background */
        color: #FFFFFF;             /* Light text */
        border: 1px solid #5C5C5C;
        border-radius: 5px;
        padding: 5px;
    }
    QComboBox:hover {
        background-color: #505355;
        border: 1px solid #6C6C6C;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid #5C5C5C;
    }
    QLabel {
        color: #FFFFFF;  /* White text */
    }
    QPlotWidget {
        background-color: #2B2B2B;  /* Match window background */
    }
    QMenuBar {
        background-color: #3C3F41;
        color: #FFFFFF;
    }
    QMenuBar::item {
        background-color: transparent;
        padding: 5px 10px;
    }
    QMenuBar::item:selected {
        background-color: #505355;
    }
    QMenu {
        background-color: #3C3F41;
        color: #FFFFFF;
        border: 1px solid #5C5C5C;
    }
    QMenu::item:selected {
        background-color: #505355;
    }
    QScrollBar:vertical {
        background-color: #2B2B2B;
        width: 12px;
        margin: 0px 0px 0px 0px;
    }
    QScrollBar::handle:vertical {
        background-color: #5C5C5C;
        min-height: 20px;
        border-radius: 6px;
    }
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        background: none;
    }
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {
        background: none;
    }
""")


        # Main Layout
        main_layout = QHBoxLayout()

        # Left Panel - Waveform Display
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#000')  # Black background
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)  # Add transparency to grid lines
        self.plot_widget.setLabel('left', 'Voltage', units='V')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_curve = self.plot_widget.plot(pen={'color': 'r', 'width': 4})  # Thicker line for better visibility

        # Enable hover events on the plot
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.scene().sigMouseMoved.connect(self.mouse_moved)

        # Add a label to display hovered point coordinates
        self.hover_label = QLabel("Hover over the curve to see data points")
        self.hover_label.setAlignment(Qt.AlignCenter)

        # Add cursors for measurements
        self.add_cursors()

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.plot_widget)
        left_layout.addWidget(self.hover_label)

        # Right Panel - Controls
        controls_layout = QVBoxLayout()

        # COM Port and Baud Rate Selection
        controls_layout.addWidget(QLabel("COM N°:"))
        self.com_select = QComboBox()

        controls_layout.addWidget(self.com_select)

        controls_layout.addWidget(QLabel("Baud Rate:"))
        self.baud_select = QComboBox()
        self.baud_select.addItems(["115200", "9600", "250000"])  # Example baud rates
        controls_layout.addWidget(self.baud_select)

        # Start and Pause Buttons
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "start_icon.png")))
        self.pause_btn = QPushButton("Pause Signal")
        self.pause_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "pause_icon.png")))
        controls_layout.addWidget(self.start_btn)
        controls_layout.addWidget(self.pause_btn)

        # Zoom Buttons (Horizontal Layout)
        zoom_layout = QHBoxLayout()
        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "zoom_out.png")))
        self.zoom_out_btn.setFixedWidth(100)  # Set fixed width for the zoom out button
        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "zoom_in.png")))
        self.zoom_in_btn.setFixedWidth(100)  # Set fixed width for the zoom in button
        zoom_layout.addWidget(self.zoom_out_btn)
        zoom_layout.addWidget(self.zoom_in_btn)
        controls_layout.addLayout(zoom_layout)

        # Additional Buttons
        self.fft_btn = QPushButton("FFT")
        self.fft_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "fft_icon.png")))
        self.filter_btn = QPushButton("Filtering")
        self.filter_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "filter_icon.png")))
        self.export_btn = QPushButton("Export")
        self.export_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "export_icon.png")))
        self.open_btn = QPushButton("Open Signal")
        self.open_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "open_icon.png")))
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setIcon(QIcon(os.path.join(dir_path, "icon", "clear_icon.png")))  # Add an icon if available
        controls_layout.addWidget(self.clear_btn)

        # Connect the Clear button to its function
        self.clear_btn.clicked.connect(self.clear_screen)
        controls_layout.addWidget(self.fft_btn)
        controls_layout.addWidget(self.filter_btn)
        controls_layout.addWidget(self.export_btn)
        controls_layout.addWidget(self.open_btn)

        # Add stretch to push buttons to the top
        controls_layout.addStretch()

        # Wrap Everything
        main_layout.addLayout(left_layout)
        main_layout.addLayout(controls_layout)

        self.setLayout(main_layout)

        # Connect buttons to their respective functions
        self.start_btn.clicked.connect(self.start_signal)
        self.pause_btn.clicked.connect(self.pause_signal)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.export_btn.clicked.connect(self.export_data)
        self.open_btn.clicked.connect(self.open_signal)
        self.fft_btn.clicked.connect(self.compute_fft)  # Connect FFT button
        self.filter_btn.clicked.connect(self.apply_filter)



    def refresh_ports(self):
            """Scan for available serial ports and update the dropdown menu."""
            # Remember the currently selected port if there is one
            current_port = self.com_select.currentText() if self.com_select.count() > 0 else ""

            # Clear the current list of ports
            self.com_select.clear()

            # Get list of available serial ports
            available_ports = [port.device for port in serial.tools.list_ports.comports()]

            if available_ports:
                # Add available ports to the dropdown
                self.com_select.addItems(available_ports)

                # If the previously selected port is still available, select it again
                if current_port in available_ports:
                    self.com_select.setCurrentText(current_port)

                # Update the tooltip to show port descriptions
                port_descriptions = {port.device: f"{port.device}: {port.description}"
                                     for port in serial.tools.list_ports.comports()}

                for i in range(self.com_select.count()):
                    port = self.com_select.itemText(i)
                    if port in port_descriptions:
                        self.com_select.setItemData(i, port_descriptions[port], Qt.ToolTipRole)
            else:
                # If no ports are available, add a placeholder item
                self.com_select.addItem("No ports available")
                self.com_select.setEnabled(False)


    def high_pass_filter(self, data, cutoff, fs, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='high', analog=False)
        return signal.filtfilt(b, a, data)

    def band_pass_filter(self, data, lowcut, highcut, fs, order=5):
        nyq = 0.5 * fs
        low = lowcut / nyq
        high = highcut / nyq
        b, a = signal.butter(order, [low, high], btype='band')
        return signal.filtfilt(b, a, data)
    def low_pass_filter(self, data, cutoff_freq, sampling_rate, order=5):
        """Apply a low-pass filter to the signal."""
        nyquist_freq = 0.5 * sampling_rate
        normal_cutoff = cutoff_freq / nyquist_freq
        b, a = butter(order, normal_cutoff, btype='low', analog=False)
        return lfilter(b, a, data)

    def apply_filter(self):
        if not self.data:
            QMessageBox.warning(self, "No Signal", "There is no signal to filter.")
            return

        with self.data_lock:
            signal_data = np.array(self.data)
            time_data = np.array(self.timestamps)

        # Estimate sampling rate
        if len(time_data) >= 2:
            dt = np.mean(np.diff(time_data))
            sampling_rate = 1.0 / dt
        else:
            sampling_rate = 1000  # Fallback

        print(f"Sampling Rate: {sampling_rate:.2f} Hz")

        # Choose a reasonable cutoff (e.g., 10% of Nyquist)
        cutoff_freq = 0.1 * (0.5 * sampling_rate)

        filtered_data = self.low_pass_filter(signal_data, cutoff_freq, sampling_rate, order=4)

        with self.data_lock:
            self.data = filtered_data.tolist()

        self.update_plot()

    def moving_average(self, data, window_size=5):
        """Apply a moving average filter to the signal."""
        return np.convolve(data, np.ones(window_size) / window_size, mode='valid')


    def clear_screen(self):
        """Clear the plot and reset data."""
        # Ask for confirmation before clearing
        reply = QMessageBox.question(
            self,
            "Clear Screen",
            "Are you sure you want to clear the screen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # Reset data and timestamps
            with self.data_lock:
                self.data = []
                self.timestamps = []

            # Clear the plot
            self.plot_widget.clear()
            self.plot_curve = self.plot_widget.plot(pen='r', width=4)  # Reinitialize the plot curve

            # Reset cursors (optional)
            self.v_cursor.setPos(0)
            self.h_cursor.setPos(0)

            print("Screen cleared.")

    def start_signal(self):
        # Get COM port and baud rate
        com_port = self.com_select.currentText()
        # Check if a valid port is selected
        if com_port == "No ports available":
            QMessageBox.warning(self, "No Port Available",
                                "No COM port is available. Please connect a device and refresh ports.")
            return
        baud_rate = int(self.baud_select.currentText())

        # Open serial connection
        try:
            self.ser = serial.Serial(com_port, baud_rate, timeout=1)
            self.is_running = True
            self.data = []  # Reset data buffer
            self.timestamps = []  # Reset timestamps
            self.timer.start(50)  # Update graph every 50ms

            # Start a new thread to continuously read from the serial port
            threading.Thread(target=self.read_data, daemon=True).start()
        except serial.SerialException as e:
            print(f"Failed to open serial port: {e}")

    def pause_signal(self):
        self.is_running = False
        self.timer.stop()

        if self.ser and self.ser.isOpen():
            self.ser.close()
        # Update UI to show connection is inactive
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.com_select.setEnabled(True)  # Re-enable port selection
        self.baud_select.setEnabled(True)

    def read_data(self):
        max_data_points = 1000
        start_time = datetime.now()
        vref = 3.3
        max_adc_value = 4095  # 12-bit ADC resolution

        while self.is_running:
            if self.ser and self.ser.isOpen():
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    numbers = list(map(int, re.findall(r"\d+", line)))  # keep only positive integers

                    if numbers:
                        adc_value = numbers[-1]  # Get the last number (assumed to be ADC)
                        voltage = (adc_value / max_adc_value) * vref -0.6  # Convert to real voltage
                        print(voltage)
                        current_time = datetime.now()
                        timestamp = (current_time - start_time).total_seconds()

                        with self.data_lock:
                            self.timestamps.append(timestamp)
                            self.data.append(voltage)
                            if len(self.data) > max_data_points:
                                self.timestamps.pop(0)
                                self.data.pop(0)
                except ValueError:
                    print("Invalid data received from serial port.")
                except serial.SerialException as e:
                    print(f"Serial port error: {e}")
                    self.is_running = False
                    self.timer.stop()
                    if self.ser and self.ser.isOpen():
                        self.ser.close()


    def update_plot(self):
        with self.data_lock:
            if self.data and self.timestamps:
                # Ensure both arrays are aligned
                min_length = min(len(self.data), len(self.timestamps))
                trimmed_data = self.data[:min_length]
                trimmed_timestamps = self.timestamps[:min_length]

                # Smooth the signal
                smoothed_data = self.moving_average(trimmed_data, window_size=5)

                # Plot using the same length for timestamps
                self.plot_curve.setData(trimmed_timestamps[:len(smoothed_data)], smoothed_data)

                # Auto-scale both axes
                self.auto_scale_y_axis(smoothed_data)
                self.auto_scale_x_axis(trimmed_timestamps[:len(smoothed_data)])

    def auto_scale_x_axis(self, timestamps, window_size=5):
        """Auto-scroll the x-axis to follow the incoming data."""
        if not timestamps:
            return

        latest_time = timestamps[-1]

        if len(timestamps) == 1:
            # Only one timestamp, center the window around it
            self.plot_widget.setXRange(latest_time - window_size / 2, latest_time + window_size / 2)
        else:
            # Scroll the window to always show the latest 'window_size' seconds/units
            start_time = max(timestamps[0], latest_time - window_size)
            self.plot_widget.setXRange(start_time, latest_time)

# 
    def auto_scale_y_axis(self, data):
        """Auto-scale the y-axis based on the signal's min and max values."""
        if len(data) > 0:
            min_val = min(data)
            max_val = max(data)
            margin = 0.1 * (max_val - min_val)  # Add 10% margin
            self.plot_widget.setYRange(min_val - margin, max_val + margin)

    def moving_average(self, data, window_size=5):
        """Apply a moving average filter to smooth the signal."""
        return np.convolve(data, np.ones(window_size) / window_size, mode='valid')

    def add_cursors(self):
        """Add vertical and horizontal cursors for measurements."""
        # Vertical cursor
        self.v_cursor = pg.InfiniteLine(angle=90, movable=True, pen='g')
        self.plot_widget.addItem(self.v_cursor)

        # Horizontal cursor
        self.h_cursor = pg.InfiniteLine(angle=0, movable=True, pen='b')
        self.plot_widget.addItem(self.h_cursor)

        # Display cursor positions
        self.v_cursor.sigPositionChanged.connect(self.update_cursor_positions)
        self.h_cursor.sigPositionChanged.connect(self.update_cursor_positions)

    def update_cursor_positions(self):
        """Update the displayed cursor positions."""
        v_pos = self.v_cursor.pos().x()
        h_pos = self.h_cursor.pos().y()
        self.plot_widget.setTitle(f"Vertical Cursor: {v_pos:.3f} s, Horizontal Cursor: {h_pos:.3f} V")

    def compute_fft(self):
        """Compute and display the FFT of the signal."""
        if len(self.data) > 0:
            # Compute FFT
            N = len(self.data)
            T = self.timestamps[1] - self.timestamps[0]  # Sampling interval
            yf = fft(self.data)
            xf = np.linspace(0.0, 1.0 / (2.0 * T), N // 2)

            # Plot FFT
            self.plot_widget.clear()
            self.plot_widget.plot(xf, 2.0 / N * np.abs(yf[:N // 2]), pen='r')
            self.plot_widget.setLabel('left', 'Amplitude')
            self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')

    def export_data(self):
        # Open a file dialog to select the save location and filename
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Data", dir_path,
                                                   "Text Files (*.txt);;PNG Files (*.png);;All Files (*)", options=options)

        if file_path:
            if file_path.endswith(".txt"):
                # Save signal data to a text file (timestamp and value)
                with open(file_path, "w") as file:
                    with self.data_lock:  # Acquire lock before accessing data
                        for timestamp, voltage in zip(self.timestamps, self.data):
                            file.write(f"{timestamp} {voltage}\n")
                print(f"Signal data exported as {file_path}")
            elif file_path.endswith(".png"):
                # Save the graph as an image
                exporter = ImageExporter(self.plot_widget.plotItem)
                exporter.parameters()['width'] = 3000  # Higher width in pixels
                exporter.parameters()['height'] = 2000  # Higher height in pixels
                exporter.export(file_path)
                print(f"Graph exported as {file_path}")
            else:
                print("Unsupported file format. Please use .txt or .png.")

    def open_signal(self):
        # Open a file dialog to select a .txt file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Signal Data", dir_path,
                                                  "Text Files (*.txt);;All Files (*)", options=options)

        if file_path and file_path.endswith(".txt"):
            try:
                with open(file_path, "r") as file:
                    # Read the signal data from the file
                    timestamps = []
                    data = []
                    for line in file.readlines():
                        parts = line.strip().split()
                        if len(parts) == 2:
                            timestamps.append(float(parts[0]))  # First column: timestamp
                            data.append(float(parts[1]))  # Second column: value

                # Plot the signal data
                with self.data_lock:  # Acquire lock before modifying data
                    self.timestamps = timestamps  # Replace current timestamps
                    self.data = data  # Replace current data
                self.plot_curve.setData(self.timestamps, self.data)  # Update the plot
                self.auto_scale_y_axis(data)  # Auto-scale the y-axis
                print(f"Signal data loaded from {file_path}")
            except Exception as e:
                print(f"Error loading signal data: {e}")
        else:
            print("Unsupported file format. Please select a .txt file.")

    def zoom_in(self):
        self.plot_widget.getViewBox().scaleBy((0.9, 0.9))  # Zoom in by 10%

    def zoom_out(self):
        self.plot_widget.getViewBox().scaleBy((1.1, 1.1))  # Zoom out by 10%

    def mouse_moved(self, pos):
        """Handle mouse movement over the plot."""
        if len(self.data) == 0 or len(self.timestamps) == 0:
            return

        # Convert mouse position to plot coordinates
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        x_mouse = mouse_point.x()
        y_mouse = mouse_point.y()

        # Find the nearest data point
        nearest_index = self.find_nearest_point(x_mouse, y_mouse)
        if nearest_index is not None:
            x_nearest = self.timestamps[nearest_index]
            y_nearest = self.data[nearest_index]
            self.hover_label.setText(f"Time: {x_nearest:.3f} s, Voltage: {y_nearest:.3f} V")

    def find_nearest_point(self, x_mouse, y_mouse):
        """Find the index of the nearest data point to the mouse cursor."""
        if len(self.timestamps) == 0 or len(self.data) == 0:
            return None

        # Calculate the distance between the mouse position and each data point
        distances = np.sqrt((np.array(self.timestamps) - x_mouse) ** 2 + (np.array(self.data) - y_mouse) ** 2)
        nearest_index = np.argmin(distances)

        # Check if the nearest point is within a reasonable distance
        if distances[nearest_index] < 0.1:  # Adjust threshold as needed
            return nearest_index
        return None

    def closeEvent(self, event):
        # Ensure the serial port is closed when the application exits
        self.is_running = False
        if self.ser and self.ser.isOpen():
            self.ser.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    oscilloscope = OscilloscopeUI()
    oscilloscope.show()
    sys.exit(app.exec_())