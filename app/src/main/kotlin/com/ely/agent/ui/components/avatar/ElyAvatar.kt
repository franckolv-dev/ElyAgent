package com.ely.agent.ui.components.avatar

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlin.math.*

/**
 * Avatar wireframe animé d'ELY pour Android.
 *
 * Reproduit fidèlement l'esthétique du composant desktop (CyberpunkAvatar / AvatarScene.tsx) :
 * - Grille sphérique (lignes de latitude + longitude)
 * - 5 états avec transition de couleur fluide
 * - Animation de respiration
 * - Scan line animée
 * - Balancement de tête (THINKING)
 * - Pulsation de la zone bouche (SPEAKING)
 * - Effet de glitch (ALERT)
 * - Overlay HUD (NEURAL, SYNC, LAT, VER, état courant)
 */
@Composable
fun ElyAvatar(
    state: AvatarState,
    modifier: Modifier = Modifier
) {
    // Compteur de temps en secondes (≈60 fps)
    var t by remember { mutableStateOf(0f) }
    LaunchedEffect(Unit) {
        val start = System.currentTimeMillis()
        while (true) {
            t = (System.currentTimeMillis() - start) / 1000f
            delay(16L)
        }
    }

    // Transition de couleur fluide entre états (même lerp 0.08 que le shader desktop)
    val animatedColor by animateColorAsState(
        targetValue = state.color,
        animationSpec = tween(durationMillis = 500),
        label = "avatarColor"
    )

    Box(
        modifier = modifier
            .background(Color(0xFF060C12))
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawWireframeAvatar(t, animatedColor, state)
        }
        HudOverlay(state = state, color = animatedColor)
    }
}

// ---------------------------------------------------------------------------
// Dessin principal du wireframe
// ---------------------------------------------------------------------------

