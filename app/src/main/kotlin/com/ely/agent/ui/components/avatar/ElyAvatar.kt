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
 * Avatar wireframe animé d'ELY — forme de tête réelle.
 *
 * Reproduit l'esthétique du composant desktop (AvatarScene.tsx + shader GLSL) :
 * - Silhouette tête : crâne arrondi + mâchoire effilée vers le menton
 * - Grille latitude/longitude adaptée à la forme
 * - 5 états avec transitions de couleur fluides
 * - Respiration, balancement (THINKING), pulsation lèvres (SPEAKING), glitch (ALERT)
 * - Scan line animée + nœuds de grille
 * - Overlay HUD (NEURAL, SYNC, LAT, VER, état courant)
 */
@Composable
fun ElyAvatar(
    state: AvatarState,
    modifier: Modifier = Modifier
) {
    var t by remember { mutableStateOf(0f) }
    LaunchedEffect(Unit) {
        val start = System.currentTimeMillis()
        while (true) {
            t = (System.currentTimeMillis() - start) / 1000f
            delay(16L)
        }
    }

    val animatedColor by animateColorAsState(
        targetValue = state.color,
        animationSpec = tween(durationMillis = 500),
        label = "avatarColor"
    )

    Box(modifier = modifier.background(Color(0xFF060C12))) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawHeadAvatar(t, animatedColor, state)
        }
        HudOverlay(state = state, color = animatedColor)
    }
}

// ---------------------------------------------------------------------------
// Dessin principal — silhouette de tête
// ---------------------------------------------------------------------------

private fun DrawScope.drawHeadAvatar(t: Float, color: Color, state: AvatarState) {
    val w = size.width
    val h = size.height

    // ── Proportions tête : rx nettement plus petit que ry ──
    // Ratio ry/rx ≈ 1.45 → clairement une tête, pas une boule
    val baseRx = h * 0.27f
    val baseRy = h * 0.39f

    // Centre légèrement vers le haut pour laisser de la place au menton
    val cx = w / 2f
    val cy = h * 0.48f

    // ── Animations dépendant de l'état ──

    val breathSpeed = if (state == AvatarState.LISTENING) 3f else 0.7f
    val breathScale = 1f + 0.018f * sin(t * breathSpeed)
    val rx = baseRx * breathScale
    val ry = baseRy * breathScale

    val swayDx = if (state == AvatarState.THINKING) sin(t * 0.5f) * baseRx * 0.09f else 0f

    val glitchDx = if (state == AvatarState.ALERT) {
        val seed = (t * 13f).toInt()
        if (seed % 7 == 0) ((seed * 11 + 37) % 9 - 4) * 3f else 0f
    } else 0f

    val alphaPulse = if (state == AvatarState.ALERT) 0.7f + 0.3f * abs(sin(t * 4f)) else 1f

    val scanPos = (t * 0.08f) % 1f

    val mouthBoost = if (state == AvatarState.SPEAKING) {
        val phase = (t * 8f) % 1f
        if (phase < 0.15f) (1f - phase / 0.15f) * 3.5f else 0f
    } else 0f

    val faceCx = cx + swayDx + glitchDx

    // ── Halo ambiant ──
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(color.copy(alpha = 0.08f * alphaPulse), Color.Transparent),
            center = Offset(faceCx, cy),
            radius = rx * 1.9f
        ),
        radius = rx * 1.9f,
        center = Offset(faceCx, cy)
    )

    // ── Silhouette de tête (bezier) ──
    // Crâne = arc large en haut ; mâchoire = effilée vers le bas
    val headPath = buildHeadPath(faceCx, cy, rx, ry)

    // Contour principal
    drawPath(
        headPath,
        color = color.copy(alpha = 0.62f * alphaPulse),
        style = Stroke(width = 1.8.dp.toPx())
    )
    // Halo de bord (fresnel)
    val haloPath = buildHeadPath(faceCx, cy, rx + 3.dp.toPx(), ry + 3.dp.toPx())
    drawPath(
        haloPath,
        color = color.copy(alpha = 0.18f * alphaPulse),
        style = Stroke(width = 5.dp.toPx())
    )

    clipPath(headPath) {
        val strokePx = 1.3.dp.toPx()

        // ── Lignes de longitude (ellipses verticales) ──
        val lonWidths = floatArrayOf(0.87f, 0.71f, 0.50f, 0.26f)
        for (wf in lonWidths) {
            val hw = rx * wf
            val fresnel = 0.25f + 0.35f * wf
            drawOval(
                color = color.copy(alpha = fresnel * 0.85f * alphaPulse),
                topLeft = Offset(faceCx - hw, cy - ry),
                size = Size(hw * 2f, ry * 2f),
                style = Stroke(width = strokePx)
            )
        }
        // Méridien central
        drawLine(
            color = color.copy(alpha = 0.28f * alphaPulse),
            start = Offset(faceCx, cy - ry),
            end = Offset(faceCx, cy + ry),
            strokeWidth = strokePx
        )

        // ── Lignes de latitude (arcs courbés) ──
        val numLat = 10
        for (i in 0..numLat) {
            val phi = (-PI.toFloat() / 2f + PI.toFloat() * i / numLat)
            val lineY = cy + ry * sin(phi)
            val halfW = rx * cos(phi)

            if (halfW < 2f) continue

            // La ligne de latitude doit respecter la forme tête :
            // en haut (crâne) la tête est large ; en bas (menton) elle se rétrécit.
            // On applique un facteur de rétrécissement dans la moitié inférieure.
            val chinFactor = if (phi < 0f) {
                // sin(phi) ∈ [-1, 0] quand phi ∈ [-π/2, 0]
                // On réduit progressivement vers le menton : 1.0 au centre → 0.55 au bas
                1.0f + sin(phi) * 0.45f     // = 1 + négatif → < 1 vers le menton
            } else 1.0f
            val adjustedHalfW = halfW * chinFactor

            val fresnel = 0.25f + 0.50f * abs(sin(phi))
            var baseAlpha = (0.28f + fresnel * 0.32f) * alphaPulse

            // Boost scan line
            val normY = (lineY - (cy - ry)) / (2f * ry)
            val scanDist = abs(normY - scanPos)
            val scanBoost = (1f - smoothStep(0f, 0.08f, scanDist)) * 0.28f
            baseAlpha = (baseAlpha + scanBoost).coerceIn(0f, 1f)

            // Boost zone bouche (SPEAKING)
            val mouthFactor = if (mouthBoost > 0f && phi < 0f && phi > -PI.toFloat() * 0.45f)
                mouthBoost * 0.14f else 0f
            val lineAlpha = (baseAlpha + mouthFactor).coerceIn(0f, 1f)

            // Courbure
            val curvature = sin(phi) * adjustedHalfW * 0.14f

            val path = Path().apply {
                moveTo(faceCx - adjustedHalfW, lineY)
                cubicTo(
                    faceCx - adjustedHalfW * 0.5f, lineY - curvature,
                    faceCx + adjustedHalfW * 0.5f, lineY - curvature,
                    faceCx + adjustedHalfW, lineY
                )
            }
            drawPath(path, color = color.copy(alpha = lineAlpha), style = Stroke(width = strokePx))
        }

        // ── Nœuds de grille ──
        val nodeR = 2.dp.toPx()
        for (i in 1 until numLat) {
            val phi = (-PI.toFloat() / 2f + PI.toFloat() * i / numLat)
            val lineY = cy + ry * sin(phi)
            val halfW = rx * cos(phi)
            if (halfW < 2f) continue

            val chinFactor = if (phi < 0f) 1.0f + sin(phi) * 0.45f else 1.0f
            val adjustedHalfW = halfW * chinFactor

            val normY = (lineY - (cy - ry)) / (2f * ry)
            val scanBoost = (1f - smoothStep(0f, 0.08f, abs(normY - scanPos))) * 0.45f

            for (wf in lonWidths) {
                val nodeHw = adjustedHalfW * wf
                val nodeAlpha = (0.48f + scanBoost) * alphaPulse
                drawCircle(color.copy(alpha = nodeAlpha), nodeR, Offset(faceCx + nodeHw, lineY))
                drawCircle(color.copy(alpha = nodeAlpha * 0.65f), nodeR, Offset(faceCx - nodeHw, lineY))
            }
        }

        // ── Scan line ──
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

        // ── Lignes de glitch (ALERT) ──
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
}

