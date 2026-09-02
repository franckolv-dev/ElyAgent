package com.ely.agent.ui.navigation

sealed class Screen(val route: String) {
    object Login : Screen("login")
    object Chat : Screen("chat")
    object Settings : Screen("settings")
    object Dashboard : Screen("dashboard")
}
