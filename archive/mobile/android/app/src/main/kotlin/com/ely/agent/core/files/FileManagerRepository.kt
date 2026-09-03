// =============================================================================
// @project    ELY — Exactly Like You
// @file       core/files/FileManagerRepository.kt
// @brief      Storage Access Framework wrapper — scan, filter, dedupe, delete
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @license    MIT
//            https://opensource.org/licenses/MIT
// =============================================================================

package com.ely.agent.core.files

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.LinkedList
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Reads a folder selected by the user via the Storage Access Framework
 * (ACTION_OPEN_DOCUMENT_TREE), scans it recursively and exposes filter
 * / dedup / delete operations.
 *
 * All I/O happens on [Dispatchers.IO]. No runtime permissions needed —
 * SAF grants access for exactly the tree the user picked.
 */
@Singleton
class FileManagerRepository @Inject constructor(
    @ApplicationContext private val appContext: Context,
) {

    /**
     * Recursively enumerate every file inside [treeUri]. Returns a flat
     * list ordered by size descending so the UI can highlight the
     * heaviest items first.
     *
     * [maxFiles] caps the enumeration to avoid stalling on very large
     * trees (e.g. the full SD card).
     */
    suspend fun scanTree(
        treeUri: Uri,
        maxFiles: Int = 20_000,
        onProgress: ((scanned: Int) -> Unit)? = null,
    ): List<FileEntry> = withContext(Dispatchers.IO) {
        val root = DocumentFile.fromTreeUri(appContext, treeUri) ?: return@withContext emptyList()
        val result = mutableListOf<FileEntry>()
        val queue: LinkedList<Pair<DocumentFile, String>> = LinkedList()
        queue.add(root to "")
        var scanned = 0

        while (queue.isNotEmpty() && result.size < maxFiles) {
            val (node, prefix) = queue.removeFirst()
            for (child in node.listFiles()) {
                scanned++
                if (scanned % 500 == 0) onProgress?.invoke(scanned)
                val rel = if (prefix.isBlank()) child.name ?: "" else "$prefix/${child.name ?: ""}"
                if (child.isDirectory) {
                    queue.add(child to rel)
                } else {
                    val name = child.name ?: continue
                    val mime = child.type
                    result.add(
                        FileEntry(
                            uri = child.uri,
                            name = name,
                            relativePath = rel,
                            sizeBytes = child.length(),
                            mimeType = mime,
                            lastModified = child.lastModified(),
                            category = FileCategory.fromMime(mime, name),
                        )
                    )
                    if (result.size >= maxFiles) break
                }
            }
        }
        onProgress?.invoke(scanned)
        result.sortedByDescending { it.sizeBytes }
    }

    /**
     * Same as [scanTree] but operates on a plain filesystem path when the
     * app has `MANAGE_EXTERNAL_STORAGE` — this sidesteps the SAF blocklist
     * (Download, Android/data, etc.) that Android 11+ imposes on the tree
     * picker, and also avoids a confirmation dialog for every subfolder.
     */
    suspend fun scanDirectory(
        root: File,
        maxFiles: Int = 50_000,
        onProgress: ((scanned: Int) -> Unit)? = null,
    ): List<FileEntry> = withContext(Dispatchers.IO) {
        if (!root.exists() || !root.isDirectory) return@withContext emptyList()
        val result = mutableListOf<FileEntry>()
        val queue: LinkedList<Pair<File, String>> = LinkedList()
        queue.add(root to "")
        var scanned = 0
        while (queue.isNotEmpty() && result.size < maxFiles) {
            val (node, prefix) = queue.removeFirst()
            val children = node.listFiles() ?: continue
            for (child in children) {
                scanned++
                if (scanned % 500 == 0) onProgress?.invoke(scanned)
                val rel = if (prefix.isBlank()) child.name else "$prefix/${child.name}"
                if (child.isDirectory) {
                    queue.add(child to rel)
                } else {
                    val mime = guessMime(child.name)
                    result.add(
                        FileEntry(
                            uri = Uri.fromFile(child),
                            name = child.name,
                            relativePath = rel,
                            sizeBytes = child.length(),
                            mimeType = mime,
                            lastModified = child.lastModified(),
                            category = FileCategory.fromMime(mime, child.name),
                        )
                    )
                    if (result.size >= maxFiles) break
                }
            }
        }
        onProgress?.invoke(scanned)
        result.sortedByDescending { it.sizeBytes }
    }

    private fun guessMime(name: String): String? {
        val ext = name.substringAfterLast('.', "").lowercase().ifBlank { return null }
        return android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
    }

    /**
     * Compute MD5 for every file in [entries] and return a map of
     * md5 → list of duplicates (only groups of 2+ are returned).
     *
     * For huge trees, [sizeThreshold] lets the caller skip very large
     * files if needed (hashing a 4 GB video is slow).
     */
    suspend fun findExactDuplicates(
        entries: List<FileEntry>,
        sizeThreshold: Long = Long.MAX_VALUE,
        onProgress: ((done: Int, total: Int) -> Unit)? = null,
    ): Map<String, List<FileEntry>> = withContext(Dispatchers.IO) {
        val resolver = appContext.contentResolver
        // First pass: group by size — two files with different sizes can't
        // be exact duplicates, and hashing is expensive, so this prunes
        // hard before we even start.
        val bySize = entries.filter { it.sizeBytes in 1..sizeThreshold }
            .groupBy { it.sizeBytes }
            .filterValues { it.size > 1 }
        val candidates = bySize.values.flatten()
        val hashed = mutableListOf<FileEntry>()
        candidates.forEachIndexed { i, e ->
            val md5 = FileHashing.md5(resolver, e.uri)
            if (md5 != null) hashed.add(e.copy(md5 = md5))
            if (i % 20 == 0) onProgress?.invoke(i, candidates.size)
        }
        onProgress?.invoke(candidates.size, candidates.size)
        hashed.groupBy { it.md5!! }.filterValues { it.size > 1 }
    }

    /**
     * Find near-duplicate images via perceptual dHash. Returns groups
     * of 2+ images with Hamming distance ≤ [maxDistance] (6 is the
     * usual "clearly the same image" threshold).
     *
     * Only operates on [FileCategory.IMAGE] entries.
     */
    suspend fun findSimilarImages(
        entries: List<FileEntry>,
        maxDistance: Int = 6,
        onProgress: ((done: Int, total: Int) -> Unit)? = null,
    ): List<List<FileEntry>> = withContext(Dispatchers.IO) {
        val resolver = appContext.contentResolver
        val images = entries.filter { it.category == FileCategory.IMAGE }
        val hashed = mutableListOf<FileEntry>()
        images.forEachIndexed { i, e ->
            val h = FileHashing.dHash(resolver, e.uri)
            if (h != null) hashed.add(e.copy(pHash = h))
            if (i % 10 == 0) onProgress?.invoke(i, images.size)
        }
        onProgress?.invoke(images.size, images.size)

        // Simple O(n²) grouping — fine up to ~2 000 images. Beyond
        // that we'd need an LSH / BK-tree.
        val visited = BooleanArray(hashed.size)
        val groups = mutableListOf<List<FileEntry>>()
        for (i in hashed.indices) {
            if (visited[i]) continue
            val group = mutableListOf(hashed[i])
            visited[i] = true
            for (j in i + 1 until hashed.size) {
                if (visited[j]) continue
                if (FileHashing.hammingHex(hashed[i].pHash, hashed[j].pHash) <= maxDistance) {
                    group.add(hashed[j])
                    visited[j] = true
                }
            }
            if (group.size > 1) groups.add(group)
        }
        groups
    }

    /**
     * Delete files — the caller is expected to ask the user for
     * confirmation first. Returns the list of entries that failed.
     *
     * Uses DocumentFile.delete() which handles both the normal case
     * and the Android 11+ scoped storage permission model.
     */
    suspend fun delete(uris: List<Uri>): List<Uri> = withContext(Dispatchers.IO) {
        val failed = mutableListOf<Uri>()
        for (u in uris) {
            try {
                if (u.scheme == "file") {
                    // Direct filesystem path — requires MANAGE_EXTERNAL_STORAGE
                    val f = File(u.path ?: "")
                    if (!f.delete()) failed.add(u)
                } else {
                    // SAF-backed document
                    val doc = DocumentFile.fromSingleUri(appContext, u)
                    if (doc == null || !doc.delete()) failed.add(u)
                }
            } catch (_: Exception) {
                failed.add(u)
            }
        }
        failed
    }
}
