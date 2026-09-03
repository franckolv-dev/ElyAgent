// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/components/HitlCard.kt
// @brief      HITL approval card
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ely.agent.core.model.HitlRequest

@Composable
fun HitlCard(
    hitlRequest: HitlRequest,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier.fillMaxWidth().padding(8.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.3f)
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("⚠️ Autorisation requise", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text("Action : ${hitlRequest.tool}", style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(hitlRequest.description, style = MaterialTheme.typography.bodyMedium)
            if (hitlRequest.args.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                hitlRequest.args.forEach { (k, v) ->
                    Text("• $k: $v", style = MaterialTheme.typography.labelSmall)
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onApprove,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF34A853)),
                    modifier = Modifier.weight(1f)) { Text("✓ Approuver") }
                OutlinedButton(onClick = onDeny, modifier = Modifier.weight(1f)) { Text("✗ Refuser") }
            }
        }
    }
}
