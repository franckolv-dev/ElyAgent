// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/settings/SettingsScreen.kt
// @brief      Settings screen — server URL and preferences
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

package com.ely.agent.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel

@Composable
fun SettingsScreen(onBack: () -> Unit, onLogout: () -> Unit, viewModel: SettingsViewModel = hiltViewModel()) {
    val uiState by viewModel.uiState.collectAsState()
    LaunchedEffect(uiState.isSaved) { if (uiState.isSaved) onBack() }
    LaunchedEffect(uiState.isLoggedOut) { if (uiState.isLoggedOut) onLogout() }
    Scaffold(topBar = {
        TopAppBar(title = { Text("Paramètres") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") } })
    }) { padding ->
        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                Text("Connexion", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = uiState.serverUrl, onValueChange = viewModel::onServerUrlChange,
                    label = { Text("URL du serveur ELY") }, modifier = Modifier.fillMaxWidth())
            }
            item {
                Text("Thème", style = MaterialTheme.typography.titleMedium)
                listOf("SYSTEM" to "Système", "LIGHT" to "Clair", "DARK" to "Sombre").forEach { (v, l) ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                        RadioButton(selected = uiState.theme == v, onClick = { viewModel.onThemeChange(v) })
                        Text(l)
                    }
                }
            }
            if (uiState.skills.isNotEmpty()) {
                item { Text("Compétences (${uiState.skills.size})", style = MaterialTheme.typography.titleMedium) }
                items(uiState.skills) { skill ->
                    ListItem(headlineContent = { Text("${skill.icon} ${skill.displayName}") },
                        supportingContent = { Text(skill.description, maxLines = 2) },
                        trailingContent = { Switch(checked = skill.enabled, onCheckedChange = {}) })
                    HorizontalDivider()
                }
            }
            item {
                Button(onClick = viewModel::save, modifier = Modifier.fillMaxWidth()) { Text("Enregistrer") }
            }
            item {
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = viewModel::logout,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) { Text("Se déconnecter") }
            }
        }
    }
}
