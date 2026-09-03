// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/data/repository/SkillsRepository.kt
// @brief      Skills repository interface
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.data.repository

import com.ely.agent.core.model.Skill
import kotlinx.coroutines.flow.Flow

interface SkillsRepository {
    fun observeSkills(): Flow<List<Skill>>
    suspend fun refreshSkills()
    suspend fun toggleSkill(name: String, enabled: Boolean)
}
