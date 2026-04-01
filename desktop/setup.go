package main

import (
	"fmt"
	"os/exec"
	"runtime"
)

// dep describes a system dependency required by the daemon.
type dep struct {
	binary  string // binary to look for in PATH
	pkg     string // package name to install (apt / brew)
	purpose string // human-readable description
}

// platformDeps lists the dependencies per OS.
var platformDeps = map[string][]dep{
	"linux": {
		{"scrot", "scrot", "screen capture"},
		{"xdotool", "xdotool", "mouse & keyboard control"},
	},
	"darwin": {
		// screencapture is built-in on macOS; only cliclick is needed.
		{"cliclick", "cliclick", "mouse & keyboard control"},
	},
	// Windows uses PowerShell + user32.dll — no external packages needed.
}

// EnsureDependencies checks for required system packages and installs any
// that are missing. It prints a clear message for each action taken.
// On unsupported platforms (Windows) it is a no-op.
func EnsureDependencies() {
	deps, ok := platformDeps[runtime.GOOS]
	if !ok {
		// Windows or unknown platform — nothing to do.
		return
	}

	var missing []dep
	for _, d := range deps {
		if _, err := exec.LookPath(d.binary); err != nil {
			missing = append(missing, d)
		}
	}

	if len(missing) == 0 {
		fmt.Println("[setup] All required dependencies are already installed.")
		return
	}

	fmt.Println("[setup] Some dependencies are missing — installing automatically…")
	for _, d := range missing {
		fmt.Printf("[setup]   missing: %s (%s)\n", d.binary, d.purpose)
	}

	switch runtime.GOOS {
	case "linux":
		installLinux(missing)
	case "darwin":
		installMacOS(missing)
	}
}

// installLinux tries apt-get (Debian/Ubuntu/Mint) then dnf (Fedora/RHEL).
func installLinux(deps []dep) {
	pkgs := make([]string, len(deps))
	for i, d := range deps {
		pkgs[i] = d.pkg
	}

	if path, err := exec.LookPath("apt-get"); err == nil {
		args := append([]string{"install", "-y"}, pkgs...)
		fmt.Printf("[setup] Running: %s %v\n", path, args)
		// Try without sudo first (already root), then with sudo.
		cmd := exec.Command(path, args...)
		cmd.Stdout = nil
		cmd.Stderr = nil
		if err := cmd.Run(); err != nil {
			// Retry with sudo
			sudoArgs := append([]string{path}, args...)
			cmd = exec.Command("sudo", sudoArgs...)
			if out, err := cmd.CombinedOutput(); err != nil {
				fmt.Printf("[setup] apt-get failed: %v\n%s\n", err, out)
				printManualInstructions("linux", deps)
				return
			}
		}
		fmt.Println("[setup] ✓ Dependencies installed via apt-get.")
		return
	}

	if path, err := exec.LookPath("dnf"); err == nil {
		args := append([]string{"install", "-y"}, pkgs...)
		cmd := exec.Command("sudo", append([]string{path}, args...)...)
		if out, err := cmd.CombinedOutput(); err != nil {
			fmt.Printf("[setup] dnf failed: %v\n%s\n", err, out)
			printManualInstructions("linux", deps)
			return
		}
		fmt.Println("[setup] ✓ Dependencies installed via dnf.")
		return
	}

	fmt.Println("[setup] No supported package manager found (apt-get / dnf).")
	printManualInstructions("linux", deps)
}

// installMacOS uses Homebrew.
func installMacOS(deps []dep) {
	brew, err := exec.LookPath("brew")
	if err != nil {
		fmt.Println("[setup] Homebrew not found. Install it from https://brew.sh then re-run ely-desktop.")
		printManualInstructions("darwin", deps)
		return
	}

	for _, d := range deps {
		fmt.Printf("[setup] Running: brew install %s\n", d.pkg)
		cmd := exec.Command(brew, "install", d.pkg)
		if out, err := cmd.CombinedOutput(); err != nil {
			fmt.Printf("[setup] brew install %s failed: %v\n%s\n", d.pkg, err, out)
		} else {
			fmt.Printf("[setup] ✓ %s installed.\n", d.pkg)
		}
	}
}

// printManualInstructions prints what the user should run manually.
func printManualInstructions(os string, deps []dep) {
	fmt.Println("[setup] Please install the following packages manually:")
	switch os {
	case "linux":
		pkgs := ""
		for _, d := range deps {
			pkgs += " " + d.pkg
		}
		fmt.Printf("[setup]   sudo apt install%s\n", pkgs)
	case "darwin":
		for _, d := range deps {
			fmt.Printf("[setup]   brew install %s\n", d.pkg)
		}
	}
}
