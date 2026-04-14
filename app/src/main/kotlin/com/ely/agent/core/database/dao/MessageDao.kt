package com.ely.agent.core.database.dao

import androidx.room.*
import com.ely.agent.core.database.entity.MessageEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface MessageDao {
    @Query("SELECT * FROM messages WHERE conversationId = :conversationId ORDER BY timestamp ASC")
    fun observeMessages(conversationId: String): Flow<List<MessageEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMessage(message: MessageEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMessages(messages: List<MessageEntity>)

    @Query("DELETE FROM messages WHERE conversationId = :conversationId")
    suspend fun deleteMessagesForConversation(conversationId: String)

    @Query("SELECT * FROM messages ORDER BY timestamp ASC")
    fun observeAllMessages(): Flow<List<MessageEntity>>

    @Query("SELECT * FROM messages ORDER BY timestamp DESC LIMIT 50")
    suspend fun getRecentMessages(): List<MessageEntity>
}
