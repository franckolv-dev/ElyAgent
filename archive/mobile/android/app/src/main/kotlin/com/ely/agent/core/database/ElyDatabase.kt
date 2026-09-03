// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/database/ElyDatabase.kt
// @brief      Room database definition
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.core.database

import androidx.room.Database
import androidx.room.RoomDatabase
import com.ely.agent.core.database.dao.ConversationDao
import com.ely.agent.core.database.dao.MessageDao
import com.ely.agent.core.database.dao.SkillDao
import com.ely.agent.core.database.entity.ConversationEntity
import com.ely.agent.core.database.entity.MessageEntity
import com.ely.agent.core.database.entity.SkillEntity

@Database(
    entities = [MessageEntity::class, ConversationEntity::class, SkillEntity::class],
    version = 1,
    exportSchema = false
)
abstract class ElyDatabase : RoomDatabase() {
    abstract fun messageDao(): MessageDao
    abstract fun conversationDao(): ConversationDao
    abstract fun skillDao(): SkillDao
}
