// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/components/LinkifiedText.kt
// @brief      Text composable that auto-detects URLs and makes them tappable
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
// @version    1.1.0
// =============================================================================

package com.ely.agent.ui.components

import android.content.Intent
import androidx.compose.foundation.text.ClickableText
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.core.net.toUri

/**
 * URL regex that matches:
 *   - http(s)://example.com/path?q=1
 *   - www.example.com
 *   - example.com (domain with at least one dot and a known TLD-ish pattern)
 * Bracket / paren boundaries are treated as delimiters so "(https://x.com)"
 * doesn't swallow the trailing ")" into the link.
 */
private val URL_REGEX = Regex(
    """((https?://|www\.)[^\s<>()\[\]"']+)""",
    RegexOption.IGNORE_CASE,
)

/**
 * A [Text] replacement that detects URLs in [content] and makes them
 * tappable — tapping opens the default browser.
 *
 * Falls back to plain [Text] if no URL is found (zero-cost on most messages).
 */
@Composable
fun LinkifiedText(
    content: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.bodyLarge,
    color: Color = LocalContentColor.current,
) {
    val matches = remember(content) { URL_REGEX.findAll(content).toList() }
    if (matches.isEmpty()) {
        // Fast path — no link, plain text (no recomposition cost)
        Text(text = content, modifier = modifier, style = style, color = color)
        return
    }

    val context = LocalContext.current
    val linkColor = MaterialTheme.colorScheme.primary

    val annotated = remember(content, linkColor) {
        buildAnnotatedStringWithLinks(content, matches, linkColor)
    }

    ClickableText(
        text = annotated,
        modifier = modifier,
        style = style.copy(color = color),
        onClick = { offset ->
            annotated.getStringAnnotations(tag = "URL", start = offset, end = offset)
                .firstOrNull()
                ?.let { annotation ->
                    val url = annotation.item.let {
                        if (it.startsWith("http", ignoreCase = true)) it else "https://$it"
                    }
                    try {
                        context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
                    } catch (_: Exception) {
                        // No browser installed or malformed URL — silent fail
                    }
                }
        },
    )
}

private fun buildAnnotatedStringWithLinks(
    text: String,
    matches: List<MatchResult>,
    linkColor: Color,
): AnnotatedString {
    val builder = AnnotatedString.Builder()
    var cursor = 0
    for (m in matches) {
        val range = m.range
        // Plain text before the link
        if (cursor < range.first) {
            builder.append(text.substring(cursor, range.first))
        }
        // The link itself — styled + annotated
        val url = m.value
        val linkStart = builder.length
        builder.withStyle(
            SpanStyle(
                color = linkColor,
                textDecoration = TextDecoration.Underline,
            )
        ) {
            append(url)
        }
        builder.addStringAnnotation(
            tag = "URL",
            annotation = url,
            start = linkStart,
            end = builder.length,
        )
        cursor = range.last + 1
    }
    // Remaining text after the last link
    if (cursor < text.length) {
        builder.append(text.substring(cursor))
    }
    return builder.toAnnotatedString()
}