private fun DrawScope.drawWireframeAvatar(t: Float, color: Color, state: AvatarState) {
    val cx = size.width / 2f
    val cy = size.height / 2f

    // Taille de base : s'adapte à la zone disponible
    val baseRx = minOf(size.width * 0.29f, size.height * 0.36f)
    val baseRy = minOf(size.height * 0.40f, size.width * 0.36f)

    // --- Animations dépendant de l'état ---

    // Respiration : sin(uTime * 0.7) * 0.003 dans le shader → 2.2 % de variation ici
    val breathSpeed = if (state == AvatarState.LISTENING) 3f else 0.7f
    val breathScale = 1f + 0.022f * sin(t * breathSpeed)
    val rx = baseRx * breathScale
    val ry = baseRy * breathScale

    // Balancement de tête (THINKING) : sin(t * 0.5) * 0.12 rad → ~8° max
    val swayDx = if (state == AvatarState.THINKING) sin(t * 0.5f) * baseRx * 0.09f else 0f

    // Décalage glitch horizontal (ALERT)
    val glitchDx = if (state == AvatarState.ALERT) {
        val seed = (t * 13f).toInt()
        if (seed % 7 == 0) ((seed * 11 + 37) % 9 - 4) * 3f else 0f
    } else 0f

    // Pulsation de l'alpha (ALERT) : 0.7 + 0.3 * |sin(t * 4)|
    val alphaPulse = if (state == AvatarState.ALERT) 0.7f + 0.3f * abs(sin(t * 4f)) else 1f

    // Position de la scan line : fract(uTime * 0.08)
    val scanPos = (t * 0.08f) % 1f

    // Éclat de la zone bouche (SPEAKING) — blink 8 fois/s avec décroissance
    val mouthBoost = if (state == AvatarState.SPEAKING) {
        val phase = (t * 8f) % 1f
        if (phase < 0.15f) (1f - phase / 0.15f) * 3.5f else 0f
    } else 0f

    val faceCx = cx + swayDx + glitchDx

    // Halo ambiant (simule le bloom du desktop)
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(color.copy(alpha = 0.09f * alphaPulse), Color.Transparent),
            center = Offset(faceCx, cy),
            radius = rx * 1.7f
        ),
        radius = rx * 1.7f,
        center = Offset(faceCx, cy)
    )

    // Zone de clip = ellipse du visage
    val facePath = Path().apply {
        addOval(Rect(faceCx - rx, cy - ry, faceCx + rx, cy + ry))
    }

    clipPath(facePath) {
        val strokePx = 1.3.dp.toPx()
        val numLat = 9   // lignes de latitude
        val lonWidths = floatArrayOf(0.87f, 0.71f, 0.50f, 0.26f) // fractions de rx

        // --- Lignes de longitude (ellipses verticales) ---
        for (w in lonWidths) {
            val hw = rx * w
            val fresnel = 0.25f + 0.35f * w
            val alpha = (fresnel * 0.85f) * alphaPulse
            drawOval(
                color = color.copy(alpha = alpha),
                topLeft = Offset(faceCx - hw, cy - ry),
                size = Size(hw * 2f, ry * 2f),
                style = Stroke(width = strokePx)
            )
        }
        // Méridien central (longitude 90° → trait vertical)
        val lonCenterAlpha = 0.30f * alphaPulse
        drawLine(
            color = color.copy(alpha = lonCenterAlpha),
            start = Offset(faceCx, cy - ry),
            end = Offset(faceCx, cy + ry),
            strokeWidth = strokePx
        )

        // --- Lignes de latitude (arcs courbés pour l'effet 3D) ---
        for (i in 0..numLat) {
            val phi = (-PI.toFloat() / 2f + PI.toFloat() * i / numLat)
            val lineY = cy + ry * sin(phi)
            val halfW = rx * cos(phi)

            if (halfW < 2f) continue  // trop proche des pôles, on saute

            // Effet fresnel : les bords (près des pôles) sont plus lumineux
            val fresnel = 0.25f + 0.50f * abs(sin(phi))
            var baseAlpha = (0.28f + fresnel * 0.32f) * alphaPulse

            // Boost scan line
            val normY = (lineY - (cy - ry)) / (2f * ry)
            val scanDist = abs(normY - scanPos)
            val scanBoost = (1f - smoothStep(0f, 0.08f, scanDist)) * 0.28f
            baseAlpha = (baseAlpha + scanBoost).coerceIn(0f, 1f)

            // Boost zone bouche (SPEAKING) — tiers inférieur du visage
            val mouthFactor = if (mouthBoost > 0f && phi < 0f && phi > -PI.toFloat() * 0.45f)
                mouthBoost * 0.14f else 0f
            val lineAlpha = (baseAlpha + mouthFactor).coerceIn(0f, 1f)

            // Courbure des lignes de latitude : simule la surface sphérique
            // phi > 0 (moitié haute) → l'arc se bombe vers le haut ; phi < 0 → vers le bas
            val curvature = sin(phi) * halfW * 0.14f

            val path = Path().apply {
                moveTo(faceCx - halfW, lineY)
                cubicTo(
                    faceCx - halfW * 0.5f, lineY - curvature,
                    faceCx + halfW * 0.5f, lineY - curvature,
                    faceCx + halfW, lineY
                )
            }
            drawPath(path, color = color.copy(alpha = lineAlpha), style = Stroke(width = strokePx))
        }

        // --- Nœuds de grille (intersections latitude × longitude) ---
        val nodeR = 2.dp.toPx()
        for (i in 1 until numLat) {
            val phi = (-PI.toFloat() / 2f + PI.toFloat() * i / numLat)
            val lineY = cy + ry * sin(phi)
            val halfW = rx * cos(phi)
            if (halfW < 2f) continue

            val normY = (lineY - (cy - ry)) / (2f * ry)
            val scanBoost = (1f - smoothStep(0f, 0.08f, abs(normY - scanPos))) * 0.45f

            for (w in lonWidths) {
                val nodeHw = halfW * w  // intersection réelle sur la sphère
                val nodeAlpha = (0.48f + scanBoost) * alphaPulse
                drawCircle(color.copy(alpha = nodeAlpha), nodeR, Offset(faceCx + nodeHw, lineY))
                drawCircle(color.copy(alpha = nodeAlpha * 0.65f), nodeR, Offset(faceCx - nodeHw, lineY))
            }
        }

        // --- Scan line (bande lumineuse animée) ---
        val scanY = (cy - ry) + scanPos * 2f * ry
        drawRect(
            brush = Brush.horizontalGradient(
                colors = listOf(
                    Color.Transparent,
                    color.copy(alpha = 0.42f * alphaPulse),
                    color.copy(alpha = 0.42f * alphaPulse),
                    Color.Transparent
                ),
                startX = faceCx - rx, endX = faceCx + rx
            ),
            topLeft = Offset(faceCx - rx, scanY - 1.5.dp.toPx()),
            size = Size(rx * 2f, 3.dp.toPx())
        )

        // --- Lignes de glitch (ALERT) ---
        if (state == AvatarState.ALERT) {
            val seed = (t * 7f).toInt()
            if (seed % 5 == 0) {
                val glitchY = cy + (((seed * 17 + 43) % 100 - 50) / 50f) * ry
                drawRect(
                    color = color.copy(alpha = 0.55f),
                    topLeft = Offset(faceCx - rx * 0.88f, glitchY - 1.dp.toPx()),
                    size = Size(rx * 1.76f, 2.dp.toPx())
                )
            }
        }
    }

    // --- Contour du visage (dessiné après le clip pour l'éclat de bord) ---
    drawOval(
        color = color.copy(alpha = 0.60f * alphaPulse),
        topLeft = Offset(faceCx - rx, cy - ry),
        size = Size(rx * 2f, ry * 2f),
        style = Stroke(width = 1.8.dp.toPx())
    )
    // Halo de bord (effet fresnel)
    drawOval(
        color = color.copy(alpha = 0.20f * alphaPulse),
        topLeft = Offset(faceCx - rx - 3.dp.toPx(), cy - ry - 3.dp.toPx()),
        size = Size((rx + 3.dp.toPx()) * 2f, (ry + 3.dp.toPx()) * 2f),
        style = Stroke(width = 5.dp.toPx())
    )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

