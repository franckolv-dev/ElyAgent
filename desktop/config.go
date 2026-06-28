// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/config.go
// @brief      Configuration loading — server URL, auth token, settings
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    Elastic License 2.0
//            https://www.elastic.co/licensing/elastic-license
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
//   - INTERDIT : Revente comme SaaS / service managé à des tiers.
//   - INTERDIT : Suppression des notices de copyright ou de licence.
// =============================================================================

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Config holds the ELY Desktop daemon configuration loaded from ely-config.json.
type Config struct {
	// VPSURL is the base URL of the ELY backend (e.g. "https://my-vps.example.com")
	VPSURL string `json:"vps_url"`

	// Token is the long-lived JWT used to authenticate the daemon WebSocket connection.
	Token string `json:"token"`

	// SandboxDirs is the list of local directories the daemon is allowed to access.
	SandboxDirs []string `json:"sandbox_dirs"`

	// Version is the config file format version (for future migrations).
	Version string `json:"version"`
}

// LoadConfig reads ely-config.json from the same directory as the binary.
func LoadConfig() (*Config, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, fmt.Errorf("cannot determine executable path: %w", err)
	}
	dir := filepath.Dir(exe)
	configPath := filepath.Join(dir, "ely-config.json")

	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("cannot read %s: %w\n\nDownload ely-config.json from the ELY web interface (Settings > ELY Desktop > Download config) and place it in the same folder as this binary.", configPath, err)
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("invalid ely-config.json: %w", err)
	}

	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return &cfg, nil
}

// Validate checks that required fields are present.
func (c *Config) Validate() error {
	if c.VPSURL == "" {
		return fmt.Errorf("ely-config.json: vps_url is required")
	}
	if c.Token == "" {
		return fmt.Errorf("ely-config.json: token is required")
	}
	// Normalise URL — strip trailing slash
	c.VPSURL = strings.TrimRight(c.VPSURL, "/")
	return nil
}

// WebSocketURL builds the wss:// (or ws://) URL for the daemon endpoint.
func (c *Config) WebSocketURL() string {
	base := c.VPSURL
	if strings.HasPrefix(base, "https://") {
		base = "wss://" + strings.TrimPrefix(base, "https://")
	} else if strings.HasPrefix(base, "http://") {
		base = "ws://" + strings.TrimPrefix(base, "http://")
	}
	return base + "/ws/desktop"
}

// FrontendURL returns the URL of the ELY web interface.
func (c *Config) FrontendURL() string {
	// The frontend is typically served at the same domain on port 3000 or /
	return c.VPSURL
}
