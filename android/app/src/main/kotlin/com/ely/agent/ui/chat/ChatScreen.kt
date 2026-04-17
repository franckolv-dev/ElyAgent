// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/chat/ChatScreen.kt
// @brief      Chat screen — message list, input, conversation drawer
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
// @version    1.1.0
// =============================================================================

package com.ely.agent.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.ely.agent.core.model.MessageRole
import com.ely.agent.data.remote.websocket.ChatWebSocketClient
import com.ely.agent.data.repository.ConversationSummary
import com.ely.agent.ui.components.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    onNavigateToSettings: () -> Unit,
    onNavigateToDashboard: () -> Unit,
    viewModel: ChatViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val listState = rememberLazyListState()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var conversations by remember { mutableStateOf<List<ConversationSummary>>(emptyList()) }
    var conversationsLoading by remember { mutableStateOf(false) }

    // Reload the conversation list whenever the drawer opens
    LaunchedEffect(drawerState.currentValue) {
        if (drawerState.isOpen) {
            conversationsLoading = true
            conversations = viewModel.loadConversations()
            conversationsLoading = false
        }
    }

    LaunchedEffect(uiState.messages.size, uiState.streamingContent) {
        val count = uiState.messages.size + if (uiState.isStreaming) 1 else 0
        if (count > 0) listState.animateScrollToItem(count - 1)
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ConversationsDrawer(
                conversations = conversations,
                loading = conversationsLoading,
                currentId = uiState.currentConversationId,
                onNewConversation = {
                    viewModel.startNewConversation()
                    scope.launch { drawerState.close() }
                },
                onSelectConversation = { id ->
                    viewModel.switchConversation(id)
                    scope.launch { drawerState.close() }
                },
            )
        }
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("ELY", style = MaterialTheme.typography.titleLarge)
                            Spacer(Modifier.width(8.dp))
                            val dotColor = when (uiState.connectionState) {
                                is ChatWebSocketClient.ConnectionState.Connected -> Color(0xFF34A853)
                                is ChatWebSocketClient.ConnectionState.Connecting -> Color(0xFFFBBC05)
                                else -> Color(0xFFEA4335)
                            }
                            Surface(color = dotColor, shape = MaterialTheme.shapes.small, modifier = Modifier.size(8.dp)) {}
                        }
                    },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "Mes conversations")
                        }
                    },
                    actions = {
                        IconButton(onClick = { viewModel.startNewConversation() }) {
                            Icon(Icons.Default.Add, contentDescription = "Nouvelle conversation")
                        }
                        IconButton(onClick = onNavigateToDashboard) { Icon(Icons.Default.BarChart, "Dashboard") }
                        IconButton(onClick = onNavigateToSettings) { Icon(Icons.Default.Settings, "Paramètres") }
                    }
                )
            },
            bottomBar = {
                ChatInputBar(
                    text = uiState.inputText,
                    onTextChange = viewModel::onInputChange,
                    onSend = viewModel::sendMessage,
                    onCancel = viewModel::cancelStreaming,
                    isLoading = uiState.isLoading,
                    isStreaming = uiState.isStreaming,
                )
            }
        ) { padding ->
            if (uiState.messages.isEmpty() && !uiState.isStreaming) {
                // Empty state — helpful prompt to start a new conversation
                Box(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.padding(32.dp),
                    ) {
                        Icon(
                            Icons.Default.ChatBubbleOutline,
                            contentDescription = null,
                            modifier = Modifier.size(64.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                        )
                        Spacer(Modifier.height(16.dp))
                        Text(
                            "Nouvelle conversation",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "Demande-moi n'importe quoi — je gère tes emails, ton agenda, tes fichiers, tes rappels et bien plus.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        )
                    }
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize().padding(padding),
                    contentPadding = PaddingValues(vertical = 8.dp)
                ) {
                    itemsIndexed(uiState.messages, key = { _, m -> m.id }) { index, message ->
                        val prevTimestamp = if (index > 0) uiState.messages[index - 1].timestamp else 0L
                        if (index == 0 || !isSameDay(prevTimestamp, message.timestamp)) {
                            DateSeparator(timestamp = message.timestamp)
                        }
                        if (message.role == MessageRole.HITL_PENDING && message.hitlRequest != null) {
                            HitlCard(
                                hitlRequest = message.hitlRequest,
                                onApprove = { viewModel.resolveHitl(message.hitlRequest.actionId, "allow") },
                                onDeny = { viewModel.resolveHitl(message.hitlRequest.actionId, "deny") }
                            )
                        } else {
                            MessageBubble(message = message)
                        }
                    }
                    if (uiState.isStreaming) {
                        item {
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                                horizontalArrangement = Arrangement.Start
                            ) {
                                Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceVariant) {
                                    if (uiState.streamingContent.isNotEmpty())
                                        StreamingText(
                                            text = uiState.streamingContent,
                                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp).widthIn(max = 280.dp)
                                        )
                                    else
                                        LoadingDots(modifier = Modifier.padding(12.dp))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ChatInputBar(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onCancel: () -> Unit,
    isLoading: Boolean,
    isStreaming: Boolean,
) {
    Surface(tonalElevation = 3.dp) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp)
                .navigationBarsPadding().imePadding(),
            verticalAlignment = Alignment.Bottom
        ) {
            OutlinedTextField(
                value = text,
                onValueChange = onTextChange,
                placeholder = { Text("Demandez quelque chose…") },
                modifier = Modifier.weight(1f),
                maxLines = 5,
                shape = MaterialTheme.shapes.extraLarge,
                // Input remains typable at all times so the user can prepare
                // the next message while Éli is still answering. Send is
                // disabled only while loading the local insert.
                enabled = true,
            )
            Spacer(Modifier.width(8.dp))
            if (isStreaming) {
                // Cancel button — interrupts the current response
                FilledIconButton(
                    onClick = onCancel,
                    modifier = Modifier.size(48.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Icon(Icons.Default.Cancel, "Annuler la réponse")
                }
            } else {
                FilledIconButton(
                    onClick = onSend,
                    enabled = text.isNotBlank() && !isLoading,
                    modifier = Modifier.size(48.dp),
                ) {
                    Icon(Icons.Default.Send, "Envoyer")
                }
            }
        }
    }
}

@Composable
private fun ConversationsDrawer(
    conversations: List<ConversationSummary>,
    loading: Boolean,
    currentId: String?,
    onNewConversation: () -> Unit,
    onSelectConversation: (String) -> Unit,
) {
    ModalDrawerSheet(modifier = Modifier.widthIn(max = 320.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "ELY",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = onNewConversation,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.Add, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Nouvelle conversation")
            }
            Spacer(Modifier.height(16.dp))
            HorizontalDivider()
            Spacer(Modifier.height(8.dp))
            Text(
                "RÉCENTES",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 4.dp),
            )
        }
        if (loading) {
            Box(modifier = Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
            }
        } else if (conversations.isEmpty()) {
            Text(
                "Aucune conversation pour l'instant",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        } else {
            LazyColumn {
                items(conversations, key = { it.id }) { conv ->
                    NavigationDrawerItem(
                        label = {
                            Text(
                                text = conv.title.ifBlank { "Conversation" },
                                maxLines = 2,
                            )
                        },
                        selected = conv.id == currentId,
                        onClick = { onSelectConversation(conv.id) },
                        modifier = Modifier.padding(horizontal = 8.dp),
                    )
                }
            }
        }
    }
}
