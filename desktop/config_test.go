// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/config_test.go
// @brief      Config parsing contract — open_browser opt-in default
// @license    Elastic License 2.0
// =============================================================================
//
// 2026-07-18 — the daemon used to open the web UI in a new browser tab at
// EVERY launch, which duplicated tabs whenever the daemon was relaunched
// while an ELY tab was already open. Auto-open is now opt-in via the
// "open_browser" key in ely-config.json. These tests pin the contract:
// key absent → false (existing configs stop duplicating tabs without any
// user action), explicit true → true.

package main

import (
	"encoding/json"
	"testing"
)

// parseConfig unmarshals + validates a raw ely-config.json payload the same
// way LoadConfig does, without depending on os.Executable.
func parseConfig(t *testing.T, raw string) *Config {
	t.Helper()
	var cfg Config
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("validate: %v", err)
	}
	return &cfg
}

func TestOpenBrowserDefaultsToFalse(t *testing.T) {
	// Configs downloaded before the option existed have no "open_browser"
	// key — the daemon must NOT auto-open the browser for them.
	cfg := parseConfig(t, `{"vps_url":"https://ely.example.com","token":"tok"}`)
	if cfg.OpenBrowser {
		t.Error("open_browser absent from config must default to false")
	}
}

func TestOpenBrowserExplicitTrue(t *testing.T) {
	cfg := parseConfig(t, `{"vps_url":"https://ely.example.com","token":"tok","open_browser":true}`)
	if !cfg.OpenBrowser {
		t.Error("open_browser:true in config must enable auto-open")
	}
}
