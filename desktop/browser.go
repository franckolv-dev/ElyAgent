package main

import (
	"os/exec"
	"runtime"
)

// OpenBrowser opens the given URL in the default system browser.
// This is a best-effort operation — errors are silently ignored so they
// never crash the daemon (the user can always open the browser manually).
func OpenBrowser(url string) {
	var cmd *exec.Cmd

	switch runtime.GOOS {
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "darwin":
		cmd = exec.Command("open", url)
	case "windows":
		cmd = exec.Command("cmd", "/c", "start", url)
	default:
		return
	}

	// Run detached — we don't wait for the browser to close.
	_ = cmd.Start()
}
