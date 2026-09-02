// =============================================================================
// @project    ELY — Exactly Like You
// @file       ui/files/FileManagerViewModel.kt
// @brief      ViewModel — scan, filter, dedupe, delete
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @license    PolyForm Strict License 1.0.0
// =============================================================================

package com.ely.agent.ui.files

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ely.agent.core.files.FileEntry
import com.ely.agent.core.files.FileFilter
import com.ely.agent.core.files.FileManagerRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File
import javax.inject.Inject

enum class ViewMode { LIST, THUMBNAILS }

data class FileManagerUiState(
    val rootUri: Uri? = null,
    val rootPath: String? = null,   // When set, direct File-based access (MANAGE_EXTERNAL_STORAGE)
    val rootLabel: String? = null,
    val viewMode: ViewMode = ViewMode.LIST,
    /** When true, only files currently in [selection] are shown. */
    val showSelectionOnly: Boolean = false,
    val loading: Boolean = false,
    val scanProgress: Int = 0,
    val allEntries: List<FileEntry> = emptyList(),
    val filter: FileFilter = FileFilter(),
    val visibleEntries: List<FileEntry> = emptyList(),
    val selection: Set<Uri> = emptySet(),
    /** Groups of exact duplicates (MD5 matches). */
    val exactDupGroups: List<List<FileEntry>> = emptyList(),
    /** Groups of visually similar images (dHash). */
    val similarImageGroups: List<List<FileEntry>> = emptyList(),
    val dedupRunning: Boolean = false,
    val dedupProgress: Pair<Int, Int>? = null,  // (done, total)
    val error: String? = null,
    val toast: String? = null,
)

