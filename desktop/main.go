package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"runtime"
	"syscall"
)

// version is the daemon version — injected at build time via -ldflags if desired.
var version = "1.0.0"

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("ELY Desktop daemon v%s (os=%s arch=%s)", version, runtime.GOOS, runtime.GOARCH)

	// ── Load configuration ────────────────────────────────────────────────
	cfg, err := LoadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "\n[ERROR] %v\n\n", err)
		os.Exit(1)
	}

	log.Printf("Config loaded: vps_url=%s, sandbox_dirs=%v", cfg.VPSURL, cfg.SandboxDirs)

	// ── Auto-install system dependencies (scrot, xdotool on Linux, etc.) ─
	EnsureDependencies()

	// ── Open browser in background ────────────────────────────────────────
	go OpenBrowser(cfg.FrontendURL())

	// ── Build handlers ────────────────────────────────────────────────────
	fsHandler    := NewFSHandler(cfg.SandboxDirs)
	inputHandler := NewInputHandler()

	// ── Graceful shutdown channel ─────────────────────────────────────────
	doneCh := make(chan struct{})

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigCh
		log.Printf("Received signal %v — shutting down …", sig)
		close(doneCh)
	}()

	// ── WebSocket connection loop (reconnects automatically) ──────────────
	ConnectAndRun(cfg, fsHandler, inputHandler, doneCh)

	log.Println("ELY Desktop daemon stopped.")
}

// getPlatform returns a human-readable OS identifier sent in the handshake.
func getPlatform() string {
	switch runtime.GOOS {
	case "linux":
		return "linux"
	case "darwin":
		return "macos"
	case "windows":
		return "windows"
	default:
		return runtime.GOOS
	}
}
