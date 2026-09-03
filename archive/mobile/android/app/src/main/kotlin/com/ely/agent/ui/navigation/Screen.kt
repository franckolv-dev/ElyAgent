// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/ui/navigation/Screen.kt
// @brief      Navigation screen destinations
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//             https://opensource.org/licenses/MIT
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent.ui.navigation

sealed class Screen(val route: String) {
    object Login : Screen("login")
    object Chat : Screen("chat")
    object Settings : Screen("settings")
    object Dashboard : Screen("dashboard")
    object FileManager : Screen("file_manager")
}
