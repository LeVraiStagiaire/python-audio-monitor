# vinyl_monitor_debug.py
import sys, math, queue
import numpy as np
import sounddevice as sd
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QSlider, QComboBox, QHBoxLayout, QPushButton,
    QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtWidgets import QSizePolicy

BLOCKSIZE = 1024

# --- VU-mètre stéréo (idem que toi, avec lissage) ---
class StereoVuMeter(QWidget):
    def __init__(self):
        super().__init__()
        self.level_l = 0.0
        self.level_r = 0.0
        self.setMinimumSize(250, 150)

    @pyqtSlot(float, float)
    def setLevels(self, l, r):
        self.level_l = 0.7*self.level_l + 0.3*max(0.0, min(l, 1.0))
        self.level_r = 0.7*self.level_r + 0.3*max(0.0, min(r, 1.0))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = min(w//4, h//2) - 20
        center_y = h // 2
        center_l = w//4, center_y
        center_r = 3*w//4, center_y

        for center in (center_l, center_r):
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawArc(center[0]-radius, center[1]-radius,
                            2*radius, 2*radius, 45*16, 90*16)

            # colored arc segments on the right: red (last 2 ticks), orange (next tick)
            seg_step = 9  # degrees between ticks
            red_start = 45
            orange_start = red_start + seg_step
            painter.setPen(QPen(QColor("red"), 2))
            painter.drawArc(center[0]-radius, center[1]-radius,
                            2*radius, 2*radius, int(red_start*16), int(seg_step*16))
            painter.setPen(QPen(QColor("orange"), 2))
            painter.drawArc(center[0]-radius, center[1]-radius,
                            2*radius, 2*radius, int(orange_start*16), int(seg_step*16))

            for i in range(0, 11):
                angle = 135- i*9
                rad = math.radians(angle)
                x1 = center[0] + (radius-10)*math.cos(rad)
                y1 = center[1] - (radius-10)*math.sin(rad)
                x2 = center[0] + radius*math.cos(rad)
                y2 = center[1] - radius*math.sin(rad)
                if i >= 9:
                    painter.setPen(QPen(QColor("red"), 2))
                elif i == 8:
                    painter.setPen(QPen(QColor("orange"), 2))
                else:
                    painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            painter.drawText(center[0]-5, center[1]+radius+15, "L" if center==center_l else "R")

        # aiguilles
        angle_l = 135 - self.level_l * 90
        rad_l = math.radians(angle_l)
        x_l = center_l[0] + (radius - 15) * math.cos(rad_l)
        y_l = center_l[1] - (radius - 15) * math.sin(rad_l)
        painter.setPen(QPen(QColor("red"), 3))
        painter.drawLine(center_l[0], center_l[1], int(x_l), int(y_l))

        angle_r = 135 - self.level_r * 90
        rad_r = math.radians(angle_r)
        x_r = center_r[0] + (radius - 15) * math.cos(rad_r)
        y_r = center_r[1] - (radius - 15) * math.sin(rad_r)
        painter.setPen(QPen(QColor("red"), 3))
        painter.drawLine(center_r[0], center_r[1], int(x_r), int(y_r))

# --- App principale (robuste) ---
class MonitorApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Audio monitor app (debug)")
        self.resize(480, 340)

        layout = QVBoxLayout()

        # liste des périphériques (on affiche index: name pour éviter les collisions)
        devs = sd.query_devices()
        input_items = [f"{i}: {d['name']}" for i, d in enumerate(devs) if d['max_input_channels'] > 0]
        output_items = [f"{i}: {d['name']}" for i, d in enumerate(devs) if d['max_output_channels'] > 0]

        self.hl1 = QHBoxLayout()
        self.hl1.addWidget(QLabel("Entrée :"))

        self.input_box = QComboBox();
        self.input_box.addItems(input_items)

        self.hl1.addWidget(self.input_box)
        self.hl1.addWidget(QLabel("Sortie :"))

        self.output_box = QComboBox(); 
        self.output_box.addItems(output_items)

        self.hl1.addWidget(self.output_box)
        layout.addLayout(self.hl1)

        # volume
        self.label = QLabel("Volume: 100%"); self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0,200); self.slider.setValue(100); self.slider.valueChanged.connect(self.change_volume)
        layout.addWidget(self.slider)

        # VU meter
        self.vu = StereoVuMeter()
        # ensure the VU is the only widget allowed to expand vertically:
        self.vu.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.vu, 1)  # give VU the stretch so it takes extra height when available

        # start/stop
        self.btn = QPushButton("▶️ Démarrer"); self.btn.clicked.connect(self.toggle_stream)
        layout.addWidget(self.btn)

        # status
        self.hl2 = QHBoxLayout()
        self.hl2.addWidget(QLabel("Status:"))
        self.status = QLabel("Sélectionne entrée + sortie puis Démarrer")
        self.hl2.addWidget(self.status)
        self.monitor_only = QCheckBox("Monitor only (no output)")
        self.monitor_only.toggled.connect(self.switch_to_monitor_only)
        self.hl2.addWidget(self.monitor_only)
        layout.addLayout(self.hl2)

        self.setLayout(layout)
        self.volume = 1.0

        # Make all non-VU widgets keep a fixed vertical size so the overall height
        # won't change except for the VU meter expanding/shrinking.
        fixed_vertical_widgets = (
            self.input_box, self.output_box, self.slider,
            self.btn, self.label, self.status
        )
        for w in fixed_vertical_widgets:
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # audio handles
        self.full_stream = None
        self.in_stream = None
        self.out_stream = None
        self.queue = None
    
    def switch_to_monitor_only(self, checked):
        if checked:
            self.output_box.setEnabled(False)
            self.volume = 1.0
            self.slider.setValue(100)
            self.label.setText("Volume: 100% (monitor only)")
            self.slider.setEnabled(False)
        else:
            self.output_box.setEnabled(True)
            self.slider.setEnabled(True)
            self.change_volume(self.slider.value())

    def change_volume(self, v):
        self.volume = v / 100.0
        self.label.setText(f"Volume: {v}%")

    def _parse_index(self, text):
        # "12: Device name"
        try:
            return int(text.split(":", 1)[0])
        except Exception:
            return None

    # ---- full-duplex callback (if possible) ----
    def _full_callback(self, indata, outdata, frames, time, status):
        if status:
            print("Status (full):", status)
        # defensive: ensure we have some data
        if indata is None or indata.size == 0:
            outdata.fill(0)
            return

        # ensure 2 channels for RMS calculation
        arr = indata
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        ch = arr.shape[1]
        rms_l = np.sqrt(np.mean(arr[:,0]**2)) if ch >= 1 else 0.0
        rms_r = np.sqrt(np.mean(arr[:,1]**2)) if ch >= 2 else rms_l
        level_l = min(rms_l * 10, 1.0) * self.volume
        level_r = min(rms_r * 10, 1.0) * self.volume
        # QTimer.singleShot(0, lambda l=level_l, r=level_r: self.vu.setLevels(l, r))
        QMetaObject.invokeMethod(self.vu, "setLevels", Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(float, level_l), Q_ARG(float, level_r))

        # prepare output channels
        out_ch = outdata.shape[1] if outdata.ndim > 1 else 1
        if arr.shape[1] == 1 and out_ch >= 2:
            outdata[:] = np.repeat(arr, out_ch, axis=1) * self.volume
        else:
            # slice or pad channels as needed
            needed = out_ch
            if arr.shape[1] < needed:
                arr2 = np.pad(arr, ((0,0),(0, needed - arr.shape[1])), 'constant')
            else:
                arr2 = arr[:, :needed]
            outdata[:] = arr2 * self.volume

    # ---- fallback: separate input callback ----
    def _in_callback(self, indata, frames, time, status):
        if status:
            print("Status (in):", status)
        if indata is None or indata.size == 0:
            return
        arr = indata
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        ch = arr.shape[1]
        rms_l = np.sqrt(np.mean(arr[:,0]**2)) if ch >= 1 else 0.0
        rms_r = np.sqrt(np.mean(arr[:,1]**2)) if ch >= 2 else rms_l
        level_l = min(rms_l * 10, 1.0)
        level_r = min(rms_r * 10, 1.0)
        QTimer.singleShot(0, lambda l=level_l, r=level_r: self.vu.setLevels(l, r))

        # push block to queue (non-blocking)
        try:
            self.queue.put_nowait(arr.copy())
        except queue.Full:
            pass  # drop if consumer too slow

    # ---- fallback: separate output callback ----
    def _out_callback(self, outdata, frames, time, status):
        if status:
            print("Status (out):", status)
        # default silence
        outdata.fill(0)
        try:
            block = self.queue.get_nowait()
        except queue.Empty:
            return

        # ensure block rows == frames
        if block.shape[0] != frames:
            if block.shape[0] < frames:
                block = np.pad(block, ((0, frames - block.shape[0]), (0,0)), mode='constant')
            else:
                block = block[:frames, :]

        out_ch = outdata.shape[1] if outdata.ndim > 1 else 1
        if block.shape[1] == 1 and out_ch >= 2:
            outdata[:] = np.repeat(block, out_ch, axis=1) * self.volume
        else:
            needed = out_ch
            if block.shape[1] < needed:
                block2 = np.pad(block, ((0,0),(0, needed - block.shape[1])), 'constant')
            else:
                block2 = block[:, :needed]
            outdata[:] = block2 * self.volume

    def toggle_stream(self):
        if self.full_stream or self.in_stream or self.out_stream:
            self.stop_streams()
            self.btn.setText("▶️ Démarrer")
            self.status.setText("Arrêté.")
            self.monitor_only.setEnabled(True)
            return

        # parse devices
        in_text = self.input_box.currentText()
        out_text = self.output_box.currentText()
        in_id = self._parse_index(in_text)
        out_id = self._parse_index(out_text)
        if in_id is None or out_id is None:
            self.status.setText("Erreur: impossible de parser périphériques.")
            return

        try:
            in_info = sd.query_devices(in_id, 'input')
            out_info = sd.query_devices(out_id, 'output')
            in_ch = min(2, in_info['max_input_channels'])
            out_ch = min(2, out_info['max_output_channels'])
            sr = int(in_info['default_samplerate'] or 44100)
            print(f"Selected in={in_id} ({in_info['name']}) ch={in_ch} sr={sr}")
            print(f"Selected out={out_id} ({out_info['name']}) ch={out_ch} sr={int(out_info['default_samplerate'] or sr)}")
        except Exception as e:
            self.status.setText(f"Erreur query_devices: {e}")
            print("query_devices error:", e)
            return

        if self.monitor_only.isChecked():
            print("Monitor only mode: no output stream will be opened.")
            # Input-only callback that only updates VU meters (no queueing / no output)
            def monitor_callback(indata, frames, time, status):
                if status:
                    print("Status (monitor):", status)
                if indata is None or indata.size == 0:
                    return
                arr = indata
                if arr.ndim == 1:
                    arr = arr.reshape(-1, 1)
                ch = arr.shape[1]
                rms_l = np.sqrt(np.mean(arr[:, 0] ** 2)) if ch >= 1 else 0.0
                rms_r = np.sqrt(np.mean(arr[:, 1] ** 2)) if ch >= 2 else rms_l
                level_l = min(rms_l * 10, 1.0)
                level_r = min(rms_r * 10, 1.0)
                QMetaObject.invokeMethod(self.vu, "setLevels", Qt.ConnectionType.QueuedConnection,
                            Q_ARG(float, level_l), Q_ARG(float, level_r))

            try:
                self.in_stream = sd.InputStream(device=in_id, channels=in_ch, samplerate=sr,
                                blocksize=BLOCKSIZE, dtype='float32',
                                callback=monitor_callback)
                self.in_stream.start()
                self.btn.setText("⏹️ Arrêter")
                self.status.setText("Input stream actif (monitor only).")
                self.monitor_only.setEnabled(False)
                print("Input stream started (monitor only)")
                return
            except Exception as e:
                print("Input stream failed:", e)
                self.status.setText(f"Erreur ouverture input stream: {e}")
                self.stop_streams()
                return

        # Try full-duplex stream first
        try:
            print("Trying full-duplex stream...")
            self.full_stream = sd.Stream(
                device=(in_id, out_id),
                samplerate=sr,
                blocksize=BLOCKSIZE,
                dtype='float32',
                channels=(in_ch, out_ch),
                callback=self._full_callback
            )
            self.full_stream.start()
            self.btn.setText("⏹️ Arrêter")
            self.status.setText("Full-duplex stream actif.")
            self.monitor_only.setEnabled(False)
            print("Full-duplex started")
            return
        except Exception as e:
            print("Full-duplex failed:", e)
            # fallback to separate streams
        try:
            print("Falling back to separate input/output streams...")
            self.queue = queue.Queue(maxsize=20)
            self.in_stream = sd.InputStream(device=in_id, channels=in_ch, samplerate=sr,
                                            blocksize=BLOCKSIZE, dtype='float32',
                                            callback=self._in_callback)
            self.out_stream = sd.OutputStream(device=out_id, channels=out_ch, samplerate=sr,
                                            blocksize=BLOCKSIZE, dtype='float32',
                                            callback=self._out_callback)
            self.in_stream.start()
            self.out_stream.start()
            self.btn.setText("⏹️ Arrêter")
            self.status.setText("Streams séparés actifs (fallback).")
            self.monitor_only.setEnabled(False)
            print("Separate streams started")
            return
        except Exception as e:
            print("Fallback streams failed:", e)
            self.status.setText(f"Erreur ouverture streams: {e}")
            # cleanup partial
            self.stop_streams()

    def stop_streams(self):
        for s in (self.full_stream, self.in_stream, self.out_stream):
            if s is not None:
                try:
                    s.stop(); s.close()
                except Exception:
                    pass
        self.full_stream = None
        self.in_stream = None
        self.out_stream = None
        self.queue = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MonitorApp()
    win.show()
    print("PyAudio/SoundDevice devices:")
    for i, d in enumerate(sd.query_devices()):
        print(f"{i}: {d['name']}  in={d['max_input_channels']} out={d['max_output_channels']} sr={d['default_samplerate']}")
    sys.exit(app.exec())
