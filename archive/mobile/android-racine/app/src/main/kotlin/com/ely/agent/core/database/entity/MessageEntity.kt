package com.ely.agent.core.database.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "messages")
data class MessageEntity(
    @PrimaryKey val id: String,
    val conversationId: String,
    val role: String,
    val content: String,
    val timestamp: Long,
    val hitlActionId: String? = null,
    val hitlTool: String? = null,
    val hitlDescription: String? = null
)
