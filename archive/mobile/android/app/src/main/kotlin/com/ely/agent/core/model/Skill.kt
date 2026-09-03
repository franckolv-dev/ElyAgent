// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/core/model/Skill.kt
// @brief      Skill data model
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================

package com.ely.agent.core.model

data class Skill(
    val name: String,
    val displayName: String,
    val description: String,
    val icon: String,
    val enabled: Boolean,
    val version: String = "1.0.0"
)
