# Plasma GPU Router

Route GPU assignment for KDE Plasma desktop environments.

## Features

- Real-time GPU monitoring (VRAM, utilization, temperature, power)
- Configure which GPU handles desktop rendering, login screen, and display output
- Quick presets for common configurations
- Compatible with AMD dual-GPU setups (iGPU + dGPU)
- System tray integration
- **Dolphin context menu**: Right-click any app to launch it on a specific GPU

## Requirements

- KDE Plasma (Wayland)
- Python 3.10+
- PyQt6
- AMD ROCm (for AMD GPU monitoring)
- Polkit (for applying configuration)
- kdialog (for GPU selection dialog)

## Installation

### Manual Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/plasma-gpu-router.git
   cd plasma-gpu-router
   ```

2. Install dependencies:
   ```bash
   pip install PyQt6
   ```

3. Run the application:
   ```bash
   python src/plasma-gpu-router.py
   ```

### Desktop Integration

Copy the desktop file to your applications directory:
```bash
cp share/applications/plasma-gpu-router.desktop ~/.local/share/applications/
```

### Dolphin Context Menu (GPU Launch)

Install the right-click service menu:
```bash
cp src/gpu-launch.py ~/.local/bin/gpu-launch.py
chmod +x ~/.local/bin/gpu-launch.py
mkdir -p ~/.local/share/kservices5/ServiceMenus
cp share/kservices5/ServiceMenus/gpu-launch.desktop ~/.local/share/kservices5/ServiceMenus/
```

Restart Dolphin or log out/in for the context menu to appear.

## Usage

### Quick Presets

- **Recommended**: iGPU for desktop rendering, dGPU for display output (PRIME offload)
- **iGPU Only**: All desktop tasks on iGPU (monitor connected to motherboard)
- **Default**: Remove custom configuration, use system defaults

### Detailed Configuration

1. Select which GPU handles the login screen (SDDM)
2. Select which GPU handles desktop rendering (KWin)
3. Select which GPU outputs the display signal
4. Click "Apply Configuration" and authenticate with your password
5. Log out and log back in for changes to take effect

### Launch Apps on Specific GPU

Right-click any `.desktop` file or executable in Dolphin and select **Launch on GPU → Select GPU and Launch...**. A dialog will show your detected GPUs with VRAM usage. Select one and the app will launch with the correct GPU environment variables.

### BIOS/UEFI Requirements

For iGPU configuration to work, ensure your BIOS has:
- **iGPU Multi-Monitor**: Enabled
- **Primary Display**: iGPU or Auto (NOT PCIe/dGPU)
- **Above 4G Decoding**: Enabled

## License

Copyright (C) 2026 Audi Etoffe. All Rights Reserved.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See [LICENSE](LICENSE) for more details.

## Author

Audi Etoffe (2026) AcidReignProductions.com
