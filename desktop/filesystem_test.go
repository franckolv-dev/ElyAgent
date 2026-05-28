// =============================================================================
// @project    ELY — Exactly Like You
// @file       desktop/filesystem_test.go
// @brief      Security tests for FSHandler.validatePath
// @license    Elastic License 2.0
// =============================================================================
//
// Hotfix 2026-05-28 — code-review-2026_05_28.md flagged validatePath as
// fragile (manual symlink resolution + string-prefix sandbox check). These
// tests pin the security contract: NO path outside the configured sandbox
// dirs must ever resolve to a valid result, even with symlink chains,
// `..` traversal, partial-prefix tricks, or write-through-symlink attempts
// on non-existent paths.
//
// The TEST CASES were written first (TDD-for-security): every one of them
// targets a specific class of attack we want validatePath to reject.

package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// ─── helpers ───────────────────────────────────────────────────────────────

// newSandbox creates a temporary directory tree representing the user's
// "authorised" sandbox + an "outside" directory that MUST NOT be reachable.
// Returns (sandboxDir, outsideDir, cleanup).
func newSandbox(t *testing.T) (string, string, func()) {
	t.Helper()
	root := t.TempDir()
	sandbox := filepath.Join(root, "sandbox")
	outside := filepath.Join(root, "outside")
	if err := os.MkdirAll(sandbox, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	// Plant a "secret" file outside the sandbox that no attack should reach.
	if err := os.WriteFile(filepath.Join(outside, "secret.txt"),
		[]byte("TOP SECRET"), 0o600); err != nil {
		t.Fatal(err)
	}
	return sandbox, outside, func() {}
}

func mustFail(t *testing.T, h *FSHandler, path, why string) {
	t.Helper()
	if _, err := h.validatePath(path); err == nil {
		t.Errorf("SECURITY: validatePath(%q) returned no error — %s", path, why)
	}
}

func mustPass(t *testing.T, h *FSHandler, path, why string) {
	t.Helper()
	if _, err := h.validatePath(path); err != nil {
		t.Errorf("validatePath(%q) returned error %v — %s", path, err, why)
	}
}

// ─── basic invariants ──────────────────────────────────────────────────────

func TestValidatePath_EmptyRejected(t *testing.T) {
	h := NewFSHandler([]string{t.TempDir()})
	mustFail(t, h, "", "empty path must always fail")
}

func TestValidatePath_RelativeRejected(t *testing.T) {
	h := NewFSHandler([]string{t.TempDir()})
	mustFail(t, h, "relative/file.txt", "relative paths are unsafe — caller must always pass absolute")
}

func TestValidatePath_InsideSandboxAccepted(t *testing.T) {
	sandbox, _, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	if err := os.WriteFile(filepath.Join(sandbox, "ok.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	mustPass(t, h, filepath.Join(sandbox, "ok.txt"), "trivial inside-sandbox path must pass")
}

func TestValidatePath_NestedInsideSandboxAccepted(t *testing.T) {
	sandbox, _, cleanup := newSandbox(t)
	defer cleanup()
	nested := filepath.Join(sandbox, "deep", "nested", "dir")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	h := NewFSHandler([]string{sandbox})
	mustPass(t, h, filepath.Join(nested, "f.txt"),
		"deep nested write inside sandbox must pass even if file doesn't exist yet")
}

// ─── attack vectors that MUST be rejected ──────────────────────────────────

// Attack 1 — naive directory traversal with ..
func TestValidatePath_RejectsDotDotEscape(t *testing.T) {
	sandbox, outside, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	rel := "../" + filepath.Base(outside) + "/secret.txt"
	mustFail(t, h, filepath.Join(sandbox, rel),
		"`/sandbox/../outside/secret.txt` MUST be rejected")
}

// Attack 2 — symlink in the sandbox pointing outside
func TestValidatePath_RejectsSymlinkPointingOutside(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks require admin on Windows")
	}
	sandbox, outside, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	// Plant a symlink INSIDE the sandbox that points OUTSIDE.
	linkPath := filepath.Join(sandbox, "evil_link")
	if err := os.Symlink(outside, linkPath); err != nil {
		t.Fatal(err)
	}
	// Reading through the symlink would expose outside/secret.txt
	mustFail(t, h, filepath.Join(linkPath, "secret.txt"),
		"symlink pointing outside the sandbox must be detected after EvalSymlinks")
}

// Attack 3 — symlink ON the sandbox dir itself, set by the user via
// the Settings UI. validatePath must resolve symlinks on sandboxDirs too
// (which NewFSHandler does) so the comparison is between fully-resolved
// canonical paths.
func TestValidatePath_RespectsResolvedSandboxRoot(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks require admin on Windows")
	}
	root := t.TempDir()
	realDir := filepath.Join(root, "real_sandbox")
	if err := os.MkdirAll(realDir, 0o755); err != nil {
		t.Fatal(err)
	}
	linkedDir := filepath.Join(root, "linked_sandbox")
	if err := os.Symlink(realDir, linkedDir); err != nil {
		t.Fatal(err)
	}
	// User configured the sandbox via the symlink path.
	h := NewFSHandler([]string{linkedDir})
	// Both forms (symlink path + real path) must accept files inside.
	if err := os.WriteFile(filepath.Join(realDir, "ok.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	mustPass(t, h, filepath.Join(linkedDir, "ok.txt"), "access via the symlink path must work")
	mustPass(t, h, filepath.Join(realDir, "ok.txt"), "access via the real path must also work")
}

// Attack 4 — REGRESSION: prefix-match trick. If sandbox=`/sb` and the
// candidate path is `/sb-evil/foo`, a naive HasPrefix check would accept
// it. The +PathSeparator suffix the current code uses prevents this, but
// the rewritten validatePath must keep that guarantee — pin it with a test.
func TestValidatePath_RejectsPrefixSiblingDir(t *testing.T) {
	root := t.TempDir()
	sandbox := filepath.Join(root, "sb")
	sibling := filepath.Join(root, "sb-evil")
	if err := os.MkdirAll(sandbox, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(sibling, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sibling, "secret.txt"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	h := NewFSHandler([]string{sandbox})
	mustFail(t, h, filepath.Join(sibling, "secret.txt"),
		"`/root/sb-evil/secret.txt` MUST be rejected even though it starts with the sandbox name `sb`")
}

// Attack 5 — write to a non-existent file whose PARENT contains a symlink
// pointing outside the sandbox. The current code resolves the parent of
// the candidate path; the rewritten version must keep doing so AND
// re-check the resolved candidate against the sandbox.
func TestValidatePath_RejectsWriteThroughIntermediateSymlink(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks require admin on Windows")
	}
	sandbox, outside, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	// Inside the sandbox, create a symlink that points OUTSIDE.
	innerLink := filepath.Join(sandbox, "secret_link")
	if err := os.Symlink(outside, innerLink); err != nil {
		t.Fatal(err)
	}
	// Now try to WRITE a brand new file through that symlink.
	mustFail(t, h, filepath.Join(innerLink, "new_evil_file.txt"),
		"writing a NEW file through an intermediate symlink pointing outside MUST be rejected")
}

// Attack 6 — partial path with traversal that re-enters via a different name.
// `/sandbox/../sandbox/foo.txt` clean is `/sandbox/foo.txt` so it's legitimate.
// `/sandbox/../outside/foo.txt` clean is `/outside/foo.txt` so it's traversal.
// Pin both behaviours.
func TestValidatePath_TraversalIntoSameSandboxIsLegal(t *testing.T) {
	sandbox, _, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	if err := os.WriteFile(filepath.Join(sandbox, "ok.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	mustPass(t, h,
		filepath.Join(sandbox, "..", filepath.Base(sandbox), "ok.txt"),
		"path that re-enters the same sandbox after a `..` must work (filepath.Clean handles it)")
}

// Attack 7 — sandbox dir itself must be accessible (e.g. for ListDir on root)
func TestValidatePath_AcceptsSandboxRootItself(t *testing.T) {
	sandbox, _, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox})
	mustPass(t, h, sandbox, "sandbox root itself must be listable")
}

// Attack 8 — trailing slash on sandbox config must be handled.
// If user types `/Users/franck/Documents/` in Settings, normalisation
// must strip the slash so the prefix check still works.
func TestValidatePath_TrailingSlashOnSandboxDir(t *testing.T) {
	sandbox, _, cleanup := newSandbox(t)
	defer cleanup()
	h := NewFSHandler([]string{sandbox + string(os.PathSeparator)})
	if err := os.WriteFile(filepath.Join(sandbox, "ok.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	mustPass(t, h, filepath.Join(sandbox, "ok.txt"),
		"trailing slash in sandbox config must be normalised, not break the check")
}

// Attack 9 — multiple sandbox dirs. Each must be independently checked.
func TestValidatePath_MultipleSandboxDirs(t *testing.T) {
	root := t.TempDir()
	sb1 := filepath.Join(root, "sb1")
	sb2 := filepath.Join(root, "sb2")
	other := filepath.Join(root, "other")
	for _, d := range []string{sb1, sb2, other} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	h := NewFSHandler([]string{sb1, sb2})
	mustPass(t, h, filepath.Join(sb1, "a.txt"), "first sandbox dir")
	mustPass(t, h, filepath.Join(sb2, "b.txt"), "second sandbox dir")
	mustFail(t, h, filepath.Join(other, "c.txt"), "not in any sandbox dir")
}

// Attack 10 — REAL vulnerability in the pre-hotfix code: write a NEW file
// whose grand-parent doesn't exist, with a symlink at an intermediate
// level pointing outside the sandbox. The original validatePath only
// EvalSymlinks the IMMEDIATE parent; if that parent doesn't exist, the
// fallback leaves `resolved` as the unresolved abs path, which still
// starts with `/sandbox/` and would be ACCEPTED by the prefix check.
//
// Concretely : sandbox=/sb, attacker has /sb/evil_link → /outside, the
// agent is told to write /sb/evil_link/missing_dir/newfile.txt. The
// chain is :
//   - filepath.Dir(abs) = /sb/evil_link/missing_dir  (doesn't exist)
//   - EvalSymlinks(/sb/evil_link/missing_dir)         → error
//   - resolved stays = /sb/evil_link/missing_dir/newfile.txt (unresolved)
//   - prefix check : HasPrefix(resolved, "/sb/")      → TRUE !
//   - → ACCEPTED, then os.MkdirAll follows the symlink → /outside/missing_dir
//     gets created, then /outside/missing_dir/newfile.txt is written.
//
// The hardened validatePath must walk UP until it finds an existing
// ancestor, EvalSymlinks IT, then re-join with the missing components.
func TestValidatePath_RejectsDeepSymlinkWithMissingIntermediateDirs(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks require admin on Windows")
	}
	sandbox, outside, cleanup := newSandbox(t)
	defer cleanup()
	// IMPORTANT: feed validatePath the EvalSymlinks'd form of the sandbox
	// so the comparison isn't an accidental pass due to macOS `/tmp` →
	// `/private/tmp` mismatch. We want this test to exercise the
	// validatePath logic, not OS path-normalisation quirks.
	resolvedSandbox, err := filepath.EvalSymlinks(sandbox)
	if err != nil {
		t.Fatal(err)
	}
	resolvedOutside, err := filepath.EvalSymlinks(outside)
	if err != nil {
		t.Fatal(err)
	}
	h := NewFSHandler([]string{resolvedSandbox})
	// Plant a symlink INSIDE the sandbox that points OUTSIDE.
	linkPath := filepath.Join(resolvedSandbox, "evil_link")
	if err := os.Symlink(resolvedOutside, linkPath); err != nil {
		t.Fatal(err)
	}
	// Now ask to write /sandbox/evil_link/MISSING_DIR/newfile.txt — the
	// missing_dir doesn't exist yet, which would defeat the parent-only
	// EvalSymlinks fallback.
	target := filepath.Join(linkPath, "missing_dir", "newfile.txt")
	mustFail(t, h, target,
		"SECURITY: write to /sandbox/symlink_to_outside/MISSING/file MUST be rejected — "+
			"the parent-only EvalSymlinks fallback fails on missing dirs and lets the path through")
}

// Attack 11 — same class, even deeper. Multiple missing intermediate dirs.
func TestValidatePath_RejectsVeryDeepMissingPathThroughSymlink(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlinks require admin on Windows")
	}
	sandbox, outside, cleanup := newSandbox(t)
	defer cleanup()
	resolvedSandbox, err := filepath.EvalSymlinks(sandbox)
	if err != nil {
		t.Fatal(err)
	}
	resolvedOutside, err := filepath.EvalSymlinks(outside)
	if err != nil {
		t.Fatal(err)
	}
	h := NewFSHandler([]string{resolvedSandbox})
	linkPath := filepath.Join(resolvedSandbox, "evil_link")
	if err := os.Symlink(resolvedOutside, linkPath); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(linkPath, "a", "b", "c", "d", "e", "newfile.txt")
	mustFail(t, h, target,
		"SECURITY: arbitrarily deep missing-dir chain through a symlink MUST be rejected")
}

// ─── ~ expansion ────────────────────────────────────────────────────────────

func TestExpandHome_TildeAlone(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil {
		t.Skip("no home dir")
	}
	if got := expandHome("~"); got != home {
		t.Errorf("expandHome(~) = %q, want %q", got, home)
	}
}

func TestExpandHome_TildeSlash(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil {
		t.Skip("no home dir")
	}
	got := expandHome("~/Documents")
	want := filepath.Join(home, "Documents")
	if got != want {
		t.Errorf("expandHome(~/Documents) = %q, want %q", got, want)
	}
}

func TestExpandHome_NoTildeUnchanged(t *testing.T) {
	if got := expandHome("/abs/path"); got != "/abs/path" {
		t.Errorf("expandHome(/abs/path) modified the path: %q", got)
	}
}

// TestExpandHome_TildeUserPattern documents that ~user is intentionally
// NOT supported (POSIX-only, rarely used, would require pwd lookup).
// The path is returned unchanged so the misconfiguration is visible.
func TestExpandHome_TildeUserUnchanged(t *testing.T) {
	if got := expandHome("~someuser/file"); !strings.HasPrefix(got, "~") {
		t.Errorf("expandHome(~someuser/file) unexpectedly expanded: %q", got)
	}
}