/**
 * Construit le Path de la silhouette de tête :
 * - Crâne arrondi (haut large)
 * - Tempes / pommettes (largeur maximale au niveau du milieu)
 * - Mâchoire effilée → menton pointu
 */
private fun buildHeadPath(cx: Float, cy: Float, rx: Float, ry: Float): Path = Path().apply {
    // Point de départ : pommette gauche (largeur maximale, niveau centre)
    moveTo(cx - rx, cy)

    // Arc du crâne : pommette gauche → sommet du crâne → pommette droite
    cubicTo(
        cx - rx * 1.0f, cy - ry * 0.35f,  // montée gauche vers le crâne
        cx - rx * 0.72f, cy - ry * 1.0f,  // haut gauche du crâne
        cx, cy - ry                         // sommet du crâne
    )
    cubicTo(
        cx + rx * 0.72f, cy - ry * 1.0f,  // haut droit du crâne
        cx + rx * 1.0f, cy - ry * 0.35f,  // montée droite
        cx + rx, cy                         // pommette droite
    )

    // Arc de la mâchoire : pommette droite → menton → pommette gauche
    cubicTo(
        cx + rx * 0.90f, cy + ry * 0.52f,  // joue droite
        cx + rx * 0.48f, cy + ry * 1.0f,   // mâchoire droite
        cx, cy + ry                          // menton
    )
    cubicTo(
        cx - rx * 0.48f, cy + ry * 1.0f,   // mâchoire gauche
        cx - rx * 0.90f, cy + ry * 0.52f,  // joue gauche
        cx - rx, cy                          // retour pommette gauche
    )
    close()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

private fun smoothStep(edge0: Float, edge1: Float, x: Float): Float {
    val t = ((x - edge0) / (edge1 - edge0)).coerceIn(0f, 1f)
    return t * t * (3f - 2f * t)
}

// ---------------------------------------------------------------------------
// Overlay HUD
// ---------------------------------------------------------------------------

@Composable
private fun BoxScope.HudOverlay(state: AvatarState, color: Color) {
    Column(
        modifier = Modifier
            .align(Alignment.TopStart)
            .padding(start = 10.dp, top = 8.dp)
    ) {
        HudText("NEURAL:98.3%", color)
        HudText("SYNC:99.72", color)
    }
    Column(
        modifier = Modifier
            .align(Alignment.TopEnd)
            .padding(end = 10.dp, top = 8.dp),
        horizontalAlignment = Alignment.End
    ) {
        HudText("LAT:12ms", color)
        HudText("VER:3.0.0", color)
    }
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
