package com.ely.agent.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.ely.agent.ui.chat.ChatScreen
import com.ely.agent.ui.dashboard.DashboardScreen
import com.ely.agent.ui.login.LoginScreen
import com.ely.agent.ui.settings.SettingsScreen

@Composable
fun AppNavGraph(isLoggedIn: Boolean) {
    val navController = rememberNavController()
    val startDestination = if (isLoggedIn) Screen.Chat.route else Screen.Login.route
    NavHost(navController = navController, startDestination = startDestination) {
        composable(Screen.Login.route) {
            LoginScreen(onLoginSuccess = {
                navController.navigate(Screen.Chat.route) {
                    popUpTo(Screen.Login.route) { inclusive = true }
                }
            })
        }
        composable(Screen.Chat.route) {
            ChatScreen(
                onNavigateToSettings = { navController.navigate(Screen.Settings.route) },
                onNavigateToDashboard = { navController.navigate(Screen.Dashboard.route) }
            )
        }
        composable(Screen.Settings.route) { SettingsScreen(onBack = { navController.popBackStack() }) }
        composable(Screen.Dashboard.route) { DashboardScreen(onBack = { navController.popBackStack() }) }
    }
}
