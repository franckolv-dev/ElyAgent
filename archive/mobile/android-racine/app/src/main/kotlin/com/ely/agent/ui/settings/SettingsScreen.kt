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
fun SettingsScreen(
    onBack: () -> Unit,
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    LaunchedEffect(uiState.isSaved) { if (uiState.isSaved) onBack() }
    LaunchedEffect(uiState.isLoggedOut) { if (uiState.isLoggedOut) onLogout() }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Paramètres") },
            navigationIcon = {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            }
        )
    }) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // --- Connexion ---
            item {
                Text("Connexion", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = uiState.serverUrl,
                    onValueChange = viewModel::onServerUrlChange,
                    label = { Text("URL du serveur ELY") },
                    modifier = Modifier.fillMaxWidth()
                )
            }

            // --- Thème ---
            item {
                Text("Thème", style = MaterialTheme.typography.titleMedium)
                listOf("SYSTEM" to "Système", "LIGHT" to "Clair", "DARK" to "Sombre").forEach { (v, l) ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        RadioButton(selected = uiState.theme == v, onClick = { viewModel.onThemeChange(v) })
                        Text(l)
                    }
                }
            }

            // --- Affichage ---
            item {
                Text("Affichage", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Avatar ELY", style = MaterialTheme.typography.bodyLarge)
                        Text(
                            text = "Afficher l'avatar animé en haut du chat",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Spacer(Modifier.width(16.dp))
                    Switch(
                        checked = uiState.showAvatar,
                        onCheckedChange = viewModel::onShowAvatarChange
                    )
                }
            }

            // --- Compétences ---
            if (uiState.skills.isNotEmpty()) {
                item { Text("Compétences (${uiState.skills.size})", style = MaterialTheme.typography.titleMedium) }
                items(uiState.skills) { skill ->
                    ListItem(
                        headlineContent = { Text("${skill.icon} ${skill.displayName}") },
                        supportingContent = { Text(skill.description, maxLines = 2) },
                        trailingContent = {
                        Switch(
                            checked = skill.enabled,
                            onCheckedChange = { viewModel.toggleSkill(skill.name, it) }
                        )
                    }
                    )
                    HorizontalDivider()
                }
            }

            // --- Boutons d'action ---
            item {
                Button(onClick = viewModel::save, modifier = Modifier.fillMaxWidth()) {
                    Text("Enregistrer")
                }
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