private fun smoothStep(edge0: Float, edge1: Float, x: Float): Float {
    val t = ((x - edge0) / (edge1 - edge0)).coerceIn(0f, 1f)
    return t * t * (3f - 2f * t)
}

// ---------------------------------------------------------------------------
// Overlay HUD (miroir exact du desktop)
// ---------------------------------------------------------------------------

@Composable
private fun BoxScope.HudOverlay(state: AvatarState, color: Color) {
    // Haut-gauche
    Column(
        modifier = Modifier
            .align(Alignment.TopStart)
            .padding(start = 10.dp, top = 8.dp)
    ) {
        HudText("NEURAL:98.3%", color)
        HudText("SYNC:99.72", color)
    }
    // Haut-droite
    Column(
        modifier = Modifier
            .align(Alignment.TopEnd)
            .padding(end = 10.dp, top = 8.dp),
        horizontalAlignment = Alignment.End
    ) {
        HudText("LAT:12ms", color)
        HudText("VER:3.0.0", color)
    }
    // Bas-centre : label d'état avec bordure lumineuse
    Box(
        modifier = Modifier
            .align(Alignment.BottomCenter)
            .padding(bottom = 8.dp)
            .background(color.copy(alpha = 0.10f), MaterialTheme.shapes.extraSmall)
            .padding(horizontal = 10.dp, vertical = 3.dp)
    ) {
        Text(
            text = "ELY :: ${state.label}",
            color = color,
            fontSize = 10.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.2.sp
        )
    }
}

@Composable
private fun HudText(text: String, color: Color) {
    Text(
        text = text,
        color = color.copy(alpha = 0.62f),
        fontSize = 8.sp,
        fontFamily = FontFamily.Monospace,
        letterSpacing = 0.5.sp
    )
}
