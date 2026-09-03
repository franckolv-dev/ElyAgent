// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/SkillsRepositoryImpl.kt
// @brief      Skills repository implementation
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.repository

import com.ely.agent.core.database.dao.SkillDao
import com.ely.agent.core.database.entity.SkillEntity
import com.ely.agent.core.model.Skill
import com.ely.agent.data.remote.api.SkillsApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject

class SkillsRepositoryImpl @Inject constructor(
    private val skillsApi: SkillsApi,
    private val skillDao: SkillDao
) : SkillsRepository {

    override fun observeSkills(): Flow<List<Skill>> =
        skillDao.observeAll().map { it.map { e -> e.toDomain() } }

    override suspend fun refreshSkills() {
        val dtos = skillsApi.getSkills()
        skillDao.deleteAll()
        skillDao.insertAll(dtos.map {
            SkillEntity(it.name, it.displayName, it.description, it.icon, it.enabled, it.version)
        })
    }

    override suspend fun toggleSkill(name: String, enabled: Boolean) {
        // TODO: PUT /api/skills/{name}
    }

    private fun SkillEntity.toDomain() = Skill(name, displayName, description, icon, enabled, version)
}
