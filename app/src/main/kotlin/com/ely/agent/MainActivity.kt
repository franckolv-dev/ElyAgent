package com.ely.agent

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import com.ely.agent.core.datastore.PreferencesDataStore.userPreferencesDataStore
import com.ely.agent.core.model.ThemePreference
import com.ely.agent.ui.navigation.AppNavGraph
import com.ely.agent.ui.theme.ElyTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val prefs by userPreferencesDataStore.data.collectAsState(
                initial = com.ely.agent.UserPreferences.getDefaultInstance()
            )
            val theme = when (prefs.theme) {
                "LIGHT" -> ThemePreference.LIGHT
                "DARK" -> ThemePreference.DARK
                else -> ThemePreference.SYSTEM
            }
            ElyTheme(themePreference = theme) {
                AppNavGraph(isLoggedIn = prefs.accessToken.isNotBlank())
            }
        }
    }
}
