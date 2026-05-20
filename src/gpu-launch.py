#!/usr/bin/env python3
"""
GPU Launch - Right-click context menu launcher for KDE Dolphin
Select which GPU to launch an application on.
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
"""

import sys
import os
import subprocess
import re
from pathlib import Path


def detect_gpus():
    """Detect all GPUs via /sys/class/drm and lspci"""
    gpus = []
    drm_path = Path("/sys/class/drm")

    for card in sorted(drm_path.glob("card[0-9]*")):
        if "-" in card.name:
            continue

        card_id = card.name
        device_path = card / "device"
        if not device_path.exists():
            continue

        try:
            lspci_out = subprocess.run(
                ["lspci", "-v", "-s", (device_path / "uevent").read_text().split("\n")[0].split("=")[1] if (device_path / "uevent").exists() else ""],
                capture_output=True, text=True, timeout=5
            )
        except:
            lspci_out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)

        vendor_id_path = device_path / "vendor"
        device_id_path = device_path / "device"

        vendor = "Unknown"
        name = "Unknown GPU"

        if vendor_id_path.exists():
            vid = vendor_id_path.read_text().strip()
            if vid == "0x1002":
                vendor = "AMD"
            elif vid == "0x8086":
                vendor = "Intel"
            elif vid == "0x10de":
                vendor = "NVIDIA"

        try:
            lspci_all = subprocess.run(
                ["lspci", "-nn"],
                capture_output=True, text=True, timeout=5
            )
            for line in lspci_all.stdout.split("\n"):
                if "VGA" in line or "3D controller" in line or "Display controller" in line:
                    if vendor == "AMD" and "1002" in line:
                        match = re.search(r"\[(.*?)\]", line)
                        if match:
                            name = match.group(1)
                            break
                    elif vendor == "Intel" and "8086" in line:
                        match = re.search(r"\[(.*?)\]", line)
                        if match:
                            name = match.group(1)
                            break
                    elif vendor == "NVIDIA" and "10de" in line:
                        match = re.search(r"\[(.*?)\]", line)
                        if match:
                            name = match.group(1)
                            break
        except:
            pass

        gpus.append({
            "card_id": card_id,
            "vendor": vendor,
            "name": name,
            "display_name": f"{name} ({card_id})",
        })

    return gpus


def get_vram_info(card_id):
    """Get VRAM usage for a GPU"""
    try:
        mem_info_path = Path(f"/sys/class/drm/{card_id}/device/mem_info_vram_total")
        used_path = Path(f"/sys/class/drm/{card_id}/device/mem_info_vram_used")

        if mem_info_path.exists() and used_path.exists():
            total = int(mem_info_path.read_text().strip())
            used = int(used_path.read_text().strip())
            return f"{used // (1024*1024)} / {total // (1024*1024)} MB"
    except:
        pass
    return "N/A"


def parse_desktop_file(filepath):
    """Parse a .desktop file and return the Exec command"""
    exec_cmd = None
    try:
        with open(filepath, "r") as f:
            in_desktop_entry = False
            for line in f:
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_desktop_entry = True
                    continue
                elif line.startswith("["):
                    in_desktop_entry = False
                    continue

                if in_desktop_entry and line.startswith("Exec="):
                    exec_cmd = line[5:]
                    break
    except:
        pass
    return exec_cmd


def show_gpu_dialog(gpus):
    """Show kdialog menu to select GPU"""
    if not gpus:
        subprocess.run(["kdialog", "--error", "No GPUs detected."])
        return None

    if len(gpus) == 1:
        subprocess.run(["kdialog", "--sorry", f"Only one GPU found:\n{gpus[0]['display_name']}"])
        return None

    menu_items = []
    for i, gpu in enumerate(gpus):
        vram = get_vram_info(gpu["card_id"])
        menu_items.append(str(i))
        menu_items.append(f"{gpu['display_name']} (VRAM: {vram})")

    result = subprocess.run(
        ["kdialog", "--menu", "Select GPU to launch on:", "--title", "GPU Launch"] + menu_items,
        capture_output=True, text=True
    )

    if result.returncode != 0:
        return None

    try:
        idx = int(result.stdout.strip())
        return gpus[idx]
    except:
        return None


def launch_on_gpu(gpu, exec_cmd, cwd=None):
    """Launch application with GPU environment variables"""
    env = os.environ.copy()

    if gpu["vendor"] in ["AMD", "Intel"]:
        env["DRI_PRIME"] = "0" if gpu["card_id"] == "card0" else "1"

        if gpu["vendor"] == "AMD":
            amd_icd_paths = []
            for icd in [
                "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/radeon_icd.i686.json",
                "/usr/share/vulkan/icd.d/amd_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/amd_icd.i686.json",
            ]:
                if Path(icd).exists():
                    amd_icd_paths.append(icd)
            if amd_icd_paths:
                env["VK_ICD_FILENAMES"] = ":".join(amd_icd_paths)

        elif gpu["vendor"] == "Intel":
            intel_icd_paths = []
            for icd in [
                "/usr/share/vulkan/icd.d/intel_icd.x86_64.json",
                "/usr/share/vulkan/icd.d/intel_icd.i686.json",
            ]:
                if Path(icd).exists():
                    intel_icd_paths.append(icd)
            if intel_icd_paths:
                env["VK_ICD_FILENAMES"] = ":".join(intel_icd_paths)

    elif gpu["vendor"] == "NVIDIA":
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"

    app_name = exec_cmd.split()[0]
    subprocess.run(
        ["kdialog", "--passivepopup", f"Launching {app_name} on {gpu['display_name']}...", "3", "--title", "GPU Launch"],
    )

    subprocess.Popen(
        exec_cmd,
        shell=True,
        env=env,
        cwd=cwd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    filepath = sys.argv[1]

    if not Path(filepath).exists():
        subprocess.run(["kdialog", "--error", f"File not found:\n{filepath}"])
        sys.exit(1)

    exec_cmd = None
    cwd = None

    if filepath.endswith(".desktop"):
        exec_cmd = parse_desktop_file(filepath)
        if not exec_cmd:
            subprocess.run(["kdialog", "--error", "Could not parse .desktop file."])
            sys.exit(1)
        try:
            cwd = str(Path(filepath).parent)
        except:
            pass
    else:
        exec_cmd = filepath
        try:
            cwd = str(Path(filepath).parent)
        except:
            pass

    gpus = detect_gpus()
    selected_gpu = show_gpu_dialog(gpus)

    if selected_gpu:
        launch_on_gpu(selected_gpu, exec_cmd, cwd)


if __name__ == "__main__":
    main()
