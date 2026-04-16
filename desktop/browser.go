// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/browser.go
// @brief      Browser automation — Playwright-based web interaction
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

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
