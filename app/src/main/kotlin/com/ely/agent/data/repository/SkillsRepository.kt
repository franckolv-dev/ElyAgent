package com.ely.agent.data.repository

import com.ely.agent.core.model.Skill
import kotlinx.coroutines.flow.Flow

interface SkillsRepository {
    fun observeSkills(): Flow<List<Skill>>
    suspend fun refreshSkills()
    suspend fun toggleSkill(name: String, enabled: Boolean)
}
