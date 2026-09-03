// =============================================================================
// @project    ELY — Exactly Like You
// @file       core/files/FileHashing.kt
// @brief      MD5 + perceptual dHash — for duplicate detection
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @license    MIT
// =============================================================================

package com.ely.agent.core.files

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import java.io.InputStream
import java.security.MessageDigest

/**
 * Utilities to compute content hashes for duplicate detection.
 *
 * - [md5] — exact binary duplicate detection. Fast and 100 % accurate
 *   for files copied/moved without modification.
 * - [dHash] — perceptual hash for images (8×9 → 64 bits). Robust to
 *   resize, re-encoding and small edits. Hamming distance ≤ 6 usually
 *   means same image.
 */
object FileHashing {

    /** MD5 of the whole binary content. Returns null on I/O error. */
    fun md5(resolver: ContentResolver, uri: Uri): String? {
        return try {
            resolver.openInputStream(uri)?.use { input ->
                val md = MessageDigest.getInstance("MD5")
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n <= 0) break
                    md.update(buf, 0, n)
                }
                md.digest().joinToString("") { "%02x".format(it) }
            }
        } catch (_: Exception) { null }
    }

    /**
     * Perceptual dHash 8×9 → 64 bits → hex string of length 16.
     *
     * Algorithm (reliable, well-known):
     *   1. Decode the image downsampled to 9 × 8 (width × height).
     *   2. Convert each pixel to grayscale luminance.
     *   3. For each row, compare adjacent pixels horizontally.
     *      Bit = 1 if left > right, else 0. This gives 8 × 8 = 64 bits.
     *   4. Pack into a 16-char hex string.
     */
    fun dHash(resolver: ContentResolver, uri: Uri): String? {
        return try {
            val options = BitmapFactory.Options().apply {
                inJustDecodeBounds = true
            }
            resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }

            val sampleSize = run {
                val maxSide = maxOf(options.outWidth, options.outHeight)
                if (maxSide <= 256) 1 else maxOf(1, maxSide / 256)
            }

            val decode = BitmapFactory.Options().apply {
                inSampleSize = sampleSize
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
            val src: Bitmap = resolver.openInputStream(uri)?.use { input ->
                BitmapFactory.decodeStream(input, null, decode)
            } ?: return null

            // Resize to 9×8 for dHash
            val small = Bitmap.createScaledBitmap(src, 9, 8, true)
            src.recycle()

            // Compute 8 * 8 = 64 bits
            var bits = 0L
            var i = 0
            for (y in 0 until 8) {
                for (x in 0 until 8) {
                    val left = small.getPixel(x, y)
                    val right = small.getPixel(x + 1, y)
                    val leftLum = _luminance(left)
                    val rightLum = _luminance(right)
                    if (leftLum > rightLum) {
                        bits = bits or (1L shl (63 - i))
                    }
                    i++
                }
            }
            small.recycle()

            "%016x".format(bits)
        } catch (_: Exception) { null }
    }

    /** Hamming distance between two hex hashes. Returns 64 if either is invalid. */
    fun hammingHex(a: String?, b: String?): Int {
        if (a == null || b == null || a.length != b.length) return 64
        val la = a.toLongOrNull(16) ?: return 64
        val lb = b.toLongOrNull(16) ?: return 64
        return (la xor lb).countOneBits()
    }

    private fun _luminance(pixel: Int): Int {
        // Standard ITU-R BT.601 luma
        val r = Color.red(pixel)
        val g = Color.green(pixel)
        val b = Color.blue(pixel)
        return (r * 299 + g * 587 + b * 114) / 1000
    }
}
