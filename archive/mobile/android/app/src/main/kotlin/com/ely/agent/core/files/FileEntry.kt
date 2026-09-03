// =============================================================================
// @project    ELY — Exactly Like You
// @file       core/files/FileEntry.kt
// @brief      Metadata for a single file surfaced by the file manager
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @license    MIT
// =============================================================================

package com.ely.agent.core.files

import android.net.Uri

/**
 * Lightweight projection of a file in the user's picked directory.
 *
 * Intentionally decoupled from Android's DocumentFile — keeps the UI
 * layer working on a plain immutable snapshot that is easy to filter,
 * sort and pass around.
 */
data class FileEntry(
    val uri: Uri,
    val name: String,
    val relativePath: String,
    val sizeBytes: Long,
    val mimeType: String?,
    val lastModified: Long,
    /** "image" | "video" | "audio" | "apk" | "document" | "archive" | "other" */
    val category: String,
    /** MD5 of the binary content (filled lazily for dedup) — null if not yet computed. */
    val md5: String? = null,
    /** Perceptual hash for image similarity (dHash 8×8 → 64 bits hex) — null if not computed / not an image. */
    val pHash: String? = null,
)

object FileCategory {
    const val IMAGE = "image"
    const val VIDEO = "video"
    const val AUDIO = "audio"
    const val APK = "apk"
    const val DOCUMENT = "document"
    const val ARCHIVE = "archive"
    const val OTHER = "other"

    fun fromMime(mime: String?, name: String): String {
        val m = mime?.lowercase().orEmpty()
        val ext = name.substringAfterLast('.', "").lowercase()
        return when {
            m.startsWith("image/") -> IMAGE
            m.startsWith("video/") -> VIDEO
            m.startsWith("audio/") -> AUDIO
            ext == "apk" || m == "application/vnd.android.package-archive" -> APK
            ext in listOf("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt") -> DOCUMENT
            ext in listOf("zip", "rar", "7z", "tar", "gz", "bz2") -> ARCHIVE
            else -> OTHER
        }
    }
}
