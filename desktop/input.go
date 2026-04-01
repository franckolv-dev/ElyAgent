package main

// input.go — Screen capture and input simulation commands for ELY Desktop.
//
// Supported commands: screenshot, mouse_move, mouse_click, type_text, hotkey,
// get_screen_size.
//
// Platform support:
//   Linux   — scrot (screenshot), xdotool (mouse/keyboard)
//   macOS   — screencapture (screenshot), cliclick or osascript (mouse/keyboard)
//   Windows — PowerShell + System.Windows.Forms (all operations)
//
// Required packages on Linux: sudo apt install scrot xdotool
// Required packages on macOS: brew install cliclick  (optional but recommended)

import (
	"encoding/base64"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// InputHandler handles screen-capture and input-simulation commands.
type InputHandler struct{}

// NewInputHandler creates an InputHandler.
func NewInputHandler() *InputHandler { return &InputHandler{} }

// IsInputCmd returns true when cmd belongs to the InputHandler namespace.
func IsInputCmd(cmd string) bool {
	switch cmd {
	case "screenshot", "mouse_move", "mouse_click", "type_text", "hotkey", "get_screen_size":
		return true
	}
	return false
}

// Handle dispatches an input-control command and returns the result.
func (h *InputHandler) Handle(cmd string, args map[string]interface{}) (interface{}, error) {
	switch cmd {
	case "screenshot":
		delayMs := 0
		if d, ok := args["delay_ms"].(float64); ok {
			delayMs = int(d)
		}
		return h.Screenshot(delayMs)

	case "mouse_move":
		x, _ := args["x"].(float64)
		y, _ := args["y"].(float64)
		return h.MouseMove(int(x), int(y))

	case "mouse_click":
		x, _ := args["x"].(float64)
		y, _ := args["y"].(float64)
		button, _ := args["button"].(string)
		if button == "" {
			button = "left"
		}
		double, _ := args["double"].(bool)
		return h.MouseClick(int(x), int(y), button, double)

	case "type_text":
		text, _ := args["text"].(string)
		return h.TypeText(text)

	case "hotkey":
		keys, _ := args["keys"].(string)
		return h.Hotkey(keys)

	case "get_screen_size":
		return h.GetScreenSize()

	default:
		return nil, fmt.Errorf("unknown input command: %s", cmd)
	}
}

// ── Screenshot ────────────────────────────────────────────────────────────────

// Screenshot captures the primary screen and returns it as a base64-encoded PNG.
func (h *InputHandler) Screenshot(delayMs int) (map[string]interface{}, error) {
	if delayMs > 0 {
		time.Sleep(time.Duration(delayMs) * time.Millisecond)
	}

	tmpFile := filepath.Join(os.TempDir(), "ely_screenshot.png")

	var cmd *exec.Cmd
	switch runtime.GOOS {

	case "linux":
		if _, err := exec.LookPath("scrot"); err == nil {
			// Capture all monitors combined (virtual desktop).
			// --overwrite replaces the file if it already exists.
			// Note: on multi-monitor setups this produces a wide image
			// (e.g. 5760×1080 for 3×1920). The vision LLM receives the
			// full image and coordinates are absolute across all screens.
			cmd = exec.Command("scrot", "--overwrite", tmpFile)
		} else if _, err := exec.LookPath("gnome-screenshot"); err == nil {
			cmd = exec.Command("gnome-screenshot", "--file="+tmpFile)
		} else if _, err := exec.LookPath("import"); err == nil {
			cmd = exec.Command("import", "-window", "root", tmpFile)
		} else {
			return nil, fmt.Errorf("no screenshot tool found — install scrot: sudo apt install scrot")
		}

	case "darwin":
		cmd = exec.Command("screencapture", "-x", tmpFile)

	case "windows":
		psScript := fmt.Sprintf(`
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($s.Width,$s.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size)
$bmp.Save('%s')
$g.Dispose(); $bmp.Dispose()
`, strings.ReplaceAll(tmpFile, `\`, `\\`))
		cmd = exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", psScript)

	default:
		return nil, fmt.Errorf("unsupported platform: %s", runtime.GOOS)
	}

	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("screenshot failed: %v — %s", err, out)
	}
	defer os.Remove(tmpFile)

	data, err := os.ReadFile(tmpFile)
	if err != nil {
		return nil, fmt.Errorf("read screenshot: %w", err)
	}

	return map[string]interface{}{
		"image_b64":  base64.StdEncoding.EncodeToString(data),
		"media_type": "image/png",
		"size_bytes": len(data),
	}, nil
}

// ── Mouse ─────────────────────────────────────────────────────────────────────

// MouseMove moves the cursor to (x, y).
func (h *InputHandler) MouseMove(x, y int) (map[string]interface{}, error) {
	var cmd *exec.Cmd
	xs, ys := strconv.Itoa(x), strconv.Itoa(y)

	switch runtime.GOOS {
	case "linux":
		cmd = exec.Command("xdotool", "mousemove", xs, ys)
	case "darwin":
		if _, err := exec.LookPath("cliclick"); err == nil {
			cmd = exec.Command("cliclick", fmt.Sprintf("m:%d,%d", x, y))
		} else {
			script := fmt.Sprintf(`tell application "System Events" to set mouse location to {%d, %d}`, x, y)
			cmd = exec.Command("osascript", "-e", script)
		}
	case "windows":
		ps := fmt.Sprintf(`
Add-Type @"
using System;using System.Runtime.InteropServices;
public class M{[DllImport("user32.dll")]public static extern bool SetCursorPos(int x,int y);}
"@
[M]::SetCursorPos(%d,%d)`, x, y)
		cmd = exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	default:
		return nil, fmt.Errorf("unsupported platform: %s", runtime.GOOS)
	}

	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("mouse_move failed: %v — %s", err, out)
	}
	return map[string]interface{}{"x": x, "y": y}, nil
}

// MouseClick clicks at (x, y).  button = "left"|"right"|"middle", double = double-click.
func (h *InputHandler) MouseClick(x, y int, button string, double bool) (map[string]interface{}, error) {
	xs, ys := strconv.Itoa(x), strconv.Itoa(y)

	switch runtime.GOOS {
	case "linux":
		btnNum := "1"
		switch button {
		case "right":
			btnNum = "3"
		case "middle":
			btnNum = "2"
		}
		if _, err := exec.Command("xdotool", "mousemove", xs, ys).CombinedOutput(); err != nil {
			return nil, fmt.Errorf("mouse_move (pre-click): %v", err)
		}
		time.Sleep(50 * time.Millisecond)
		repeat := "1"
		if double {
			repeat = "2"
		}
		if out, err := exec.Command("xdotool", "click", "--repeat", repeat, "--delay", "80", btnNum).CombinedOutput(); err != nil {
			return nil, fmt.Errorf("mouse_click failed: %v — %s", err, out)
		}

	case "darwin":
		if _, err := exec.LookPath("cliclick"); err == nil {
			action := "c"
			if button == "right" {
				action = "rc"
			}
			if double {
				action = "dc"
			}
			if out, err := exec.Command("cliclick", fmt.Sprintf("%s:%d,%d", action, x, y)).CombinedOutput(); err != nil {
				return nil, fmt.Errorf("mouse_click failed: %v — %s", err, out)
			}
		} else {
			script := fmt.Sprintf(`tell application "System Events" to click at {%d,%d}`, x, y)
			if out, err := exec.Command("osascript", "-e", script).CombinedOutput(); err != nil {
				return nil, fmt.Errorf("mouse_click failed: %v — %s", err, out)
			}
		}

	case "windows":
		downFlag, upFlag := "0x0002", "0x0004" // LEFTDOWN/LEFTUP
		if button == "right" {
			downFlag, upFlag = "0x0008", "0x0010"
		}
		clicks := 1
		if double {
			clicks = 2
		}
		ps := fmt.Sprintf(`
Add-Type @"
using System;using System.Runtime.InteropServices;
public class M{
  [DllImport("user32.dll")]public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")]public static extern void mouse_event(int f,int dx,int dy,int c,int e);
}
"@
[M]::SetCursorPos(%d,%d); Start-Sleep -Milliseconds 60
for($i=0;$i<%d;$i++){
  [M]::mouse_event(%s,0,0,0,0); Start-Sleep -Milliseconds 50
  [M]::mouse_event(%s,0,0,0,0); Start-Sleep -Milliseconds 80
}`, x, y, clicks, downFlag, upFlag)
		if out, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).CombinedOutput(); err != nil {
			return nil, fmt.Errorf("mouse_click failed: %v — %s", err, out)
		}

	default:
		return nil, fmt.Errorf("unsupported platform: %s", runtime.GOOS)
	}

	return map[string]interface{}{"x": x, "y": y, "button": button, "double": double}, nil
}

// ── Keyboard ──────────────────────────────────────────────────────────────────

// TypeText simulates typing the given text.
func (h *InputHandler) TypeText(text string) (map[string]interface{}, error) {
	var cmd *exec.Cmd

	switch runtime.GOOS {
	case "linux":
		cmd = exec.Command("xdotool", "type", "--clearmodifiers", "--delay", "30", "--", text)
	case "darwin":
		script := fmt.Sprintf(`tell application "System Events" to keystroke %q`, text)
		cmd = exec.Command("osascript", "-e", script)
	case "windows":
		ps := fmt.Sprintf(`
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait(%q)`, text)
		cmd = exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)
	default:
		return nil, fmt.Errorf("unsupported platform: %s", runtime.GOOS)
	}

	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("type_text failed: %v — %s", err, out)
	}
	return map[string]interface{}{"typed": text}, nil
}

// Hotkey simulates a key combination such as "ctrl+c", "ctrl+shift+t", "alt+f4".
func (h *InputHandler) Hotkey(keys string) (map[string]interface{}, error) {
	var cmd *exec.Cmd

	switch runtime.GOOS {
	case "linux":
		// xdotool key accepts "ctrl+c" — convert "+" to "+" (it already works)
		cmd = exec.Command("xdotool", "key", "--clearmodifiers", keys)

	case "darwin":
		parts := strings.Split(strings.ToLower(keys), "+")
		key := parts[len(parts)-1]
		mods := parts[:len(parts)-1]

		var modParts []string
		for _, m := range mods {
			switch m {
			case "ctrl":
				modParts = append(modParts, "control down")
			case "cmd", "command":
				modParts = append(modParts, "command down")
			case "shift":
				modParts = append(modParts, "shift down")
			case "alt", "option":
				modParts = append(modParts, "option down")
			}
		}
		usingClause := ""
		if len(modParts) > 0 {
			usingClause = " using {" + strings.Join(modParts, ", ") + "}"
		}
		script := fmt.Sprintf(`tell application "System Events" to keystroke %q%s`, key, usingClause)
		cmd = exec.Command("osascript", "-e", script)

	case "windows":
		ps := fmt.Sprintf(`
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait(%q)`, convertToSendKeys(keys))
		cmd = exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps)

	default:
		return nil, fmt.Errorf("unsupported platform: %s", runtime.GOOS)
	}

	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("hotkey failed: %v — %s", err, out)
	}
	return map[string]interface{}{"keys": keys}, nil
}

// ── Screen size ───────────────────────────────────────────────────────────────

// GetScreenSize returns the primary display dimensions.
func (h *InputHandler) GetScreenSize() (map[string]interface{}, error) {
	width, height := 1920, 1080 // safe fallback

	switch runtime.GOOS {
	case "linux":
		out, err := exec.Command("xdotool", "getdisplaygeometry").Output()
		if err == nil {
			parts := strings.Fields(strings.TrimSpace(string(out)))
			if len(parts) == 2 {
				if w, e := strconv.Atoi(parts[0]); e == nil {
					width = w
				}
				if h, e := strconv.Atoi(parts[1]); e == nil {
					height = h
				}
			}
		}
	case "darwin":
		out, err := exec.Command("osascript", "-e",
			`tell application "Finder" to get bounds of window of desktop`).Output()
		if err == nil {
			// Returns "0, 0, 2560, 1440"
			parts := strings.Split(string(out), ",")
			if len(parts) == 4 {
				if w, e := strconv.Atoi(strings.TrimSpace(parts[2])); e == nil {
					width = w
				}
				if h, e := strconv.Atoi(strings.TrimSpace(parts[3])); e == nil {
					height = h
				}
			}
		}
	case "windows":
		ps := `Add-Type -AssemblyName System.Windows.Forms; $s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; Write-Host "$($s.Width) $($s.Height)"`
		out, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", ps).Output()
		if err == nil {
			parts := strings.Fields(strings.TrimSpace(string(out)))
			if len(parts) == 2 {
				if w, e := strconv.Atoi(parts[0]); e == nil {
					width = w
				}
				if h, e := strconv.Atoi(parts[1]); e == nil {
					height = h
				}
			}
		}
	}

	return map[string]interface{}{"width": width, "height": height}, nil
}

// ── Windows SendKeys helper ───────────────────────────────────────────────────

// convertToSendKeys converts "ctrl+c" notation to Windows SendKeys format.
func convertToSendKeys(keys string) string {
	parts := strings.Split(strings.ToLower(keys), "+")
	key := parts[len(parts)-1]
	mods := parts[:len(parts)-1]

	prefix := ""
	for _, m := range mods {
		switch m {
		case "ctrl":
			prefix += "^"
		case "shift":
			prefix += "+"
		case "alt":
			prefix += "%"
		}
	}

	specials := map[string]string{
		"enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}",
		"esc": "{ESC}", "escape": "{ESC}", "backspace": "{BACKSPACE}",
		"delete": "{DELETE}", "del": "{DELETE}", "home": "{HOME}",
		"end": "{END}", "pgup": "{PGUP}", "pgdn": "{PGDN}",
		"up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
		"f1": "{F1}", "f2": "{F2}", "f3": "{F3}", "f4": "{F4}",
		"f5": "{F5}", "f6": "{F6}", "f7": "{F7}", "f8": "{F8}",
		"f9": "{F9}", "f10": "{F10}", "f11": "{F11}", "f12": "{F12}",
	}
	if sk, ok := specials[key]; ok {
		return prefix + sk
	}
	return prefix + key
}
