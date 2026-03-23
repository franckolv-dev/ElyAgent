package com.ely.agent.core.database.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "skills")
data class SkillEntity(
    @PrimaryKey val name: String,
    val displayName: String,
    val description: String,
    val icon: String,
    val enabled: Boolean,
    val version: String = "1.0.0"
)
