// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/SkillsRepositoryImpl.kt
// @brief      Skills repository implementation
//
// @author     Franck OLLIVIER <franck.olv@gmail.com>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
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
