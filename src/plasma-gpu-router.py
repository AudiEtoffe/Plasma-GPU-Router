#!/usr/bin/env python3
"""
Plasma GPU Router - Route GPU assignment for KDE Plasma desktop
Copyright (C) 2026 Audi Etoffe. All Rights Reserved.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Author: Audi Etoffe
Year: 2026
"""

import sys
import os
import subprocess
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QTextEdit, QComboBox,
    QProgressBar, QMessageBox, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtGui import QFont, QAction


class GPUInfo:
    IGPU_PCI = "0000:6c:00.0"
    DGPU_PCI = "0000:03:00.0"
    
    @staticmethod
    def get_gpu_stats():
        stats = {"igpu": {}, "dgpu": {}}
        
        try:
            result = subprocess.run(
                ["rocm-smi", "--showallinfo", "--json"], 
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                json_str = result.stdout.split("{", 1)
                if len(json_str) > 1:
                    json_str = "{" + json_str[1]
                    data = json.loads(json_str)
                    
                    for card_id, card_data in data.items():
                        if card_id.startswith("card"):
                            pci = card_data.get("PCI Bus", "").lower()
                            is_dgpu = pci == GPUInfo.DGPU_PCI.lower()
                            key = "dgpu" if is_dgpu else "igpu"
                            
                            stats[key] = {
                                "name": card_data.get("Card Series", "Unknown"),
                                "gpu_util": GPUInfo._parse_int(card_data.get("GPU use (%)", 0)),
                                "temp": GPUInfo._parse_float(card_data.get("Temperature (Sensor edge) (C)", 0)),
                                "power": GPUInfo._parse_float(card_data.get("Average Graphics Package Power (W)", 0)),
                                "pci": pci,
                            }
        except Exception as e:
            print(f"rocm-smi error: {e}")
        
        for key, pci in [("dgpu", GPUInfo.DGPU_PCI), ("igpu", GPUInfo.IGPU_PCI)]:
            if not stats[key].get("name"):
                stats[key]["name"] = "Unknown"
                stats[key]["pci"] = pci
            
            try:
                mem = Path(f"/sys/bus/pci/devices/{pci}/mem_info_vram_total")
                if mem.exists():
                    stats[key]["vram_total"] = int(mem.read_text()) / (1024*1024)
            except:
                stats[key]["vram_total"] = 0
                
            try:
                mem = Path(f"/sys/bus/pci/devices/{pci}/mem_info_vram_used")
                if mem.exists():
                    stats[key]["vram_used"] = int(mem.read_text()) / (1024*1024)
            except:
                stats[key]["vram_used"] = 0
        
        return stats
    
    @staticmethod
    def _parse_int(val):
        try:
            return int(float(str(val).replace("%", "").strip()))
        except:
            return 0
    
    @staticmethod
    def _parse_float(val):
        try:
            return float(str(val).replace("%", "").replace("W", "").strip())
        except:
            return 0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Plasma GPU Router")
        self.setMinimumSize(700, 800)
        
        self.info_labels = {}
        
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_stats)
        self.refresh_timer.start(2000)
        
        self.setup_ui()
        self.setup_tray()
        self.refresh_stats()
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # GPU Status Section
        status_group = QGroupBox("GPU Status")
        status_layout = QVBoxLayout()
        
        cards_layout = QHBoxLayout()
        cards_layout.addWidget(self.create_gpu_card("iGPU (Desktop)", "igpu"))
        cards_layout.addWidget(self.create_gpu_card("dGPU (Games/AI)", "dgpu"))
        status_layout.addLayout(cards_layout)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Warning box
        warning_group = QGroupBox("WARNING")
        warning_layout = QVBoxLayout()
        
        warning_text = QTextEdit()
        warning_text.setReadOnly(True)
        warning_text.setMaximumHeight(60)
        warning_text.setStyleSheet("background-color: #fff3cd; color: #856404; border: 2px solid #ffc107;")
        warning_text.setHtml("""
        <p><b>Changing GPU configuration can cause:</b> black screen, display output switching between motherboard and dedicated GPU, or session crash. Make sure you know which GPU your monitor is physically connected to.</p>
        """)
        warning_layout.addWidget(warning_text)
        warning_group.setLayout(warning_layout)
        layout.addWidget(warning_group)
        
        # BIOS/UEFI Settings Info
        bios_group = QGroupBox("BIOS/UEFI Settings (Important)")
        bios_layout = QVBoxLayout()
        
        bios_text = QTextEdit()
        bios_text.setReadOnly(True)
        bios_text.setMaximumHeight(120)
        bios_text.setStyleSheet("background-color: #e8f5e9; color: #1b5e20; border: 2px solid #4caf50;")
        bios_text.setHtml("""
        <p><b>For iGPU desktop configuration to work, your BIOS must be configured correctly:</b></p>
        <ul>
            <li><b>iGPU Multi-Monitor / IGPU Multi-Display:</b> Must be <b>Enabled</b></li>
            <li><b>Primary Display / Initiate Graphic Adapter:</b> Set to <b>iGPU</b> or <b>Auto</b> (NOT PCIe/dGPU)</li>
            <li><b>Above 4G Decoding:</b> Should be <b>Enabled</b></li>
        </ul>
        <p>If these settings are wrong, the system will ignore software GPU assignment.</p>
        """)
        bios_layout.addWidget(bios_text)
        bios_group.setLayout(bios_layout)
        layout.addWidget(bios_group)
        
        # GPU Selection Panel
        selection_group = QGroupBox("GPU Assignment")
        selection_layout = QVBoxLayout()
        
        # Quick presets
        presets_layout = QHBoxLayout()
        presets_layout.addWidget(QLabel("Quick Preset:"))
        
        self.preset_recommended = QPushButton("Recommended (iGPU Desktop + dGPU Display)")
        self.preset_recommended.clicked.connect(lambda: self.apply_preset("hybrid"))
        self.preset_recommended.setStyleSheet("background-color: #27ae60; color: white; padding: 8px;")
        presets_layout.addWidget(self.preset_recommended)
        
        self.preset_igpu_only = QPushButton("iGPU Only (All Desktop on iGPU)")
        self.preset_igpu_only.clicked.connect(lambda: self.apply_preset("igpu"))
        self.preset_igpu_only.setStyleSheet("background-color: #3498db; color: white; padding: 8px;")
        presets_layout.addWidget(self.preset_igpu_only)
        
        self.preset_default = QPushButton("Default (System Choice)")
        self.preset_default.clicked.connect(lambda: self.apply_preset("default"))
        self.preset_default.setStyleSheet("background-color: #95a5a6; color: white; padding: 8px;")
        presets_layout.addWidget(self.preset_default)
        
        selection_layout.addLayout(presets_layout)
        
        # Detailed selection
        detailed_group = QGroupBox("Detailed Configuration")
        detailed_layout = QVBoxLayout()
        
        login_layout = QHBoxLayout()
        login_layout.addWidget(QLabel("Login Screen (SDDM):"))
        self.login_combo = QComboBox()
        self.login_combo.addItem("iGPU (Recommended)", "igpu")
        self.login_combo.addItem("dGPU", "dgpu")
        self.login_combo.currentIndexChanged.connect(self.update_compatibility)
        login_layout.addWidget(self.login_combo)
        detailed_layout.addLayout(login_layout)
        
        render_layout = QHBoxLayout()
        render_layout.addWidget(QLabel("Desktop Rendering:"))
        self.render_combo = QComboBox()
        self.render_combo.addItem("iGPU (Recommended)", "igpu")
        self.render_combo.addItem("dGPU", "dgpu")
        self.render_combo.currentIndexChanged.connect(self.update_compatibility)
        render_layout.addWidget(self.render_combo)
        detailed_layout.addLayout(render_layout)
        
        display_layout = QHBoxLayout()
        display_layout.addWidget(QLabel("Display Output:"))
        self.display_combo = QComboBox()
        self.display_combo.addItem("Same as Rendering", "same")
        self.display_combo.addItem("dGPU (Monitor on dGPU)", "dgpu")
        self.display_combo.addItem("iGPU (Monitor on motherboard)", "igpu")
        self.display_combo.currentIndexChanged.connect(self.update_compatibility)
        display_layout.addWidget(self.display_combo)
        detailed_layout.addLayout(display_layout)
        
        self.compat_status = QLabel("")
        self.compat_status.setFont(QFont("Monospace", 10))
        self.compat_status.setWordWrap(True)
        detailed_layout.addWidget(self.compat_status)
        
        detailed_group.setLayout(detailed_layout)
        selection_layout.addWidget(detailed_group)
        
        # Apply buttons
        apply_layout = QHBoxLayout()
        self.btn_apply_config = QPushButton("Apply Configuration")
        self.btn_apply_config.clicked.connect(self.apply_selection)
        self.btn_apply_config.setStyleSheet("background-color: #27ae60; color: white; padding: 12px; font-size: 14px;")
        apply_layout.addWidget(self.btn_apply_config)
        
        self.btn_revert_config = QPushButton("Revert to Default")
        self.btn_revert_config.clicked.connect(self.revert_config)
        self.btn_revert_config.setStyleSheet("background-color: #e74c3c; color: white; padding: 12px; font-size: 14px;")
        apply_layout.addWidget(self.btn_revert_config)
        
        selection_layout.addLayout(apply_layout)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)
        
        # Current status
        status_cfg_group = QGroupBox("Current Configuration")
        status_cfg_layout = QVBoxLayout()
        self.config_status_label = QLabel("Checking configuration...")
        self.config_status_label.setFont(QFont("Monospace", 10))
        status_cfg_layout.addWidget(self.config_status_label)
        status_cfg_group.setLayout(status_cfg_layout)
        layout.addWidget(status_cfg_group)
        
        # Log output
        log_group = QGroupBox("Output Log")
        log_layout = QVBoxLayout()
        self.config_log = QTextEdit()
        self.config_log.setReadOnly(True)
        self.config_log.setMaximumHeight(60)
        log_layout.addWidget(self.config_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        self.check_current_config()
        self.update_compatibility()
    
    def create_gpu_card(self, title, key):
        group = QGroupBox(title)
        layout = QVBoxLayout()
        
        tooltips = {
            "name": "GPU model name",
            "vram": "Video RAM usage",
            "gpu_util": "GPU utilization percentage",
            "temp": "GPU temperature in Celsius",
            "power": "Power consumption in watts"
        }
        
        for field in ["name", "vram", "gpu_util", "temp", "power"]:
            row = QHBoxLayout()
            label = QLabel(f"{field.replace('_', ' ').title()}:")
            label.setMinimumWidth(80)
            label.setToolTip(tooltips.get(field, ""))
            
            value = QLabel("--")
            value.setToolTip(tooltips.get(field, ""))
            self.info_labels[f"{key}_{field}"] = value
            
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            layout.addLayout(row)
            
            if field == "vram":
                bar = QProgressBar()
                bar.setTextVisible(True)
                self.info_labels[f"{key}_vram_bar"] = bar
                layout.addWidget(bar)
            
            if field == "gpu_util":
                bar = QProgressBar()
                bar.setTextVisible(True)
                self.info_labels[f"{key}_util_bar"] = bar
                layout.addWidget(bar)
        
        group.setLayout(layout)
        return group
    
    def update_compatibility(self):
        render = self.render_combo.currentData()
        display = self.display_combo.currentData()
        
        if render == "igpu" and display == "dgpu":
            self.compat_status.setText("Compatible: PRIME offload - Desktop renders on iGPU, display outputs through dGPU. Recommended.")
            self.compat_status.setStyleSheet("color: #27ae60;")
        elif render == "igpu" and display == "igpu":
            self.compat_status.setText("Compatible: All desktop tasks on iGPU. Use if monitor is on motherboard output.")
            self.compat_status.setStyleSheet("color: #27ae60;")
        elif render == "igpu" and display == "same":
            self.compat_status.setText("Compatible: Desktop renders and displays on iGPU.")
            self.compat_status.setStyleSheet("color: #27ae60;")
        elif render == "dgpu" and display == "dgpu":
            self.compat_status.setText("Compatible: All desktop tasks on dGPU. Uses dGPU VRAM for desktop.")
            self.compat_status.setStyleSheet("color: #f39c12;")
        elif render == "dgpu" and display == "igpu":
            self.compat_status.setText("Compatible but unusual: Reverse PRIME. May have performance overhead.")
            self.compat_status.setStyleSheet("color: #e67e22;")
        elif render == "dgpu" and display == "same":
            self.compat_status.setText("Compatible: Desktop renders and displays on dGPU.")
            self.compat_status.setStyleSheet("color: #f39c12;")
    
    def apply_preset(self, preset):
        if preset == "hybrid":
            self.render_combo.setCurrentText("iGPU (Recommended)")
            self.display_combo.setCurrentText("dGPU (Monitor on dGPU)")
            self.login_combo.setCurrentText("iGPU (Recommended)")
        elif preset == "igpu":
            self.render_combo.setCurrentText("iGPU (Recommended)")
            self.display_combo.setCurrentText("iGPU (Monitor on motherboard)")
            self.login_combo.setCurrentText("iGPU (Recommended)")
        elif preset == "default":
            self.revert_config()
            return
        self.update_compatibility()
    
    def check_current_config(self):
        plasma_igpu = False
        plasma_hybrid = False
        sddm_configured = False
        
        plasma_igpu_file = Path("/etc/profile.d/kwin-igpu.sh")
        plasma_hybrid_file = Path("/etc/profile.d/kwin-hybrid.sh")
        
        if plasma_igpu_file.exists():
            content = plasma_igpu_file.read_text()
            if "KWIN_DRM_DEVICES=/dev/dri/card1" in content and "card0" not in content:
                plasma_igpu = True
        
        if plasma_hybrid_file.exists():
            content = plasma_hybrid_file.read_text()
            if "KWIN_DRM_DEVICES=/dev/dri/card1:/dev/dri/card0" in content:
                plasma_hybrid = True
        
        sddm_override = Path("/etc/systemd/system/sddm.service.d/override.conf")
        if sddm_override.exists():
            content = sddm_override.read_text()
            if "KWIN_DRM_DEVICES=/dev/dri/card1" in content:
                sddm_configured = True
        
        if plasma_hybrid and sddm_configured:
            self.config_status_label.setText("Hybrid Plasma + SDDM configured (render on iGPU, display on dGPU)")
            self.config_status_label.setStyleSheet("color: #27ae60;")
        elif plasma_igpu and sddm_configured:
            self.config_status_label.setText("iGPU-only Plasma + SDDM configured")
            self.config_status_label.setStyleSheet("color: #1abc9c;")
        elif plasma_hybrid:
            self.config_status_label.setText("Hybrid Plasma configured (SDDM not configured)")
            self.config_status_label.setStyleSheet("color: #e67e22;")
        elif plasma_igpu:
            self.config_status_label.setText("iGPU-only Plasma configured (SDDM not configured)")
            self.config_status_label.setStyleSheet("color: #f39c12;")
        elif sddm_configured:
            self.config_status_label.setText("SDDM is configured for iGPU (Plasma not configured)")
            self.config_status_label.setStyleSheet("color: #f39c12;")
        else:
            self.config_status_label.setText("No custom GPU configuration applied (using system defaults)")
            self.config_status_label.setStyleSheet("color: #95a5a6;")
    
    def apply_selection(self):
        login = self.login_combo.currentData()
        render = self.render_combo.currentData()
        display = self.display_combo.currentData()
        
        desc_parts = []
        desc_parts.append("Login on iGPU" if login == "igpu" else "Login on dGPU")
        desc_parts.append("Desktop renders on iGPU" if render == "igpu" else "Desktop renders on dGPU")
        
        if display == "dgpu":
            desc_parts.append("Display outputs through dGPU")
        elif display == "igpu":
            desc_parts.append("Display outputs through iGPU")
        else:
            desc_parts.append(f"Display same as rendering ({render})")
        
        description = ", ".join(desc_parts)
        
        reply = QMessageBox.warning(
            self, "Warning: Display Output May Change",
            f"You are about to apply: <b>{description}</b>\n\n"
            "This may cause:\n"
            "• A black screen after logging out\n"
            "• Your display output to switch between the motherboard (iGPU) and dedicated graphics card (dGPU)\n"
            "• The desktop session to fail to restart\n\n"
            "Make sure you know which GPU your monitor is physically connected to.\n"
            "If you get a black screen, you may need to move your monitor cable or boot from a live USB to revert.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        if render == "igpu" and display == "dgpu":
            plasma_cmd = "kwin-hybrid.sh"
            plasma_content = "export KWIN_DRM_DEVICES=/dev/dri/card1:/dev/dri/card0\nexport WLR_DRM_DEVICES=/dev/dri/card1:/dev/dri/card0"
        elif render == "igpu" and (display == "igpu" or display == "same"):
            plasma_cmd = "kwin-igpu.sh"
            plasma_content = "export KWIN_DRM_DEVICES=/dev/dri/card1\nexport WLR_DRM_DEVICES=/dev/dri/card1"
        else:
            plasma_cmd = None
            plasma_content = ""
        
        sddm_card = "card1" if login == "igpu" else "card0"
        
        cmd_parts = []
        if plasma_cmd:
            cmd_parts.append(f"mkdir -p /etc/profile.d && cat > /etc/profile.d/{plasma_cmd} << 'EOF'\n{plasma_content}\nEOF\nchmod 644 /etc/profile.d/{plasma_cmd}")
            other = "kwin-igpu.sh" if plasma_cmd == "kwin-hybrid.sh" else "kwin-hybrid.sh"
            cmd_parts.append(f"rm -f /etc/profile.d/{other}")
        else:
            cmd_parts.append("rm -f /etc/profile.d/kwin-igpu.sh /etc/profile.d/kwin-hybrid.sh")
        
        if login in ["igpu", "dgpu"]:
            cmd_parts.append(f"mkdir -p /etc/systemd/system/sddm.service.d && cat > /etc/systemd/system/sddm.service.d/override.conf << 'EOF'\n[Service]\nEnvironment=KWIN_DRM_DEVICES=/dev/dri/{sddm_card}\nEnvironment=WLR_DRM_DEVICES=/dev/dri/{sddm_card}\nEOF\nsystemctl daemon-reload")
        
        cmd = "bash -c '" + " && ".join(cmd_parts) + "'"
        
        self.config_log.append(f"\nApplying: {description}")
        self.config_log.append("Authentication dialog will appear...")
        
        process = QProcess(self)
        process.setProgram("pkexec")
        process.setArguments(["bash", "-c", cmd])
        
        output = []
        def read_output():
            data = process.readAllStandardOutput().data().decode()
            if data:
                output.append(data)
                self.config_log.append(data.strip())
        
        def read_error():
            data = process.readAllStandardError().data().decode()
            if data:
                output.append(data)
                self.config_log.append(data.strip())
        
        def finished(exit_code, exit_status):
            if exit_code == 0:
                self.config_log.append("\nSuccess! Configuration applied.")
                self.config_log.append("Please log out and log back in for changes to take effect.")
                QMessageBox.information(
                    self, "Success",
                    f"Configuration applied successfully!\n\n{description}\n\n"
                    "You need to log out and log back in (or reboot) for changes to take effect."
                )
            else:
                error_msg = "".join(output) if output else "Unknown error"
                self.config_log.append(f"\nFailed: {error_msg}")
                if exit_code == 126 or exit_code == 127:
                    QMessageBox.warning(
                        self, "Authentication Failed",
                        "Authentication was cancelled or failed.\n\n"
                        "Please try again and enter your password when prompted."
                    )
                else:
                    QMessageBox.warning(self, "Error", f"Failed to apply configuration:\n{error_msg}")
            self.check_current_config()
        
        process.readyReadStandardOutput.connect(read_output)
        process.readyReadStandardError.connect(read_error)
        process.finished.connect(finished)
        process.start()
    
    def revert_config(self):
        reply = QMessageBox.warning(
            self, "Warning: Reverting Configuration",
            "This will remove all iGPU/dGPU configuration for Plasma and SDDM.\n\n"
            "This may cause:\n"
            "• A black screen after rebooting\n"
            "• Your display output to switch between the motherboard (iGPU) and dedicated graphics card (dGPU)\n"
            "• The desktop session to use a different GPU than expected\n\n"
            "Your system will return to default GPU selection behavior.\n"
            "If you get a black screen, you may need to move your monitor cable.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        cmd = '''bash -c 'rm -f /etc/profile.d/kwin-igpu.sh
rm -f /etc/profile.d/kwin-hybrid.sh
rm -f /etc/systemd/system/sddm.service.d/override.conf
rmdir /etc/systemd/system/sddm.service.d 2>/dev/null || true
systemctl daemon-reload' '''
        
        self.config_log.append("\nReverting configuration...")
        self.config_log.append("Authentication dialog will appear...")
        
        process = QProcess(self)
        process.setProgram("pkexec")
        process.setArguments(["bash", "-c", cmd])
        
        output = []
        def read_output():
            data = process.readAllStandardOutput().data().decode()
            if data:
                output.append(data)
                self.config_log.append(data.strip())
        
        def read_error():
            data = process.readAllStandardError().data().decode()
            if data:
                output.append(data)
                self.config_log.append(data.strip())
        
        def finished(exit_code, exit_status):
            if exit_code == 0:
                self.config_log.append("\nSuccess! Configuration reverted.")
                QMessageBox.information(
                    self, "Success",
                    "Configuration reverted successfully!\n\n"
                    "Your desktop will use default GPU selection after reboot."
                )
            else:
                error_msg = "".join(output) if output else "Unknown error"
                self.config_log.append(f"\nFailed: {error_msg}")
                QMessageBox.warning(self, "Error", f"Failed to revert configuration:\n{error_msg}")
            self.check_current_config()
        
        process.readyReadStandardOutput.connect(read_output)
        process.readyReadStandardError.connect(read_error)
        process.finished.connect(finished)
        process.start()
    
    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip("Plasma GPU Router")
        
        menu = QMenu()
        
        action_status = QAction("Show Plasma GPU Router", self)
        action_status.triggered.connect(self.show)
        menu.addAction(action_status)
        
        menu.addSeparator()
        
        action_quit = QAction("Quit", self)
        action_quit.triggered.connect(QApplication.quit)
        menu.addAction(action_quit)
        
        self.tray.setContextMenu(menu)
        self.tray.show()
    
    def refresh_stats(self):
        stats = GPUInfo.get_gpu_stats()
        
        for key in ["igpu", "dgpu"]:
            data = stats[key]
            
            if self.info_labels.get(f"{key}_name"):
                self.info_labels[f"{key}_name"].setText(data.get("name", "--"))
            
            vram_used = data.get("vram_used", 0)
            vram_total = data.get("vram_total", 1)
            vram_pct = (vram_used / vram_total * 100) if vram_total > 0 else 0
            
            if self.info_labels.get(f"{key}_vram"):
                self.info_labels[f"{key}_vram"].setText(f"{vram_used:.0f} MB / {vram_total:.0f} MB")
            
            if self.info_labels.get(f"{key}_vram_bar"):
                self.info_labels[f"{key}_vram_bar"].setValue(int(vram_pct))
                self.info_labels[f"{key}_vram_bar"].setFormat(f"{vram_pct:.1f}% VRAM")
            
            gpu_util = data.get("gpu_util", 0)
            if self.info_labels.get(f"{key}_gpu_util"):
                self.info_labels[f"{key}_gpu_util"].setText(f"{gpu_util}%")
            
            if self.info_labels.get(f"{key}_util_bar"):
                self.info_labels[f"{key}_util_bar"].setValue(int(gpu_util))
            
            temp = data.get("temp", 0)
            if self.info_labels.get(f"{key}_temp"):
                self.info_labels[f"{key}_temp"].setText(f"{temp}°C")
            
            power = data.get("power", 0)
            if self.info_labels.get(f"{key}_power"):
                self.info_labels[f"{key}_power"].setText(f"{power}W")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Plasma GPU Router")
    app.setDesktopFileName("plasma-gpu-router.desktop")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
