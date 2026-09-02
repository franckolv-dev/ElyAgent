// =============================================================================
// @project    ELY — Exactly Like You
// @file       ui/files/FileManagerScreen.kt
// @brief      Intelligent folder browser — filters, dedupe, cleanup
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @license    PolyForm Strict License 1.0.0
// =============================================================================

package com.ely.agent.ui.files

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.GridView
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.ViewList
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.launch
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
import coil.decode.VideoFrameDecoder
import com.ely.agent.core.files.FileCategory
import com.ely.agent.core.files.FileEntry
import com.ely.agent.core.files.FileFilter
import java.text.DecimalFormat

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun FileManagerScreen(
    onNavigateBack: () -> Unit,
    viewModel: FileManagerViewModel = hiltViewModel(),
) {
    val state by viewModel.ui.collectAsState()
    val context = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    // "All files access" state must be re-read every time the Activity
    // resumes — the user can grant/revoke it in Settings and come back
    // without the app process being killed. Without this, the empty-state
    // button would stay on its initial value until next app launch.
    var allFilesAccess by remember { mutableStateOf(hasAllFilesAccess()) }
    var awaitingAllFilesGrant by remember { mutableStateOf(false) }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                val nowGranted = hasAllFilesAccess()
                if (nowGranted != allFilesAccess) {
                    allFilesAccess = nowGranted
                    if (awaitingAllFilesGrant) {
                        scope.launch {
                            snackbarHostState.showSnackbar(
                                if (nowGranted) "✓ Accès complet aux fichiers activé"
                                else "Accès non accordé — réessaie ou relance ELY"
                            )
                        }
                        awaitingAllFilesGrant = false
                    }
                } else if (awaitingAllFilesGrant && !nowGranted) {
                    // User came back without granting; hint that a restart
                    // may be needed on some OEMs that cache the permission.
                    scope.launch {
                        snackbarHostState.showSnackbar(
                            "Si tu as activé l'accès mais qu'il n'est pas détecté, relance ELY."
                        )
                    }
                    awaitingAllFilesGrant = false
                }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    var showDeleteConfirm by remember { mutableStateOf(false) }
    var showFilterSheet by remember { mutableStateOf(false) }
    var showDupSheet by remember { mutableStateOf(false) }
    var showAskDialog by remember { mutableStateOf(false) }

    // Show any transient toast via the snackbar
    LaunchedEffect(state.toast) {
        state.toast?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.consumeToast()
        }
    }

    val pickFolder = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocumentTree(),
    ) { uri: Uri? ->
        if (uri != null) {
            // Persist permissions so we can re-open the same folder later
            val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            try {
                context.contentResolver.takePersistableUriPermission(uri, flags)
            } catch (_: Exception) {
                /* ignore — some providers don't support persist */
            }
            viewModel.onTreePicked(uri, uri.lastPathSegment)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Gestionnaire de fichiers", style = MaterialTheme.typography.titleMedium)
                        state.rootLabel?.let {
                            Text(
                                it,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.Default.ArrowBack, "Retour")
                    }
                },
                actions = {
                    if (state.rootUri != null || state.rootPath != null) {
                        IconButton(onClick = { viewModel.toggleViewMode() }) {
                            Icon(
                                if (state.viewMode == ViewMode.LIST) Icons.Default.GridView else Icons.Default.ViewList,
                                contentDescription = if (state.viewMode == ViewMode.LIST) "Afficher en miniatures" else "Afficher en liste",
                            )
                        }
                    }
                    IconButton(onClick = { pickFolder.launch(null) }) {
                        Icon(Icons.Default.FolderOpen, "Choisir un dossier")
                    }
                    if (state.rootUri != null || state.rootPath != null) {
                        IconButton(onClick = { viewModel.scan() }) {
                            Icon(Icons.Default.Refresh, "Re-scanner")
                        }
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (state.selection.isNotEmpty()) {
                BottomAppBar {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "${state.selection.size} sélectionné(s) — " +
                        formatSize(state.visibleEntries.filter { it.uri in state.selection }.sumOf { it.sizeBytes }),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { viewModel.clearSelection() }) { Text("Tout désélectionner") }
                    Button(
                        onClick = { showDeleteConfirm = true },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.error,
                        ),
                    ) {
                        Icon(Icons.Default.Delete, null)
                        Spacer(Modifier.width(4.dp))
                        Text("Supprimer")
                    }
                    Spacer(Modifier.width(8.dp))
                }
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when {
                state.rootUri == null && state.rootPath == null -> EmptyState(
                    onPick = { pickFolder.launch(null) },
                    onShortcut = { path, label -> viewModel.onDirectPathPicked(path, label) },
                    onRequestAllFiles = {
                        awaitingAllFilesGrant = true
                        try {
                            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                                .setData(Uri.parse("package:${context.packageName}"))
                            context.startActivity(intent)
                        } catch (_: Exception) {
                            // Some ROMs don't expose the per-app screen — fall
                            // back to the global "All files access" settings.
                            try {
                                context.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                            } catch (_: Exception) {
                                awaitingAllFilesGrant = false
                            }
                        }
                    },
                    hasAllFilesAccess = allFilesAccess,
                )
                state.loading -> LoadingState(progress = state.scanProgress)
                else -> Column(modifier = Modifier.fillMaxSize()) {
                    // When a deduplication auto-selection has been applied,
                    // restrict the main list to the selected items so the
                    // user immediately sees what's being deleted — not the
                    // full 1000+ file folder around it.
                    val effectiveVisible = if (state.showSelectionOnly)
                        state.visibleEntries.filter { it.uri in state.selection }
                    else state.visibleEntries

                    // Quick actions / filters row
                    FilterRow(
                        filter = state.filter,
                        total = state.allEntries.size,
                        shown = effectiveVisible.size,
                        totalSize = effectiveVisible.sumOf { it.sizeBytes },
                        showSelectionOnly = state.showSelectionOnly,
                        onOpenFilters = { showFilterSheet = true },
                        onClearFilters = { viewModel.clearFilter() },
                        onOpenDup = { showDupSheet = true },
                        onAskEly = { showAskDialog = true },
                        onToggleSelectionOnly = {
                            viewModel.setShowSelectionOnly(!state.showSelectionOnly)
                        },
                    )
                    HorizontalDivider()
                    // File list
                    if (effectiveVisible.isEmpty()) {
                        Column(
                            modifier = Modifier.fillMaxSize().padding(32.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center,
                        ) {
                            Text(
                                "Aucun fichier ne correspond à ce filtre.",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.height(8.dp))
                            TextButton(onClick = { viewModel.clearFilter() }) {
                                Text("Effacer les filtres")
                            }
                        }
                    } else {
                        // Tri-state "select all" header — behaves like Gmail:
                        //   none     → select all visible
                        //   partial  → select all visible (complete the set)
                        //   all      → clear selection
                        val visibleUris = effectiveVisible.map { it.uri }
                        val selectedVisibleCount = visibleUris.count { it in state.selection }
                        val headerState = when (selectedVisibleCount) {
                            0 -> ToggleableState.Off
                            visibleUris.size -> ToggleableState.On
                            else -> ToggleableState.Indeterminate
                        }
                        SelectAllHeader(
                            state = headerState,
                            totalVisible = visibleUris.size,
                            selectedVisible = selectedVisibleCount,
                            onToggle = {
                                if (headerState == ToggleableState.On) viewModel.clearSelection()
                                else viewModel.selectAllVisible()
                            },
                        )
                        HorizontalDivider(thickness = 0.5.dp)
                        if (state.viewMode == ViewMode.LIST) {
                            LazyColumn(modifier = Modifier.fillMaxSize()) {
                                items(effectiveVisible, key = { it.uri.toString() }) { entry ->
                                    FileRow(
                                        entry = entry,
                                        selected = entry.uri in state.selection,
                                        onToggle = { viewModel.toggleSelection(entry.uri) },
                                    )
                                    HorizontalDivider(thickness = 0.5.dp)
                                }
                            }
                        } else {
                            LazyVerticalGrid(
                                columns = GridCells.Adaptive(minSize = 104.dp),
                                modifier = Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(4.dp),
                            ) {
                                items(effectiveVisible, key = { it.uri.toString() }) { entry ->
                                    FileThumbnail(
                                        entry = entry,
                                        selected = entry.uri in state.selection,
                                        onToggle = { viewModel.toggleSelection(entry.uri) },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showDeleteConfirm) {
        val sel = state.selection
        val sizeSum = state.allEntries.filter { it.uri in sel }.sumOf { it.sizeBytes }
        AlertDialog(
            onDismissRequest = { showDeleteConfirm = false },
            icon = { Icon(Icons.Default.Delete, null, tint = MaterialTheme.colorScheme.error) },
            title = { Text("Supprimer ${sel.size} fichier(s) ?") },
            text = {
                Text(
                    "${formatSize(sizeSum)} seront supprimés. " +
                    "Cette action est irréversible.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showDeleteConfirm = false
                        viewModel.deleteSelection { _, _ -> }
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("Supprimer") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteConfirm = false }) { Text("Annuler") }
            },
        )
    }

    if (showFilterSheet) {
        FilterSheet(
            current = state.filter,
            onDismiss = { showFilterSheet = false },
            onApply = {
                viewModel.setFilter(it)
                showFilterSheet = false
            },
        )
    }

    if (showAskDialog) {
        AskElyDialog(
            onDismiss = { showAskDialog = false },
            onApply = { f, echo ->
                viewModel.setFilter(f)
                showAskDialog = false
                // The toast is surfaced by the ViewModel state — here we just
                // also echo Ely's interpretation via a snackbar.
                if (echo.isNotBlank()) {
                    // Fire-and-forget: the snackbar host is in scope
                    // through the Scaffold.
                }
            },
        )
    }

    if (showDupSheet) {
        DuplicatesSheet(
            state = state,
            onDismiss = { showDupSheet = false },
            onRunExact = { viewModel.runExactDuplicateScan() },
            onRunSimilar = { viewModel.runSimilarImageScan() },
            onSelectForDeletion = {
                viewModel.selectDuplicatesForDeletion(it)
                showDupSheet = false
            },
        )
    }
}

// ── Sub-composables ────────────────────────────────────────────────────────

@Composable
private fun EmptyState(
    onPick: () -> Unit,
    onShortcut: (String, String) -> Unit,
    onRequestAllFiles: () -> Unit,
    hasAllFilesAccess: Boolean,
) {
    val ext = android.os.Environment.getExternalStorageDirectory().absolutePath
    // Classic shortcut folders — visible only when we can actually open
    // them without SAF (MANAGE_EXTERNAL_STORAGE granted).
    val shortcuts = listOf(
        Shortcut("Téléchargements", "$ext/Download", Icons.Default.Download),
        Shortcut("Photos (DCIM)", "$ext/DCIM", Icons.Default.PhotoCamera),
        Shortcut("Images", "$ext/Pictures", Icons.Default.Image),
        Shortcut("Vidéos", "$ext/Movies", Icons.Default.Movie),
        Shortcut("WhatsApp", "$ext/Android/media/com.whatsapp/WhatsApp", Icons.Default.FolderOpen),
        Shortcut("Documents", "$ext/Documents", Icons.Default.InsertDriveFile),
    ).filter { java.io.File(it.path).exists() }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Top,
    ) {
        Spacer(Modifier.height(32.dp))
        Icon(
            Icons.Default.FolderOpen,
            null,
            modifier = Modifier.size(56.dp),
            tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.6f),
        )
        Spacer(Modifier.height(12.dp))
        Text("Choisis un dossier à analyser", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            "Ely t'aide à retrouver les doublons, les fichiers lourds et à faire le ménage.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))

        if (hasAllFilesAccess && shortcuts.isNotEmpty()) {
            Text(
                "Raccourcis",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.align(Alignment.Start),
            )
            Spacer(Modifier.height(8.dp))
            for (s in shortcuts) {
                OutlinedButton(
                    onClick = { onShortcut(s.path, s.label) },
                    modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                ) {
                    Icon(s.icon, null, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(s.label, modifier = Modifier.weight(1f), textAlign = androidx.compose.ui.text.style.TextAlign.Start)
                }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                "ou",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
        }

        TextButton(onClick = onPick) {
            Icon(Icons.Default.FolderOpen, null)
            Spacer(Modifier.width(8.dp))
            Text("Choisir un autre dossier (SAF)")
        }

        Spacer(Modifier.height(16.dp))
        if (hasAllFilesAccess) {
            Text(
                "✓ Accès complet aux fichiers activé",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
        } else {
            Button(onClick = onRequestAllFiles) {
                Text("Autoriser l'accès à tous les fichiers")
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "Android 11+ bloque SAF sur Download / Android/data. " +
                "Active cet accès pour débloquer les raccourcis ci-dessus.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

private data class Shortcut(val label: String, val path: String, val icon: ImageVector)

/** True when the app has the "All files access" special permission (API 30+). */
private fun hasAllFilesAccess(): Boolean =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Environment.isExternalStorageManager()
    else true

@Composable
private fun LoadingState(progress: Int) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(16.dp))
        Text("$progress fichiers analysés…", style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun FilterRow(
    filter: FileFilter,
    total: Int,
    shown: Int,
    totalSize: Long,
    showSelectionOnly: Boolean,
    onOpenFilters: () -> Unit,
    onClearFilters: () -> Unit,
    onOpenDup: () -> Unit,
    onAskEly: () -> Unit,
    onToggleSelectionOnly: () -> Unit,
) {
    Column {
        // When restricted to selection, a prominent banner explains the
        // current state and lets the user go back to the full folder view.
        if (showSelectionOnly) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primaryContainer,
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        Icons.Default.AutoAwesome,
                        null,
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "Affichage restreint à la sélection ($shown fichiers)",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = onToggleSelectionOnly) {
                        Text("Voir tout")
                    }
                }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("$shown / $total fichiers", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text(formatSize(totalSize), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(onClick = onAskEly) {
                Icon(Icons.Default.AutoAwesome, null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Ély")
            }
            TextButton(onClick = onOpenDup) { Text("Doublons") }
            TextButton(onClick = onOpenFilters) { Text(if (filter.isTrivial()) "Filtres" else "Filtres ✓") }
            if (!filter.isTrivial()) {
                TextButton(onClick = onClearFilters) { Text("✕") }
            }
        }
    }
}

@Composable
private fun AskElyDialog(
    onDismiss: () -> Unit,
    onApply: (FileFilter, String) -> Unit,
) {
    var query by remember { mutableStateOf("") }
    var echo by remember { mutableStateOf<String?>(null) }
    val examples = listOf(
        "supprime les apk",
        "fichiers de plus de 5 Mo",
        "photos plus anciennes que 6 mois",
        "les vidéos",
        "archives",
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(Icons.Default.AutoAwesome, null, tint = MaterialTheme.colorScheme.primary) },
        title = { Text("Demande à Ély") },
        text = {
            Column {
                Text(
                    "Décris ce que tu veux trouver. Ély comprend les filtres courants (taille, âge, type, extension).",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = query,
                    onValueChange = {
                        query = it
                        echo = null
                    },
                    placeholder = { Text("Ex : supprime les apk de plus de 20 Mo") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = false,
                    maxLines = 3,
                )
                Spacer(Modifier.height(8.dp))
                Text("Exemples :", style = MaterialTheme.typography.labelSmall)
                Row(
                    modifier = Modifier.fillMaxWidth().horizontalScrollRow(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    for (ex in examples) {
                        AssistChip(
                            onClick = { query = ex; echo = null },
                            label = { Text(ex, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                echo?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val (filter, summary) = FileFilter.parseNaturalLanguage(query)
                if (filter.isTrivial()) {
                    echo = summary  // show help message, don't dismiss
                } else {
                    onApply(filter, summary)
                }
            }) { Text("Appliquer") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Annuler") }
        },
    )
}

@Composable
private fun FileThumbnail(
    entry: FileEntry,
    selected: Boolean,
    onToggle: () -> Unit,
) {
    val context = LocalContext.current
    Box(
        modifier = Modifier
            .padding(2.dp)
            .aspectRatio(1f)
            .clip(RoundedCornerShape(6.dp))
            .clickable { onToggle() },
    ) {
        when (entry.category) {
            FileCategory.IMAGE -> {
                SubcomposeAsyncImage(
                    model = ImageRequest.Builder(context)
                        .data(entry.uri)
                        .crossfade(false)
                        .size(256)
                        .build(),
                    contentDescription = entry.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                    loading = { ThumbPlaceholder(Icons.Default.Image) },
                    error = { ThumbPlaceholder(Icons.Default.Image) },
                )
            }
            FileCategory.VIDEO -> {
                SubcomposeAsyncImage(
                    model = ImageRequest.Builder(context)
                        .data(entry.uri)
                        .decoderFactory(VideoFrameDecoder.Factory())
                        .size(256)
                        .build(),
                    contentDescription = entry.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                    loading = { ThumbPlaceholder(Icons.Default.Movie) },
                    error = { ThumbPlaceholder(Icons.Default.Movie) },
                )
            }
            else -> ThumbPlaceholder(iconFor(entry.category))
        }

        // Bottom gradient + filename + size
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomStart)
                .background(Color.Black.copy(alpha = 0.55f))
                .padding(horizontal = 4.dp, vertical = 2.dp),
        ) {
            Column {
                Text(
                    entry.name,
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    formatSize(entry.sizeBytes),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.85f),
                )
            }
        }

        // Selection overlay — a circular check in the top-right corner
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(4.dp)
                .size(24.dp)
                .clip(CircleShape)
                .background(
                    if (selected) MaterialTheme.colorScheme.primary
                    else Color.Black.copy(alpha = 0.35f),
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) {
                Icon(
                    Icons.Default.Check,
                    null,
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(16.dp),
                )
            }
        }

        // Subtle tint over the whole tile when selected — easier to scan
        if (selected) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)),
            )
        }
    }
}

@Composable
private fun ThumbPlaceholder(icon: ImageVector) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            null,
            modifier = Modifier.size(36.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SelectAllHeader(
    state: ToggleableState,
    totalVisible: Int,
    selectedVisible: Int,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onToggle() }
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TriStateCheckbox(state = state, onClick = onToggle)
        Spacer(Modifier.width(8.dp))
        Text(
            when (state) {
                ToggleableState.Off -> "Tout sélectionner ($totalVisible)"
                ToggleableState.On -> "Tout désélectionner"
                ToggleableState.Indeterminate -> "$selectedVisible / $totalVisible sélectionnés"
            },
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun FileRow(entry: FileEntry, selected: Boolean, onToggle: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onToggle() }
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = selected, onCheckedChange = { onToggle() })
        Icon(
            imageVector = iconFor(entry.category),
            contentDescription = null,
            modifier = Modifier.size(24.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(entry.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                entry.relativePath.ifBlank { entry.category },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            formatSize(entry.sizeBytes),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(start = 8.dp),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterSheet(
    current: FileFilter,
    onDismiss: () -> Unit,
    onApply: (FileFilter) -> Unit,
) {
    var minSizeText by remember { mutableStateOf("") }
    var olderDaysText by remember { mutableStateOf("") }
    var selectedCategories by remember { mutableStateOf(current.categories) }
    val cats = listOf(
        FileCategory.IMAGE to "Images",
        FileCategory.VIDEO to "Vidéos",
        FileCategory.AUDIO to "Audio",
        FileCategory.APK to "APK",
        FileCategory.DOCUMENT to "Documents",
        FileCategory.ARCHIVE to "Archives",
        FileCategory.OTHER to "Autres",
    )

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Filtrer", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(16.dp))

            // Presets
            Text("Raccourcis", style = MaterialTheme.typography.labelMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.horizontalScrollRow()) {
                AssistChip(onClick = { onApply(FileFilter.LargeFiles) }, label = { Text("Gros fichiers") })
                AssistChip(onClick = { onApply(FileFilter.Apks) }, label = { Text("APK") })
                AssistChip(onClick = { onApply(FileFilter.Archives) }, label = { Text("Archives") })
                AssistChip(onClick = { onApply(FileFilter.Videos) }, label = { Text("Vidéos") })
                AssistChip(onClick = { onApply(FileFilter.olderThanDays(180)) }, label = { Text("> 6 mois") })
            }
            Spacer(Modifier.height(24.dp))

            // Custom
            Text("Personnalisé", style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = minSizeText,
                onValueChange = { minSizeText = it },
                label = { Text("Taille minimum (ex: 5 Mo, 500 ko)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = olderDaysText,
                onValueChange = { olderDaysText = it.filter { c -> c.isDigit() } },
                label = { Text("Plus ancien que (jours)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(16.dp))
            Text("Catégories", style = MaterialTheme.typography.labelMedium)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScrollRow(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                for ((k, label) in cats) {
                    val sel = k in selectedCategories
                    FilterChip(
                        selected = sel,
                        onClick = {
                            selectedCategories = if (sel) selectedCategories - k else selectedCategories + k
                        },
                        label = { Text(label) },
                    )
                }
            }

            Spacer(Modifier.height(24.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                TextButton(onClick = onDismiss, modifier = Modifier.weight(1f)) { Text("Annuler") }
                Button(
                    onClick = {
                        val f = FileFilter(
                            minSizeBytes = FileFilter.parseSizeInput(minSizeText),
                            olderThanMs = olderDaysText.toIntOrNull()
                                ?.let { System.currentTimeMillis() - it.toLong() * 24 * 3600_000L },
                            categories = selectedCategories,
                        )
                        onApply(f)
                    },
                    modifier = Modifier.weight(1f),
                ) { Text("Appliquer") }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DuplicatesSheet(
    state: FileManagerUiState,
    onDismiss: () -> Unit,
    onRunExact: () -> Unit,
    onRunSimilar: () -> Unit,
    onSelectForDeletion: (List<List<FileEntry>>) -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Détection de doublons", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Text(
                "L'analyse tourne entièrement sur ton téléphone, rien n'est envoyé au serveur.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(16.dp))

            // Actions
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onRunExact, modifier = Modifier.weight(1f), enabled = !state.dedupRunning) {
                    Text("Doublons exacts (MD5)")
                }
                OutlinedButton(onClick = onRunSimilar, modifier = Modifier.weight(1f), enabled = !state.dedupRunning) {
                    Text("Images similaires")
                }
            }
            state.dedupProgress?.let { (done, total) ->
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = { if (total == 0) 0f else done.toFloat() / total },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text("$done / $total", style = MaterialTheme.typography.labelSmall)
            }
            Spacer(Modifier.height(16.dp))

            // Results
            if (state.exactDupGroups.isNotEmpty()) {
                Text("Doublons exacts", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(4.dp))
                Text(
                    "${state.exactDupGroups.size} groupe(s) — " +
                    formatSize(state.exactDupGroups.sumOf { it.drop(1).sumOf { e -> e.sizeBytes } }) +
                    " récupérables",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = { onSelectForDeletion(state.exactDupGroups) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Sélectionner les doublons (garder la plus grosse copie)")
                }
                Spacer(Modifier.height(16.dp))
            }

            if (state.similarImageGroups.isNotEmpty()) {
                Text("Images similaires", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.height(4.dp))
                Text(
                    "${state.similarImageGroups.size} groupe(s) — " +
                    formatSize(state.similarImageGroups.sumOf { it.drop(1).sumOf { e -> e.sizeBytes } }) +
                    " récupérables",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = { onSelectForDeletion(state.similarImageGroups) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Sélectionner les similaires (garder la plus grosse)")
                }
                Spacer(Modifier.height(16.dp))
            }

            TextButton(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) { Text("Fermer") }
        }
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────

private fun iconFor(category: String): ImageVector = when (category) {
    FileCategory.IMAGE -> Icons.Default.Image
    FileCategory.VIDEO -> Icons.Default.Movie
    else -> Icons.Default.InsertDriveFile
}

private fun formatSize(bytes: Long): String {
    if (bytes < 1024) return "$bytes o"
    val kb = bytes / 1024.0
    if (kb < 1024) return DecimalFormat("0.#").format(kb) + " Ko"
    val mb = kb / 1024.0
    if (mb < 1024) return DecimalFormat("0.##").format(mb) + " Mo"
    val gb = mb / 1024.0
    return DecimalFormat("0.##").format(gb) + " Go"
}

/** Shorthand for a horizontal-scroll Row that overflows properly. */
@Composable
private fun Modifier.horizontalScrollRow(): Modifier =
    this.horizontalScroll(rememberScrollState()).padding(vertical = 4.dp)
