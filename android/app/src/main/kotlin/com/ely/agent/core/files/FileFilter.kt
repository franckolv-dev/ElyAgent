// =============================================================================
// @project    ELY — Exactly Like You
// @file       core/files/FileFilter.kt
// @brief      Declarative filter applied to the scan result
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @license    PolyForm Strict License 1.0.0
// =============================================================================

package com.ely.agent.core.files

/**
 * Immutable filter spec — one instance fully describes a selection,
 * can be serialised to JSON (for the Ely NL-to-filter tool) and
 * applied locally via [apply].
 *
 * All criteria are combined with AND. Null/empty fields are ignored.
 */
data class FileFilter(
    /** Lower bound on file size in bytes. */
    val minSizeBytes: Long? = null,
    /** Upper bound on file size in bytes. */
    val maxSizeBytes: Long? = null,
    /** File must be older than this timestamp (epoch ms). */
    val olderThanMs: Long? = null,
    /** File must be newer than this timestamp (epoch ms). */
    val newerThanMs: Long? = null,
    /** Whitelist of categories (image, video, apk, archive, document, audio, other). */
    val categories: Set<String> = emptySet(),
    /** Whitelist of extensions, lowercase, no dot (eg "jpg", "apk"). */
    val extensions: Set<String> = emptySet(),
    /** Substring filter on the file name, case-insensitive. */
    val nameContains: String? = null,
) {
    fun isTrivial(): Boolean =
        minSizeBytes == null && maxSizeBytes == null &&
        olderThanMs == null && newerThanMs == null &&
        categories.isEmpty() && extensions.isEmpty() &&
        nameContains.isNullOrBlank()

    fun apply(entries: List<FileEntry>): List<FileEntry> {
        if (isTrivial()) return entries
        val needle = nameContains?.lowercase()?.trim()
        return entries.filter { e ->
            if (minSizeBytes != null && e.sizeBytes < minSizeBytes) return@filter false
            if (maxSizeBytes != null && e.sizeBytes > maxSizeBytes) return@filter false
            if (olderThanMs != null && e.lastModified > olderThanMs) return@filter false
            if (newerThanMs != null && e.lastModified < newerThanMs) return@filter false
            if (categories.isNotEmpty() && e.category !in categories) return@filter false
            if (extensions.isNotEmpty()) {
                val ext = e.name.substringAfterLast('.', "").lowercase()
                if (ext !in extensions) return@filter false
            }
            if (!needle.isNullOrEmpty() && !e.name.lowercase().contains(needle)) return@filter false
            true
        }
    }

    companion object {
        // ── Presets covering the most common "clean up" requests ──
        val LargeFiles = FileFilter(minSizeBytes = 100L * 1024 * 1024)   // > 100 Mo
        val Apks = FileFilter(extensions = setOf("apk"))
        val Archives = FileFilter(categories = setOf(FileCategory.ARCHIVE))
        val Videos = FileFilter(categories = setOf(FileCategory.VIDEO))

        /** Older than N days. */
        fun olderThanDays(days: Int): FileFilter =
            FileFilter(olderThanMs = System.currentTimeMillis() - days.toLong() * 24 * 3600_000L)

        /**
         * Parse a free-text user request and return a best-effort filter.
         *
         * Supports common cleanup phrasings, in French and English:
         *   - "supprime les apk" / "remove the apks"              → Apks
         *   - "fichiers de plus de 5 Mo"                          → minSizeBytes=5Mo
         *   - "photos plus anciennes que 6 mois"                  → IMAGE + olderThanDays(180)
         *   - "les vidéos"                                        → Videos
         *   - "archives"                                          → Archives
         *   - "fichiers contenant 'facture'"                      → nameContains="facture"
         *
         * This is intentionally local & deterministic — no LLM round-trip.
         * Returns [FileFilter] (possibly empty) and a short human-readable
         * echo of what was understood.
         */
        fun parseNaturalLanguage(input: String): Pair<FileFilter, String> {
            val t = input.lowercase().trim()
            if (t.isBlank()) return FileFilter() to ""

            val explain = StringBuilder()
            var min: Long? = null
            var older: Long? = null
            val cats = mutableSetOf<String>()
            val exts = mutableSetOf<String>()
            var contains: String? = null

            // Size — "plus de 5 mo", "> 500 ko", "supérieur à 1 go"
            Regex("""(?:plus\s*de|sup[ée]rieur[e]?\s*[àa]|>|au\s*moins|gros[^a-z]*)\s*(\d+(?:[.,]\d+)?)\s*(k|m|g)?o""")
                .find(t)?.let { m ->
                    parseSizeInput(m.value.removePrefix(">").trim())?.let {
                        min = it
                        explain.append("taille > ${m.groupValues[1]} ${m.groupValues[2]}o, ")
                    }
                }

            // Age — "plus de 6 mois", "plus vieux que 30 jours", "older than 2 years"
            Regex("""(?:plus\s*(?:de|vieux|anciens?)\s*(?:que|de)?|older\s*than|>)\s*(\d+)\s*(jours?|days?|semaines?|weeks?|mois|months?|ans?|years?)""")
                .find(t)?.let { m ->
                    val n = m.groupValues[1].toIntOrNull() ?: 0
                    val unit = m.groupValues[2]
                    val days = when {
                        unit.startsWith("jour") || unit.startsWith("day") -> n
                        unit.startsWith("sem") || unit.startsWith("week") -> n * 7
                        unit.startsWith("mois") || unit.startsWith("month") -> n * 30
                        unit.startsWith("an") || unit.startsWith("year") -> n * 365
                        else -> 0
                    }
                    if (days > 0) {
                        older = System.currentTimeMillis() - days.toLong() * 24 * 3600_000L
                        explain.append("plus vieux que $days j, ")
                    }
                }

            // Categories
            val catMap = mapOf(
                FileCategory.IMAGE to listOf("photo", "photos", "image", "images", "picture"),
                FileCategory.VIDEO to listOf("video", "vidéo", "vidéos", "videos", "film", "films", "movie"),
                FileCategory.AUDIO to listOf("audio", "musique", "music", "mp3", "chanson"),
                FileCategory.APK to listOf("apk", "apks", "application téléchargée", "applications téléchargées", "downloaded app"),
                FileCategory.DOCUMENT to listOf("document", "documents", "pdf"),
                FileCategory.ARCHIVE to listOf("archive", "archives", "zip", "rar"),
            )
            for ((cat, words) in catMap) {
                if (words.any { w -> Regex("\\b${Regex.escape(w)}\\b").containsMatchIn(t) }) {
                    cats.add(cat)
                    explain.append("$cat, ")
                }
            }

            // Explicit extensions — "fichiers .log", "en .zip"
            Regex("""\.([a-z0-9]{2,5})\b""").findAll(t).forEach {
                exts.add(it.groupValues[1])
                explain.append(".${it.groupValues[1]}, ")
            }

            // Name substring — quoted text
            Regex("""[«"']([^«»"']{2,40})[»"']""").find(t)?.let {
                contains = it.groupValues[1]
                explain.append("nom contient « ${it.groupValues[1]} », ")
            }

            val filter = FileFilter(
                minSizeBytes = min,
                olderThanMs = older,
                categories = cats,
                extensions = exts,
                nameContains = contains,
            )
            val summary = if (filter.isTrivial())
                "Je n'ai rien compris — essaie par exemple « apk », « plus de 5 Mo », « photos plus anciennes que 6 mois »."
            else "Compris : " + explain.toString().trimEnd(',', ' ')
            return filter to summary
        }

        /** Parse "> 5 Mo" / "plus de 5 mb" / "> 100 ko" etc. Returns null if not parseable. */
        fun parseSizeInput(input: String): Long? {
            val t = input.lowercase().trim()
            val match = Regex("""([0-9]+(?:[.,][0-9]+)?)\s*(k|m|g)?o?""").find(t) ?: return null
            val value = match.groupValues[1].replace(',', '.').toDoubleOrNull() ?: return null
            val multiplier = when (match.groupValues[2]) {
                "k" -> 1024.0
                "m" -> 1024.0 * 1024.0
                "g" -> 1024.0 * 1024.0 * 1024.0
                else -> 1.0
            }
            return (value * multiplier).toLong()
        }
    }
}