@HiltViewModel
class FileManagerViewModel @Inject constructor(
    private val repo: FileManagerRepository,
) : ViewModel() {

    private val _ui = MutableStateFlow(FileManagerUiState())
    val ui: StateFlow<FileManagerUiState> = _ui.asStateFlow()

    fun onTreePicked(uri: Uri, label: String?) {
        _ui.update {
            it.copy(
                rootUri = uri,
                rootPath = null,
                rootLabel = label,
                allEntries = emptyList(),
                visibleEntries = emptyList(),
                selection = emptySet(),
                exactDupGroups = emptyList(),
                similarImageGroups = emptyList(),
                error = null,
            )
        }
        scan()
    }

    /** Scan a folder via plain filesystem path (requires MANAGE_EXTERNAL_STORAGE). */
    fun onDirectPathPicked(path: String, label: String? = null) {
        _ui.update {
            it.copy(
                rootUri = null,
                rootPath = path,
                rootLabel = label ?: File(path).name,
                allEntries = emptyList(),
                visibleEntries = emptyList(),
                selection = emptySet(),
                exactDupGroups = emptyList(),
                similarImageGroups = emptyList(),
                error = null,
            )
        }
        scan()
    }

    fun scan() {
        val state = _ui.value
        val directPath = state.rootPath
        val treeUri = state.rootUri
        if (directPath == null && treeUri == null) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, scanProgress = 0, error = null) }
            try {
                val entries = if (directPath != null) {
                    repo.scanDirectory(File(directPath)) { scanned ->
                        _ui.update { it.copy(scanProgress = scanned) }
                    }
                } else {
                    repo.scanTree(treeUri!!) { scanned ->
                        _ui.update { it.copy(scanProgress = scanned) }
                    }
                }
                _ui.update { s ->
                    s.copy(
                        allEntries = entries,
                        visibleEntries = s.filter.apply(entries),
                        loading = false,
                    )
                }
            } catch (e: Exception) {
                _ui.update { it.copy(loading = false, error = e.message ?: "Scan failed") }
            }
        }
    }

    fun setFilter(filter: FileFilter) {
        _ui.update { s ->
            s.copy(filter = filter, visibleEntries = filter.apply(s.allEntries), selection = emptySet())
        }
    }

    fun clearFilter() = setFilter(FileFilter())

    fun toggleSelection(uri: Uri) {
        _ui.update { s ->
            val next = s.selection.toMutableSet()
            if (!next.add(uri)) next.remove(uri)
            s.copy(selection = next)
        }
    }

    fun selectAllVisible() {
        _ui.update { s -> s.copy(selection = s.visibleEntries.map { it.uri }.toSet()) }
    }

    fun clearSelection() {
        _ui.update { s -> s.copy(selection = emptySet(), showSelectionOnly = false) }
    }

    fun toggleViewMode() {
        _ui.update { s ->
            s.copy(viewMode = if (s.viewMode == ViewMode.LIST) ViewMode.THUMBNAILS else ViewMode.LIST)
        }
    }

    /** Delete the current selection. Caller must have already confirmed with the user. */
    fun deleteSelection(onDone: (removed: Int, failed: Int) -> Unit) {
        val toDelete = _ui.value.selection.toList()
        if (toDelete.isEmpty()) return
        viewModelScope.launch {
            val failed = repo.delete(toDelete)
            val removed = toDelete.size - failed.size
            _ui.update { s ->
                val remaining = s.allEntries.filter { it.uri !in toDelete || it.uri in failed }
                val newSelection = failed.toSet()
                s.copy(
                    allEntries = remaining,
                    visibleEntries = s.filter.apply(remaining),
                    selection = newSelection,
                    // If everything was deleted, exit the "selection only"
                    // view so the user doesn't land on an empty list.
                    showSelectionOnly = s.showSelectionOnly && newSelection.isNotEmpty(),
                    toast = if (failed.isEmpty()) "$removed fichier(s) supprimé(s)"
                            else "$removed supprimé(s), ${failed.size} échec(s)",
                )
            }
            onDone(removed, failed.size)
        }
    }

    fun runExactDuplicateScan() {
        val entries = _ui.value.allEntries
        if (entries.isEmpty()) return
        viewModelScope.launch {
            _ui.update { it.copy(dedupRunning = true, dedupProgress = 0 to 0) }
            val groups = repo.findExactDuplicates(entries) { d, t ->
                _ui.update { it.copy(dedupProgress = d to t) }
            }
            _ui.update {
                it.copy(
                    dedupRunning = false,
                    dedupProgress = null,
                    exactDupGroups = groups.values.toList()
                        .sortedByDescending { it.sumOf { e -> e.sizeBytes } },
                    toast = if (groups.isEmpty()) "Aucun doublon exact trouvé"
                            else "${groups.size} groupe(s) de doublons trouvés",
                )
            }
        }
    }

    fun runSimilarImageScan() {
        val entries = _ui.value.allEntries
        if (entries.isEmpty()) return
        viewModelScope.launch {
            _ui.update { it.copy(dedupRunning = true, dedupProgress = 0 to 0) }
            val groups = repo.findSimilarImages(entries) { d, t ->
                _ui.update { it.copy(dedupProgress = d to t) }
            }
            _ui.update {
                it.copy(
                    dedupRunning = false,
                    dedupProgress = null,
                    similarImageGroups = groups.sortedByDescending { it.sumOf { e -> e.sizeBytes } },
                    toast = if (groups.isEmpty()) "Aucune image similaire trouvée"
                            else "${groups.size} groupe(s) d'images similaires",
                )
            }
        }
    }

    /**
     * Pre-select one file per duplicate group, keeping the one with the
     * largest size (assumed best quality). Duplicates of smaller size
     * land in the selection ready for deletion.
     */
    fun selectDuplicatesForDeletion(groups: List<List<FileEntry>>) {
        val toDelete = mutableSetOf<Uri>()
        for (g in groups) {
            val keeper = g.maxByOrNull { it.sizeBytes } ?: continue
            g.filter { it.uri != keeper.uri }.forEach { toDelete.add(it.uri) }
        }
        // After an automatic dedup selection, switch the main view to
        // "selection only" so the user immediately sees exactly what Ely
        // picked to delete — no need to scroll the full folder.
        _ui.update { it.copy(selection = toDelete, showSelectionOnly = toDelete.isNotEmpty()) }
    }

    fun setShowSelectionOnly(enabled: Boolean) {
        _ui.update { it.copy(showSelectionOnly = enabled) }
    }

    fun consumeToast() {
        _ui.update { it.copy(toast = null) }
    }
}
