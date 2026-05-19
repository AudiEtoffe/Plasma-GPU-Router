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
import re
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QTextEdit, QComboBox,
    QProgressBar, QMessageBox, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtGui import QFont, QAction


class GPU:
    """Represents a detected GPU"""
    def __init__(self, card_id, card_path, pci_slot):
        self.card_id = card_id  # e.g., "card0"
        self.card_path = card_path  # e.g., "/dev/dri/card0"
        self.pci_slot = pci_slot  # e.g., "0000:03:00.0"
        self.name = "Unknown GPU"
        self.vendor = "Unknown"
        self.driver = "Unknown"
        self.is_boot_vga = False
        self._load_info()
    
    def _load_info(self):
        pci_path = f"/sys/bus/pci/devices/{self.pci_slot}"
        
        # Get vendor and device
        try:
            vendor_id = Path(f"{pci_path}/vendor").read_text().strip()
            device_id = Path(f"{pci_path}/device").read_text().strip()
            self.vendor = self._vendor_name(vendor_id)
        except:
            pass
        
        # Get GPU name from lspci
        try:
            result = subprocess.run(
                ["lspci", "-s", self.pci_slot, "-v"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n'):
                if 'VGA' in line or '3D' in line or 'Display' in line:
                    # Extract name after the colon
                    parts = line.split(':', 2)
                    if len(parts) > 2:
                        self.name = parts[2].strip()
                    break
        except:
            pass
        
        # Get driver
        try:
            driver_link = Path(f"{pci_path}/driver")
            if driver_link.is_symlink():
                self.driver = driver_link.resolve().name
        except:
            pass
        
        # Check if boot VGA
        try:
            boot_vga = Path(f"{pci_path}/boot_vga").read_text().strip()
            self.is_boot_vga = boot_vga == "1"
        except:
            pass
    
    def _vendor_name(self, vendor_id):
        vendors = {
            "0x1002": "AMD",
            "0x8086": "Intel",
            "0x10de": "NVIDIA",
            "0x1022": "AMD",
        }
        return vendors.get(vendor_id, f"Vendor {vendor_id}")
    
    def display_name(self):
        """Human-readable name for UI"""
        boot_tag = " [Boot VGA]" if self.is_boot_vga else ""
        return f"{self.name} ({self.card_id}){boot_tag}"
    
    def drm_device(self):
        return f"/dev/dri/{self.card_id}"


class GPUInfo:
    """Detects and manages GPUs"""
    
    @staticmethod
    def detect_gpus():
        """Detect all available GPUs"""
        gpus = []
        
        # Scan /sys/class/drm for card devices
        drm_path = Path("/sys/class/drm")
        if not drm_path.exists():
            return gpus
        
        for card_dir in sorted(drm_path.iterdir()):
            if not card_dir.name.startswith("card") or "-" in card_dir.name:
                continue
            
            card_id = card_dir.name
            card_path = f"/dev/dri/{card_id}"
            
            # Get PCI slot
            device_link = card_dir / "device"
            if not device_link.is_symlink():
                continue
            
            pci_slot = device_link.resolve().name
            if not pci_slot.startswith("0000:"):
                continue
            
            gpu = GPU(card_id, card_path, pci_slot)
            gpus.append(gpu)
        
        return gpus
    
    @staticmethod
    def get_gpu_stats(gpus):
        """Get stats for all detected GPUs"""
        stats = {}
        
        for gpu in gpus:
            key = gpu.card_id
            stats[key] = {
                "name": gpu.name,
                "card_id": gpu.card_id,
                "vram_total": 0,
                "vram_used": 0,
                "gpu_util": 0,
                "temp": 0,
                "power": 0,
            }
            
            # Get VRAM from sysfs
            pci_path = f"/sys/bus/pci/devices/{gpu.pci_slot}"
            try:
                mem = Path(f"{pci_path}/mem_info_vram_total")
                if mem.exists():
                    stats[key]["vram_total"] = int(mem.read_text()) / (1024*1024)
            except:
                pass
            
            try:
                mem = Path(f"{pci_path}/mem_info_vram_used")
                if mem.exists():
                    stats[key]["vram_used"] = int(mem.read_text()) / (1024*1024)
            except:
                pass
            
            # Try rocm-smi for AMD GPUs
            if gpu.vendor == "AMD":
                try:
                    result = subprocess.run(
                        ["rocm-smi", "--showallinfo", "--json"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        json_str = result.stdout.split("{", 1)
                        if len(json_str) > 1:
                            data = json.loads("{" + json_str[1])
                            for card_id, card_data in data.items():
                                if card_data.get("PCI Bus", "").lower() == gpu.pci_slot.lower():
                                    stats[key]["gpu_util"] = GPUInfo._parse_int(card_data.get("GPU use (%)", 0))
                                    stats[key]["temp"] = GPUInfo._parse_float(card_data.get("Temperature (Sensor edge) (C)", 0))
                                    stats[key]["power"] = GPUInfo._parse_float(card_data.get("Average Graphics Package Power (W)", 0))
                                    break
                except:
                    pass
        
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
        self.gpus = []
        
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
        
        self.gpu_cards_layout = QHBoxLayout()
        status_layout.addLayout(self.gpu_cards_layout)
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
        <p><b>Changing GPU configuration can cause:</b> black screen, display output switching between GPUs, or session crash. Make sure you know which GPU your monitor is physically connected to.</p>
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
        <p><b>For GPU configuration to work, your BIOS must be configured correctly:</b></p>
        <ul>
            <li><b>iGPU Multi-Monitor / IGPU Multi-Display:</b> Must be <b>Enabled</b></li>
            <li><b>Primary Display / Initiate Graphic Adapter:</b> Set to desired GPU or <b>Auto</b></li>
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
        
        # Login screen selection
        login_layout = QHBoxLayout()
        login_layout.addWidget(QLabel("Login Screen (SDDM):"))
        self.login_combo = QComboBox()
        self.login_combo.currentIndexChanged.connect(self.update_compatibility)
        login_layout.addWidget(self.login_combo)
        detailed_layout.addLayout(login_layout)
        
        # Desktop rendering selection
        render_layout = QHBoxLayout()
        render_layout.addWidget(QLabel("Desktop Rendering:"))
        self.render_combo = QComboBox()
        self.render_combo.currentIndexChanged.connect(self.update_compatibility)
        render_layout.addWidget(self.render_combo)
        detailed_layout.addLayout(render_layout)
        
        # Display output selection
        display_layout = QHBoxLayout()
        display_layout.addWidget(QLabel("Display Output:"))
        self.display_combo = QComboBox()
        self.display_combo.addItem("Same as Rendering", "same")
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
    
    def refresh_gpu_list(self):
        """Detect GPUs and update UI"""
        self.gpus = GPUInfo.detect_gpus()
        
        # Update combo boxes with detected GPUs
        for combo in [self.login_combo, self.render_combo]:
            combo.clear()
            for gpu in self.gpus:
                combo.addItem(gpu.display_name(), gpu.card_id)
        
        # Update display combo
        self.display_combo.clear()
        self.display_combo.addItem("Same as Rendering", "same")
        for gpu in self.gpus:
            self.display_combo.addItem(gpu.display_name(), gpu.card_id)
        
        # Update GPU status cards
        self._update_gpu_cards()
        
        # Update presets visibility
        if len(self.gpus) < 2:
            self.preset_recommended.setEnabled(False)
            self.preset_recommended.setToolTip("Requires at least 2 GPUs")
            self.preset_igpu_only.setEnabled(False)
            self.preset_igpu_only.setToolTip("Requires at least 2 GPUs")
        else:
            self.preset_recommended.setEnabled(True)
            self.preset_recommended.setToolTip("")
            self.preset_igpu_only.setEnabled(True)
            self.preset_igpu_only.setToolTip("")
    
    def _update_gpu_cards(self):
        """Create or update GPU status cards"""
        # Clear existing cards
        while self.gpu_cards_layout.count():
            item = self.gpu_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.info_labels = {}
        
        for gpu in self.gpus:
            card = self._create_gpu_card(gpu)
            self.gpu_cards_layout.addWidget(card)
    
    def _create_gpu_card(self, gpu):
        """Create a status card for a GPU"""
        group = QGroupBox(gpu.display_name())
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
            self.info_labels[f"{gpu.card_id}_{field}"] = value
            
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            layout.addLayout(row)
            
            if field == "vram":
                bar = QProgressBar()
                bar.setTextVisible(True)
                self.info_labels[f"{gpu.card_id}_vram_bar"] = bar
                layout.addWidget(bar)
            
            if field == "gpu_util":
                bar = QProgressBar()
                bar.setTextVisible(True)
                self.info_labels[f"{gpu.card_id}_util_bar"] = bar
                layout.addWidget(bar)
        
        group.setLayout(layout)
        return group
    
    def update_compatibility(self):
        render_idx = self.render_combo.currentIndex()
        display_idx = self.display_combo.currentIndex()
        
        render_data = self.render_combo.currentData()
        display_data = self.display_combo.currentData()
        
        render_name = self.render_combo.currentText()
        display_name = self.display_combo.currentText()
        
        if display_data == "same":
            self.compat_status.setText(f"Compatible: Desktop renders and displays on {render_name}.")
            self.compat_status.setStyleSheet("color: #27ae60;")
        else:
            self.compat_status.setText(f"Compatible: Desktop renders on {render_name}, display outputs through {display_name}.")
            self.compat_status.setStyleSheet("color: #27ae60;")
    
    def apply_preset(self, preset):
        if len(self.gpus) < 2:
            return
        
        # Find iGPU (usually Intel or AMD integrated)
        igpu = None
        dgpu = None
        
        for gpu in self.gpus:
            if gpu.vendor in ["Intel"] or (gpu.vendor == "AMD" and "Ryzen" in gpu.name):
                igpu = gpu
            elif gpu.vendor in ["AMD", "NVIDIA"] and "Radeon" in gpu.name or "GeForce" in gpu.name or "RTX" in gpu.name or "RX" in gpu.name:
                dgpu = gpu
        
        # Fallback: first GPU is iGPU, second is dGPU
        if not igpu:
            igpu = self.gpus[0]
        if not dgpu:
            dgpu = self.gpus[1] if len(self.gpus) > 1 else self.gpus[0]
        
        if preset == "hybrid":
            # Set rendering to iGPU
            for i in range(self.render_combo.count()):
                if self.render_combo.itemData(i) == igpu.card_id:
                    self.render_combo.setCurrentIndex(i)
                    break
            
            # Set display to dGPU
            for i in range(self.display_combo.count()):
                if self.display_combo.itemData(i) == dgpu.card_id:
                    self.display_combo.setCurrentIndex(i)
                    break
            
            # Set login to iGPU
            for i in range(self.login_combo.count()):
                if self.login_combo.itemData(i) == igpu.card_id:
                    self.login_combo.setCurrentIndex(i)
                    break
                    
        elif preset == "igpu":
            for i in range(self.render_combo.count()):
                if self.render_combo.itemData(i) == igpu.card_id:
                    self.render_combo.setCurrentIndex(i)
                    break
            
            for i in range(self.display_combo.count()):
                if self.display_combo.itemData(i) == igpu.card_id:
                    self.display_combo.setCurrentIndex(i)
                    break
            
            for i in range(self.login_combo.count()):
                if self.login_combo.itemData(i) == igpu.card_id:
                    self.login_combo.setCurrentIndex(i)
                    break
                    
        elif preset == "default":
            self.revert_config()
            return
        
        self.update_compatibility()
    
    def check_current_config(self):
        # Check for any profile.d configs
        plasma_config = None
        sddm_configured = False
        
        for config_file in Path("/etc/profile.d").glob("kwin-*.sh"):
            content = config_file.read_text()
            if "KWIN_DRM_DEVICES=" in content:
                plasma_config = config_file.name
        
        sddm_override = Path("/etc/systemd/system/sddm.service.d/override.conf")
        if sddm_override.exists():
            content = sddm_override.read_text()
            if "KWIN_DRM_DEVICES=" in content:
                sddm_configured = True
        
        if plasma_config and sddm_configured:
            self.config_status_label.setText(f"Plasma ({plasma_config}) + SDDM configured")
            self.config_status_label.setStyleSheet("color: #27ae60;")
        elif plasma_config:
            self.config_status_label.setText(f"Plasma configured ({plasma_config}), SDDM not configured")
            self.config_status_label.setStyleSheet("color: #f39c12;")
        elif sddm_configured:
            self.config_status_label.setText("SDDM configured, Plasma not configured")
            self.config_status_label.setStyleSheet("color: #f39c12;")
        else:
            self.config_status_label.setText("No custom GPU configuration applied (using system defaults)")
            self.config_status_label.setStyleSheet("color: #95a5a6;")
    
    def apply_selection(self):
        login_card = self.login_combo.currentData()
        render_card = self.render_combo.currentData()
        display_card = self.display_combo.currentData()
        
        login_name = self.login_combo.currentText()
        render_name = self.render_combo.currentText()
        display_name = self.display_combo.currentText() if display_card != "same" else render_name
        
        description = f"Login on {login_name}, Desktop renders on {render_name}, Display outputs through {display_name}"
        
        reply = QMessageBox.warning(
            self, "Warning: Display Output May Change",
            f"You are about to apply: <b>{description}</b>\n\n"
            "This may cause:\n"
            "• A black screen after logging out\n"
            "• Your display output to switch between GPUs\n"
            "• The desktop session to fail to restart\n\n"
            "Make sure you know which GPU your monitor is physically connected to.\n"
            "If you get a black screen, you may need to move your monitor cable or boot from a live USB to revert.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Build device list for KWIN_DRM_DEVICES
        if display_card == "same" or display_card == render_card:
            # Single GPU mode
            device_list = f"/dev/dri/{render_card}"
        else:
            # Multi-GPU mode (render first, display second)
            device_list = f"/dev/dri/{render_card}:/dev/dri/{display_card}"
        
        cmd_parts = []
        
        # Create plasma config
        config_content = f"export KWIN_DRM_DEVICES={device_list}\nexport WLR_DRM_DEVICES={device_list}"
        cmd_parts.append(f"mkdir -p /etc/profile.d && cat > /etc/profile.d/kwin-custom.sh << 'EOF'\n{config_content}\nEOF\nchmod 644 /etc/profile.d/kwin-custom.sh")
        
        # Remove old configs
        cmd_parts.append("rm -f /etc/profile.d/kwin-igpu.sh /etc/profile.d/kwin-hybrid.sh")
        
        # Create SDDM config
        sddm_device = f"/dev/dri/{login_card}"
        cmd_parts.append(f"mkdir -p /etc/systemd/system/sddm.service.d && cat > /etc/systemd/system/sddm.service.d/override.conf << 'EOF'\n[Service]\nEnvironment=KWIN_DRM_DEVICES={sddm_device}\nEnvironment=WLR_DRM_DEVICES={sddm_device}\nEOF\nsystemctl daemon-reload")
        
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
            "This will remove all GPU configuration for Plasma and SDDM.\n\n"
            "This may cause:\n"
            "• A black screen after rebooting\n"
            "• Your display output to switch between GPUs\n"
            "• The desktop session to use a different GPU than expected\n\n"
            "Your system will return to default GPU selection behavior.\n"
            "If you get a black screen, you may need to move your monitor cable.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        cmd = '''bash -c 'rm -f /etc/profile.d/kwin-*.sh
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
        # Detect GPUs first (in case hardware changed)
        self.refresh_gpu_list()
        
        stats = GPUInfo.get_gpu_stats(self.gpus)
        
        for gpu in self.gpus:
            key = gpu.card_id
            data = stats.get(key, {})
            
            if self.info_labels.get(f"{key}_name"):
                self.info_labels[f"{key}_name"].setText(data.get("name", gpu.name))
            
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
