from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout, QGridLayout
from PySide6.QtCore import Qt

class SolarDashboard(QWidget):
    def __init__(self):
        super().__init__()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        # Riga superiore: SFI, A-Index, K-Index
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self.sfi_label = self._create_index_widget("SFI", "—")
        self.a_label = self._create_index_widget("A-Index", "—")
        self.k_label = self._create_index_widget("K-Index", "—")

        top_layout.addWidget(self.sfi_label)
        top_layout.addWidget(self.a_label)
        top_layout.addWidget(self.k_label)
        main_layout.addLayout(top_layout)

        # Riga inferiore: Condizioni bande e geomagnetismo
        self.bands_label = QLabel("Condizioni: caricamento...")
        self.bands_label.setStyleSheet("font-size: 11px; color: #888;")
        self.bands_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.bands_label)

        self.geomag_label = QLabel("")
        self.geomag_label.setStyleSheet("font-size: 11px; color: #888;")
        self.geomag_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.geomag_label)

    def _create_index_widget(self, title, value):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 10px; color: #888;")
        lbl_title.setAlignment(Qt.AlignCenter)
        
        lbl_value = QLabel(value)
        lbl_value.setStyleSheet("font-size: 16px; font-weight: bold;")
        lbl_value.setAlignment(Qt.AlignCenter)
        
        v.addWidget(lbl_title)
        v.addWidget(lbl_value)
        w.value_label = lbl_value
        return w

    def update_data(self, sfi, a_index, k_index, band_conditions=None, geomag=None, noise=None):
        if sfi is not None:
            self.sfi_label.value_label.setText(str(sfi))
            if sfi >= 150: color = "#28a745"
            elif sfi >= 100: color = "#ffc107"
            else: color = "#dc3545"
            self.sfi_label.value_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")
        
        if a_index is not None:
            self.a_label.value_label.setText(str(a_index))
            if a_index <= 7: color = "#28a745"
            elif a_index <= 15: color = "#ffc107"
            else: color = "#dc3545"
            self.a_label.value_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")
        
        if k_index is not None:
            self.k_label.value_label.setText(str(k_index))
            if k_index <= 2: color = "#28a745"
            elif k_index <= 4: color = "#ffc107"
            else: color = "#dc3545"
            self.k_label.value_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")

        if band_conditions:
            day_20 = band_conditions.get("30m-20m Day", "-")
            day_40 = band_conditions.get("80m-40m Day", "-")
            night_20 = band_conditions.get("30m-20m Night", "-")
            night_40 = band_conditions.get("80m-40m Night", "-")
            
            text = f"<b>Giorno:</b> 40m {day_40} / 20m {day_20}<br>"
            text += f"<b>Notte:</b> 40m {night_40} / 20m {night_20}"
            self.bands_label.setText(text)

        if geomag:
            self.geomag_label.setText(f"<b>Geomag:</b> {geomag} | <b>Noise:</b> {noise or 'N/D'}")
