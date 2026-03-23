package com.ely.agent.ui.components

import androidx.compose.animation.core.*
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun VoiceInputButton(isRecording: Boolean, onToggle: () -> Unit, modifier: Modifier = Modifier) {
    val t = rememberInfiniteTransition(label = "pulse")
    val scale by t.animateFloat(
        initialValue = 1f, targetValue = 1.3f,
        animationSpec = infiniteRepeatable(
            animation = tween(600, easing = FastOutSlowInEasing), repeatMode = RepeatMode.Reverse
        ), label = "pulse_scale"
    )
    IconButton(
        onClick = onToggle,
        modifier = modifier.then(
            if (isRecording) Modifier.scale(scale).border(2.dp, Color.Red, CircleShape) else Modifier
        )
    ) {
        Icon(
            imageVector = if (isRecording) Icons.Default.MicOff else Icons.Default.Mic,
            contentDescription = if (isRecording) "Arrêter" else "Enregistrer",
            tint = if (isRecording) Color.Red else MaterialTheme.colorScheme.onSurface
        )
    }
}
