package com.ely.agent.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
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
import com.ely.agent.ui.components.*

@Composable
fun ChatScreen(
    onNavigateToSettings: () -> Unit,
    onNavigateToDashboard: () -> Unit,
    viewModel: ChatViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val listState = rememberLazyListState()

    LaunchedEffect(uiState.messages.size, uiState.streamingContent) {
        val count = uiState.messages.size + if (uiState.isStreaming) 1 else 0
        if (count > 0) listState.animateScrollToItem(count - 1)
    }

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
                actions = {
                    IconButton(onClick = onNavigateToDashboard) { Icon(Icons.Default.BarChart, "Dashboard") }
                    IconButton(onClick = onNavigateToSettings) { Icon(Icons.Default.Settings, "Paramètres") }
                }
            )
        },
        bottomBar = {
            ChatInputBar(text = uiState.inputText, onTextChange = viewModel::onInputChange,
                onSend = viewModel::sendMessage, isLoading = uiState.isLoading || uiState.isStreaming)
        }
    ) { padding ->
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(vertical = 8.dp)) {
            items(uiState.messages, key = { it.id }) { message ->
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
                    Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                        horizontalArrangement = Arrangement.Start) {
                        Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceVariant) {
                            if (uiState.streamingContent.isNotEmpty())
                                StreamingText(text = uiState.streamingContent,
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp).widthIn(max = 280.dp))
                            else
                                LoadingDots(modifier = Modifier.padding(12.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ChatInputBar(text: String, onTextChange: (String) -> Unit, onSend: () -> Unit, isLoading: Boolean) {
    Surface(tonalElevation = 3.dp) {
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp)
            .navigationBarsPadding().imePadding(), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(value = text, onValueChange = onTextChange,
                placeholder = { Text("Demandez quelque chose…") },
                modifier = Modifier.weight(1f), maxLines = 5, shape = MaterialTheme.shapes.extraLarge)
            Spacer(Modifier.width(8.dp))
            FilledIconButton(onClick = onSend, enabled = text.isNotBlank() && !isLoading,
                modifier = Modifier.size(48.dp)) {
                Icon(Icons.Default.Send, "Envoyer")
            }
        }
    }
}
