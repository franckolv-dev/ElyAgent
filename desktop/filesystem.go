// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/filesystem.go
// @brief      Local filesystem operations — read, write, move, delete
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//            https://opensource.org/licenses/MIT
// @version    1.2.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

const maxReadBytes = 5 * 1024 * 1024 // 5 MB

// FSHandler processes filesystem commands received from the ELY backend.
type FSHandler struct {
	sandboxDirs []string
}

// expandHome replaces a leading « ~ » or « ~/ » in a path with the
// current user's home directory. Returns the path unchanged if it
// doesn't start with ~ or if the home dir cannot be resolved.
//
// Why a daemon-side expand rather than asking the frontend / backend
// to resolve it? The Settings UI may have been edited by an admin from
// a different machine entirely (e.g. configuring a colleague's daemon),
// so the path semantics « ~ = my home » must be evaluated at the
// machine where the daemon actually runs, not at the configuration
// time. Same rationale for $HOME and other env vars — kept simple here,
// only ~ is supported.
func expandHome(path string) string {
	if path == "" || path[0] != '~' {
		return path
	}
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return path
	}
	if path == "~" {
		return home
	}
	if strings.HasPrefix(path, "~/") || strings.HasPrefix(path, `~\`) {
		return filepath.Join(home, path[2:])
	}
	// « ~someuser » is not supported — POSIX-only and rarely used.
	// Returning unchanged surfaces the misconfiguration to the user.
	return path
}

// NewFSHandler creates a new FSHandler with the provided sandbox directories.
func NewFSHandler(sandboxDirs []string) *FSHandler {
	// Resolve symlinks so sandbox checks are reliable.
	resolved := make([]string, 0, len(sandboxDirs))
	for _, d := range sandboxDirs {
		// Expand a leading ~ so the user can type « ~/Downloads » in
		// the frontend without us forcing them to know their absolute
		// home path.
		expanded := expandHome(d)
		r, err := filepath.EvalSymlinks(expanded)
		if err != nil {
			r = expanded // use as-is if resolution fails (dir may not exist yet)
		}
		resolved = append(resolved, filepath.Clean(r))
	}
	return &FSHandler{sandboxDirs: resolved}
}

// safeResolve fully resolves a path's canonical form, even when the
// terminal components don't exist yet (e.g. a new file being created).
//
// HOTFIX 2026-05-28 — the original code only called
// ``filepath.EvalSymlinks`` on either the path itself or its immediate
// parent. If a deeper ancestor was missing (write to /sb/evil_link/a/b/c
// where a/b/c don't exist), EvalSymlinks on the parent failed and the
// fallback left ``resolved`` as the unresolved absolute path. An
// attacker who controlled a symlink anywhere along the chain
// (e.g. /sb/evil_link → /outside) could then pass the prefix check —
// because the unresolved string still started with /sb/. ``os.MkdirAll``
// would then follow the symlink and create the missing dirs OUTSIDE the
// sandbox. Class : Zip Slip / symlink-write escape.
//
// The fix walks UP the path until it finds an existing ancestor,
// resolves symlinks on that ancestor (which DOES exist so EvalSymlinks
// succeeds), then re-joins the missing tail components and re-cleans.
// The result is the canonical absolute path of where the candidate
// would actually land if written.
func safeResolve(path string) (string, error) {
	abs := filepath.Clean(path)
	if !filepath.IsAbs(abs) {
		return "", fmt.Errorf("path must be absolute: %q", path)
	}
	cur := abs
	var tail []string
	for {
		if _, err := os.Lstat(cur); err == nil {
			resolved, err := filepath.EvalSymlinks(cur)
			if err != nil {
				return "", fmt.Errorf("cannot resolve %q: %w", cur, err)
			}
			// Re-join the tail components we walked past — LIFO since
			// we collected them parent-first as we walked up.
			for i := len(tail) - 1; i >= 0; i-- {
				resolved = filepath.Join(resolved, tail[i])
			}
			return filepath.Clean(resolved), nil
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			// Reached the filesystem root and nothing along the chain
			// exists. No symlinks could be involved on a tree that's
			// entirely missing, so the cleaned abs is safe to use.
			return abs, nil
		}
		tail = append(tail, filepath.Base(cur))
		cur = parent
	}
}

// validatePath checks that path is inside one of the sandbox directories.
// It fully resolves symlinks (including across missing intermediate dirs)
// to prevent path-traversal attacks, then uses ``filepath.Rel`` for a
// semantic containment check rather than a string-prefix one.
//
// HOTFIX 2026-05-28 — code review of 2026-05-28 flagged the original
// validation as fragile. Two changes :
//   1. Symlink resolution via ``safeResolve`` (handles missing
//      intermediate dirs — the original prefix-only fallback was
//      bypassable; see safeResolve's doc above).
//   2. Containment check via ``filepath.Rel`` — if the relative path
//      from sandbox to candidate starts with ``..`` (with separator),
//      we're outside. More idiomatic and less error-prone than the
//      previous ``strings.HasPrefix(resolved, sd+sep)`` heuristic,
//      which historically misbehaved on edge cases like
//      trailing-slash sandbox config and prefix-sibling dirs
//      (``/sb`` vs ``/sb-evil``).
func (h *FSHandler) validatePath(path string) (string, error) {
	if path == "" {
		return "", fmt.Errorf("path must not be empty")
	}
	// Expand a leading ~ first so callers (and the LLM) can use the
	// natural « ~/Documents/foo » form. Same expansion as for sandbox
	// dirs at boot — keeps semantics symmetrical.
	path = expandHome(path)
	if !filepath.IsAbs(filepath.Clean(path)) {
		return "", fmt.Errorf("path must be absolute: %q", path)
	}

	resolved, err := safeResolve(path)
	if err != nil {
		return "", err
	}

	for _, sd := range h.sandboxDirs {
		rel, relErr := filepath.Rel(sd, resolved)
		if relErr != nil {
			continue
		}
		// `rel == "."` → path equals the sandbox dir itself → OK
		// `rel == ".."` or starts with `../` or `..\` → outside → SKIP
		// Anything else (including weird names that happen to start with
		// dots like `..hidden` are fine — only a leading `..` followed
		// by a separator means real traversal).
		if rel == "." {
			return resolved, nil
		}
		if rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			continue
		}
		return resolved, nil
	}

	return "", fmt.Errorf(
		"access denied: %q is outside sandbox directories %v",
		path, h.sandboxDirs,
	)
}

// Handle dispatches a command to the appropriate handler.
func (h *FSHandler) Handle(cmd string, args map[string]interface{}) (interface{}, error) {
	switch cmd {
	case "list_dir":
		path, _ := args["path"].(string)
		return h.ListDir(path)
	case "read_file":
		path, _ := args["path"].(string)
		return h.ReadFile(path)
	case "write_file":
		path, _ := args["path"].(string)
		content, _ := args["content"].(string)
		return h.WriteFile(path, content)
	case "move_file":
		src, _ := args["src"].(string)
		dst, _ := args["dst"].(string)
		return h.MoveFile(src, dst)
	case "delete_file":
		path, _ := args["path"].(string)
		return h.DeleteFile(path)
	case "create_dir":
		path, _ := args["path"].(string)
		return h.CreateDir(path)
	case "stat_file":
		path, _ := args["path"].(string)
		return h.StatFile(path)
	case "hash_file":
		path, _ := args["path"].(string)
		return h.HashFile(path)
	case "search_files":
		directory, _ := args["directory"].(string)
		pattern, _ := args["pattern"].(string)
		return h.SearchFiles(directory, pattern)
	default:
		return nil, fmt.Errorf("unknown command: %q", cmd)
	}
}

// ─── DirEntry represents a single entry returned by ListDir ────────────────

type DirEntry struct {
	Name     string    `json:"name"`
	Type     string    `json:"type"` // "file" | "dir" | "symlink"
	Size     int64     `json:"size"`
	Modified time.Time `json:"modified"`
}

// ListDir returns the contents of a directory.
func (h *FSHandler) ListDir(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	entries, err := os.ReadDir(clean)
	if err != nil {
		return nil, fmt.Errorf("cannot read directory %q: %w", path, err)
	}

	result := make([]DirEntry, 0, len(entries))
	for _, e := range entries {
		info, infoErr := e.Info()
		if infoErr != nil {
			continue
		}
		entryType := "file"
		if e.IsDir() {
			entryType = "dir"
		} else if e.Type()&fs.ModeSymlink != 0 {
			entryType = "symlink"
		}
		result = append(result, DirEntry{
			Name:     e.Name(),
			Type:     entryType,
			Size:     info.Size(),
			Modified: info.ModTime(),
		})
	}

	return map[string]interface{}{"entries": result}, nil
}

// ReadFile returns the content of a file (up to 5 MB).
// Binary files are base64-encoded.
func (h *FSHandler) ReadFile(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	info, err := os.Stat(clean)
	if err != nil {
		return nil, fmt.Errorf("file not found: %q", path)
	}
	if info.IsDir() {
		return nil, fmt.Errorf("%q is a directory, not a file", path)
	}
	if info.Size() > maxReadBytes {
		return nil, fmt.Errorf(
			"file too large (%d bytes > %d byte limit)", info.Size(), maxReadBytes,
		)
	}

	data, err := os.ReadFile(clean)
	if err != nil {
		return nil, fmt.Errorf("cannot read file %q: %w", path, err)
	}

	// Detect if content is valid UTF-8; if not, encode as base64
	content := string(data)
	encoding := "utf-8"
	if !isValidUTF8(data) {
		content = base64.StdEncoding.EncodeToString(data)
		encoding = "base64"
	}

	return map[string]interface{}{
		"content":  content,
		"encoding": encoding,
		"size":     info.Size(),
	}, nil
}

// WriteFile writes text content to a file (creates or overwrites).
func (h *FSHandler) WriteFile(path, content string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	// Ensure parent directory exists
	if mkErr := os.MkdirAll(filepath.Dir(clean), 0o755); mkErr != nil {
		return nil, fmt.Errorf("cannot create parent directory: %w", mkErr)
	}

	if err := os.WriteFile(clean, []byte(content), 0o644); err != nil {
		return nil, fmt.Errorf("cannot write file %q: %w", path, err)
	}

	return map[string]interface{}{"bytes_written": len(content)}, nil
}

// MoveFile renames or moves a file/directory within the sandbox.
func (h *FSHandler) MoveFile(src, dst string) (map[string]interface{}, error) {
	cleanSrc, err := h.validatePath(src)
	if err != nil {
		return nil, fmt.Errorf("source: %w", err)
	}
	cleanDst, err := h.validatePath(dst)
	if err != nil {
		return nil, fmt.Errorf("destination: %w", err)
	}

	if err := os.Rename(cleanSrc, cleanDst); err != nil {
		return nil, fmt.Errorf("cannot move %q to %q: %w", src, dst, err)
	}

	return map[string]interface{}{"moved": true}, nil
}

// DeleteFile removes a file or directory (recursively).
func (h *FSHandler) DeleteFile(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	if err := os.RemoveAll(clean); err != nil {
		return nil, fmt.Errorf("cannot delete %q: %w", path, err)
	}

	return map[string]interface{}{"deleted": true}, nil
}

// CreateDir creates a directory and all parent directories.
func (h *FSHandler) CreateDir(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	if err := os.MkdirAll(clean, 0o755); err != nil {
		return nil, fmt.Errorf("cannot create directory %q: %w", path, err)
	}

	return map[string]interface{}{"created": true}, nil
}

// StatFile returns file/directory metadata.
func (h *FSHandler) StatFile(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	info, err := os.Stat(clean)
	if err != nil {
		return nil, fmt.Errorf("cannot stat %q: %w", path, err)
	}

	entryType := "file"
	if info.IsDir() {
		entryType = "dir"
	}

	return map[string]interface{}{
		"name":     info.Name(),
		"type":     entryType,
		"size":     info.Size(),
		"mode":     info.Mode().String(),
		"modified": info.ModTime().Format(time.RFC3339),
		"is_dir":   info.IsDir(),
	}, nil
}

// HashFile computes the SHA-256 of a file.
func (h *FSHandler) HashFile(path string) (map[string]interface{}, error) {
	clean, err := h.validatePath(path)
	if err != nil {
		return nil, err
	}

	f, err := os.Open(clean)
	if err != nil {
		return nil, fmt.Errorf("cannot open %q: %w", path, err)
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		return nil, fmt.Errorf("cannot stat %q: %w", path, err)
	}

	h256 := sha256.New()
	if _, err := io.Copy(h256, f); err != nil {
		return nil, fmt.Errorf("cannot hash %q: %w", path, err)
	}

	return map[string]interface{}{
		"sha256": hex.EncodeToString(h256.Sum(nil)),
		"size":   info.Size(),
	}, nil
}

// SearchFiles finds files matching a glob pattern inside a directory.
func (h *FSHandler) SearchFiles(directory, pattern string) (map[string]interface{}, error) {
	cleanDir, err := h.validatePath(directory)
	if err != nil {
		return nil, err
	}

	var matches []string
	err = filepath.WalkDir(cleanDir, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil // skip unreadable entries
		}
		name := d.Name()
		matched, matchErr := filepath.Match(pattern, name)
		if matchErr != nil {
			return fmt.Errorf("invalid pattern %q: %w", pattern, matchErr)
		}
		if matched {
			// Return path relative to the search directory
			rel, relErr := filepath.Rel(cleanDir, path)
			if relErr != nil {
				rel = path
			}
			matches = append(matches, rel)
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("search failed: %w", err)
	}

	return map[string]interface{}{"matches": matches}, nil
}

// ─── Helpers ───────────────────────────────────────────────────────────────

// isValidUTF8 checks whether data is valid UTF-8 text without null bytes.
// Files containing null bytes are treated as binary.
func isValidUTF8(data []byte) bool {
	for _, b := range data {
		if b == 0 {
			return false
		}
	}
	return utf8.Valid(data)
}
