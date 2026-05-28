// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/ws.go
// @brief      WebSocket client — connection to ELY backend
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
//   - AUTORISÉ : Modification et redistribution avec attribution.
//   - INTERDIT : Revente comme SaaS / service managé à des tiers.
//   - INTERDIT : Suppression des notices de copyright ou de licence.
// =============================================================================

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"

	"github.com/gorilla/websocket"
)

const (
	reconnectBaseDelay = 2 * time.Second
	reconnectMaxDelay  = 60 * time.Second
	reconnectMaxJitter = 2000 // milliseconds
	writeTimeout       = 10 * time.Second
	pongTimeout        = 60 * time.Second
	pingInterval       = 30 * time.Second
)

// Message types exchanged over the WebSocket.

// IncomingCommand is a command sent by the backend to the daemon.
type IncomingCommand struct {
	CmdID string                 `json:"cmd_id"`
	Cmd   string                 `json:"cmd"`
	Args  map[string]interface{} `json:"args"`
}

// OutgoingResult is the daemon's response to a backend command.
type OutgoingResult struct {
	CmdID  string      `json:"cmd_id"`
	Status string      `json:"status"` // "ok" | "error"
	Result interface{} `json:"result,omitempty"`
	Error  string      `json:"error,omitempty"`
}

// ConnectAndRun establishes a WebSocket connection to the ELY backend and
// processes commands until the context is cancelled (via doneCh).
// It reconnects automatically with exponential backoff + jitter.
func ConnectAndRun(cfg *Config, fs *FSHandler, input *InputHandler, doneCh <-chan struct{}) {
	delay := reconnectBaseDelay

	for {
		select {
		case <-doneCh:
			log.Println("[ws] shutdown requested, not reconnecting")
			return
		default:
		}

		log.Printf("[ws] connecting to %s …", cfg.WebSocketURL())
		err := runSession(cfg, fs, input, doneCh)
		if err != nil {
			log.Printf("[ws] session ended: %v", err)
		}

		select {
		case <-doneCh:
			return
		default:
		}

		jitter := time.Duration(rand.Intn(reconnectMaxJitter)) * time.Millisecond
		log.Printf("[ws] reconnecting in %v (+%v jitter) …", delay, jitter)
		select {
		case <-doneCh:
			return
		case <-time.After(delay + jitter):
		}

		// Exponential backoff capped at reconnectMaxDelay
		delay *= 2
		if delay > reconnectMaxDelay {
			delay = reconnectMaxDelay
		}
	}
}

// runSession opens one WebSocket session, sends the handshake, then loops
// reading commands and dispatching them to the FSHandler or InputHandler.
// Returns when the connection is lost or doneCh fires.
func runSession(cfg *Config, fs *FSHandler, input *InputHandler, doneCh <-chan struct{}) error {
	headers := http.Header{}
	conn, _, err := websocket.DefaultDialer.Dial(cfg.WebSocketURL(), headers)
	if err != nil {
		return fmt.Errorf("dial %s: %w", cfg.WebSocketURL(), err)
	}
	defer conn.Close()

	log.Println("[ws] connected")

	// ── Handshake ────────────────────────────────────────────────────────
	handshake := map[string]interface{}{
		"token":        cfg.Token,
		"platform":     getPlatform(),
		"version":      version,
		"sandbox_dirs": cfg.SandboxDirs,
	}
	if err := writeJSON(conn, handshake); err != nil {
		return fmt.Errorf("handshake: %w", err)
	}

	// ── Ping/pong keepalive ───────────────────────────────────────────────
	conn.SetReadDeadline(time.Now().Add(pongTimeout))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(pongTimeout))
		return nil
	})

	// Background ping ticker
	pingTicker := time.NewTicker(pingInterval)
	defer pingTicker.Stop()

	pingDone := make(chan struct{})
	go func() {
		defer close(pingDone)
		for {
			select {
			case <-pingTicker.C:
				conn.SetWriteDeadline(time.Now().Add(writeTimeout))
				if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
					return
				}
			case <-doneCh:
				return
			}
		}
	}()
	defer func() { <-pingDone }()

	// ── Read / dispatch loop ──────────────────────────────────────────────
	for {
		// Check shutdown signal (non-blocking)
		select {
		case <-doneCh:
			conn.WriteMessage(websocket.CloseMessage,
				websocket.FormatCloseMessage(websocket.CloseNormalClosure, "shutdown"))
			return nil
		default:
		}

		_, raw, readErr := conn.ReadMessage()
		if readErr != nil {
			if websocket.IsCloseError(readErr,
				websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				return nil
			}
			return fmt.Errorf("read: %w", readErr)
		}

		// The first message may be the server acknowledgement — skip non-command msgs
		var msg map[string]json.RawMessage
		if err := json.Unmarshal(raw, &msg); err != nil {
			log.Printf("[ws] malformed JSON (ignored): %s", raw)
			continue
		}

		// Only process messages that look like commands (have cmd_id + cmd)
		if _, hasCmdID := msg["cmd_id"]; !hasCmdID {
			continue
		}

		var cmd IncomingCommand
		if err := json.Unmarshal(raw, &cmd); err != nil {
			log.Printf("[ws] cannot parse command: %v", err)
			continue
		}

		// Dispatch in a goroutine so slow ops don't block reads.
		// Input commands (screenshot, mouse, keyboard) are routed to InputHandler;
		// filesystem commands go to FSHandler.
		go func(c IncomingCommand) {
			var result interface{}
			var dispatchErr error
			if IsInputCmd(c.Cmd) {
				result, dispatchErr = input.Handle(c.Cmd, c.Args)
			} else {
				result, dispatchErr = fs.Handle(c.Cmd, c.Args)
			}
			var resp OutgoingResult
			if dispatchErr != nil {
				resp = OutgoingResult{
					CmdID:  c.CmdID,
					Status: "error",
					Error:  dispatchErr.Error(),
				}
				log.Printf("[fs] command %q error: %v", c.Cmd, dispatchErr)
			} else {
				resp = OutgoingResult{
					CmdID:  c.CmdID,
					Status: "ok",
					Result: result,
				}
				log.Printf("[fs] command %q ok", c.Cmd)
			}

			if writeErr := writeJSON(conn, resp); writeErr != nil {
				log.Printf("[ws] write result error: %v", writeErr)
			}
		}(cmd)
	}
}

// writeJSON marshals v and sends it as a text message.
func writeJSON(conn *websocket.Conn, v interface{}) error {
	data, err := json.Marshal(v)
	if err != nil {
		return err
	}
	conn.SetWriteDeadline(time.Now().Add(writeTimeout))
	return conn.WriteMessage(websocket.TextMessage, data)
}
