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

// NewFSHandler creates a new FSHandler with the provided sandbox directories.
func NewFSHandler(sandboxDirs []string) *FSHandler {
	// Resolve symlinks so sandbox checks are reliable.
	resolved := make([]string, 0, len(sandboxDirs))
	for _, d := range sandboxDirs {
		r, err := filepath.EvalSymlinks(d)
		if err != nil {
			r = d // use as-is if resolution fails (dir may not exist yet)
		}
		resolved = append(resolved, filepath.Clean(r))
	}
	return &FSHandler{sandboxDirs: resolved}
}

// validatePath checks that path is inside one of the sandbox directories.
// It resolves symlinks to prevent path-traversal attacks.
func (h *FSHandler) validatePath(path string) (string, error) {
	if path == "" {
		return "", fmt.Errorf("path must not be empty")
	}

	// Resolve symlinks on the longest existing prefix to catch traversal attempts
	// even when the full path doesn't exist yet (e.g. a file being written).
	abs := filepath.Clean(path)
	if !filepath.IsAbs(abs) {
		return "", fmt.Errorf("path must be absolute: %q", path)
	}

	// Try to resolve the real path; if the path doesn't exist, resolve the parent.
	resolved := abs
	if _, err := os.Lstat(abs); err == nil {
		if r, err := filepath.EvalSymlinks(abs); err == nil {
			resolved = r
		}
	} else {
		if r, err := filepath.EvalSymlinks(filepath.Dir(abs)); err == nil {
			resolved = filepath.Join(r, filepath.Base(abs))
		}
	}

	for _, sd := range h.sandboxDirs {
		if strings.HasPrefix(resolved, sd+string(os.PathSeparator)) || resolved == sd {
			return resolved, nil
		}
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
